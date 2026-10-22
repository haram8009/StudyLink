import inspect
from fastapi import APIRouter, HTTPException
from ..schemas.http import AskRequest, ChatCreate
from ..services import chats

router = APIRouter(prefix='/api')

def _call_answer_service(workspace_id: str, body: AskRequest, chat_id: str, history: list[dict]):
    from ..services import answer as answer_service
    answer_question = answer_service.answer_question
    try:
        parameters = inspect.signature(answer_question).parameters
    except (TypeError, ValueError):
        parameters = {}
    if 'chat_id' in parameters or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
        return answer_question(workspace_id, body.question, body.include_notes, chat_id=chat_id, history=history)
    # Transitional: answer service without the day-two keywords (no history, chat_id attached afterwards).
    return answer_question(workspace_id, body.question, body.include_notes)

def ask_in_chat(chat: dict, body: AskRequest) -> dict:
    """Search scope comes from the stored chat's workspace; context only from this chat."""
    from ..adapters.gms import ProviderUnavailable
    from ..services.retrieval import NoSearchableContent
    try:
        with chats.chat_turn(chat['id']):
            history = chats.load_history(chat['id'])
            try:
                result = _call_answer_service(chat['workspace_id'], body, chat['id'], history)
            except NoSearchableContent as exc:
                raise HTTPException(400, str(exc)) from exc
            except ProviderUnavailable as exc:
                raise HTTPException(503, '모델 서비스에 연결할 수 없습니다. 잠시 후 재시도하세요') from exc
            answer = result.model_dump() if hasattr(result, 'model_dump') else dict(result)
            chats.attach_answer(chat['id'], answer['answer_id'])
            chats.touch_chat(chat['id'])
    except chats.ChatBusy as exc:
        raise HTTPException(409, '이 채팅에서 답변을 생성하는 중입니다. 완료 후 다시 질문하세요') from exc
    try:
        return chats.get_answer(answer['answer_id'])
    except HTTPException:
        # Answer row not stored (e.g. stubbed service); still return the generated answer.
        return {**answer, 'question': body.question, 'chat_id': chat['id'], 'workspace_id': chat['workspace_id'], 'created_at': None}

@router.get('/workspaces/{workspace_id}/chats')
def list_chats(workspace_id: str):
    return chats.list_chats(workspace_id)

@router.post('/workspaces/{workspace_id}/chats', status_code=201)
def create_chat(workspace_id: str, body: ChatCreate | None = None):
    return chats.create_chat(workspace_id, body.title if body else None)

@router.get('/chats/{chat_id}')
def get_chat(chat_id: str):
    return chats.get_chat(chat_id)

@router.get('/chats/{chat_id}/messages')
def list_messages(chat_id: str):
    return chats.list_messages(chat_id)

@router.post('/chats/{chat_id}/ask')
def ask_chat(chat_id: str, body: AskRequest):
    return ask_in_chat(chats.get_chat(chat_id), body)

@router.get('/workspaces/{workspace_id}/answers')
def recent_answers(workspace_id: str):
    return chats.recent_answers(workspace_id)

@router.get('/answers/{answer_id}')
def get_answer(answer_id: str):
    return chats.get_answer(answer_id)
