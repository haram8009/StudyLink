"""Day-three backend: quiz storage/grading, answer leakage, reviews, note-draft/related HTTP (C stubbed)."""
import sqlite3
import sys
import threading
import types
import importlib
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.config import get_settings
from app.db import get_connection, init_db

@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setenv('MOCK_LLM', '1')
    monkeypatch.setenv('LANGFUSE_ENABLED', '0')
    monkeypatch.setenv('EMBEDDING_DIM', '1536')
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()

from app.services.quiz_generation import NoQuizEvidence, NoValidQuestions, QuizDeadlineExceeded

def make_question(doc, n, answer='b'):
    return {'stem': f'Q{n}?', 'options': [{'option_id': o, 'text': f'{o}-text-{n}'} for o in 'abcd'],
            'answer_option_id': answer, 'explanation': f'because {n}', 'document_id': doc, 'page': n,
            'quote': f'quote {n}', 'chunk_id': f'{doc}-chunk-{n}'}

@pytest.fixture
def generator(monkeypatch):
    """Stand-in for C's quiz_generation module (contract: generate_quiz_questions, NoQuizEvidence, NoValidQuestions)."""
    state = {'calls': [], 'mode': 'ok', 'doc': None, 'gate': threading.Event(), 'started': threading.Event()}
    module = importlib.import_module('app.services.quiz_generation')
    def generate_quiz_questions(workspace_id, count=5, *, difficulty='medium'):
        from app.adapters.gms import ProviderUnavailable
        state['calls'].append((workspace_id, count))
        with get_connection() as db:
            doc = db.execute('SELECT id FROM documents WHERE workspace_id=?', (workspace_id,)).fetchone()['id']
        mode = state['mode']
        if mode == 'slow':
            state['started'].set()
            assert state['gate'].wait(10)
        if mode == 'no_evidence':
            raise NoQuizEvidence('출제할 자료가 없습니다')
        if mode == 'invalid':
            raise NoValidQuestions('유효 문항 0개')
        if mode == 'down':
            raise ProviderUnavailable('secret-key')
        if mode == 'deadline':
            raise QuizDeadlineExceeded('timeout')
        produced = count if mode in ('ok', 'slow') else 2
        return {'requested_count': count, 'questions': [make_question(doc, i + 1) for i in range(produced)]}
    monkeypatch.setattr(module, 'generate_quiz_questions', generate_quiz_questions)
    return state

@pytest.fixture
def related(monkeypatch):
    state = {'calls': [], 'result': [], 'error': None}
    module = types.ModuleType('app.services.related_notes')
    def related_notes(text, exclude_note_id=None, k=3):
        state['calls'].append({'text': text, 'exclude_note_id': exclude_note_id, 'k': k})
        if state['error']:
            raise state['error']
        return state['result']
    module.related_notes = related_notes
    monkeypatch.setitem(sys.modules, 'app.services.related_notes', module)
    return state

@pytest.fixture
def client(env, generator, related):
    from app.main import app
    with TestClient(app) as client:
        yield client

def setup_workspace(client, generator, title='NLP'):
    ws = client.post('/api/workspaces', json={'title': title}).json()['id']
    doc = str(uuid4())
    with get_connection() as db:
        db.execute("INSERT INTO documents(id,workspace_id,filename,path,page_count,status) VALUES (?,?,?,?,10,'ready')",
                   (doc, ws, 'study.pdf', 'missing.pdf'))
        for n in range(1, 11):
            db.execute('INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?)',
                       (f'{doc}-chunk-{n}', 'doc', doc, n, f'quote {n}\n' + '자료 설명 ' * 50, b'', 'm', 1536))
    generator['doc'] = doc
    return ws, doc

def make_quiz(client, ws, **body):
    response = client.post(f'/api/workspaces/{ws}/quizzes', json=body)
    assert response.status_code == 201, response.text
    return response.json()

LEAK_KEYS = {'answer_option_id', 'explanation', 'quote', 'correct', 'chunk_id'}

