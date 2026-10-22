"""Runtime settings; mock and provider data always live in separate databases."""
from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / '.env')

@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    mock_llm: bool
    embedding_model: str
    embedding_dim: int
    gms_base_url: str
    gms_api_key: str
    chat_model: str
    max_upload_bytes: int
    min_score: float
    relative_margin: float
    max_evidence: int
    max_evidence_chars: int
    request_timeout: float
    http_timeout: float
    mock_scenario: str

    @property
    def retrieval_min_score(self):
        return self.min_score

    @property
    def max_context_chars(self):
        return self.max_evidence_chars

@lru_cache
def get_settings() -> Settings:
    mock = os.getenv('MOCK_LLM', '0').lower() in {'1', 'true', 'yes'}
    data = Path(os.getenv('DATA_DIR', str(ROOT / 'backend' / 'data'))).resolve()
    model = os.getenv('EMBEDDING_MODEL', 'text-embedding-3-small')
    return Settings(
        data_dir=data,
        db_path=data / ('mock.db' if mock else 'app.db'),
        mock_llm=mock, embedding_model=model,
        embedding_dim=int(os.getenv('EMBEDDING_DIM', '3072' if model.endswith('large') else '1536')),
        gms_base_url=os.getenv('GMS_BASE_URL', 'https://gms.ssafy.io/gmsapi/api.openai.com/v1').rstrip('/'),
        gms_api_key=os.getenv('GMS_KEY', os.getenv('GMS_API_KEY', '')), chat_model=os.getenv('CHAT_MODEL', 'gpt-4.1-mini'),
        max_upload_bytes=int(os.getenv('MAX_UPLOAD_BYTES', str(30 * 1024 * 1024))),
        min_score=float(os.getenv('MIN_SCORE', '0.2')), relative_margin=float(os.getenv('RELATIVE_MARGIN', '0.15')),
        max_evidence=int(os.getenv('MAX_EVIDENCE', '12')), max_evidence_chars=int(os.getenv('MAX_EVIDENCE_CHARS', '8000')),
        request_timeout=float(os.getenv('REQUEST_TIMEOUT', '30')), http_timeout=float(os.getenv('HTTP_TIMEOUT', '20')),
        mock_scenario=os.getenv('MOCK_SCENARIO', 'normal'),
    )
