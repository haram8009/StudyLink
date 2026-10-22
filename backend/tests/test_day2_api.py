"""Day-two backend: chats, history isolation, legacy migration, notes and links (no external GMS)."""
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import threading
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.config import get_settings
from app.db import get_connection, init_db, legacy_chat_id

BASE_TIME = datetime(2026, 10, 21, tzinfo=timezone.utc)

@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setenv('MOCK_LLM', '1')
    monkeypatch.setenv('LANGFUSE_ENABLED', '0')
    monkeypatch.setenv('EMBEDDING_DIM', '1536')
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()

@pytest.fixture
def indexed(monkeypatch):
    """Stand-in for C's index_note: marks the note ok without embeddings."""
    from app.services import notes
    calls = []
    def fake_index(note_id):
        calls.append(note_id)
        with get_connection() as db:
            db.execute("UPDATE notes SET index_status='ok' WHERE id=?", (note_id,))
    monkeypatch.setattr(notes, '_run_index', fake_index)
    return calls

@pytest.fixture
def client(env, indexed):
    from app.main import app
    with TestClient(app) as client:
        yield client

@pytest.fixture
def answers(monkeypatch):
    """Stand-in for C's answer_question following the day-two contract."""
    from app.schemas.answer import AnswerOut
    from app.services import answer as answer_service
    state = {'calls': [], 'gate': threading.Event(), 'started': threading.Event()}
    def answer_question(workspace_id, question, include_notes=True, *, chat_id=None, history=()):
        state['calls'].append({'workspace_id': workspace_id, 'question': question, 'chat_id': chat_id, 'history': list(history)})
        if question == 'slow':
            state['started'].set()
            assert state['gate'].wait(10)
        answer = AnswerOut(answer_id=str(uuid4()), status='grounded',
            segments=[{'text': f'answer to {question}', 'citation_ids': ['e1']}],
            citations=[{'id': 'e1', 'source_type': 'doc', 'document_id': 'd', 'page': 1, 'title': 'study.pdf', 'quote': 'q'}])
        with get_connection() as db:
            db.execute('INSERT INTO answers(id,workspace_id,question,body_json,created_at,chat_id) VALUES (?,?,?,?,?,?)',
                (answer.answer_id, workspace_id, question, json.dumps(answer.model_dump()), datetime.now(timezone.utc).isoformat(), chat_id))
        return answer
    monkeypatch.setattr(answer_service, 'answer_question', answer_question)
    return state

def make_workspace(client, title='NLP'):
    response = client.post('/api/workspaces', json={'title': title})
    assert response.status_code == 201
    return response.json()['id']

def insert_answer(chat_id, workspace_id, question, text, minutes):
    body = {'answer_id': 'x', 'status': 'grounded', 'segments': [{'text': text, 'citation_ids': ['e1']}], 'citations': []}
    with get_connection() as db:
        db.execute('INSERT INTO answers(id,workspace_id,question,body_json,created_at,chat_id) VALUES (?,?,?,?,?,?)',
            (str(uuid4()), workspace_id, question, json.dumps(body), (BASE_TIME + timedelta(minutes=minutes)).isoformat(), chat_id))

def test_chat_create_list_and_detail(client):
    ws = make_workspace(client)
    first = client.post(f'/api/workspaces/{ws}/chats', json={})
    assert first.status_code == 201 and first.json()['title'] == '새 채팅'
    named = client.post(f'/api/workspaces/{ws}/chats', json={'title': '  어텐션  '}).json()
    assert named['title'] == '어텐션' and named['workspace_id'] == ws
    assert set(named) == {'id', 'workspace_id', 'title', 'created_at', 'updated_at'}
    assert {c['id'] for c in client.get(f'/api/workspaces/{ws}/chats').json()} == {first.json()['id'], named['id']}
    assert client.get(f'/api/chats/{named["id"]}').json() == named
    assert client.get('/api/chats/missing').status_code == 404
    assert client.get('/api/workspaces/missing/chats').status_code == 404
    assert client.post('/api/workspaces/missing/chats', json={}).status_code == 404
    assert client.post(f'/api/workspaces/{ws}/chats', json={'title': 'x' * 201}).status_code == 422
    detail = client.get(f'/api/workspaces/{ws}').json()
    assert {c['id'] for c in detail['chats']} == {first.json()['id'], named['id']}
    assert detail['documents'] == [] and detail['notes'] == []

