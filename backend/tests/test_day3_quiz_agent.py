"""Day-three quiz agent: evidence sampling and the quiz graph (generation, validation, regeneration, exclusion)."""
import json
import random
import threading
import time
import pytest
from app.adapters import gms
from app.agents import quiz as quiz_agent
from app.config import get_settings
from app.db import get_connection, init_db
from app.schemas.quiz_generation import GeneratedQuestion
from app.services import quiz_generation
from app.services.quiz_generation import NoQuizEvidence, NoValidQuestions, generate_quiz_questions, select_quiz_evidence

DIM = 8


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
    yield
    get_settings.cache_clear()


def text_for(chunk_id, length=250):
    return (f'CHUNK[{chunk_id}] 잔차 연결은 입력을 출력에 더해 기울기 흐름을 돕는다. ' * 20)[:length]


def add_doc(doc_id, pages, workspace='w', status='ready', length=250):
    """pages: list of (chunk_id, page). Chunk text embeds its id so fakes can tell branches apart."""
    with get_connection() as db:
        db.execute('INSERT INTO documents(id,workspace_id,filename,path,page_count,status,error) VALUES(?,?,?,?,?,?,?)',
                   (doc_id, workspace, doc_id + '.pdf', 'unused', 10, status, None))
        for chunk_id, page in pages:
            db.execute('INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?)',
                       (chunk_id, 'doc', doc_id, page, text_for(chunk_id, length), b'', 'm', DIM))


