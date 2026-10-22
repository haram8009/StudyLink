"""Day-two agent: chat follow-ups, linked-note search, note guarantee, weak-evidence re-search, note indexing."""
import json
import numpy as np
import pytest
from app.adapters import gms
from app.config import get_settings
from app.db import get_connection, init_db
from app.schemas.answer import GeneratedAnswer, NoteLinks, RewrittenQuery
from app.services.answer import answer_question
from app.services.note_index import index_note
from app.services.retrieval import NoSearchableContent, retrieve

DIM = 8

def unit(index):
    vector = np.zeros(DIM, dtype=np.float32)
    vector[index] = 1
    return vector

@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setenv('MOCK_LLM', '1')
    monkeypatch.setenv('MOCK_SCENARIO', 'normal')
    monkeypatch.setenv('LANGFUSE_ENABLED', '0')
    monkeypatch.setenv('EMBEDDING_DIM', str(DIM))
    get_settings.cache_clear()
    init_db()
    with get_connection() as db:
        for workspace in ('w', 'other'):
            db.execute('INSERT INTO workspaces(id,title,goal,created_at) VALUES(?,?,?,?)', (workspace, workspace, '', 'now'))
        # chats / answers.chat_id come from B's schema; answers.chat_id references chats(id).
        for chat in ('chat-a', 'c', 'chat-1'):
            db.execute('INSERT INTO chats(id,workspace_id,title,created_at,updated_at) VALUES(?,?,?,?,?)', (chat, 'w', chat, 'now', 'now'))
    yield
    get_settings.cache_clear()

def add_doc(identifier, workspace='w', vector=None, text='document text'):
    settings = get_settings()
    vector = unit(0) if vector is None else np.asarray(vector, dtype=np.float32)
    with get_connection() as db:
        db.execute('INSERT INTO documents(id,workspace_id,filename,path,page_count,status,error) VALUES(?,?,?,?,?,?,?)',
                   (identifier, workspace, identifier + '.pdf', 'unused', 3, 'ready', None))
        db.execute('INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?)',
                   (identifier, 'doc', identifier, 2, text, vector.tobytes(), settings.embedding_model, DIM))

