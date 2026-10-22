from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class Segment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str
    citation_ids: list[str]

class GeneratedAnswer(BaseModel):
    model_config = ConfigDict(extra='forbid')
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

class RewrittenQuery(BaseModel):
    """Standalone search query produced from a follow-up question or a weak first search."""
    model_config = ConfigDict(extra='forbid')
    query: str
