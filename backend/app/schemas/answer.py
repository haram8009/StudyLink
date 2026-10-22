from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class Segment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str
    citation_ids: list[str]

class GeneratedAnswer(BaseModel):
    """answerable comes first so the model decides whether the evidence answers the question before writing."""
    model_config = ConfigDict(extra='forbid')
    answerable: bool
    segments: list[Segment]

class Citation(BaseModel):
    id: str
    source_type: Literal['doc', 'note']
    document_id: str | None = None
    note_id: str | None = None
    page: int | None = Field(default=None, ge=1)
    title: str = ''
    quote: str = ''

class AnswerOut(BaseModel):
    answer_id: str
    status: Literal['grounded', 'insufficient_evidence']
    segments: list[Segment]
    citations: list[Citation]

class NoteLinks(BaseModel):
    """Sentences from the learner's notes that explain terms used in a grounded answer."""
    model_config = ConfigDict(extra='forbid')
    note_explanations: list[Segment]

class RewrittenQuery(BaseModel):
    """Standalone search query produced from a follow-up question or a weak first search."""
    model_config = ConfigDict(extra='forbid')
    query: str
