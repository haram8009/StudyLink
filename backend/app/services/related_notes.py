"""related_notes(text): notes similar to unsaved text, across every indexed note (no workspace scope).

The input text is embedded once and never stored. Scores stay internal."""
import numpy as np
from ..adapters import gms
from ..adapters.telemetry import observe
from ..config import get_settings
from ..db import get_connection

SNIPPET_CHARS = 160

_SQL = '''SELECT c.id, c.source_id AS note_id, c.text, c.embedding, n.title FROM chunks c
    JOIN notes n ON c.source_type='note' AND c.source_id=n.id
    WHERE n.index_status='ok' AND c.embedding_model=? AND c.embedding_dim=?'''


def _snippet(text: str, title: str) -> str:
    # note_index chunks are "title\nparagraph": show the paragraph only.
    if title and text.startswith(title + '\n'):
        text = text[len(title) + 1:]
    text = ' '.join(text.split())
    return text if len(text) <= SNIPPET_CHARS else text[:SNIPPET_CHARS - 1].rstrip() + '…'


def related_notes(text: str, exclude_note_id: str | None = None, k: int = 3) -> list[dict]:
    """Up to k distinct notes [{'note_id','title','snippet'}], best chunk per note, MIN_SCORE applied.

    ProviderUnavailable from the embedding call propagates."""
    if not text or not text.strip() or k <= 0:
        return []
    settings = get_settings()
    with observe('related_notes', as_type='retriever',
                 input={'text_chars': len(text), 'exclude_note_id': exclude_note_id, 'k': k}) as span:
        params = [settings.embedding_model, settings.embedding_dim]
        sql = _SQL
        if exclude_note_id:
            sql += ' AND n.id<>?'
            params.append(exclude_note_id)
        with get_connection() as db:
            rows = db.execute(sql, params).fetchall()
        if not rows:
            span.update(output=[], metadata={'candidate_count': 0})
            return []
        query = np.asarray(gms.embed([text])[0], dtype=np.float32)
        query_norm = float(np.linalg.norm(query))
        best: dict[str, tuple[float, str, dict]] = {}
        if query_norm and np.isfinite(query).all():
            for row in rows:
                if len(row['embedding']) != settings.embedding_dim * 4:
                    continue
                vector = np.frombuffer(row['embedding'], dtype=np.float32)
                norm = float(np.linalg.norm(vector))
                if not norm or not np.isfinite(vector).all():
                    continue
                score = float(np.dot(vector, query) / (norm * query_norm))
                if score < settings.min_score:
                    continue
                current = best.get(row['note_id'])
                if current is None or (score, row['id']) > (current[0], current[1]):
                    best[row['note_id']] = (score, row['id'], row)
        ranked = sorted(best.items(), key=lambda item: (-item[1][0], item[0]))[:k]
        result = [{'note_id': note_id, 'title': row['title'] or '', 'snippet': _snippet(row['text'], row['title'] or '')}
                  for note_id, (_, _, row) in ranked]
        span.update(output=[item['note_id'] for item in result],
                    metadata={'candidate_count': len(rows), 'above_min_score': len(best)})
        return result
