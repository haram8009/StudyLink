import time
import json
from datetime import datetime, timezone
from typing import Sequence
from uuid import uuid4
from ..adapters.gms import check_deadline
from ..adapters.telemetry import current_trace_id, observe
from ..agents.answer import answer_graph
from ..config import get_settings
from ..db import get_connection
from ..schemas.answer import AnswerOut, Citation

def answer_question(workspace_id: str, question: str, include_notes: bool = True, *,
                    chat_id: str | None = None, history: Sequence[dict] = ()) -> AnswerOut:
    """Answer within one chat. history is that chat's capped [{'question','answer'}] list, oldest first."""
    deadline = time.monotonic() + get_settings().request_timeout
    answer_id = str(uuid4())
    history = [dict(item) for item in history]
    with observe('ask', input=question,
                 metadata={'request_id': answer_id, 'workspace_id': workspace_id, 'include_notes': include_notes,
                           'chat_id': chat_id, 'history_turns': len(history)}) as span:
        state = answer_graph.invoke({'workspace_id': workspace_id, 'question': question, 'include_notes': include_notes,
            'chat_id': chat_id, 'history': history, 'deadline': deadline, 'segments': [], 'attempts': 0},
            config={'recursion_limit': 12})
        check_deadline(deadline)
        segments = state['segments']
        used = {value for segment in segments for value in segment.citation_ids}
        citations = [Citation(id=f'e{i}', source_type=item.source_type,
            document_id=item.source_id if item.source_type == 'doc' else None,
            note_id=item.source_id if item.source_type == 'note' else None,
            page=item.page, title=item.title, quote=item.text)
            for i, item in enumerate(state['evidence'], 1) if f'e{i}' in used]
        answer = AnswerOut(answer_id=answer_id, status='grounded' if segments else 'insufficient_evidence', segments=segments, citations=citations)
        stored = answer.model_dump()
        stored['retrieval'] = [{'chunk_id': item.chunk_id, 'source_type': item.source_type, 'score': item.score} for item in state['evidence']]
        stored['search_query'] = state.get('search_query', question)
        stored['research'] = {'performed': bool(state.get('researched')), 'query': state.get('research_query')}
        stored['note_guaranteed'] = bool(state.get('note_guaranteed'))
        stored['trace_id'] = current_trace_id()
        with get_connection() as connection:
            connection.execute('INSERT INTO answers(id,workspace_id,chat_id,question,body_json,created_at) VALUES(?,?,?,?,?,?)',
                (answer.answer_id, workspace_id, chat_id, question, json.dumps(stored, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
        span.update(output=answer.model_dump(), metadata={'chat_id': chat_id, 'search_query': stored['search_query'],
                    'research': stored['research'], 'note_guaranteed': stored['note_guaranteed']})
        return answer
