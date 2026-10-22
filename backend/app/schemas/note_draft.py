"""Note draft: model output (with request-scoped [eN] markers) and the draft returned to the client.

NoteDraftCitation mirrors schemas.http.NoteCitationIn so a draft can be posted to POST /api/notes as is."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class GeneratedNoteDraft(BaseModel):
    """What the model returns: a short title and a Markdown body citing the source answer's [eN] ids."""
    model_config = ConfigDict(extra='forbid')
    title: str
    body: str


class NoteDraftCitation(BaseModel):
    id: str = Field(pattern=r'^c[1-9][0-9]*$')
    source_type: Literal['doc', 'note']
    document_id: str | None = None
    page: int | None = Field(default=None, ge=1)
    quote: str = Field(default='', max_length=4000)
    note_id: str | None = None


class NoteDraftOut(BaseModel):
    title: str
    body: str
    citations: list[NoteDraftCitation]
    fallback: bool