def test_chat_history_isolated_between_chats(client, answers):
    ws = make_workspace(client)
    a = client.post(f'/api/workspaces/{ws}/chats', json={'title': 'A'}).json()['id']
    b = client.post(f'/api/workspaces/{ws}/chats', json={'title': 'B'}).json()['id']
    first = client.post(f'/api/chats/{a}/ask', json={'question': 'What is attention?'})
    assert first.status_code == 200
    body = first.json()
    assert body['chat_id'] == a and body['question'] == 'What is attention?' and body['status'] == 'grounded'
    assert client.post(f'/api/chats/{a}/ask', json={'question': 'Explain more'}).status_code == 200
    assert client.post(f'/api/chats/{b}/ask', json={'question': 'What is RNN?', 'include_notes': False}).status_code == 200
    calls = answers['calls']
    assert calls[0]['history'] == [] and calls[0]['workspace_id'] == ws and calls[0]['chat_id'] == a
    assert calls[1]['history'] == [{'question': 'What is attention?', 'answer': 'answer to What is attention?'}]
    assert calls[2]['history'] == [] and calls[2]['chat_id'] == b
    a_messages = client.get(f'/api/chats/{a}/messages').json()
    assert [m['question'] for m in a_messages] == ['What is attention?', 'Explain more']
    assert {'answer_id', 'status', 'segments', 'citations', 'question', 'created_at', 'chat_id'} <= set(a_messages[0])
    assert [m['question'] for m in client.get(f'/api/chats/{b}/messages').json()] == ['What is RNN?']
    assert client.get('/api/chats/missing/messages').status_code == 404
    assert client.post('/api/chats/missing/ask', json={'question': 'x'}).status_code == 404
    assert client.post(f'/api/chats/{a}/ask', json={'question': '   '}).status_code == 422
    # Answer recovery
    recent = client.get(f'/api/workspaces/{ws}/answers').json()
    assert [r['question'] for r in recent] == ['What is RNN?', 'Explain more', 'What is attention?']
    single = client.get(f'/api/answers/{body["answer_id"]}').json()
    assert single['question'] == 'What is attention?' and single['chat_id'] == a and single['segments'] == body['segments']
    assert client.get('/api/answers/missing').status_code == 404
    # Asked chat moves to the top of the workspace chat list
    assert client.get(f'/api/workspaces/{ws}/chats').json()[0]['id'] == b

def test_load_history_limits_and_isolation(client):
    from app.services.chats import load_history
    ws = make_workspace(client)
    a = client.post(f'/api/workspaces/{ws}/chats', json={'title': 'A'}).json()['id']
    b = client.post(f'/api/workspaces/{ws}/chats', json={'title': 'B'}).json()['id']
    for i in range(8):
        insert_answer(a, ws, f'q{i}', f'a{i}', i)
    insert_answer(b, ws, 'other chat', 'secret', 100)
    history = load_history(a)
    assert [h['question'] for h in history] == [f'q{i}' for i in range(2, 8)]
    assert history[-1] == {'question': 'q7', 'answer': 'a7'}
    assert all('other chat' != h['question'] for h in history)
    assert load_history(b) == [{'question': 'other chat', 'answer': 'secret'}]
    c = client.post(f'/api/workspaces/{ws}/chats', json={}).json()['id']
    insert_answer(c, ws, 'old', 'x' * 5000, 1)
    insert_answer(c, ws, 'mid', 'y' * 5000, 2)
    insert_answer(c, ws, 'new', 'z' * 5000, 3)
    history = load_history(c)
    assert [h['question'] for h in history] == ['mid', 'new']
    assert sum(len(h['question']) + len(h['answer']) for h in history) <= 12_000
    d = client.post(f'/api/workspaces/{ws}/chats', json={}).json()['id']
    insert_answer(d, ws, 'huge', 'w' * 20_000, 1)
    history = load_history(d)
    assert len(history) == 1 and history[0]['question'] == 'huge'
    assert len(history[0]['question']) + len(history[0]['answer']) == 12_000
    empty = client.post(f'/api/workspaces/{ws}/chats', json={}).json()['id']
    assert load_history(empty) == []

