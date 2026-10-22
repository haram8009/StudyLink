"""HTTP response models for quizzes and reviews.

QuestionPublic has no answer/explanation/quote fields at all, so an ungraded response
cannot leak them by forgetting to drop a key (architecture 4.4).
"""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class OptionOut(BaseModel):
    option_id: str
    text: str

class QuestionPublic(BaseModel):
    model_config = ConfigDict(extra='ignore')
    question_id: str
    stem: str
    options: list[OptionOut]
    document_id: str
    filename: str | None = None
    page: int

class QuestionGraded(QuestionPublic):
    selected_option_id: str
    answer_option_id: str
    correct: bool
    explanation: str
    quote: str = ''

class QuizPublic(BaseModel):
    quiz_id: str
    workspace_id: str
    requested_count: int
    actual_count: int
    created_at: str
    submitted_at: None = None
    questions: list[QuestionPublic]

class QuizGraded(BaseModel):
    quiz_id: str
    workspace_id: str
    requested_count: int
    actual_count: int
    created_at: str
    submitted_at: str
    score: int
    total: int
    questions: list[QuestionGraded]

class QuizSummary(BaseModel):
    quiz_id: str
    requested_count: int
    actual_count: int
    created_at: str
    submitted_at: str | None = None
    score: int | None = None

class RelatedNoteOut(BaseModel):
    note_id: str
    title: str
    snippet: str = ''

class LinkedRelatedNote(RelatedNoteOut):
    linked: bool

class ReviewItem(BaseModel):
    review_id: str
    workspace_id: str
    quiz_id: str
    question_id: str
    stem: str
    selected_option_id: str
    answer_option_id: str
    options: list[OptionOut]
    explanation: str
    document_id: str
    filename: str | None = None
    page: int
    quote: str = ''
    status: Literal['open', 'reviewed']
    learner_reason: str
    created_at: str

class ReviewDetail(ReviewItem):
    related_notes: list[LinkedRelatedNote] = Field(default_factory=list)
    related_notes_status: Literal['ok', 'unavailable'] = 'ok'

class NoteDraftOut(BaseModel):
    model_config = ConfigDict(extra='ignore')
    title: str
    body: str
    citations: list[dict]
    fallback: bool
