"""Quiz storage, retrieval and one-shot grading (no model calls here).

Generation itself is C's `quiz_generation.generate_quiz_questions`; this module saves its
result in one transaction, guards concurrent generation per workspace, and grades submissions.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import threading
from uuid import uuid4
from fastapi import HTTPException
from ..db import get_connection
from ..schemas.quiz import QuestionGraded, QuestionPublic, QuizGraded, QuizPublic, QuizSummary
from .workspaces import require_workspace

RECENT_LIMIT = 20

class QuizBusy(RuntimeError):
    pass

_generating: set[str] = set()
_generating_guard = threading.Lock()

def _now():
    return datetime.now(timezone.utc).isoformat()

@contextmanager
def generation_turn(workspace_id: str):
    """In-process guard: one quiz generation per workspace at a time (same as chat ask)."""
    with _generating_guard:
        if workspace_id in _generating:
            raise QuizBusy(workspace_id)
        _generating.add(workspace_id)
    try:
        yield
    finally:
        with _generating_guard:
            _generating.discard(workspace_id)

def save_quiz(workspace_id: str, requested_count: int, questions: list[dict]) -> str:
    """Persist a generated quiz and its questions atomically; ids are assigned here."""
    quiz_id = str(uuid4())
    with get_connection() as db:
        db.execute('INSERT INTO quizzes(id,workspace_id,requested_count,actual_count,created_at,submitted_at) VALUES (?,?,?,?,?,NULL)',
                   (quiz_id, workspace_id, requested_count, len(questions), _now()))
        for question in questions:
            options = [{'option_id': str(o['option_id']), 'text': str(o['text'])} for o in question['options']]
            db.execute('''INSERT INTO questions(id,quiz_id,stem,options_json,answer_option_id,explanation,document_id,page,quote,chunk_id)
                VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (str(uuid4()), quiz_id, question['stem'], json.dumps(options, ensure_ascii=False), str(question['answer_option_id']),
                 question['explanation'], question['document_id'], int(question['page']), question.get('quote') or '', question.get('chunk_id')))
    return quiz_id

def _require_quiz(db, quiz_id: str):
    row = db.execute('SELECT * FROM quizzes WHERE id=?', (quiz_id,)).fetchone()
    if row is None:
        raise HTTPException(404, '퀴즈를 찾을 수 없습니다')
    return row

def _question_rows(db, quiz_id: str):
    # rowid keeps generation order; LEFT JOIN keeps questions whose document is gone (filename null).
    return db.execute('''SELECT q.*, d.filename FROM questions q LEFT JOIN documents d ON d.id=q.document_id
        WHERE q.quiz_id=? ORDER BY q.rowid''', (quiz_id,)).fetchall()

def _public(row) -> QuestionPublic:
    return QuestionPublic(question_id=row['id'], stem=row['stem'], options=json.loads(row['options_json']),
                          document_id=row['document_id'], filename=row['filename'], page=row['page'])

def _graded(row, selected: str) -> QuestionGraded:
    return QuestionGraded(**_public(row).model_dump(), selected_option_id=selected, answer_option_id=row['answer_option_id'],
                          correct=selected == row['answer_option_id'], explanation=row['explanation'], quote=row['quote'] or '')

def _stored_result(db, quiz) -> QuizGraded:
    selected = {r['question_id']: r['selected_option_id'] for r in db.execute(
        'SELECT a.question_id, a.selected_option_id FROM attempts a JOIN questions q ON q.id=a.question_id WHERE q.quiz_id=? ORDER BY a.rowid',
        (quiz['id'],))}
    questions = [_graded(row, selected.get(row['id'], '')) for row in _question_rows(db, quiz['id'])]
    return QuizGraded(quiz_id=quiz['id'], workspace_id=quiz['workspace_id'], requested_count=quiz['requested_count'],
                      actual_count=quiz['actual_count'], created_at=quiz['created_at'], submitted_at=quiz['submitted_at'],
                      score=sum(q.correct for q in questions), total=len(questions), questions=questions)

def _public_quiz(db, quiz) -> QuizPublic:
    return QuizPublic(quiz_id=quiz['id'], workspace_id=quiz['workspace_id'], requested_count=quiz['requested_count'],
                      actual_count=quiz['actual_count'], created_at=quiz['created_at'],
                      questions=[_public(row) for row in _question_rows(db, quiz['id'])])

def get_quiz(quiz_id: str) -> QuizPublic | QuizGraded:
    with get_connection() as db:
        quiz = _require_quiz(db, quiz_id)
        return _stored_result(db, quiz) if quiz['submitted_at'] else _public_quiz(db, quiz)

def get_public_quiz(quiz_id: str) -> QuizPublic:
    with get_connection() as db:
        return _public_quiz(db, _require_quiz(db, quiz_id))

def list_quizzes(workspace_id: str, limit: int = RECENT_LIMIT) -> list[QuizSummary]:
    require_workspace(workspace_id)
    with get_connection() as db:
        rows = db.execute('''SELECT z.*, (SELECT COALESCE(SUM(a.correct),0) FROM attempts a JOIN questions q ON q.id=a.question_id
                WHERE q.quiz_id=z.id) AS correct_count
            FROM quizzes z WHERE z.workspace_id=? ORDER BY z.created_at DESC, z.rowid DESC LIMIT ?''', (workspace_id, limit)).fetchall()
    return [QuizSummary(quiz_id=r['id'], requested_count=r['requested_count'], actual_count=r['actual_count'],
                        created_at=r['created_at'], submitted_at=r['submitted_at'],
                        score=r['correct_count'] if r['submitted_at'] else None) for r in rows]

def _validate_answers(rows, answers: dict[str, str]):
    options = {row['id']: {o['option_id'] for o in json.loads(row['options_json'])} for row in rows}
    unknown = [qid for qid in answers if qid not in options]
    if unknown:
        raise HTTPException(422, '이 퀴즈에 없는 문항이 포함되어 있습니다')
    missing = [qid for qid in options if qid not in answers]
    if missing:
        raise HTTPException(422, f'답하지 않은 문항이 {len(missing)}개 있습니다')
    for qid, option_id in answers.items():
        if option_id not in options[qid]:
            raise HTTPException(422, '선택지가 올바르지 않습니다')

def submit_quiz(quiz_id: str, answers: dict[str, str]) -> QuizGraded:
    """Grade once. Re-submission (or a lost race) returns the stored result unchanged."""
    with get_connection() as db:
        quiz = _require_quiz(db, quiz_id)
        if quiz['submitted_at']:
            return _stored_result(db, quiz)
        rows = _question_rows(db, quiz_id)
    _validate_answers(rows, answers)
    submitted_at = _now()
    with get_connection() as db:
        updated = db.execute('UPDATE quizzes SET submitted_at=? WHERE id=? AND submitted_at IS NULL', (submitted_at, quiz_id)).rowcount
        if updated:
            for row in rows:
                selected = answers[row['id']]
                correct = selected == row['answer_option_id']
                db.execute('INSERT INTO attempts(id,question_id,selected_option_id,correct,submitted_at) VALUES (?,?,?,?,?)',
                           (str(uuid4()), row['id'], selected, int(correct), submitted_at))
                if not correct:
                    db.execute("INSERT OR IGNORE INTO reviews(id,question_id,status,learner_reason) VALUES (?,?,'open','')",
                               (str(uuid4()), row['id']))
    with get_connection() as db:
        return _stored_result(db, _require_quiz(db, quiz_id))