def test_legacy_answers_migrate_idempotently(env):
    db_path = get_settings().db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as old:
        old.executescript('''
            CREATE TABLE workspaces (id TEXT PRIMARY KEY, title TEXT NOT NULL, goal TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
            CREATE TABLE answers (id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), question TEXT NOT NULL,
                body_json TEXT NOT NULL, created_at TEXT NOT NULL);
            INSERT INTO workspaces VALUES ('w1','one','','2026-10-20T00:00:00'),('w2','two','','2026-10-20T00:00:00'),('w3','empty','','2026-10-20T00:00:00');
            INSERT INTO answers VALUES
              ('a1','w1','q1','{"status":"grounded","segments":[{"text":"t1","citation_ids":["e1"]}],"citations":[]}','2026-10-20T01:00:00'),
              ('a2','w1','q2','{"status":"insufficient_evidence","segments":[],"citations":[]}','2026-10-20T02:00:00'),
              ('a3','w2','q3','{"status":"grounded","segments":[],"citations":[]}','2026-10-20T03:00:00');''')
    old.close()
    init_db()
    init_db()
    with get_connection() as db:
        chats = [dict(r) for r in db.execute('SELECT * FROM chats ORDER BY workspace_id')]
        assert [(c['workspace_id'], c['title']) for c in chats] == [('w1', '이전 대화'), ('w2', '이전 대화')]
        assert chats[0]['id'] == legacy_chat_id('w1') and chats[0]['updated_at'] == '2026-10-20T02:00:00'
        assignments = dict(db.execute('SELECT id, chat_id FROM answers').fetchall())
        assert assignments == {'a1': legacy_chat_id('w1'), 'a2': legacy_chat_id('w1'), 'a3': legacy_chat_id('w2')}
    from app.main import app
    with TestClient(app) as client:
        messages = client.get(f'/api/chats/{legacy_chat_id("w1")}/messages').json()
        assert [m['question'] for m in messages] == ['q1', 'q2']
        assert len(client.get('/api/workspaces/w1').json()['chats']) == 1
        assert client.get('/api/workspaces/w3').json()['chats'] == []
    with TestClient(app):
        pass
    with get_connection() as db:
        assert db.execute('SELECT count(*) FROM chats').fetchone()[0] == 2

def test_same_chat_concurrent_ask_is_409(client, answers):
    ws = make_workspace(client)
    a = client.post(f'/api/workspaces/{ws}/chats', json={}).json()['id']
    b = client.post(f'/api/workspaces/{ws}/chats', json={}).json()['id']
    results = {}
    worker = threading.Thread(target=lambda: results.update(slow=client.post(f'/api/chats/{a}/ask', json={'question': 'slow'})))
    worker.start()
    try:
        assert answers['started'].wait(10)
        busy = client.post(f'/api/chats/{a}/ask', json={'question': 'again'})
        assert busy.status_code == 409 and isinstance(busy.json()['detail'], str)
        assert client.post(f'/api/chats/{b}/ask', json={'question': 'other chat'}).status_code == 200
    finally:
        answers['gate'].set()
        worker.join(10)
    assert results['slow'].status_code == 200
    assert client.post(f'/api/chats/{a}/ask', json={'question': 'after'}).status_code == 200

