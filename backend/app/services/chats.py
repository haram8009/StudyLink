"""Chats own question/answer history inside a workspace; context never crosses chats (ADR 0002)."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import threading
from uuid import uuid4
from fastapi import HTTPException
from ..db import get_connection
from .workspaces import require_workspace

DEFAULT_TITLE = '새 채팅'
HISTORY_MAX_PAIRS = 6
HISTORY_MAX_CHARS = 12_000
CHAT_COLUMNS = 'id,workspace_id,title,created_at,updated_at'

class ChatBusy(RuntimeError):
    pass

_active: set[str] = set()
_active_guard = threading.Lock()
_default_guard = threading.Lock()

def _now():
    return datetime.now(timezone.utc).isoformat()

def list_chats(workspace_id: str):
    require_workspace(workspace_id)
    with get_connection() as db:
        return [dict(r) for r in db.execute(f'SELECT {CHAT_COLUMNS} FROM chats WHERE workspace_id=? ORDER BY updated_at DESC,id', (workspace_id,))]

def create_chat(workspace_id: str, title: str | None = None):
    require_workspace(workspace_id)
    now = _now()
    chat = dict(id=str(uuid4()), workspace_id=workspace_id, title=(title or '').strip() or DEFAULT_TITLE, created_at=now, updated_at=now)
    with get_connection() as db:
        db.execute('INSERT INTO chats(id,workspace_id,title,created_at,updated_at) VALUES (:id,:workspace_id,:title,:created_at,:updated_at)', chat)
    return chat

def get_chat(chat_id: str):
    with get_connection() as db:
        row = db.execute(f'SELECT {CHAT_COLUMNS} FROM chats WHERE id=?', (chat_id,)).fetchone()
    if row is None:
        raise HTTPException(404, '채팅을 찾을 수 없습니다')
    return dict(row)

def default_chat(workspace_id: str):
    """Compatibility target for workspace-level ask: the most recently used chat, created if none exists."""
    require_workspace(workspace_id)
    with _default_guard:
        with get_connection() as db:
            row = db.execute(f'SELECT {CHAT_COLUMNS} FROM chats WHERE workspace_id=? ORDER BY updated_at DESC,id LIMIT 1', (workspace_id,)).fetchone()
        return dict(row) if row else create_chat(workspace_id)

def touch_chat(chat_id: str):
    with get_connection() as db:
        db.execute('UPDATE chats SET updated_at=? WHERE id=?', (_now(), chat_id))

def attach_answer(chat_id: str, answer_id: str):
    """Safety net when the answer service stored the row without chat_id."""
    with get_connection() as db:
        db.execute('UPDATE answers SET chat_id=? WHERE id=? AND chat_id IS NULL', (chat_id, answer_id))

@contextmanager
def chat_turn(chat_id: str):
    """In-process guard: one answer generation per chat at a time."""
    with _active_guard:
        if chat_id in _active:
            raise ChatBusy(chat_id)
        _active.add(chat_id)
    try:
        yield
    finally:
        with _active_guard:
            _active.discard(chat_id)

def answer_item(row) -> dict:
    """Stored answer row -> question response format plus question/chat metadata."""
    body = json.loads(row['body_json'])
    return {
        'answer_id': row['id'], 'status': body.get('status', 'insufficient_evidence'),
        'segments': body.get('segments', []), 'citations': body.get('citations', []),
        'question': row['question'], 'created_at': row['created_at'],
        'chat_id': row['chat_id'], 'workspace_id': row['workspace_id'],
    }

def list_messages(chat_id: str):
    get_chat(chat_id)
    with get_connection() as db:
        rows = db.execute('SELECT * FROM answers WHERE chat_id=? ORDER BY created_at,rowid', (chat_id,)).fetchall()
    return [answer_item(row) for row in rows]

def get_answer(answer_id: str):
    with get_connection() as db:
        row = db.execute('SELECT * FROM answers WHERE id=?', (answer_id,)).fetchone()
    if row is None:
        raise HTTPException(404, '답변을 찾을 수 없습니다')
    return answer_item(row)

def recent_answers(workspace_id: str, limit: int = 20):
    require_workspace(workspace_id)
    with get_connection() as db:
        rows = db.execute('SELECT * FROM answers WHERE workspace_id=? ORDER BY created_at DESC,rowid DESC LIMIT ?', (workspace_id, limit)).fetchall()
    return [answer_item(row) for row in rows]

def load_history(chat_id: str) -> list[dict]:
    """Recent completed turns of this chat only: at most 6 pairs and 12,000 chars, oldest first.

    Newer turns win when the budget is exceeded; a single oversized newest turn is truncated.
    """
    with get_connection() as db:
        rows = db.execute('SELECT question, body_json FROM answers WHERE chat_id=? ORDER BY created_at DESC,rowid DESC LIMIT ?',
                          (chat_id, HISTORY_MAX_PAIRS)).fetchall()
    selected = []
    budget = HISTORY_MAX_CHARS
    for row in rows:
        body = json.loads(row['body_json'])
        question = row['question']
        answer = ''.join(segment.get('text', '') for segment in body.get('segments', []))
        size = len(question) + len(answer)
        if size <= budget:
            selected.append({'question': question, 'answer': answer})
            budget -= size
            continue
        if not selected:
            question = question[:budget]
            answer = answer[:budget - len(question)]
            selected.append({'question': question, 'answer': answer})
        break
    selected.reverse()
    return selected