def add_note_chunk(chunk_id):
    with get_connection() as db:
        db.execute('INSERT INTO notes(id,title,body,index_status,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                   ('n', 'n', 'x', 'ok', 'now', 'now'))
        db.execute('INSERT INTO workspace_notes VALUES(?,?)', ('w', 'n'))
        db.execute('INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?)', (chunk_id, 'note', 'n', None, text_for(chunk_id), b'', 'm', DIM))


def five_chunks():
    add_doc('d1', [('c1', 1), ('c2', 2), ('c3', 3)])
    add_doc('d2', [('c4', 1), ('c5', 2)])


def chunk_of(prompt):
    text = json.loads(prompt)['evidence']['text']
    return text[text.index('[') + 1:text.index(']')]


def valid_output(chunk_id, **override):
    data = {'stem': f'{chunk_id} 문제', 'options': [{'option_id': i, 'text': f'{chunk_id} 선택지 {i}'} for i in 'abcd'],
            'answer_option_id': 'b', 'explanation': f'{chunk_id} 해설'}
    data.update(override)
    return data


def fake_llm(monkeypatch, plan=None, calls=None, delay=0.0, gate=None):
    """complete_json stand-in. plan[chunk_id] is a list consumed per attempt: dict output, Exception, or callable."""
    plan = {key: list(value) for key, value in (plan or {}).items()}
    calls = calls if calls is not None else []
    lock = threading.Lock()
    def complete_json(prompt, schema, **kwargs):
        assert schema is GeneratedQuestion and kwargs['schema_name'] == 'quiz_question' and kwargs['prompt_version'] == 'quiz-v1'
        chunk_id = chunk_of(prompt)
        with lock:
            calls.append((chunk_id, json.loads(prompt)))
            step = plan[chunk_id].pop(0) if plan.get(chunk_id) else valid_output(chunk_id)
        if gate is not None:
            gate(chunk_id)
        if delay:
            time.sleep(delay)
        if callable(step) and not isinstance(step, type):
            step = step()
        if isinstance(step, Exception):
            raise step
        return GeneratedQuestion.model_validate(step)
    monkeypatch.setattr(gms, 'complete_json', complete_json)
    return calls


def quiz_rows():
    with get_connection() as db:
        return db.execute('SELECT count(*) FROM quizzes').fetchone()[0] + db.execute('SELECT count(*) FROM questions').fetchone()[0]


# ---------- 출제 근거 선택 ----------

def test_selection_scope_ready_docs_long_chunks_only():
    add_doc('ready', [('ok1', 1), ('ok2', 2)])
    add_doc('short', [('tiny', 1)], length=199)
    add_doc('proc', [('p1', 1)], status='processing')
    add_doc('fail', [('f1', 1)], status='failed')
    add_doc('elsewhere', [('o1', 1)], workspace='other')
    add_note_chunk('note1')
    chosen = select_quiz_evidence('w', 5, rng=random.Random(1))
    assert sorted(item.chunk_id for item in chosen) == ['ok1', 'ok2']  # fewer than count -> as many as exist
    assert all(item.source_type == 'doc' and item.source_id == 'ready' and len(item.text) >= 200 for item in chosen)


def test_selection_prefers_distinct_pages_then_fills():
    add_doc('d', [('a1', 1), ('a2', 1), ('a3', 1), ('b1', 2), ('c1', 3)])
    for seed in range(10):
        chosen = select_quiz_evidence('w', 3, rng=random.Random(seed))
        assert sorted(item.page for item in chosen) == [1, 2, 3]
        chosen = select_quiz_evidence('w', 4, rng=random.Random(seed))
        assert sorted(item.page for item in chosen) == [1, 1, 2, 3]
        assert len({item.chunk_id for item in chosen}) == 4


def test_selection_is_random_but_seedable():
    add_doc('d', [(f'k{i}', i) for i in range(1, 11)])
    first = [item.chunk_id for item in select_quiz_evidence('w', 5, rng=random.Random(7))]
    assert first == [item.chunk_id for item in select_quiz_evidence('w', 5, rng=random.Random(7))]
    others = {tuple(item.chunk_id for item in select_quiz_evidence('w', 5, rng=random.Random(seed))) for seed in range(8)}
    assert len(others) > 1


def test_selection_without_candidates_raises():
    add_doc('short', [('tiny', 1)], length=150)
    add_note_chunk('note1')
    with pytest.raises(NoQuizEvidence):
        select_quiz_evidence('w', 5)
    with pytest.raises(NoQuizEvidence):
        generate_quiz_questions('w', 5)


# ---------- 퀴즈 생성 ----------

def test_normal_five_questions_with_evidence_fields_from_chunks(monkeypatch):
    five_chunks()
    calls = fake_llm(monkeypatch)
    result = generate_quiz_questions('w', 5, rng=random.Random(3))
    assert result['requested_count'] == 5 and len(result['questions']) == 5
    assert len(calls) == 5
    with get_connection() as db:
        chunks = {row['id']: row for row in db.execute('SELECT * FROM chunks').fetchall()}
    for question in result['questions']:
        chunk = chunks[question['chunk_id']]
        assert question['document_id'] == chunk['source_id'] and question['page'] == chunk['page']
        assert question['quote'] == chunk['text']
        assert question['stem'].startswith(question['chunk_id'])  # the stem came from that chunk's branch
        assert [option['option_id'] for option in question['options']] == list('abcd')
        assert set(question) == {'stem', 'options', 'answer_option_id', 'explanation', 'document_id', 'page', 'quote', 'chunk_id'}
    assert len({question['chunk_id'] for question in result['questions']}) == 5
    assert quiz_rows() == 0  # the graph never stores


def test_prompt_contains_only_evidence_text_and_no_ids(monkeypatch):
    five_chunks()
    calls = fake_llm(monkeypatch)
    generate_quiz_questions('w', 1, rng=random.Random(0))
    payload = calls[0][1]
    assert set(payload) == {'evidence'} and set(payload['evidence']) == {'title', 'text'}
    assert 'quiz-v1' == quiz_agent.PROMPT_VERSION
    assert '근거' in quiz_agent.SYSTEM_PROMPT and '지시' in quiz_agent.SYSTEM_PROMPT and '한국어' in quiz_agent.SYSTEM_PROMPT


def test_shuffle_keeps_answer_on_the_same_text(monkeypatch):
    five_chunks()
    fake_llm(monkeypatch)
    positions = set()
    for seed in range(6):
        for question in generate_quiz_questions('w', 5, rng=random.Random(seed))['questions']:
            answer = next(option for option in question['options'] if option['option_id'] == question['answer_option_id'])
            assert answer['text'] == f"{question['chunk_id']} 선택지 b"
            positions.add(question['answer_option_id'])
    assert len(positions) > 1  # model's fixed 'b' does not leak as a fixed position


@pytest.mark.parametrize('bad', [
    valid_output('c1', options=[{'option_id': i, 'text': f't{i}'} for i in 'abc']),             # 3 options
    valid_output('c1', options=[{'option_id': i, 'text': 'same'} for i in 'abcd']),              # duplicate texts
    valid_output('c1', options=[{'option_id': i, 'text': ' ' if i == 'a' else i} for i in 'abcd']),  # blank option
    valid_output('c1', answer_option_id='z'),                                                    # answer not an option
    valid_output('c1', explanation='  '),                                                        # empty explanation
    gms.ModelOutputError('schema'),                                                              # schema failure
])
def test_invalid_question_is_regenerated_once_and_succeeds(monkeypatch, bad):
    five_chunks()
    calls = fake_llm(monkeypatch, plan={'c1': [bad, valid_output('c1')]})
    result = generate_quiz_questions('w', 5, rng=random.Random(0))
    assert len(result['questions']) == 5
    c1_calls = [payload for chunk, payload in calls if chunk == 'c1']
    assert len(c1_calls) == 2 and c1_calls[1]['previous_errors']
    assert len(calls) == 6


def test_regeneration_exhausted_excludes_question(monkeypatch):
    five_chunks()
    bad = valid_output('c2', answer_option_id='x')
    calls = fake_llm(monkeypatch, plan={'c2': [bad, bad, bad]})
    result = generate_quiz_questions('w', 5, rng=random.Random(0))
    assert result['requested_count'] == 5 and len(result['questions']) == 4
    assert 'c2' not in {question['chunk_id'] for question in result['questions']}
    assert len([chunk for chunk, _ in calls if chunk == 'c2']) == 2  # one regeneration only


def test_zero_valid_questions_raises(monkeypatch):
    five_chunks()
    fake_llm(monkeypatch, plan={c: [gms.ModelOutputError('x')] * 2 for c in ('c1', 'c2', 'c3', 'c4', 'c5')})
    with pytest.raises(NoValidQuestions):
        generate_quiz_questions('w', 5)
    assert quiz_rows() == 0


def test_all_branches_provider_failure_raises_provider_unavailable(monkeypatch):
    five_chunks()
    calls = fake_llm(monkeypatch, plan={c: [gms.ProviderUnavailable('down')] for c in ('c1', 'c2', 'c3', 'c4', 'c5')})
    with pytest.raises(gms.ProviderUnavailable):
        generate_quiz_questions('w', 5)
    assert len(calls) == 5  # provider failures are not regenerated by the graph


def test_partial_provider_failure_excludes_only_that_branch(monkeypatch):
    five_chunks()
    fake_llm(monkeypatch, plan={'c3': [gms.ProviderUnavailable('down')], 'c4': [gms.ProviderUnavailable('down')]})
    result = generate_quiz_questions('w', 5)
    assert sorted(question['chunk_id'] for question in result['questions']) == ['c1', 'c2', 'c5']


def test_provider_and_invalid_mix_with_no_valid_is_not_503(monkeypatch):
    five_chunks()
    plan = {c: [gms.ProviderUnavailable('down')] for c in ('c1', 'c2', 'c3', 'c4')}
    plan['c5'] = [gms.ModelOutputError('x')] * 2
    fake_llm(monkeypatch, plan=plan)
    with pytest.raises(NoValidQuestions):
        generate_quiz_questions('w', 5)


def test_branches_run_in_parallel_with_at_most_five(monkeypatch):
    add_doc('d', [(f'k{i}', i) for i in range(1, 8)])
    active, peak, lock = [0], [0], threading.Lock()
    def gate(_):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.15)
        with lock:
            active[0] -= 1
    fake_llm(monkeypatch, gate=gate)
    started = time.monotonic()
    result = generate_quiz_questions('w', 7)
    assert len(result['questions']) == 7
    assert 2 <= peak[0] <= 5
    assert time.monotonic() - started < 0.15 * 7