def test_ask_error_mapping_and_compat_ask(client, answers, monkeypatch):
    from app.adapters.gms import ProviderUnavailable
    from app.services import answer as answer_service
    from app.services.retrieval import NoSearchableContent
    ws = make_workspace(client)
    compat = client.post(f'/api/workspaces/{ws}/ask', json={'question': 'legacy route'})
    assert compat.status_code == 200
    chats = client.get(f'/api/workspaces/{ws}/chats').json()
    assert len(chats) == 1 and compat.json()['chat_id'] == chats[0]['id']
    assert client.post(f'/api/workspaces/{ws}/ask', json={'question': 'again'}).json()['chat_id'] == chats[0]['id']
    assert answers['calls'][1]['history'][0]['question'] == 'legacy route'
    assert client.post('/api/workspaces/missing/ask', json={'question': 'x'}).status_code == 404
    def no_content(*args, **kwargs):
        raise NoSearchableContent('검색할 자료나 노트가 없습니다')
    monkeypatch.setattr(answer_service, 'answer_question', no_content)
    response = client.post(f'/api/chats/{chats[0]["id"]}/ask', json={'question': 'x'})
    assert response.status_code == 400 and response.json()['detail'] == '검색할 자료나 노트가 없습니다'
    def unavailable(*args, **kwargs):
        raise ProviderUnavailable('secret')
    monkeypatch.setattr(answer_service, 'answer_question', unavailable)
    response = client.post(f'/api/chats/{chats[0]["id"]}/ask', json={'question': 'x'})
    assert response.status_code == 503 and 'secret' not in response.json()['detail']
    # Lock released after failures
    monkeypatch.setattr(answer_service, 'answer_question', no_content)
    assert client.post(f'/api/chats/{chats[0]["id"]}/ask', json={'question': 'x'}).status_code == 400

def make_document(ws, filename='study.pdf'):
    doc = str(uuid4())
    with get_connection() as db:
        db.execute("INSERT INTO documents(id,workspace_id,filename,path,page_count,status) VALUES (?,?,?,?,3,'ready')", (doc, ws, filename, 'missing.pdf'))
    return doc

def test_notes_create_link_filter_and_citations(client, indexed):
    ws1 = make_workspace(client, 'NLP')
    ws2 = make_workspace(client, 'LLM')
    doc = make_document(ws1)
    base = client.post('/api/notes', json={'title': '기울기 소실 정리', 'body': '역전파 중 기울기가 작아진다 [c1]', 'workspace_ids': [ws1, ws1],
        'citations': [{'id': 'c1', 'source_type': 'doc', 'document_id': doc, 'page': 2, 'quote': 'vanishing'},
                      {'id': 'c2', 'source_type': 'doc', 'document_id': doc, 'page': 3}]})
    assert base.status_code == 201, base.text
    note = base.json()
    assert note['index_status'] == 'ok' and indexed == [note['id']]
    assert note['workspace_ids'] == [ws1]
    assert [c['id'] for c in note['citations']] == ['c1']  # unused c2 dropped
    assert note['citations'][0] | {} == {'id': 'c1', 'source_type': 'doc', 'document_id': doc, 'note_id': None, 'page': 2,
                                         'quote': 'vanishing', 'title': 'study.pdf', 'missing': False}
    mixed = client.post('/api/notes', json={'title': 'Residual 메모', 'body': '[c1] 그리고 [c2]',
        'citations': [{'id': 'c1', 'source_type': 'note', 'note_id': note['id']}, {'id': 'c2', 'source_type': 'doc', 'document_id': doc, 'page': 1}]})
    assert mixed.status_code == 201
    mixed = mixed.json()
    assert mixed['workspace_ids'] == [] and mixed['citations'][0]['title'] == '기울기 소실 정리'
    # Invalid citations -> 422 with string detail and no partial write
    before = len(client.get('/api/notes').json())
    bad = client.post('/api/notes', json={'title': 'bad', 'body': 'text [c1] [c3]', 'citations': [{'id': 'c1', 'source_type': 'doc', 'document_id': doc, 'page': 1}]})
    assert bad.status_code == 422 and '[c3]' in bad.json()['detail']
    assert client.post('/api/notes', json={'title': 'bad', 'body': '[c1]', 'citations': [{'id': 'c1', 'source_type': 'doc', 'document_id': 'nope', 'page': 1}]}).status_code == 422
    assert client.post('/api/notes', json={'title': 'bad', 'body': '[c1]', 'citations': [{'id': 'c1', 'source_type': 'doc', 'document_id': doc}]}).status_code == 422
    assert client.post('/api/notes', json={'title': 'bad', 'body': '[c1]', 'citations': [{'id': 'c1', 'source_type': 'doc', 'document_id': doc, 'page': 1}] * 2}).status_code == 422
    assert client.post('/api/notes', json={'title': 'bad', 'body': 'x', 'workspace_ids': ['missing']}).status_code == 422
    assert client.post('/api/notes', json={'title': '', 'body': 'x'}).status_code == 422
    assert len(client.get('/api/notes').json()) == before
    # Link, duplicate link, filter, unlink keeps original and other links
    linked = client.post(f'/api/workspaces/{ws2}/notes/{note["id"]}')
    assert linked.status_code == 200 and sorted(linked.json()['workspace_ids']) == sorted([ws1, ws2])
    assert client.post(f'/api/workspaces/{ws2}/notes/{note["id"]}').json()['workspace_ids'] == linked.json()['workspace_ids']
    assert indexed == [note['id'], mixed['id']]  # linking never re-indexes
    assert [n['id'] for n in client.get('/api/notes', params={'workspace_id': ws2}).json()] == [note['id']]
    assert [n['id'] for n in client.get('/api/notes', params={'q': 'residual'}).json()] == [mixed['id']]
    assert [n['id'] for n in client.get('/api/notes', params={'q': '소실', 'workspace_id': ws1}).json()] == [note['id']]
    assert client.get('/api/notes', params={'q': '%'}).json() == []
    assert client.get('/api/notes', params={'workspace_id': 'missing'}).status_code == 404
    detail = client.get(f'/api/workspaces/{ws2}').json()
    assert detail['notes'] == [{'id': note['id'], 'title': '기울기 소실 정리', 'index_status': 'ok', 'updated_at': note['updated_at']}]
    unlinked = client.delete(f'/api/workspaces/{ws1}/notes/{note["id"]}')
    assert unlinked.status_code == 200 and unlinked.json()['workspace_ids'] == [ws2]
    assert client.get(f'/api/notes/{note["id"]}').json()['body'] == note['body']
    assert client.get(f'/api/workspaces/{ws1}').json()['notes'] == []
    assert client.post(f'/api/workspaces/{ws1}/notes/missing').status_code == 404
    assert client.delete(f'/api/workspaces/missing/notes/{note["id"]}').status_code == 404
    assert client.get('/api/notes/missing').status_code == 404

