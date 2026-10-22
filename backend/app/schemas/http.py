from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    goal: str = Field(default='', max_length=2000)

class AskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=4000)
    include_notes: bool = True

class HighlightRequest(BaseModel):
    """Quote text to locate on one PDF page (body, not query string, so page text stays out of URLs)."""
    page: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=4000)

class ChatCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str | None = Field(default=None, max_length=200)

class NoteCitationIn(BaseModel):
    """Persistent note citation [cN]: a document page or another note."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='ignore')
    id: str = Field(pattern=r'^c[1-9][0-9]*$')
    source_type: Literal['doc', 'note']
    document_id: str | None = None
    page: int | None = Field(default=None, ge=1)
    quote: str = Field(default='', max_length=4000)
    note_id: str | None = None

    @model_validator(mode='after')
    def check_target(self):
        if self.source_type == 'doc' and (not self.document_id or self.page is None):
            raise ValueError('자료 인용에는 document_id와 page가 필요합니다')
        if self.source_type == 'note' and not self.note_id:
            raise ValueError('노트 인용에는 note_id가 필요합니다')
        return self

class NoteCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=100_000)
    workspace_ids: list[str] = Field(default_factory=list)
    citations: list[NoteCitationIn] = Field(default_factory=list)

class NoteUpdate(BaseModel):
    """Full replacement of title/body/citations; workspace_ids=None keeps current links."""
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=100_000)
    citations: list[NoteCitationIn] = Field(default_factory=list)
    workspace_ids: list[str] | None = None

class QuizCreate(BaseModel):
    count: int = Field(default=5, ge=1, le=5)

class QuizSubmit(BaseModel):
    """answers: {question_id: option_id}; completeness is checked against the stored quiz."""
    answers: dict[str, str]

class ReviewUpdate(BaseModel):
    learner_reason: str | None = Field(default=None, max_length=2000)
    status: Literal['open', 'reviewed'] | None = None

class RelatedNotesRequest(BaseModel):
    title: str = Field(default='', max_length=200)
    body: str = Field(default='', max_length=100_000)
    exclude_note_id: str | None = None
