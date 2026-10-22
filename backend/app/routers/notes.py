from fastapi import APIRouter
from ..schemas.http import NoteCreate, NoteUpdate
from ..services import notes

router = APIRouter(prefix='/api')

@router.get('/notes')
def list_notes(q: str | None = None, workspace_id: str | None = None):
    return notes.list_notes(q, workspace_id)

@router.post('/notes', status_code=201)
def create_note(body: NoteCreate):
    return notes.create_note(body.title, body.body, body.workspace_ids, body.citations)

@router.get('/notes/{note_id}')
def get_note(note_id: str):
    return notes.get_note(note_id)

@router.put('/notes/{note_id}')
def update_note(note_id: str, body: NoteUpdate):
    return notes.update_note(note_id, body.title, body.body, body.citations, body.workspace_ids)

@router.post('/workspaces/{workspace_id}/notes/{note_id}')
def link_note(workspace_id: str, note_id: str):
    return notes.link_note(workspace_id, note_id)

@router.delete('/workspaces/{workspace_id}/notes/{note_id}')
def unlink_note(workspace_id: str, note_id: str):
    return notes.unlink_note(workspace_id, note_id)