def test_note_update_reindexes_and_rejects_atomically(client, indexed, monkeypatch):
    from app.services import notes
    ws = make_workspace(client)
    doc = make_document(ws)
    note = client.post('/api/notes', json={'title': 'T', 'body': 'old [c1]', 'workspace_ids': [ws],
        'citations': [{'id': 'c1', 'source_type': 'doc', 'document_id': doc, 'page': 1}]}).json()
    with get_connection() as db:
        db.execute("INSERT INTO chunks(id,source_type,source_id,page,text,embedding,embedding_model,embedding_dim) VALUES ('old','note',?,NULL,'old',x'00','m',1)", (note['id'],))
    rejected = client.put(f'/api/notes/{note["id"]}', json={'title': 'T2', 'body': 'new [c9]', 'citations': []})
    assert rejected.status_code == 422
    unchanged = client.get(f'/api/notes/{note["id"]}').json()
    assert unchanged['body'] == 'old [c1]' and unchanged['index_status'] == 'ok' and len(unchanged['citations']) == 1
    monkeypatch.setattr(notes, '_run_index', lambda note_id: None)  # simulate indexing failure
    updated = client.put(f'/api/notes/{note["id"]}', json={'title': 'T2', 'body': 'new text without citation', 'citations': []})
    assert updated.status_code == 200
    body = updated.json()
    assert body['title'] == 'T2' and body['citations'] == [] and body['index_status'] == 'failed'
    assert body['workspace_ids'] == [ws]  # workspace_ids omitted keeps links
    with get_connection() as db:
        assert db.execute("SELECT count(*) FROM chunks WHERE source_type='note' AND source_id=?", (note['id'],)).fetchone()[0] == 0
    assert client.put('/api/notes/missing', json={'title': 'x', 'body': 'y'}).status_code == 404
