"""Note originals, persistent [cN] citations and workspace links.

Notes are not owned by workspaces. Linking/unlinking never re-embeds. Indexing (C's
note_index.index_note) runs after the write transaction commits.
"""
from datetime import datetime, timezone
import logging
import re
from uuid import uuid4
from fastapi import HTTPException
from ..db import get_connection
from ..schemas.http import NoteCitationIn
from .workspaces import require_workspace

logger = logging.getLogger(__name__)
CITATION_MARK = re.compile(r'\[(c\d+)\]')

def _now():
    return datetime.now(timezone.utc).isoformat()

def _citation_order(value: str):
    return int(value[1:]) if value[1:].isdigit() else 0

def _require_note(db, note_id: str):
    row = db.execute('SELECT * FROM notes WHERE id=?', (note_id,)).fetchone()
    if row is None:
        raise HTTPException(404, '노트를 찾을 수 없습니다')
    return row

def _check_workspaces(db, workspace_ids):
    unique = list(dict.fromkeys(workspace_ids))
    for workspace_id in unique:
        if db.execute('SELECT 1 FROM workspaces WHERE id=?', (workspace_id,)).fetchone() is None:
            raise HTTPException(422, f'연결할 워크스페이스가 없습니다: {workspace_id}')
    return unique

def _normalize_citations(db, body: str, citations: list[NoteCitationIn], note_id: str | None):
    """Keep only citations referenced in the body; reject markers without a mapping."""
    ids = [citation.id for citation in citations]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, '인용 번호가 중복되었습니다')
    used = set(CITATION_MARK.findall(body))
    unmapped = sorted(used - set(ids), key=_citation_order)
    if unmapped:
        raise HTTPException(422, '본문의 인용 표시에 대응하는 원본 정보가 없습니다: ' + ', '.join(f'[{value}]' for value in unmapped))
    kept = sorted((citation for citation in citations if citation.id in used), key=lambda c: _citation_order(c.id))
    for citation in kept:
        if citation.source_type == 'doc':
            if db.execute('SELECT 1 FROM documents WHERE id=?', (citation.document_id,)).fetchone() is None:
                raise HTTPException(422, f'[{citation.id}] 인용 자료를 찾을 수 없습니다')
        else:
            if citation.note_id == note_id:
                raise HTTPException(422, f'[{citation.id}] 노트는 자기 자신을 인용할 수 없습니다')
            if db.execute('SELECT 1 FROM notes WHERE id=?', (citation.note_id,)).fetchone() is None:
                raise HTTPException(422, f'[{citation.id}] 인용 노트를 찾을 수 없습니다')
    return kept

def _write_citations(db, note_id: str, citations: list[NoteCitationIn]):
    db.execute('DELETE FROM note_citations WHERE note_id=?', (note_id,))
    db.executemany('INSERT INTO note_citations(note_id,citation_id,source_type,document_id,page,quote,cited_note_id) VALUES (?,?,?,?,?,?,?)',
        [(note_id, c.id, c.source_type, c.document_id if c.source_type == 'doc' else None,
          c.page if c.source_type == 'doc' else None, c.quote, c.note_id if c.source_type == 'note' else None) for c in citations])

def _run_index(note_id: str):
    """C contract: index_note(note_id) replaces chunks and sets notes.index_status; it should not raise."""
    try:
        from .note_index import index_note
        index_note(note_id)
    except Exception:
        logger.exception('note indexing failed for %s', note_id)