def test_create_quiz_hides_answers_and_lists_recent(client, generator):
    ws, doc = setup_workspace(client, generator)
    quiz = make_quiz(client, ws)
    assert generator['calls'] == [(ws, 5)]
    assert quiz['requested_count'] == 5 and quiz['actual_count'] == 5 and quiz['submitted_at'] is None
    assert len(quiz['questions']) == 5 and len({q['question_id'] for q in quiz['questions']}) == 5
    first = quiz['questions'][0]
    assert set(first) == {'question_id', 'stem', 'options', 'document_id', 'filename', 'page'}
    assert first['filename'] == 'study.pdf' and first['document_id'] == doc and first['page'] == 1
    assert first['options'][0] == {'option_id': 'a', 'text': 'a-text-1'}
    fetched = client.get(f'/api/quizzes/{quiz["quiz_id"]}').json()
    assert fetched == quiz
    for question in fetched['questions']:
        assert not LEAK_KEYS & set(question)
    assert not LEAK_KEYS & set(fetched)
    with get_connection() as db:
        row = db.execute('SELECT quote, chunk_id FROM questions WHERE id=?', (first['question_id'],)).fetchone()
        assert tuple(row) == ('quote 1', f'{doc}-chunk-1')
    listed = client.get(f'/api/workspaces/{ws}/quizzes').json()
    assert listed == [{'quiz_id': quiz['quiz_id'], 'requested_count': 5, 'actual_count': 5,
                       'difficulty': 'medium', 'created_at': quiz['created_at'], 'submitted_at': None, 'score': None}]
    assert client.get('/api/quizzes/missing').status_code == 404
    assert client.get('/api/workspaces/missing/quizzes').status_code == 404

def test_create_quiz_count_partial_and_error_mapping(client, generator):
    ws, _ = setup_workspace(client, generator)
    assert make_quiz(client, ws, count=3)['actual_count'] == 3
    for bad in (0, 11, 1.2, '5', True):
        assert client.post(f'/api/workspaces/{ws}/quizzes', json={'count': bad}).status_code == 422
    generator['mode'] = 'partial'
    assert client.post(f'/api/workspaces/{ws}/quizzes', json={}).status_code == 422
    expected = {'no_evidence': 400, 'invalid': 422, 'down': 503, 'deadline': 503}
    for mode, status in expected.items():
        generator['mode'] = mode
        response = client.post(f'/api/workspaces/{ws}/quizzes', json={})
        assert response.status_code == status and isinstance(response.json()['detail'], str)
        assert 'secret' not in response.json()['detail']
    assert client.post('/api/workspaces/missing/quizzes', json={}).status_code == 404
    with get_connection() as db:
        assert db.execute('SELECT count(*) FROM quizzes').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM questions').fetchone()[0] == 3
    generator['mode'] = 'ok'
    assert client.post(f'/api/workspaces/{ws}/quizzes').status_code == 201  # body optional, lock released

def test_same_workspace_concurrent_generation_is_409(client, generator):
    ws, _ = setup_workspace(client, generator)
    other, _ = setup_workspace(client, generator, 'LLM')
    generator['mode'] = 'slow'
    results = {}
    worker = threading.Thread(target=lambda: results.update(slow=client.post(f'/api/workspaces/{ws}/quizzes', json={})))
    worker.start()
    try:
        assert generator['started'].wait(10)
        busy = client.post(f'/api/workspaces/{ws}/quizzes', json={})
        assert busy.status_code == 409 and isinstance(busy.json()['detail'], str)
        generator['mode'] = 'ok'
        assert client.post(f'/api/workspaces/{other}/quizzes', json={}).status_code == 201
    finally:
        generator['gate'].set()
        worker.join(10)
    assert results['slow'].status_code == 201
    assert client.post(f'/api/workspaces/{ws}/quizzes', json={}).status_code == 201

def answers_for(quiz, wrong=()):
    return {q['question_id']: ('c' if i in wrong else 'b') for i, q in enumerate(quiz['questions'])}

def counts():
    with get_connection() as db:
        return tuple(db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in ('attempts', 'reviews'))

