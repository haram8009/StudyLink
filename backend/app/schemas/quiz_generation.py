"""Model output schema for one quiz question (prompt `quiz-v2`).

Only shape is declared here: option count, blanks, duplicates and the answer reference are checked in code
(agents/quiz.py validate) so a bad question is regenerated once instead of failing schema parsing in strict mode.
Document ID, page and quote never come from the model; the server fills them from the evidence chunk."""
from pydantic import BaseModel, ConfigDict


class GeneratedOption(BaseModel):
    model_config = ConfigDict(extra='forbid')
    option_id: str
    text: str


class GeneratedQuestion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    stem: str
    options: list[GeneratedOption]
    answer_option_id: str
    explanation: str
