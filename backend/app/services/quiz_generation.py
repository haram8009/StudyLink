"""Quiz question generation (C1): evidence sampling and the traced quiz graph run. Storage is B's job.

generate_quiz_questions returns validated, shuffled questions with server-filled evidence fields and never
writes to the database."""
import random
import time
from uuid import uuid4

from ..adapters.telemetry import current_trace_id, observe
from ..db import get_connection
from .retrieval import Evidence

QUIZ_TIMEOUT = 45.0      # whole-request budget (seconds); unfinished branches are excluded
MIN_QUOTE_CHARS = 200


class NoQuizEvidence(ValueError):
    """No ready document chunk of at least MIN_QUOTE_CHARS in the workspace (HTTP 400)."""


class NoValidQuestions(ValueError):
    """Every question branch was excluded for output/validation/deadline reasons (HTTP 422)."""


_EVIDENCE_SQL = '''SELECT c.id, c.source_id, c.page, c.text, d.filename FROM chunks c
    JOIN documents d ON c.source_type='doc' AND c.source_id=d.id
    WHERE d.workspace_id=? AND d.status='ready' AND c.page IS NOT NULL ORDER BY c.id'''


def select_quiz_evidence(workspace_id: str, count: int, *, rng: random.Random | None = None) -> list[Evidence]:
    """Up to `count` random doc chunks (>= 200 chars) of the workspace's ready PDFs, distinct pages first.

    Notes and other workspaces are never candidates. Fewer candidates than count returns what exists;
    none raises NoQuizEvidence."""
    if count < 1:
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


def generate_quiz_questions(workspace_id: str, count: int = 5, *, rng: random.Random | None = None) -> dict:
    """Run the quiz graph under one root trace `quiz_generate`.

    Returns {'requested_count', 'questions': [{stem, options[{option_id,text}], answer_option_id, explanation,
    document_id, page, quote, chunk_id}]}. Raises NoQuizEvidence, NoValidQuestions, or
    adapters.gms.ProviderUnavailable when every branch ended in a provider failure."""
    deadline = time.monotonic() + QUIZ_TIMEOUT
    seed = (rng or random.Random()).getrandbits(32)
    request_id = str(uuid4())
    with observe('quiz_generate', input={'workspace_id': workspace_id, 'count': count},
                 metadata={'request_id': request_id, 'workspace_id': workspace_id, 'requested_count': count,
                           'prompt_version': quiz_agent.PROMPT_VERSION}) as span:
        state = quiz_agent.quiz_graph.invoke(
            {'workspace_id': workspace_id, 'count': count, 'deadline': deadline, 'seed': seed, 'results': {}},
            config={'max_concurrency': quiz_agent.MAX_CONCURRENCY, 'recursion_limit': 10})
        questions = state['questions']
        span.update(output={'actual_count': len(questions), 'chunk_ids': [item['chunk_id'] for item in questions]},
                    metadata={'excluded': state.get('excluded') or [], 'trace_id': current_trace_id()})
        return {'requested_count': count, 'questions': questions}


from ..agents import quiz as quiz_agent  # noqa: E402  (agents.quiz imports this module's selection and errors)
