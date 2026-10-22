"""draft_note(answer_id): summarize a stored grounded answer into an unsaved note draft.

The returned citations use the POST /api/notes input shape, so the draft can be saved without edits.
Nothing is written to the database."""
import json
import time
from ..adapters.telemetry import observe
from ..agents.note_draft import PROMPT_VERSION, note_draft_graph
from ..db import get_connection
from ..schemas.note_draft import NoteDraftOut

DEADLINE_SECONDS = 20.0


class AnswerNotFound(LookupError):
    pass


class AnswerNotGrounded(ValueError):
    pass


def _load_answer(answer_id: str) -> dict:
    with get_connection() as db:
        row = db.execute('SELECT question, body_json FROM answers WHERE id=?', (answer_id,)).fetchone()
    if row is None:
        raise AnswerNotFound('답변을 찾을 수 없습니다')
    try:
        body = json.loads(row['body_json'])
    except (TypeError, ValueError):
        body = {}
    if not isinstance(body, dict):
        body = {}
    body['question'] = row['question']
    return body


def draft_note(answer_id: str) -> dict:
    """Returns {'title','body','citations','fallback'}.

    Raises AnswerNotFound for an unknown answer and AnswerNotGrounded unless it is a grounded answer
    with at least one validly cited segment. Provider failures and the deadline end in fallback=True."""
    deadline = time.monotonic() + DEADLINE_SECONDS
    with observe('note_draft', input={'answer_id': answer_id},
                 metadata={'answer_id': answer_id, 'prompt_version': PROMPT_VERSION}) as span:
        source = _load_answer(answer_id)
        state = note_draft_graph.invoke({'answer_id': answer_id, 'source_answer': source, 'deadline': deadline},
                                        config={'recursion_limit': 12})
        if state.get('not_grounded'):
            span.update(output={'error': 'not_grounded'}, metadata={'answer_id': answer_id, 'status': source.get('status')})
            raise AnswerNotGrounded('근거가 확인된 답변만 노트 초안으로 만들 수 있습니다')
        result = NoteDraftOut.model_validate(state['result']).model_dump()
        span.update(output=result, metadata={'answer_id': answer_id, 'prompt_version': PROMPT_VERSION,
            'fallback': result['fallback'], 'fallback_reason': state.get('fallback_reason'),
            'removed_citations': state.get('removed_citations', 0), 'attempts': state.get('attempts', 0)})
        return result