def test_submit_grades_once_and_creates_reviews(client, generator):
    ws, _ = setup_workspace(client, generator)
    perfect = make_quiz(client, ws)
    result = client.post(f'/api/quizzes/{perfect["quiz_id"]}/submit', json={'answers': answers_for(perfect)}).json()
    assert result['score'] == 5 and result['total'] == 5 and counts() == (5, 0)
    quiz = make_quiz(client, ws)
    submit = client.post(f'/api/quizzes/{quiz["quiz_id"]}/submit', json={'answers': answers_for(quiz, wrong=(0, 3))})
    assert submit.status_code == 200
    graded = submit.json()
    assert graded['score'] == 3 and graded['total'] == 5 and graded['submitted_at']
    first = graded['questions'][0]
    assert first['selected_option_id'] == 'c' and first['answer_option_id'] == 'b' and first['correct'] is False
    assert first['explanation'] == 'because 1' and first['quote'] == 'quote 1' and first['filename'] == 'study.pdf'
    assert [q['correct'] for q in graded['questions']] == [False, True, True, False, True]
    assert counts() == (10, 2)
    # Re-submission with different answers: stored result, no new rows
    again = client.post(f'/api/quizzes/{quiz["quiz_id"]}/submit', json={'answers': answers_for(quiz)})
    assert again.status_code == 200 and again.json() == graded and counts() == (10, 2)
    assert client.get(f'/api/quizzes/{quiz["quiz_id"]}').json() == graded
    listed = {q['quiz_id']: q['score'] for q in client.get(f'/api/workspaces/{ws}/quizzes').json()}
    assert listed == {perfect['quiz_id']: 5, quiz['quiz_id']: 3}

def test_submit_validation_errors_store_nothing(client, generator):
    ws, _ = setup_workspace(client, generator)
    quiz = make_quiz(client, ws)
    other = make_quiz(client, ws)
    good = answers_for(quiz)
    missing = dict(list(good.items())[:4])
    foreign = {**missing, other['questions'][0]['question_id']: 'b'}
    bad_option = {**good, quiz['questions'][0]['question_id']: 'z'}
    extra = {**good, other['questions'][0]['question_id']: 'b'}
    for answers in (missing, foreign, bad_option, extra, {}):
        response = client.post(f'/api/quizzes/{quiz["quiz_id"]}/submit', json={'answers': answers})
        assert response.status_code == 422 and isinstance(response.json()['detail'], str)
    assert client.post(f'/api/quizzes/{quiz["quiz_id"]}/submit', json={}).status_code == 422
    assert client.post('/api/quizzes/missing/submit', json={'answers': {}}).status_code == 404
    assert counts() == (0, 0)
    assert client.get(f'/api/quizzes/{quiz["quiz_id"]}').json()['submitted_at'] is None

