from datetime import datetime, timezone
from uuid import uuid4
from fastapi import HTTPException
from ..db import get_connection

def list_workspaces():
    with get_connection() as db:
        return [dict(row) for row in db.execute('SELECT * FROM workspaces ORDER BY created_at DESC,id')]

def create_workspace(title: str, goal: str):
    result = dict(id=str(uuid4()), title=title, goal=goal, created_at=datetime.now(timezone.utc).isoformat())
    with get_connection() as db:
        db.execute('INSERT INTO workspaces(id,title,goal,created_at) VALUES (:id,:title,:goal,:created_at)', result)
    return result

def require_workspace(workspace_id: str):
    with get_connection() as db:
        row = db.execute('SELECT * FROM workspaces WHERE id=?', (workspace_id,)).fetchone()
    if row is None:
        raise HTTPException(404, '워크스페이스를 찾을 수 없습니다')
    return dict(row)

def get_workspace(workspace_id: str):
    """Workspace detail: shared resources (documents, linked notes) plus its chats."""
    with get_connection() as db:
        row = db.execute('SELECT * FROM workspaces WHERE id=?', (workspace_id,)).fetchone()
        if row is None:
            raise HTTPException(404, '워크스페이스를 찾을 수 없습니다')
        result = dict(row)
        result['documents'] = [dict(r) for r in db.execute('SELECT id,workspace_id,filename,page_count,status,error FROM documents WHERE workspace_id=? ORDER BY rowid', (workspace_id,))]
        result['notes'] = [dict(r) for r in db.execute('''SELECT n.id,n.title,n.index_status,n.updated_at FROM notes n
            JOIN workspace_notes w ON w.note_id=n.id WHERE w.workspace_id=? ORDER BY n.updated_at DESC,n.id''', (workspace_id,))]
        result['chats'] = [dict(r) for r in db.execute('''SELECT id,workspace_id,title,created_at,updated_at FROM chats
            WHERE workspace_id=? ORDER BY updated_at DESC,id''', (workspace_id,))]
        return result
