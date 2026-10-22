import time
import json
import httpx
import numpy as np
import pytest
from app.adapters import gms, telemetry
from app.config import get_settings
from app.db import get_connection, init_db
from app.schemas.answer import GeneratedAnswer
from app.services.answer import answer_question
from app.services.retrieval import NoSearchableContent, retrieve

@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setenv('MOCK_LLM', '1')
    monkeypatch.setenv('MOCK_SCENARIO', 'normal')
    monkeypatch.setenv('LANGFUSE_ENABLED', '0')
    monkeypatch.setenv('EMBEDDING_DIM', '8')
    get_settings.cache_clear()
    init_db()
    with get_connection() as db:
        for workspace in ('w', 'other'):
            db.execute('INSERT INTO workspaces VALUES(?,?,?,?)', (workspace, workspace, '', 'now'))
    yield
    get_settings.cache_clear()

def add(identifier='d', workspace='w', status='ready', model=None, text='gradient explains learning', vector=None):
    settings = get_settings()
    vector = np.array(vector if vector is not None else [1, 0, 0, 0, 0, 0, 0, 0], dtype=np.float32)
    with get_connection() as db:
        db.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?)', (identifier, workspace, identifier+'.pdf', 'unused', 3, status, None))
        db.execute('INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?)', (identifier, 'doc', identifier, 3, text, vector.tobytes(), model or settings.embedding_model, 8))

def fixed_query(monkeypatch):
    monkeypatch.setattr(gms, 'embed', lambda texts, **kwargs: np.array([[1, 0, 0, 0, 0, 0, 0, 0]], dtype=np.float32))

def test_retrieval_excludes_workspace_status_and_model(monkeypatch):
    add('ok'); add('outside', workspace='other'); add('pending', status='processing'); add('old', model='old')
    fixed_query(monkeypatch)
    assert [item.chunk_id for item in retrieve('w', 'question')] == ['ok']

def test_retrieval_limits_characters_and_count(monkeypatch):
    for index in range(15):
        add(str(index), text='x'*1000)
    fixed_query(monkeypatch)
    result = retrieve('w', 'q')
    assert len(result) <= 12
    assert sum(len(item.text) for item in result) == 8000

def test_no_candidates_and_processing():
    with pytest.raises(NoSearchableContent, match='검색할'):
        retrieve('w', 'q')
    add(status='processing')
    with pytest.raises(NoSearchableContent, match='처리하는'):
        retrieve('w', 'q')

def test_grounded_answer_filters_invalid_segments_and_persists(monkeypatch):
    add(); fixed_query(monkeypatch)
    monkeypatch.setattr(gms, 'generate_json', lambda *args, **kwargs: GeneratedAnswer.model_validate({'segments': [
        {'text': 'grounded', 'citation_ids': ['e1','invented']}, {'text': 'unsupported', 'citation_ids': ['e99']}]}))
    result = answer_question('w', 'q')
    assert result.status == 'grounded'
    assert len(result.segments) == 1 and result.segments[0].citation_ids == ['e1']
    assert result.citations[0].document_id == 'd' and result.citations[0].page == 3
    with get_connection() as db:
        assert db.execute('SELECT count(*) FROM answers').fetchone()[0] == 1
        stored = json.loads(db.execute('SELECT body_json FROM answers').fetchone()[0])
        assert stored['retrieval'][0]['chunk_id'] == 'd'
        assert stored['retrieval'][0]['score'] == pytest.approx(1.0)

@pytest.mark.parametrize('scenario', ['invalid_json', 'invalid_citation', 'insufficient'])
def test_output_failure_terminates_with_abstention(monkeypatch, scenario):
    add(); fixed_query(monkeypatch)
    monkeypatch.setenv('MOCK_SCENARIO', scenario); get_settings.cache_clear()
    result = answer_question('w', 'q')
    assert result.status == 'insufficient_evidence' and not result.citations and not result.segments

def test_graph_output_retry_exhaustion(monkeypatch):
    add(); fixed_query(monkeypatch)
    calls = []
    def broken(*args, **kwargs):
        calls.append(1)
        raise gms.ModelOutputError('bad')
    monkeypatch.setattr(gms, 'generate_json', broken)
    assert answer_question('w', 'q').status == 'insufficient_evidence'
    assert len(calls) == 2

def test_provider_failure_is_not_abstention(monkeypatch):
    add(); fixed_query(monkeypatch)
    monkeypatch.setenv('MOCK_SCENARIO', 'provider_error'); get_settings.cache_clear()
    with pytest.raises(gms.ProviderUnavailable):
        answer_question('w', 'q')
    with get_connection() as db:
        assert db.execute('SELECT count(*) FROM answers').fetchone()[0] == 0

def test_low_similarity_abstains_without_generation(monkeypatch):
    add(vector=[0,1,0,0,0,0,0,0]); fixed_query(monkeypatch)
    def forbidden(*args, **kwargs):
        pytest.fail('generation must not run without evidence')
    monkeypatch.setattr(gms, 'generate_json', forbidden)
    assert answer_question('w', 'q').status == 'insufficient_evidence'

def test_telemetry_enter_exit_update_failures_preserve_business_exception(monkeypatch):
    class Broken:
        def start_as_current_observation(self, **kwargs): return self
        def __enter__(self): return self
        def update(self, **kwargs): raise RuntimeError('telemetry update')
        def __exit__(self, *args): raise RuntimeError('telemetry exit')
    monkeypatch.setattr(telemetry, '_client', lambda: Broken())
    with telemetry.observe('fine') as span:
        span.update(output='done')
    with pytest.raises(ValueError, match='business'):
        with telemetry.observe('bad'):
            raise ValueError('business')
    monkeypatch.setattr(telemetry, '_client', lambda: 1/0)
    with telemetry.observe('no-op'):
        pass

@pytest.mark.parametrize('statuses, expected', [([503,200],2),([401],1),([429,429],2)])
def test_http_retry_classification(monkeypatch, statuses, expected):
    monkeypatch.setenv('GMS_KEY', 'test'); get_settings.cache_clear()
    calls=[]
    def post(self, *args, **kwargs):
        calls.append(1)
        return httpx.Response(statuses[len(calls)-1], json={'ok': True})
    monkeypatch.setattr(httpx.Client, 'post', post)
    if statuses[-1] == 200:
        assert gms._post('/test', {}) == {'ok':True}
    else:
        with pytest.raises(gms.ProviderUnavailable): gms._post('/test', {})
    assert len(calls) == expected

def test_deadline_prevents_calls(monkeypatch):
    monkeypatch.setenv('GMS_KEY', 'test'); get_settings.cache_clear()
    with pytest.raises(gms.ProviderUnavailable, match='시간'):
        gms._post('/test', {}, deadline=time.monotonic()-1)

def test_mock_embeddings_stable_and_db_separated(monkeypatch):
    first=gms.embed(['gradient gradient', 'other'])
    assert first.dtype == np.float32 and np.array_equal(first, gms.embed(['gradient gradient', 'other']))
    mock_path = get_settings().db_path
    monkeypatch.setenv('MOCK_LLM', '0'); get_settings.cache_clear()
    assert mock_path != get_settings().db_path

def test_provider_embedding_shape_validation(monkeypatch):
    monkeypatch.setenv('MOCK_LLM', '0'); get_settings.cache_clear()
    monkeypatch.setattr(gms, '_post', lambda *args: {'data':[{'index':0,'embedding':[1,2]}]})
    with pytest.raises(gms.ModelOutputError): gms.embed(['text'])
