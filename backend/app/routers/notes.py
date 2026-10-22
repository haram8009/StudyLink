from fastapi import APIRouter, HTTPException
from ..schemas.http import NoteCreate, NoteUpdate, RelatedNotesRequest
from ..schemas.quiz import NoteDraftOut, RelatedNoteOut
from ..services import notes

router = APIRouter(prefix='/api')
PROVIDER_DOWN = '모델 서비스에 연결할 수 없습니다. 잠시 후 재시도하세요'

@router.post('/answers/{answer_id}/note-draft', response_model=NoteDraftOut)
def note_draft(answer_id: str):
    """Unsaved draft from a grounded answer (C's draft_note); nothing is written to the DB."""
    from ..adapters.gms import ProviderUnavailable
    from ..services.note_draft import AnswerNotFound, AnswerNotGrounded, draft_note
    try:
        return draft_note(answer_id)
    except AnswerNotFound as exc:
        raise HTTPException(404, '답변을 찾을 수 없습니다') from exc
    except AnswerNotGrounded as exc:
        raise HTTPException(422, '근거 부족 답변은 노트 초안으로 만들 수 없습니다') from exc
    except ProviderUnavailable as exc:
        raise HTTPException(503, PROVIDER_DOWN) from exc

@router.post('/notes/related', response_model=list[RelatedNoteOut])
def related(body: RelatedNotesRequest):
    """Search with unsaved title/body; the input is never stored."""
    from ..adapters.gms import ProviderUnavailable
    from ..services.related_notes import related_notes
    text = (body.title + '\n' + body.body).strip()
    if not text:
        return []
    try:
        return (related_notes(text, exclude_note_id=body.exclude_note_id, k=3) or [])[:3]
    except ProviderUnavailable as exc:
        raise HTTPException(503, PROVIDER_DOWN) from exc

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
