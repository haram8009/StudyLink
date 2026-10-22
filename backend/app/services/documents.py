from pathlib import Path
from uuid import uuid4
from fastapi import HTTPException, UploadFile
from ..config import get_settings
from ..db import get_connection
from .workspaces import get_workspace

PUBLIC_COLUMNS = 'id,workspace_id,filename,page_count,status,error'

def get_document(document_id: str, *, internal=False):
    with get_connection() as db:
        row = db.execute(f'SELECT {"*" if internal else PUBLIC_COLUMNS} FROM documents WHERE id=?', (document_id,)).fetchone()
    if row is None:
        raise HTTPException(404, '자료를 찾을 수 없습니다')
    return dict(row)

def upload_document(workspace_id: str, upload: UploadFile):
    get_workspace(workspace_id)
    filename = (upload.filename or '').replace('\\', '/').split('/')[-1]
    if not filename.lower().endswith('.pdf') or upload.content_type not in {'application/pdf', 'application/octet-stream'}:
        raise HTTPException(422, 'PDF 자료만 업로드할 수 있습니다')
    settings = get_settings()
    directory = settings.data_dir / 'uploads'
    directory.mkdir(parents=True, exist_ok=True)
    document_id = str(uuid4())
    path = directory / f'{document_id}.pdf'
    size = 0
    try:
        with path.open('wb') as output:
            while block := upload.file.read(1024 * 1024):
                size += len(block)
                if size > settings.max_upload_bytes:
                    raise HTTPException(413, '자료 크기 제한을 초과했습니다')
                output.write(block)
        with path.open('rb') as source:
            if b'%PDF-' not in source.read(1024):
                raise HTTPException(422, '유효한 PDF 자료가 아닙니다')
        with get_connection() as db:
            db.execute('INSERT INTO documents(id,workspace_id,filename,path,page_count,status) VALUES (?,?,?,?,0,?)',
                       (document_id, workspace_id, filename, str(path), 'processing'))
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return get_document(document_id)

def retry_document(document_id: str):
    get_document(document_id)
    with get_connection() as db:
        result = db.execute("UPDATE documents SET status='processing',error=NULL WHERE id=? AND status='failed'", (document_id,))
        if result.rowcount != 1:
            raise HTTPException(400, '실패한 자료만 재시도할 수 있습니다')
        db.execute("DELETE FROM chunks WHERE source_type='doc' AND source_id=?", (document_id,))
    return get_document(document_id)

def document_path(document_id: str):
    document = get_document(document_id, internal=True)
    path = Path(document['path'])
    if not path.is_file():
        raise HTTPException(404, '원본 PDF를 찾을 수 없습니다')
    return path, document['filename']