def test_deadline_excludes_slow_branch_and_keeps_finished(monkeypatch):
    five_chunks()
    monkeypatch.setattr(quiz_generation, 'QUIZ_TIMEOUT', 0.5)
    monkeypatch.setattr(quiz_agent, 'MIN_BRANCH_SECONDS', 0.0)
    def slow():
        time.sleep(0.7)
        return gms.ProviderUnavailable('질문 처리 시간 한도를 초과했습니다.')  # what the adapter's check_deadline raises
    fake_llm(monkeypatch, plan={'c5': [slow]})
    result = generate_quiz_questions('w', 5)
    assert sorted(question['chunk_id'] for question in result['questions']) == ['c1', 'c2', 'c3', 'c4']


def test_deadline_too_short_starts_no_branch(monkeypatch):
    five_chunks()
    monkeypatch.setattr(quiz_generation, 'QUIZ_TIMEOUT', 1.0)  # below MIN_BRANCH_SECONDS
    calls = fake_llm(monkeypatch)
    with pytest.raises(NoValidQuestions):
        generate_quiz_questions('w', 5)
    assert calls == []


# ---------- 목 모드 (adapter stand-in registered by the quiz module) ----------

def test_mock_mode_normal_builds_deterministic_questions():
    five_chunks()
    result = generate_quiz_questions('w', 5, rng=random.Random(2))
    assert len(result['questions']) == 5
    for question in result['questions']:
        answer = next(option['text'] for option in question['options'] if option['option_id'] == question['answer_option_id'])
        assert answer in question['quote']


@pytest.mark.parametrize('scenario, error', [('invalid_json', NoValidQuestions), ('provider_error', gms.ProviderUnavailable)])
def test_mock_mode_failure_scenarios(monkeypatch, scenario, error):
    five_chunks()
    monkeypatch.setenv('MOCK_SCENARIO', scenario)
    get_settings.cache_clear()
    with pytest.raises(error):
        generate_quiz_questions('w', 5)
