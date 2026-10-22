"""Day-three notes agent: related_notes search and the note_draft graph/service (GMS stand-ins, deterministic vectors)."""
import json
import numpy as np
import pytest
from app.adapters import gms
from app.config import get_settings
from app.db import get_connection, init_db
from app.schemas.http import NoteCitationIn
from app.schemas.note_draft import GeneratedNoteDraft
from app.services import note_draft as note_draft_service
from app.services.note_draft import AnswerNotFound, AnswerNotGrounded, draft_note
from app.services.notes import create_note, get_note
from app.services.related_notes import related_notes

DIM = 8
TABLES = ('workspaces', 'documents', 'chunks', 'notes', 'workspace_notes', 'note_citations', 'chats', 'answers')


def unit(*weights):
    vector = np.zeros(DIM, dtype=np.float32)
    for index, value in enumerate(weights):
        vector[index] = value
    return vector


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setenv('MOCK_LLM', '1')
    monkeypatch.setenv('MOCK_SCENARIO', 'normal')
    monkeypatch.setenv('LANGFUSE_ENABLED', '0')
    monkeypatch.setenv('EMBEDDING_DIM', str(DIM))
    monkeypatch.setenv('MIN_SCORE', '0.2')
    get_settings.cache_clear()
    init_db()
    with get_connection() as db:
        for workspace in ('w', 'other'):
            db.execute('INSERT INTO workspaces(id,title,goal,created_at) VALUES(?,?,?,?)', (workspace, workspace, '', 'now'))
    yield
    get_settings.cache_clear()


def counts():
    with get_connection() as db:
        return {table: db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in TABLES}


