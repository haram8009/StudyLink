import numpy as np
import pymupdf
import pytest
from fastapi.testclient import TestClient
from app.config import get_settings
from app.db import get_connection

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setenv('MOCK_LLM', '1')
    monkeypatch.setenv('LANGFUSE_ENABLED', '0')
    monkeypatch.setenv('EMBEDDING_DIM', '1536')
    get_settings.cache_clear()
    from app.main import app
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()

def pdf_bytes(pages):
    with pymupdf.open() as pdf:
        for text in pages:
            page = pdf.new_page()
            page.insert_textbox((40, 40, 550, 800), text)
        return pdf.tobytes()

def workspace(client):
    response = client.post('/api/workspaces', json={'title': 'NLP', 'goal': 'Learn embeddings'})
    assert response.status_code == 201
    return response.json()['id']

def upload(client, ws, pages):
    return client.post(f'/api/workspaces/{ws}/documents', files={'file': ('study.pdf', pdf_bytes(pages), 'application/pdf')})

def test_upload_ready_atomic_chunks_and_pdf(client):
    ws = workspace(client)
    response = upload(client, ws, ['Repeated heading\nGradient descent adjusts weights toward lower loss.\nRepeated footer\n1',
                                  'Repeated heading\nA vanishing gradient becomes very small during backpropagation.\nRepeated footer\n2'])
    assert response.status_code == 202
    assert response.json()['status'] == 'processing'
    doc = response.json()['id']
    ready = client.get(f'/api/documents/{doc}').json()
    assert ready['status'] == 'ready' and ready['page_count'] == 2
    assert 'path' not in ready
    with get_connection() as db:
        chunks = db.execute('SELECT * FROM chunks WHERE source_id=? ORDER BY page', (doc,)).fetchall()
        assert [row['page'] for row in chunks] == [1, 2]
        assert all('Repeated heading' not in row['text'] for row in chunks)
        assert all('Repeated footer' not in row['text'] for row in chunks)
        assert all(len(np.frombuffer(row['embedding'], dtype=np.float32)) == 1536 for row in chunks)
    original = client.get(f'/api/documents/{doc}/file')
    assert original.status_code == 200
    assert original.headers['content-disposition'].startswith('inline')
    assert client.get(f'/api/workspaces/{ws}').json()['documents'][0]['id'] == doc
    assert client.post(f'/api/documents/{doc}/retry').status_code == 400

def test_failure_cleanup_and_retry(client, monkeypatch):
    from app.services import ingest
    original = ingest.embed
    def fail(texts):
        raise RuntimeError('secret provider failure')
    monkeypatch.setattr(ingest, 'embed', fail)
    response = upload(client, workspace(client), ['Neural networks learn a useful representation from training examples.'])
    doc = response.json()['id']
    failed = client.get(f'/api/documents/{doc}').json()
    assert failed['status'] == 'failed' and 'secret' not in failed['error']
    with get_connection() as db:
        assert db.execute('SELECT count(*) FROM chunks WHERE source_id=?', (doc,)).fetchone()[0] == 0
    monkeypatch.setattr(ingest, 'embed', original)
    assert client.post(f'/api/documents/{doc}/retry').status_code == 202
    assert client.get(f'/api/documents/{doc}').json()['status'] == 'ready'

def test_input_errors_and_scan(client, monkeypatch):
    ws = workspace(client)
    assert client.post('/api/workspaces', json={'title': '   '}).status_code == 422
    assert client.get('/api/workspaces/missing').status_code == 404
    assert client.post(f'/api/workspaces/{ws}/documents', files={'file': ('fake.pdf', b'not pdf', 'application/pdf')}).status_code == 422
    scan = upload(client, ws, ['', ''])
    doc = client.get('/api/documents/' + scan.json()['id']).json()
    assert doc['status'] == 'failed' and '스캔' in doc['error']
    monkeypatch.setenv('MAX_UPLOAD_BYTES', '10')
    get_settings.cache_clear()
    assert upload(client, ws, ['Some text']).status_code == 413

def test_restart_preserves_ready_and_recovers_processing(client):
    ws = workspace(client)
    doc = upload(client, ws, ['Neural networks learn features from data for classification tasks.']).json()['id']
    with get_connection() as db:
        db.execute("INSERT INTO documents(id,workspace_id,filename,path,status) VALUES ('interrupted',?,'x.pdf','missing','processing')", (ws,))
    from app.main import app
    with TestClient(app) as restarted:
        assert restarted.get('/api/workspaces').json()[0]['id'] == ws
        assert restarted.get('/api/documents/' + doc).json()['status'] == 'ready'
        interrupted = restarted.get('/api/documents/interrupted').json()
        assert interrupted['status'] == 'failed' and '재시작' in interrupted['error']

def test_mock_real_database_isolation(client, monkeypatch):
    workspace(client)
    mock_path = get_settings().db_path
    monkeypatch.setenv('MOCK_LLM', '0')
    get_settings.cache_clear()
    assert get_settings().db_path != mock_path
