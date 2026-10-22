from typing import Literal
from fastapi import APIRouter, HTTPException
from ..schemas.http import QuizCreate, QuizSubmit, ReviewUpdate
from ..schemas.quiz import QuizGraded, QuizPublic, QuizSummary, ReviewDetail, ReviewItem
from ..services import quizzes, reviews
from ..services.workspaces import require_workspace

router = APIRouter(prefix='/api')

PROVIDER_DOWN = '모델 서비스에 연결할 수 없습니다. 잠시 후 재시도하세요'

def _generate(workspace_id: str, count: int) -> dict:
    from ..adapters.gms import ProviderUnavailable
    from ..services.quiz_generation import NoQuizEvidence, NoValidQuestions, generate_quiz_questions
    try:
        return generate_quiz_questions(workspace_id, count)
    except NoQuizEvidence as exc:
        raise HTTPException(400, str(exc) or '출제할 처리 완료 자료가 없습니다. 자료를 먼저 올리세요') from exc
    except NoValidQuestions as exc:
        raise HTTPException(422, str(exc) or '유효한 문항을 만들지 못했습니다. 다시 시도하세요') from exc
    except ProviderUnavailable as exc:
        raise HTTPException(503, PROVIDER_DOWN) from exc

@router.post('/workspaces/{workspace_id}/quizzes', status_code=201, response_model=QuizPublic)
def create_quiz(workspace_id: str, body: QuizCreate | None = None):
    count = body.count if body else 5
    require_workspace(workspace_id)
    try:
        with quizzes.generation_turn(workspace_id):
            result = _generate(workspace_id, count)
            questions = list(result.get('questions') or [])
            if not questions:
                raise HTTPException(422, '유효한 문항을 만들지 못했습니다. 다시 시도하세요')
            quiz_id = quizzes.save_quiz(workspace_id, int(result.get('requested_count') or count), questions)
    except quizzes.QuizBusy as exc:
        raise HTTPException(409, '이 워크스페이스에서 퀴즈를 만드는 중입니다. 완료 후 다시 시도하세요') from exc
    return quizzes.get_public_quiz(quiz_id)

@router.get('/workspaces/{workspace_id}/quizzes', response_model=list[QuizSummary])
def list_quizzes(workspace_id: str):
    return quizzes.list_quizzes(workspace_id)

@router.get('/quizzes/{quiz_id}', response_model=QuizGraded | QuizPublic)
def get_quiz(quiz_id: str):
    return quizzes.get_quiz(quiz_id)

@router.post('/quizzes/{quiz_id}/submit', response_model=QuizGraded)
def submit_quiz(quiz_id: str, body: QuizSubmit):
    return quizzes.submit_quiz(quiz_id, body.answers)

@router.get('/reviews', response_model=list[ReviewItem])
def list_reviews(workspace_id: str, status: Literal['open', 'reviewed'] | None = None):
    return reviews.list_reviews(workspace_id, status)

@router.get('/reviews/{review_id}', response_model=ReviewDetail)
def get_review(review_id: str):
    return reviews.get_review(review_id)

@router.patch('/reviews/{review_id}', response_model=ReviewItem)
def update_review(review_id: str, body: ReviewUpdate):
    return reviews.update_review(review_id, body.learner_reason, body.status)