def add_note(identifier, chunks, workspaces=(), status='ok', title=None, dim=DIM):
    """chunks: [(chunk_text, vector)]"""
    settings = get_settings()
    title = title or identifier
    with get_connection() as db:
        db.execute('INSERT INTO notes(id,title,body,index_status,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                   (identifier, title, 'body', status, 'now', 'now'))
        for workspace in workspaces:
            db.execute('INSERT INTO workspace_notes VALUES(?,?)', (workspace, identifier))
        for number, (text, vector) in enumerate(chunks):
            db.execute('INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?)', (f'{identifier}-{number}', 'note', identifier, None,
                       f'{title}\n{text}', np.asarray(vector, dtype=np.float32).tobytes(), settings.embedding_model, dim))


def add_doc(identifier, workspace='w'):
    with get_connection() as db:
        db.execute('INSERT INTO documents(id,workspace_id,filename,path,page_count,status,error) VALUES(?,?,?,?,?,?,?)',
                   (identifier, workspace, identifier + '.pdf', 'unused', 5, 'ready', None))


def fixed_embed(monkeypatch, vector, log=None):
    def embed(texts, **kwargs):
        if log is not None:
            log.extend(texts)
        return np.stack([np.asarray(vector, dtype=np.float32) for _ in texts])
    monkeypatch.setattr(gms, 'embed', embed)


# --- related notes -------------------------------------------------------------------------

def test_related_notes_returns_up_to_three_distinct_notes_best_chunk_first(monkeypatch):
    fixed_embed(monkeypatch, unit(1))
    add_note('a', [('weak paragraph', unit(1, 1)), ('best paragraph', unit(1))], workspaces=('w',))
    add_note('b', [('b text', unit(1, .5))])
    add_note('c', [('c text', unit(1, 1.5))], workspaces=('other',))
    add_note('d', [('d text', unit(1, 3))])
    add_note('e', [('e text', unit(0, 1))])                        # below MIN_SCORE
    result = related_notes('기울기 소실 정리')
    assert [item['note_id'] for item in result] == ['a', 'b', 'c']
    assert result[0] == {'note_id': 'a', 'title': 'a', 'snippet': 'best paragraph'}
    assert all(set(item) == {'note_id', 'title', 'snippet'} for item in result)   # no score exposed


def test_related_notes_excludes_self_failed_index_and_other_embedding_dims(monkeypatch):
    fixed_embed(monkeypatch, unit(1))
    add_note('self', [('same', unit(1))])
    add_note('failed', [('same', unit(1))], status='failed')
    add_note('olddim', [('same', np.ones(4))], dim=4)
    add_note('unlinked', [('same', unit(1, .2))])                 # no workspace link: still in scope
    assert [item['note_id'] for item in related_notes('query', exclude_note_id='self')] == ['unlinked']
    assert [item['note_id'] for item in related_notes('query', k=1)] == ['self']


def test_related_notes_does_not_store_input_and_handles_empty_text(monkeypatch):
    log = []
    fixed_embed(monkeypatch, unit(1), log)
    add_note('a', [('text', unit(1))])
    before = counts()
    assert related_notes('저장하지 않을 편집 중 본문')[0]['note_id'] == 'a'
    assert counts() == before
    with get_connection() as db:
        assert db.execute("SELECT COUNT(*) FROM chunks WHERE text LIKE '%저장하지 않을%'").fetchone()[0] == 0
    assert related_notes('   ') == [] and related_notes('') == []
    assert log == ['저장하지 않을 편집 중 본문']


def test_related_notes_propagates_provider_errors(monkeypatch):
    add_note('a', [('text', unit(1))])
    def broken(texts, **kwargs):
        raise gms.ProviderUnavailable('down')
    monkeypatch.setattr(gms, 'embed', broken)
    with pytest.raises(gms.ProviderUnavailable):
        related_notes('query')


# --- note draft ----------------------------------------------------------------------------

def add_answer(identifier='ans', status='grounded', segments=None, citations=None, question='기울기 소실은 왜 생기나요?'):
    segments = segments if segments is not None else [
        {'text': '시그모이드의 기울기는 작다.', 'citation_ids': ['e1']},
        {'text': '층이 깊으면 기울기가 곱해져 사라진다.', 'citation_ids': ['e3', 'e1']},
        {'text': '노트에 잔차 연결이 정리되어 있다.', 'citation_ids': ['e4']},
    ]
    citations = citations if citations is not None else [
        {'id': 'e1', 'source_type': 'doc', 'document_id': 'doc1', 'note_id': None, 'page': 3, 'title': 'doc1.pdf', 'quote': 'sigmoid quote'},
        {'id': 'e3', 'source_type': 'doc', 'document_id': 'doc1', 'note_id': None, 'page': 5, 'title': 'doc1.pdf', 'quote': 'chain rule quote'},
        {'id': 'e4', 'source_type': 'note', 'document_id': None, 'note_id': 'n-src', 'page': None, 'title': 'src', 'quote': 'note quote'},
    ]
    body = {'answer_id': identifier, 'status': status, 'segments': segments, 'citations': citations}
    with get_connection() as db:
        db.execute('INSERT INTO answers(id,workspace_id,chat_id,question,body_json,created_at) VALUES(?,?,?,?,?,?)',
                   (identifier, 'w', None, question, json.dumps(body, ensure_ascii=False), 'now'))


def scripted_llm(monkeypatch, outputs, calls=None):
    """complete_json stand-in: each output is a GeneratedNoteDraft dict or an exception."""
    outputs = list(outputs)
    calls = calls if calls is not None else []
    def complete_json(prompt, schema, **kwargs):
        assert schema is GeneratedNoteDraft and kwargs['schema_name'] == 'note_draft'
        calls.append((json.loads(prompt), kwargs['prompt_version']))
        value = outputs.pop(0)
        if isinstance(value, Exception):
            raise value
        return GeneratedNoteDraft(**value)
    monkeypatch.setattr(gms, 'complete_json', complete_json)
    return calls


def test_draft_limits_citations_to_source_answer_and_renumbers_without_storing(monkeypatch):
    add_answer()
    calls = scripted_llm(monkeypatch, [{'title': '기울기 소실', 'body':
        '## 원인\n\n깊은 층에서 사라진다 [e3]. 시그모이드 때문 [e1][e1]. 지어낸 출처 [e9]. 잔차 [e4, e9]. 이상한 [c7]'}])
    before = counts()
    draft = draft_note('ans')
    assert counts() == before
    assert draft['fallback'] is False and draft['title'] == '기울기 소실'
    assert draft['body'] == '## 원인\n\n깊은 층에서 사라진다 [c1]. 시그모이드 때문 [c2]. 지어낸 출처 . 잔차 [c3]. 이상한'
    assert draft['citations'] == [
        {'id': 'c1', 'source_type': 'doc', 'document_id': 'doc1', 'page': 5, 'quote': 'chain rule quote', 'note_id': None},
        {'id': 'c2', 'source_type': 'doc', 'document_id': 'doc1', 'page': 3, 'quote': 'sigmoid quote', 'note_id': None},
        {'id': 'c3', 'source_type': 'note', 'document_id': None, 'page': None, 'quote': 'note quote', 'note_id': 'n-src'},
    ]
    prompt, version = calls[0]
    assert version == 'note-draft-v1'
    assert prompt['allowed_citation_ids'] == ['e1', 'e3', 'e4'] and prompt['question'] == '기울기 소실은 왜 생기나요?'


def test_draft_regenerates_once_then_succeeds(monkeypatch):
    add_answer()
    calls = scripted_llm(monkeypatch, [gms.ModelOutputError('bad'), {'title': 't', 'body': '정리 [e1]'}])
    draft = draft_note('ans')
    assert len(calls) == 2 and draft['fallback'] is False and draft['body'] == '정리 [c1]'


def test_draft_falls_back_after_regeneration_is_exhausted(monkeypatch):
    add_answer()
    calls = scripted_llm(monkeypatch, [{'title': 't', 'body': '출처 없음 [e9]'}, {'title': 't', 'body': '인용 없는 요약'}])
    draft = draft_note('ans')
    assert len(calls) == 2 and draft['fallback'] is True
    assert draft['title'] == '기울기 소실은 왜 생기나요'
    assert draft['body'] == ('시그모이드의 기울기는 작다. [c1]\n\n층이 깊으면 기울기가 곱해져 사라진다. [c2][c1]\n\n'
                             '노트에 잔차 연결이 정리되어 있다. [c3]')
    assert [(c['id'], c['page'], c['note_id']) for c in draft['citations']] == [('c1', 3, None), ('c2', 5, None), ('c3', None, 'n-src')]


def test_draft_falls_back_immediately_on_provider_error(monkeypatch):
    add_answer()
    calls = scripted_llm(monkeypatch, [gms.ProviderUnavailable('down')])
    draft = draft_note('ans')
    assert len(calls) == 1 and draft['fallback'] is True and len(draft['citations']) == 3


def test_draft_falls_back_when_deadline_is_spent(monkeypatch):
    add_answer()
    monkeypatch.setattr(note_draft_service, 'DEADLINE_SECONDS', -1.0)
    draft = draft_note('ans')       # real mock-mode adapter: check_deadline raises before any model call
    assert draft['fallback'] is True and draft['body'].startswith('시그모이드의 기울기는 작다. [c1]')


@pytest.mark.parametrize('scenario, fallback', [('normal', False), ('invalid_json', True), ('provider_error', True), ('invalid_citation', True)])
def test_draft_mock_mode_scenarios(monkeypatch, scenario, fallback):
    monkeypatch.setenv('MOCK_SCENARIO', scenario)
    get_settings.cache_clear()
    add_answer()
    first, second = draft_note('ans'), draft_note('ans')
    assert first == second and first['fallback'] is fallback
    if not fallback:
        assert first['title'] == '기울기 소실은 왜 생기나요' and first['body'].startswith('## 핵심 정리')
        assert [c['id'] for c in first['citations']] == ['c1', 'c2', 'c3']


def test_draft_rejects_missing_and_ungrounded_answers(monkeypatch):
    calls = scripted_llm(monkeypatch, [])
    with pytest.raises(AnswerNotFound):
        draft_note('nope')
    add_answer('insufficient', status='insufficient_evidence', segments=[], citations=[])
    with pytest.raises(AnswerNotGrounded):
        draft_note('insufficient')
    add_answer('broken', segments=[{'text': '근거 없는 문장', 'citation_ids': ['e2']}])
    with pytest.raises(AnswerNotGrounded):
        draft_note('broken')
    assert calls == []


def test_draft_citations_save_through_notes_service_without_422(monkeypatch):
    add_doc('doc1')
    add_note('n-src', [('잔차 연결', unit(1))], title='잔차 연결 정리')
    add_answer()
    scripted_llm(monkeypatch, [{'title': '기울기 소실', 'body': '사라진다 [e3]. 시그모이드 [e1]. 잔차 [e4]. 가짜 [e8]'}])
    draft = draft_note('ans')
    # create_note runs index_note with the mock-mode embedder (only complete_json is replaced).
    saved =create_note(draft['title'], draft['body'], ['w'], [NoteCitationIn(**c) for c in draft['citations']])
    note = get_note(saved['id'])
    assert note['body'] == draft['body']
    assert [(c['id'], c['source_type'], c['document_id'], c['page'], c['note_id']) for c in note['citations']] == [
        ('c1', 'doc', 'doc1', 5, None), ('c2', 'doc', 'doc1', 3, None), ('c3', 'note', None, None, 'n-src')]
    assert not any(c['missing'] for c in note['citations'])
