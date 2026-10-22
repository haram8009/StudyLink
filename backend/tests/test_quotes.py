"""Short quotes cut from cited chunks, and their highlight boxes on the PDF page."""
from uuid import uuid4
import pymupdf
import pytest
from fastapi.testclient import TestClient
from app.config import get_settings
from app.db import get_connection, init_db
from app.services.quotes import MAX_QUOTE_CHARS, pick_quote


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setenv('MOCK_LLM', '1')
    monkeypatch.setenv('LANGFUSE_ENABLED', '0')
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def test_pick_quote_returns_closest_lines_within_limit():
    chunk = '\n'.join(['one-hot 인코딩은 단어 하나만 1인 벡터를 만든다',
                       'Vanishing Gradient 문제: 역전파시 오래된 시점의 gradient가',
                       '지수적으로 0에 가까워진다',
                       'LSTM은 cell state를 추가한다'] + ['관련 없는 긴 줄 ' * 6] * 5)
    quote = pick_quote(chunk, '역전파할수록 과거 시점의 gradient가 0에 가까워지는 문제')
    assert 'Vanishing Gradient' in quote
    assert len(quote) <= MAX_QUOTE_CHARS
    assert all(line in chunk.splitlines() for line in quote.splitlines())


def test_pick_quote_caps_a_single_long_line():
    quote = pick_quote('가' * 500, '가나다')
    assert quote == '가' * MAX_QUOTE_CHARS


def make_pdf(path, lines):
    pdf = pymupdf.open()
    page = pdf.new_page()
    for i, line in enumerate(lines):
        page.insert_text((72, 100 + 20 * i), line)
    pdf.save(path)


def test_highlight_endpoint_finds_quote_lines(env):
    init_db()
    path = env / 'doc.pdf'
    make_pdf(path, ['Residual connection learns the difference', 'between input and output', 'unrelated line'])
    workspace_id, document_id = str(uuid4()), str(uuid4())
    with get_connection() as db:
        db.execute('INSERT INTO workspaces(id,title,goal,created_at) VALUES (?,?,?,?)', (workspace_id, 'w', '', 'now'))
        db.execute('INSERT INTO documents(id,workspace_id,filename,path,page_count,status) VALUES (?,?,?,?,1,?)',
                   (document_id, workspace_id, 'doc.pdf', str(path), 'ready'))
    from app.main import app
    client = TestClient(app)
    body = client.post(f'/api/documents/{document_id}/highlight',
                       json={'page': 1, 'quote': 'Residual connection learns the difference\nbetween input and output'}).json()
    assert body['width'] > 0 and body['height'] > 0
    assert len(body['rects']) == 2
    assert body['rects'][0][1] < body['rects'][1][1]  # top-left origin, first line above second

    missing = client.post(f'/api/documents/{document_id}/highlight', json={'page': 1, 'quote': 'not on the page'}).json()
    assert missing['rects'] == []
    assert client.post(f'/api/documents/{document_id}/highlight', json={'page': 2, 'quote': 'x'}).status_code == 404
