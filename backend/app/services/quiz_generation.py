"""Quiz question generation (C1): evidence sampling and the traced quiz graph run. Storage is B's job.

generate_quiz_questions returns validated, shuffled questions with server-filled evidence fields and never
writes to the database."""
import random
import time
from uuid import uuid4

from ..adapters.telemetry import current_trace_id, observe
from ..db import get_connection
from .retrieval import Evidence

QUIZ_TIMEOUT = 120.0
MIN_QUOTE_CHARS = 200


class NoQuizEvidence(ValueError):
    """No ready document chunk of at least MIN_QUOTE_CHARS in the workspace (HTTP 400)."""


class NoValidQuestions(ValueError):
    """The round budget could not produce the requested number of valid unique questions (HTTP 422)."""


class QuizDeadlineExceeded(RuntimeError):
    """The whole generation request exhausted its time budget (HTTP 503)."""


_EVIDENCE_SQL = '''SELECT c.id, c.source_id, c.page, c.text, d.filename FROM chunks c
    JOIN documents d ON c.source_type='doc' AND c.source_id=d.id
    WHERE d.workspace_id=? AND d.status='ready' AND c.page>=1 AND c.page<=d.page_count ORDER BY c.id'''


def evidence_is_current(workspace_id: str, evidence: Evidence) -> bool:
    with get_connection() as db:
        row = db.execute('''SELECT c.text FROM chunks c JOIN documents d ON c.source_id=d.id
            WHERE c.id=? AND c.source_type='doc' AND c.source_id=? AND c.page=?
            AND d.workspace_id=? AND d.status='ready' AND c.page>=1 AND c.page<=d.page_count''',
            (evidence.chunk_id, evidence.source_id, evidence.page, workspace_id)).fetchone()
    return row is not None and row['text'].strip() == evidence.text.strip() and len(evidence.text.strip()) >= MIN_QUOTE_CHARS


def select_quiz_evidence(workspace_id: str, count: int | None, *, rng: random.Random | None = None) -> list[Evidence]:
    """Up to `count` random doc chunks (>= 200 chars) of the workspace's ready PDFs, distinct pages first.

    Notes and other workspaces are never candidates. None selects the full pool for replenishment.
    Fewer candidates than count returns what exists; none raises NoQuizEvidence."""
    if count is not None and count < 1:
        raise ValueError('count must be at least 1')
    rng = rng or random.Random()
    with get_connection() as connection:
        rows = [row for row in connection.execute(_EVIDENCE_SQL, (workspace_id,)).fetchall()
                if len(row['text'].strip()) >= MIN_QUOTE_CHARS]
        if not rows:
            processing = connection.execute("SELECT 1 FROM documents WHERE workspace_id=? AND status='processing' LIMIT 1",
                                            (workspace_id,)).fetchone()
            raise NoQuizEvidence('자료를 처리하는 중입니다' if processing else '퀴즈를 만들 수 있는 자료가 없습니다')
    rng.shuffle(rows)
    first, rest, seen = [], [], set()
    for row in rows:
        page = (row['source_id'], row['page'])
        (rest if page in seen else first).append(row)
        seen.add(page)
    chosen = (first + rest)[:count]
    return [Evidence(row['id'], 'doc', row['source_id'], row['page'], row['filename'] or '', row['text'].strip(), 0.0)
            for row in chosen]


def generate_quiz_questions(workspace_id: str, count: int = 5, *, difficulty: str = 'medium', rng: random.Random | None = None) -> dict:
    """Run the quiz graph under one root trace `quiz_generate`.

    Returns requested_count, difficulty and exactly count questions, with server-owned evidence fields.
    Raises NoQuizEvidence (400), NoValidQuestions (422), QuizDeadlineExceeded (503), or
    adapters.gms.ProviderUnavailable (503) when a round cannot progress due to provider failures."""
    if type(count) is not int or not 1 <= count <= 10 or difficulty not in ('easy', 'medium', 'hard'):
        raise ValueError('invalid quiz settings')
    started = time.monotonic()
    deadline = started + QUIZ_TIMEOUT
    seed = (rng or random.Random()).getrandbits(32)
    request_id = str(uuid4())
    with observe('quiz_generate', input={'workspace_id': workspace_id, 'count': count, 'difficulty': difficulty},
                 metadata={'request_id': request_id, 'workspace_id': workspace_id, 'requested_count': count,
                           'difficulty': difficulty, 'prompt_version': quiz_agent.PROMPT_VERSION}) as span:
        try:
            state = quiz_agent.quiz_graph.invoke(
                {'workspace_id': workspace_id, 'count': count, 'difficulty': difficulty,
                 'deadline': deadline, 'seed': seed, 'results': {}, 'questions': [], 'round': 1},
                config={'max_concurrency': quiz_agent.MAX_CONCURRENCY, 'recursion_limit': 30})
        except Exception as exc:
            span.update(metadata={**getattr(exc, 'quiz_diagnostics', {}), 'termination_reason': type(exc).__name__,
                                  'latency_seconds': time.monotonic() - started})
            raise
        questions = state['questions']
        span.update(output={'actual_count': len(questions), 'chunk_ids': [item['chunk_id'] for item in questions]},
                    metadata={'excluded': state.get('excluded') or [], 'trace_id': current_trace_id(),
                              'rounds': state['round'], 'calls': state.get('calls', 0),
                              'latency_seconds': time.monotonic() - started, 'termination_reason': 'complete'})
        return {'requested_count': count, 'difficulty': difficulty, 'questions': questions}


from ..agents import quiz as quiz_agent  # noqa: E402  (agents.quiz imports this module's selection and errors)