def test_concurrent_submit_records_once(client, generator):
    from app.services import quizzes
    ws, _ = setup_workspace(client, generator)
    quiz = make_quiz(client, ws)
    answers = answers_for(quiz, wrong=(1,))
    results = []
    barrier = threading.Barrier(4)
    def submit():
        barrier.wait()
        results.append(quizzes.submit_quiz(quiz['quiz_id'], answers).model_dump())
    threads = [threading.Thread(target=submit) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert len(results) == 4 and all(r == results[0] for r in results)
    assert counts() == (5, 1)

def test_reviews_filter_update_related_and_restart(client, generator, related):
    ws, doc = setup_workspace(client, generator)
    other_ws, _ = setup_workspace(client, generator, 'LLM')
    other_quiz = make_quiz(client, other_ws)
    client.post(f'/api/quizzes/{other_quiz["quiz_id"]}/submit', json={'answers': answers_for(other_quiz, wrong=(0,))})
    generator['doc'] = doc
    quiz = make_quiz(client, ws)
    client.post(f'/api/quizzes/{quiz["quiz_id"]}/submit', json={'answers': answers_for(quiz, wrong=(0, 2))})
    items = client.get(f'/api/reviews?workspace_id={ws}').json()
    assert len(items) == 2 and {i['quiz_id'] for i in items} == {quiz['quiz_id']}
    item = next(i for i in items if i['stem'] == 'Q1?')
    assert item['selected_option_id'] == 'c' and item['answer_option_id'] == 'b' and item['filename'] == 'study.pdf'
    assert item['quote'] == 'quote 1' and item['status'] == 'open' and item['learner_reason'] == '' and item['created_at']
    assert item['page'] == 1 and len(item['options']) == 4 and 'related_notes' not in item
    assert related['calls'] == []  # lists never compute related notes
    # Related notes for a single review
    note_linked, note_free = str(uuid4()), str(uuid4())
    with get_connection() as db:
        for note in (note_linked, note_free):
            db.execute("INSERT INTO notes(id,title,body,index_status,created_at,updated_at) VALUES (?,?,?,'ok','t','t')", (note, 'n', 'b'))
        db.execute('INSERT INTO workspace_notes(workspace_id,note_id) VALUES (?,?)', (ws, note_linked))
    related['result'] = [{'note_id': note_linked, 'title': '기울기 소실 정리', 'snippet': 's1'},
                         {'note_id': note_free, 'title': 'free', 'snippet': 's2'}]
    detail = client.get(f'/api/reviews/{item["review_id"]}').json()
    assert related['calls'] == [{'text': 'Q1? b-text-1', 'exclude_note_id': None, 'k': 3}]
    assert [(n['note_id'], n['linked']) for n in detail['related_notes']] == [(note_linked, True), (note_free, False)]
    assert detail['related_notes_status'] == 'ok'
    from app.adapters.gms import ProviderUnavailable
    related['error'] = ProviderUnavailable('down')
    degraded = client.get(f'/api/reviews/{item["review_id"]}').json()
    assert degraded['related_notes'] == [] and degraded['related_notes_status'] == 'unavailable'
    # Update memo and status
    patched = client.patch(f'/api/reviews/{item["review_id"]}', json={'learner_reason': '정의를 혼동', 'status': 'reviewed'})
    assert patched.status_code == 200
    assert patched.json()['learner_reason'] == '정의를 혼동' and patched.json()['status'] == 'reviewed'
    assert 'related_notes' not in patched.json()
    assert client.patch(f'/api/reviews/{item["review_id"]}', json={'learner_reason': 'x' * 2001}).status_code == 422
    assert client.patch(f'/api/reviews/{item["review_id"]}', json={'status': 'done'}).status_code == 422
    assert client.patch('/api/reviews/missing', json={'status': 'open'}).status_code == 404
    assert client.get('/api/reviews/missing').status_code == 404
    assert [i['stem'] for i in client.get(f'/api/reviews?workspace_id={ws}&status=reviewed').json()] == ['Q1?']
    assert [i['stem'] for i in client.get(f'/api/reviews?workspace_id={ws}&status=open').json()] == ['Q3?']
    assert client.get(f'/api/reviews?workspace_id={ws}&status=bad').status_code == 422
    assert client.get('/api/reviews?workspace_id=missing').status_code == 404
    # Missing source document keeps the record with filename null
    with get_connection() as db:
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute('DELETE FROM documents WHERE id=?', (doc,))
    kept = client.get(f'/api/reviews?workspace_id={ws}').json()
    assert len(kept) == 2 and all(i['filename'] is None for i in kept)
    # Restart: results, reviews and memo persist
    from app.main import app
    with TestClient(app) as restarted:
        graded = restarted.get(f'/api/quizzes/{quiz["quiz_id"]}').json()
        assert graded['score'] == 3 and graded['questions'][0]['selected_option_id'] == 'c'
        memo = restarted.get(f'/api/reviews?workspace_id={ws}&status=reviewed').json()
        assert memo[0]['learner_reason'] == '정의를 혼동'

def test_quiz_schema_migration_is_idempotent(env):
    db_path = get_settings().db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as old:
        old.executescript('''
            CREATE TABLE workspaces (id TEXT PRIMARY KEY, title TEXT NOT NULL, goal TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
            CREATE TABLE documents (id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, filename TEXT NOT NULL, path TEXT NOT NULL,
                page_count INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, error TEXT);
            CREATE TABLE quizzes (id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), requested_count INTEGER NOT NULL,
                actual_count INTEGER NOT NULL, created_at TEXT NOT NULL, submitted_at TEXT);
            CREATE TABLE questions (id TEXT PRIMARY KEY, quiz_id TEXT NOT NULL REFERENCES quizzes(id), stem TEXT NOT NULL, options_json TEXT NOT NULL,
                answer_option_id TEXT NOT NULL, explanation TEXT NOT NULL, document_id TEXT NOT NULL REFERENCES documents(id), page INTEGER NOT NULL);
            INSERT INTO workspaces VALUES ('w1','one','','2026-10-20T00:00:00');
            INSERT INTO documents VALUES ('d1','w1','old.pdf','x',1,'ready',NULL);
            INSERT INTO quizzes VALUES ('z1','w1',1,1,'2026-10-20T00:00:00',NULL);
            INSERT INTO questions VALUES ('q1','z1','old?','[{"option_id":"a","text":"A"},{"option_id":"b","text":"B"}]','a','e','d1',1);''')
    old.close()
    init_db()
    init_db()
    with get_connection() as db:
        columns = {row['name'] for row in db.execute('PRAGMA table_info(questions)')}
        assert {'quote', 'chunk_id'} <= columns
        indexes = {row['name'] for row in db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert {'questions_quiz', 'quizzes_workspace', 'attempts_question'} <= indexes
    from app.main import app
    with TestClient(app) as client:
        quiz = client.get('/api/quizzes/z1').json()
        assert quiz['difficulty'] is None
        assert quiz['questions'][0]['filename'] == 'old.pdf'
        graded = client.post('/api/quizzes/z1/submit', json={'answers': {'q1': 'b'}}).json()
        assert graded['score'] == 0 and graded['questions'][0]['quote'] == ''
        assert len(client.get('/api/reviews?workspace_id=w1').json()) == 1


@pytest.mark.parametrize('difficulty', ['easy', 'medium', 'hard'])
@pytest.mark.parametrize('count', [1, 10])
def test_quiz_settings_persist_through_read_list_and_submission(client, generator, count, difficulty):
    ws, _ = setup_workspace(client, generator)
    quiz = make_quiz(client, ws, count=count, difficulty=difficulty)
    assert quiz['requested_count'] == quiz['actual_count'] == len(quiz['questions']) == count
    assert quiz['difficulty'] == difficulty
    assert client.get(f'/api/quizzes/{quiz["quiz_id"]}').json()['difficulty'] == difficulty
    assert client.get(f'/api/workspaces/{ws}/quizzes').json()[0]['difficulty'] == difficulty
    result = client.post(f'/api/quizzes/{quiz["quiz_id"]}/submit', json={'answers': answers_for(quiz)}).json()
    assert result['difficulty'] == difficulty and result['score'] == count
    init_db()
    assert client.get(f'/api/quizzes/{quiz["quiz_id"]}').json() == result


@pytest.mark.parametrize('body', [{'count': 0}, {'count': 11}, {'count': 5.0}, {'count': 1.5},
                                 {'count': '5'}, {'count': True}, {'count': None},
                                 {'difficulty': 'unknown'}, {'difficulty': None}])
def test_invalid_settings_never_call_model_or_write(client, generator, body):
    ws, _ = setup_workspace(client, generator)
    assert client.post(f'/api/workspaces/{ws}/quizzes', json=body).status_code == 422
    assert generator['calls'] == []
    with get_connection() as db:
        assert db.execute('SELECT count(*) FROM quizzes').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM questions').fetchone()[0] == 0


@pytest.mark.parametrize('corruption', ['partial', 'duplicate', 'page', 'chunk', 'quote', 'empty_quote', 'content', 'scope', 'unready'])
def test_save_guard_rolls_back_invalid_generation(client, generator, corruption):
    from app.services.quizzes import save_quiz
    ws, doc = setup_workspace(client, generator)
    questions = [make_question(doc, i) for i in (1, 2)]
    if corruption == 'partial':
        questions.pop()
    elif corruption == 'duplicate':
        questions[1] = dict(questions[0])
    elif corruption in ('page', 'chunk', 'quote', 'empty_quote', 'content'):
        key, value = {'page': ('page', 3), 'chunk': ('chunk_id', 'missing'),
                      'quote': ('quote', 'fabricated'), 'empty_quote': ('quote', ''),
                      'content': ('explanation', ' ')}[corruption]
        questions[1][key] = value
    elif corruption == 'scope':
        other, _ = setup_workspace(client, generator, 'other')
        with get_connection() as db:
            db.execute('UPDATE documents SET workspace_id=? WHERE id=?', (other, doc))
    else:
        with get_connection() as db:
            db.execute("UPDATE documents SET status='processing' WHERE id=?", (doc,))
    with pytest.raises(NoValidQuestions):
        save_quiz(ws, 2, questions)
    with get_connection() as db:
        assert db.execute('SELECT count(*) FROM quizzes').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM questions').fetchone()[0] == 0


def test_existing_partial_quiz_remains_readable_and_gradable(client, generator):
    ws, doc = setup_workspace(client, generator)
    with get_connection() as db:
        db.execute("INSERT INTO quizzes(id,workspace_id,requested_count,actual_count,created_at) VALUES('legacy',?,5,1,'old')", (ws,))
        db.execute('''INSERT INTO questions(id,quiz_id,stem,options_json,answer_option_id,explanation,document_id,page)
            VALUES('old-question','legacy','old?',?,'a','old explanation',?,1)''',
            ('[{"option_id":"a","text":"A"},{"option_id":"b","text":"B"}]', doc))
    init_db()
    quiz = client.get('/api/quizzes/legacy').json()
    assert quiz['requested_count'] == 5 and quiz['actual_count'] == 1 and quiz['difficulty'] is None
    graded = client.post('/api/quizzes/legacy/submit', json={'answers': {'old-question': 'a'}}).json()
    assert graded['score'] == graded['total'] == 1 and graded['difficulty'] is None

class AnswerNotFound(Exception):
    pass

class AnswerNotGrounded(Exception):
    pass

def test_note_draft_and_related_http_mapping(client, related, monkeypatch):
    from app.adapters.gms import ProviderUnavailable
    module = types.ModuleType('app.services.note_draft')
    draft = {'title': 't', 'body': 'b [c1]', 'fallback': False,
             'citations': [{'id': 'c1', 'source_type': 'doc', 'document_id': 'd', 'page': 2, 'quote': 'q', 'note_id': None}]}
    def draft_note(answer_id):
        if answer_id == 'missing':
            raise AnswerNotFound(answer_id)
        if answer_id == 'thin':
            raise AnswerNotGrounded(answer_id)
        if answer_id == 'down':
            raise ProviderUnavailable('secret')
        return draft
    module.draft_note, module.AnswerNotFound, module.AnswerNotGrounded = draft_note, AnswerNotFound, AnswerNotGrounded
    monkeypatch.setitem(sys.modules, 'app.services.note_draft', module)
    ok = client.post('/api/answers/a1/note-draft')
    assert ok.status_code == 200 and ok.json() == draft
    assert client.post('/api/answers/missing/note-draft').status_code == 404
    assert client.post('/api/answers/thin/note-draft').status_code == 422
    assert client.post('/api/answers/down/note-draft').status_code == 503
    with get_connection() as db:
        assert db.execute('SELECT count(*) FROM notes').fetchone()[0] == 0
    related['result'] = [{'note_id': f'n{i}', 'title': f't{i}', 'snippet': 's'} for i in range(4)]
    response = client.post('/api/notes/related', json={'title': '어텐션', 'body': '본문', 'exclude_note_id': 'n9'})
    assert response.status_code == 200 and [n['note_id'] for n in response.json()] == ['n0', 'n1', 'n2']
    assert set(response.json()[0]) == {'note_id', 'title', 'snippet'}
    assert related['calls'][-1] == {'text': '어텐션\n본문', 'exclude_note_id': 'n9', 'k': 3}
    assert client.post('/api/notes/related', json={'title': '', 'body': ''}).json() == []
    related['error'] = ProviderUnavailable('x')
    assert client.post('/api/notes/related', json={'title': 'a', 'body': 'b'}).status_code == 503
    with get_connection() as db:
        assert db.execute('SELECT count(*) FROM notes').fetchone()[0] == 0
