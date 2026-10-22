from fastapi import APIRouter, BackgroundTasks, File, UploadFile
from fastapi.responses import FileResponse
from ..schemas.http import WorkspaceCreate, AskRequest, HighlightRequest
from ..services import chats, workspaces, documents, quotes
from ..services.ingest import ingest_document
from .chats import ask_in_chat

router = APIRouter(prefix='/api')

@router.get('/workspaces')
def list_workspaces():
    return workspaces.list_workspaces()

@router.post('/workspaces', status_code=201)
def create_workspace(body: WorkspaceCreate):
    return workspaces.create_workspace(body.title, body.goal)

@router.get('/workspaces/{workspace_id}')
def get_workspace(workspace_id: str):
    return workspaces.get_workspace(workspace_id)

@router.post('/workspaces/{workspace_id}/documents', status_code=202)
def upload_document(workspace_id: str, background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    document = documents.upload_document(workspace_id, file)
    background_tasks.add_task(ingest_document, document['id'])
    return document

@router.get('/documents/{document_id}')
def get_document(document_id: str):
    return documents.get_document(document_id)

@router.post('/documents/{document_id}/retry', status_code=202)
def retry_document(document_id: str, background_tasks: BackgroundTasks):
    document = documents.retry_document(document_id)
    background_tasks.add_task(ingest_document, document_id)
    return document

@router.get('/documents/{document_id}/file')
def get_document_file(document_id: str):
    path, filename = documents.document_path(document_id)
    return FileResponse(path, media_type='application/pdf', filename=filename, content_disposition_type='inline')

@router.post('/documents/{document_id}/highlight')
def highlight_quote(document_id: str, body: HighlightRequest):
    return quotes.find_highlights(document_id, body.page, body.quote)

@router.post('/workspaces/{workspace_id}/ask')
def ask(workspace_id: str, body: AskRequest):
    """Compatibility endpoint: asks in the workspace's default chat (most recently used, created if none)."""
    return ask_in_chat(chats.default_chat(workspace_id), body)
