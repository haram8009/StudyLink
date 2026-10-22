"""Wrong-answer reviews: one row per incorrectly answered question (created at submit time).

Related notes are computed on demand for a single review only (never stored, never in lists).
"""
import json
import logging
from fastapi import HTTPException
from ..db import get_connection
from ..schemas.quiz import LinkedRelatedNote, ReviewDetail, ReviewItem
from .workspaces import require_workspace

logger = logging.getLogger(__name__)
RELATED_LIMIT = 3

_SELECT = '''SELECT r.id AS review_id, r.status, r.learner_reason, z.workspace_id, z.id AS quiz_id,
    q.id AS question_id, q.stem, q.options_json, q.answer_option_id, q.explanation, q.document_id, q.page, q.quote,
    d.filename, a.selected_option_id, a.submitted_at AS created_at
  FROM reviews r
  JOIN questions q ON q.id=r.question_id
  JOIN quizzes z ON z.id=q.quiz_id
  LEFT JOIN documents d ON d.id=q.document_id
  LEFT JOIN attempts a ON a.question_id=q.id'''

def _item(row) -> ReviewItem:
    data = dict(row)
    data['options'] = json.loads(data.pop('options_json'))
    data['quote'] = data['quote'] or ''
    data['selected_option_id'] = data['selected_option_id'] or ''
    data['created_at'] = data['created_at'] or ''
    return ReviewItem(**data)

def _load(db, review_id: str) -> ReviewItem:
    row = db.execute(_SELECT + ' WHERE r.id=?', (review_id,)).fetchone()
    if row is None:
        raise HTTPException(404, '오답을 찾을 수 없습니다')
    return _item(row)

def list_reviews(workspace_id: str, status: str | None = None) -> list[ReviewItem]:
    require_workspace(workspace_id)
    sql = _SELECT + ' WHERE z.workspace_id=?'
    params: list = [workspace_id]
    if status:
        sql += ' AND r.status=?'
        params.append(status)
    sql += ' ORDER BY a.submitted_at DESC, q.rowid'
    with get_connection() as db:
        return [_item(row) for row in db.execute(sql, params)]

def get_review_item(review_id: str) -> ReviewItem:
    with get_connection() as db:
        return _load(db, review_id)

def _related(item: ReviewItem) -> tuple[list[LinkedRelatedNote], str]:
    """Query = stem + correct option text over all indexed notes; linked = in this review's workspace."""
    from ..adapters.gms import ProviderUnavailable
    answer_text = next((o.text for o in item.options if o.option_id == item.answer_option_id), '')
    try:
        from ..services.related_notes import related_notes
        found = related_notes(f'{item.stem} {answer_text}'.strip(), k=RELATED_LIMIT) or []
    except (ImportError, ProviderUnavailable) as exc:
        logger.warning('related notes unavailable for review %s: %s', item.review_id, type(exc).__name__)
        return [], 'unavailable'
    with get_connection() as db:
        linked = {r['note_id'] for r in db.execute('SELECT note_id FROM workspace_notes WHERE workspace_id=?', (item.workspace_id,))}
    notes = [LinkedRelatedNote(note_id=n['note_id'], title=n['title'], snippet=n.get('snippet') or '',
                               linked=n['note_id'] in linked) for n in found[:RELATED_LIMIT]]
    return notes, 'ok'

def get_review(review_id: str) -> ReviewDetail:
    item = get_review_item(review_id)
    notes, status = _related(item)
    return ReviewDetail(**item.model_dump(), related_notes=notes, related_notes_status=status)

def update_review(review_id: str, learner_reason: str | None, status: str | None) -> ReviewItem:
    with get_connection() as db:
        _load(db, review_id)
        if learner_reason is not None:
            db.execute('UPDATE reviews SET learner_reason=? WHERE id=?', (learner_reason, review_id))
        if status is not None:
            db.execute('UPDATE reviews SET status=? WHERE id=?', (status, review_id))
        return _load(db, review_id)