def get_note(note_id: str):
    with get_connection() as db:
        note = dict(_require_note(db, note_id))
        note['workspace_ids'] = [r['workspace_id'] for r in db.execute('SELECT workspace_id FROM workspace_notes WHERE note_id=? ORDER BY workspace_id', (note_id,))]
        citations = []
        for row in db.execute('''SELECT c.*, d.filename AS doc_title, n.title AS note_title FROM note_citations c
                LEFT JOIN documents d ON c.source_type='doc' AND d.id=c.document_id
                LEFT JOIN notes n ON c.source_type='note' AND n.id=c.cited_note_id
                WHERE c.note_id=?''', (note_id,)):
            is_doc = row['source_type'] == 'doc'
            title = row['doc_title'] if is_doc else row['note_title']
            citations.append({'id': row['citation_id'], 'source_type': row['source_type'],
                'document_id': row['document_id'] if is_doc else None, 'note_id': None if is_doc else row['cited_note_id'],
                'page': row['page'], 'quote': row['quote'] or '', 'title': title or '', 'missing': title is None})
        note['citations'] = sorted(citations, key=lambda c: _citation_order(c['id']))
        return note

def list_notes(q: str | None = None, workspace_id: str | None = None):
    if workspace_id:
        require_workspace(workspace_id)
    sql = 'SELECT n.id,n.title,n.index_status,n.created_at,n.updated_at FROM notes n'
    params = []
    where = []
    if workspace_id:
        sql += ' JOIN workspace_notes w ON w.note_id=n.id'
        where.append('w.workspace_id=?')
        params.append(workspace_id)
    if q and q.strip():
        escaped = q.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        where.append("n.title LIKE ? ESCAPE '\\'")
        params.append(f'%{escaped}%')
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY n.updated_at DESC,n.id'
    with get_connection() as db:
        notes = [dict(r) for r in db.execute(sql, params)]
        for note in notes:
            note['workspace_ids'] = [r['workspace_id'] for r in db.execute('SELECT workspace_id FROM workspace_notes WHERE note_id=? ORDER BY workspace_id', (note['id'],))]
    return notes

def create_note(title: str, body: str, workspace_ids: list[str], citations: list[NoteCitationIn]):
    note_id = str(uuid4())
    now = _now()
    with get_connection() as db:
        linked = _check_workspaces(db, workspace_ids)
        kept = _normalize_citations(db, body, citations, note_id)
        # Not searchable until index_note succeeds.
        db.execute("INSERT INTO notes(id,title,body,index_status,created_at,updated_at) VALUES (?,?,?,'failed',?,?)", (note_id, title, body, now, now))
        db.executemany('INSERT OR IGNORE INTO workspace_notes(workspace_id,note_id) VALUES (?,?)', [(w, note_id) for w in linked])
        _write_citations(db, note_id, kept)
    _run_index(note_id)
    return get_note(note_id)

def update_note(note_id: str, title: str, body: str, citations: list[NoteCitationIn], workspace_ids: list[str] | None = None):
    with get_connection() as db:
        _require_note(db, note_id)
        linked = _check_workspaces(db, workspace_ids) if workspace_ids is not None else None
        kept = _normalize_citations(db, body, citations, note_id)
        # Old chunks must never answer for the new body: hide and drop them until re-indexed.
        db.execute("UPDATE notes SET title=?,body=?,index_status='failed',updated_at=? WHERE id=?", (title, body, _now(), note_id))
        db.execute("DELETE FROM chunks WHERE source_type='note' AND source_id=?", (note_id,))
        _write_citations(db, note_id, kept)
        if linked is not None:
            db.execute('DELETE FROM workspace_notes WHERE note_id=?', (note_id,))
            db.executemany('INSERT OR IGNORE INTO workspace_notes(workspace_id,note_id) VALUES (?,?)', [(w, note_id) for w in linked])
    _run_index(note_id)
    return get_note(note_id)

def link_note(workspace_id: str, note_id: str):
    require_workspace(workspace_id)
    with get_connection() as db:
        _require_note(db, note_id)
        db.execute('INSERT OR IGNORE INTO workspace_notes(workspace_id,note_id) VALUES (?,?)', (workspace_id, note_id))
    return get_note(note_id)

def unlink_note(workspace_id: str, note_id: str):
    require_workspace(workspace_id)
    with get_connection() as db:
        _require_note(db, note_id)
        db.execute('DELETE FROM workspace_notes WHERE workspace_id=? AND note_id=?', (workspace_id, note_id))
    return get_note(note_id)