def add_note(identifier, workspaces=('w',), vector=None, status='ok', text='note text', title=None):
    settings = get_settings()
    vector = unit(0) if vector is None else np.asarray(vector, dtype=np.float32)
    with get_connection() as db:
        db.execute('INSERT INTO notes(id,title,body,index_status,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                   (identifier, title or identifier, text, status, 'now', 'now'))
        for workspace in workspaces:
            db.execute('INSERT INTO workspace_notes VALUES(?,?)', (workspace, identifier))
        db.execute('INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?)',
                   ('chunk-' + identifier, 'note', identifier, None, text, vector.tobytes(), settings.embedding_model, DIM))

def query_vectors(monkeypatch, mapping, default=None, log=None):
    """embed() stand-in: the query text selects a deterministic vector."""
    def embed(texts, **kwargs):
        if log is not None:
            log.extend(texts)
        return np.stack([np.asarray(mapping.get(text, default if default is not None else unit(0)), dtype=np.float32) for text in texts])
    monkeypatch.setattr(gms, 'embed', embed)

def fake_llm(monkeypatch, rewrites=None, answer_ids=('e1',), calls=None):
    """complete_json/generate_json stand-in recording rewrite and generation prompts."""
    rewrites = list(rewrites or [])
    calls = calls if calls is not None else []
    def complete_json(prompt, schema, **kwargs):
        calls.append(('rewrite' if schema is RewrittenQuery else 'other', json.loads(prompt), kwargs.get('prompt_version')))
        if schema is RewrittenQuery:
            value = rewrites.pop(0)
            if isinstance(value, Exception):
                raise value
            return RewrittenQuery(query=value)
        if schema is NoteLinks:
            return NoteLinks(note_explanations=[])
        raise AssertionError('unexpected schema')
    def generate_json(prompt, schema, **kwargs):
        data = json.loads(prompt)
        calls.append(('generate', data, None))
        return GeneratedAnswer.model_validate({'answerable': True, 'segments': [{'text': 'answer sentence', 'citation_ids': list(answer_ids)}]})
    monkeypatch.setattr(gms, 'complete_json', complete_json)
    monkeypatch.setattr(gms, 'generate_json', generate_json)
    return calls

HISTORY = [{'question': 'What is a residual connection?', 'answer': 'It adds the input to the output [e1].'}]

def test_history_rewrites_search_query_and_keeps_original_question_for_generation(monkeypatch):
    add_doc('d', vector=unit(1))
    searched = []
    query_vectors(monkeypatch, {'residual connection purpose': unit(1)}, default=unit(2), log=searched)
    calls = fake_llm(monkeypatch, rewrites=['residual connection purpose'])
    result = answer_question('w', 'Why is it used?', chat_id='chat-a', history=HISTORY)
    assert result.status == 'grounded'
    assert searched == ['residual connection purpose']
    rewrite = [call for call in calls if call[0] == 'rewrite']
    assert len(rewrite) == 1 and rewrite[0][1]['conversation'][0]['answer'] == 'It adds the input to the output .'
    assert rewrite[0][2] == 'query-followup-v1'
    generated = [call[1] for call in calls if call[0] == 'generate'][0]
    assert generated['question'] == 'Why is it used?'
    assert generated['conversation'][0]['question'] == HISTORY[0]['question']
    assert '[e1]' not in json.dumps(generated['conversation'])
    assert [item['id'] for item in generated['evidence']] == ['e1']

def test_no_history_searches_original_question_without_rewrite(monkeypatch):
    add_doc('d')
    searched = []
    query_vectors(monkeypatch, {}, log=searched)
    calls = fake_llm(monkeypatch)
    assert answer_question('w', 'plain question').status == 'grounded'
    assert searched == ['plain question']
    assert not [call for call in calls if call[0] == 'rewrite']
    assert 'conversation' not in [call[1] for call in calls if call[0] == 'generate'][0]

def test_rewrite_output_error_falls_back_to_original_question(monkeypatch):
    add_doc('d')
    searched = []
    query_vectors(monkeypatch, {}, log=searched)
    fake_llm(monkeypatch, rewrites=[gms.ModelOutputError('bad')])
    assert answer_question('w', 'Why is it used?', history=HISTORY).status == 'grounded'
    assert searched == ['Why is it used?']

def test_rewrite_provider_failure_propagates(monkeypatch):
    add_doc('d'); query_vectors(monkeypatch, {})
    fake_llm(monkeypatch, rewrites=[gms.ProviderUnavailable('down')])
    with pytest.raises(gms.ProviderUnavailable):
        answer_question('w', 'Why is it used?', chat_id='c', history=HISTORY)
    with get_connection() as db:
        assert db.execute('SELECT count(*) FROM answers').fetchone()[0] == 0

def test_note_scope_excludes_other_workspace_unlinked_failed_and_include_notes_false(monkeypatch):
    add_doc('d')
    add_note('linked')
    add_note('elsewhere', workspaces=('other',))
    add_note('unlinked', workspaces=())
    add_note('broken', status='failed')
    query_vectors(monkeypatch, {})
    found = retrieve('w', 'q')
    assert {item.chunk_id for item in found} == {'d', 'chunk-linked'}
    note = next(item for item in found if item.source_type == 'note')
    assert note.source_id == 'linked' and note.page is None and note.title == 'linked'
    assert [item.chunk_id for item in retrieve('w', 'q', include_notes=False)] == ['d']

def test_note_only_workspace_answers_with_note_citation(monkeypatch):
    add_note('n', title='Gradient note')
    query_vectors(monkeypatch, {})
    fake_llm(monkeypatch)
    result = answer_question('w', 'q')
    assert result.status == 'grounded'
    citation = result.citations[0]
    assert citation.source_type == 'note' and citation.note_id == 'n' and citation.document_id is None
    assert citation.title == 'Gradient note'
    with pytest.raises(NoSearchableContent):
        retrieve('w', 'q', include_notes=False)

def test_note_guarantee_replaces_last_document_within_caps(monkeypatch):
    for index in range(12):
        add_doc(f'd{index:02}', text='x' * 100)
    weak_note = np.asarray([.6, .8, 0, 0, 0, 0, 0, 0], dtype=np.float32)  # cosine .6 >= MIN_SCORE, outside relative margin
    add_note('n', vector=weak_note)
    add_note('below', vector=unit(1) * -1 + unit(0) * 0)  # cosine 0: below MIN_SCORE, never guaranteed
    query_vectors(monkeypatch, {})
    found = retrieve('w', 'q')
    assert len(found) == 12
    assert found[-1].chunk_id == 'chunk-n'
    assert 'd11' not in {item.chunk_id for item in found}
    assert 'chunk-below' not in {item.chunk_id for item in found}

def test_note_guarantee_respects_character_cap(monkeypatch):
    add_doc('a', text='x' * 5000); add_doc('b', text='y' * 5000)
    add_note('n', vector=[.6, .8, 0, 0, 0, 0, 0, 0], text='z' * 300)
    query_vectors(monkeypatch, {})
    found = retrieve('w', 'q')
    assert [item.chunk_id for item in found] == ['a', 'chunk-n']
    assert sum(len(item.text) for item in found) <= 8000

def test_weak_evidence_researches_once_and_merges(monkeypatch):
    add_doc('d', vector=unit(1))
    searched = []
    query_vectors(monkeypatch, {'expanded query': unit(1)}, default=unit(2), log=searched)
    calls = fake_llm(monkeypatch, rewrites=['expanded query'])
    result = answer_question('w', 'vague', chat_id='c')
    assert result.status == 'grounded' and result.citations[0].document_id == 'd'
    assert searched == ['vague', 'expanded query']
    assert [call[2] for call in calls if call[0] == 'rewrite'] == ['query-research-v1']
    with get_connection() as db:
        stored = json.loads(db.execute('SELECT body_json FROM answers').fetchone()[0])
    assert stored['research'] == {'performed': True, 'query': 'expanded query'}
    assert stored['search_query'] == 'vague'

def test_research_is_capped_at_one_then_abstains(monkeypatch):
    add_doc('d', vector=unit(1))
    searched = []
    query_vectors(monkeypatch, {}, default=unit(2), log=searched)
    calls = fake_llm(monkeypatch, rewrites=['still weak', 'never used'])
    result = answer_question('w', 'vague', history=HISTORY)
    assert result.status == 'insufficient_evidence'
    rewrites = [call[2] for call in calls if call[0] == 'rewrite']
    assert rewrites == ['query-followup-v1', 'query-research-v1']
    assert len(searched) == 2
    assert not [call for call in calls if call[0] == 'generate']

def test_chat_id_and_trace_fields_persisted(monkeypatch):
    add_doc('d'); add_note('n', vector=[.6, .8, 0, 0, 0, 0, 0, 0])
    query_vectors(monkeypatch, {})
    fake_llm(monkeypatch)
    result = answer_question('w', 'q', chat_id='chat-1')
    with get_connection() as db:
        row = db.execute('SELECT chat_id, body_json FROM answers WHERE id=?', (result.answer_id,)).fetchone()
    assert row['chat_id'] == 'chat-1'
    stored = json.loads(row['body_json'])
    assert stored['note_guaranteed'] is True
    assert {item['source_type'] for item in stored['retrieval']} == {'doc', 'note'}

def note_row(identifier, title='Vanishing gradient', body='First paragraph about gradients.\n\nSecond paragraph about ReLU.', status='ok'):
    with get_connection() as db:
        db.execute('INSERT INTO notes(id,title,body,index_status,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                   (identifier, title, body, status, 'now', 'now'))

def note_chunks_in_db(identifier):
    with get_connection() as db:
        return db.execute("SELECT text, embedding_model, embedding_dim, page FROM chunks WHERE source_type='note' AND source_id=? ORDER BY text",
                          (identifier,)).fetchall()

def test_index_note_success_replaces_chunks(monkeypatch):
    note_row('n', status='failed')
    with get_connection() as db:
        db.execute('INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?)', ('stale', 'note', 'n', None, 'old body', unit(0).tobytes(), 'm', DIM))
    assert index_note('n') == 'ok'
    rows = note_chunks_in_db('n')
    assert [row['text'] for row in rows] == ['Vanishing gradient\nFirst paragraph about gradients.', 'Vanishing gradient\nSecond paragraph about ReLU.']
    assert all(row['embedding_model'] == get_settings().embedding_model and row['embedding_dim'] == DIM and row['page'] is None for row in rows)
    with get_connection() as db:
        assert db.execute("SELECT index_status FROM notes WHERE id='n'").fetchone()[0] == 'ok'
        db.execute("INSERT INTO workspace_notes VALUES('w','n')")
    assert any(item.source_id == 'n' for item in retrieve('w', 'ReLU'))

@pytest.mark.parametrize('failure', [gms.ProviderUnavailable('down'), gms.ModelOutputError('shape'), RuntimeError('boom')])
def test_index_note_failure_removes_old_chunks_and_never_raises(monkeypatch, failure):
    note_row('n')
    assert index_note('n') == 'ok' and note_chunks_in_db('n')
    def broken(*args, **kwargs):
        raise failure
    monkeypatch.setattr(gms, 'embed', broken)
    assert index_note('n') == 'failed'
    assert not note_chunks_in_db('n')
    with get_connection() as db:
        assert db.execute("SELECT index_status, body FROM notes WHERE id='n'").fetchone()[0] == 'failed'

def test_index_note_wrong_dimension_and_missing_note(monkeypatch):
    note_row('n')
    monkeypatch.setattr(gms, 'embed', lambda texts, **kwargs: np.zeros((len(texts), DIM + 1), dtype=np.float32))
    assert index_note('n') == 'failed' and not note_chunks_in_db('n')
    assert index_note('missing') == 'failed'

def test_index_note_skips_publish_when_note_changed_during_embedding(monkeypatch):
    note_row('n')
    real_embed = gms.embed
    def embed_while_edited(texts, **kwargs):
        with get_connection() as db:
            db.execute("UPDATE notes SET body='edited elsewhere' WHERE id='n'")
        return real_embed(texts, **kwargs)
    monkeypatch.setattr(gms, 'embed', embed_while_edited)
    index_note('n')
    assert not note_chunks_in_db('n')

def test_mock_mode_followup_runs_without_stubs():
    add_doc('d', vector=gms.embed(['residual connection'])[0], text='residual connection adds input')
    result = answer_question('w', 'why use it', chat_id='chat-a', history=[{'question': 'residual connection', 'answer': 'adds input'}])
    assert result.status == 'grounded'
    with get_connection() as db:
        stored = json.loads(db.execute('SELECT body_json FROM answers').fetchone()[0])
    assert stored['search_query'] == 'residual connection why use it'

def _note_answer(monkeypatch, answerable, segments, note_explanations=(), link_error=None):
    """generate_json gives the answer; complete_json(NoteLinks) gives the link_notes output and records its calls."""
    calls = []
    monkeypatch.setattr(gms, 'generate_json', lambda *args, **kwargs: GeneratedAnswer.model_validate(
        {'answerable': answerable, 'segments': segments}))
    def complete_json(prompt, schema, **kwargs):
        assert schema is NoteLinks
        calls.append(json.loads(prompt))
        if link_error:
            raise link_error
        return NoteLinks.model_validate({'note_explanations': list(note_explanations)})
    monkeypatch.setattr(gms, 'complete_json', complete_json)
    return calls

def test_link_notes_adds_note_sentences_citing_notes_only(monkeypatch):
    add_doc('d', vector=unit(0)); add_note('n', vector=(unit(0) + unit(1)) / np.sqrt(2), title='기울기 소실 정리')  # doc ranks first: e1 doc, e2 note
    query_vectors(monkeypatch, {}, default=unit(0))
    calls = _note_answer(monkeypatch, True, [{'text': 'doc sentence', 'citation_ids': ['e1']}],
                         [{'text': 'note sentence', 'citation_ids': ['e2']}, {'text': 'mislabelled doc sentence', 'citation_ids': ['e1']}])
    result = answer_question('w', 'q')
    assert [s.text for s in result.segments] == ['doc sentence', 'note sentence']
    assert next(c for c in result.citations if c.source_type == 'note').note_id == 'n'
    assert calls[0]['answer'] == ['doc sentence'] and [n['id'] for n in calls[0]['notes']] == ['e2']

def test_link_notes_skipped_without_grounded_answer_or_notes(monkeypatch):
    add_doc('d', vector=unit(0)); add_note('n', vector=unit(0))
    query_vectors(monkeypatch, {}, default=unit(0))
    calls = _note_answer(monkeypatch, False, [])
    assert answer_question('w', 'q').status == 'insufficient_evidence' and calls == []

def test_link_notes_failure_keeps_answer(monkeypatch):
    add_doc('d', vector=unit(0)); add_note('n', vector=(unit(0) + unit(1)) / np.sqrt(2))
    query_vectors(monkeypatch, {}, default=unit(0))
    _note_answer(monkeypatch, True, [{'text': 'doc sentence', 'citation_ids': ['e1']}], link_error=gms.ProviderUnavailable('down'))
    result = answer_question('w', 'q')
    assert result.status == 'grounded' and [s.text for s in result.segments] == ['doc sentence']
