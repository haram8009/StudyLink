"""Evidence search over a workspace's ready PDFs and, optionally, its linked and indexed notes."""
from dataclasses import asdict, dataclass, replace
import numpy as np
from ..adapters import gms
from ..adapters.telemetry import observe
from ..config import get_settings
from ..db import get_connection

class NoSearchableContent(ValueError):
    pass

@dataclass(frozen=True)
class Evidence:
    chunk_id: str
    source_type: str
    source_id: str
    page: int | None
    title: str
    text: str
    score: float

_DOC_SQL = '''SELECT c.id, c.source_type, c.source_id, c.page, c.text, c.embedding, d.filename AS title FROM chunks c
    JOIN documents d ON c.source_type='doc' AND c.source_id=d.id
    WHERE d.workspace_id=? AND d.status='ready' AND c.embedding_model=? AND c.embedding_dim=?'''
_NOTE_SQL = '''SELECT c.id, c.source_type, c.source_id, c.page, c.text, c.embedding, n.title AS title FROM chunks c
    JOIN notes n ON c.source_type='note' AND c.source_id=n.id
    JOIN workspace_notes wn ON wn.note_id=n.id
    WHERE wn.workspace_id=? AND n.index_status='ok' AND c.embedding_model=? AND c.embedding_dim=?'''

def _load_candidates(workspace_id, include_notes):
    settings = get_settings()
    params = (workspace_id, settings.embedding_model, settings.embedding_dim)
    sql = f'{_DOC_SQL} UNION ALL {_NOTE_SQL} ORDER BY 1' if include_notes else f'{_DOC_SQL} ORDER BY 1'
    with get_connection() as connection:
        rows = connection.execute(sql, params * 2 if include_notes else params).fetchall()
        if not rows:
            processing = connection.execute("SELECT 1 FROM documents WHERE workspace_id=? AND status='processing' LIMIT 1", (workspace_id,)).fetchone()
            raise NoSearchableContent('자료를 처리하는 중입니다' if processing else '검색할 자료나 노트가 없습니다')
    return rows

def search_candidates(workspace_id: str, query: str, include_notes: bool = True, *, deadline=None) -> tuple[list[Evidence], int]:
    """All in-scope chunks scoring at least MIN_SCORE (best first) and the in-scope candidate count.

    Raises NoSearchableContent when the scope has no searchable chunk at all."""
    settings = get_settings()
    gms.check_deadline(deadline)
    rows = _load_candidates(workspace_id, include_notes)
    query_vector = gms.embed([query], deadline=deadline)[0]
    query_norm = float(np.linalg.norm(query_vector))
    ranked = []
    for row in rows:
        if len(row['embedding']) != settings.embedding_dim * 4:
            continue
        vector = np.frombuffer(row['embedding'], dtype=np.float32)
        norm = float(np.linalg.norm(vector))
        if not norm or not query_norm or not np.isfinite(vector).all():
            continue
        score = float(np.dot(vector, query_vector) / (norm * query_norm))
        if score >= settings.min_score:
            ranked.append(Evidence(row['id'], row['source_type'], row['source_id'], row['page'], row['title'] or '', row['text'], score))
    ranked.sort(key=lambda item: (-item.score, item.chunk_id))
    gms.check_deadline(deadline)
    return ranked, len(rows)

def merge_ranked(*lists: list[Evidence]) -> list[Evidence]:
    """Union by chunk_id keeping the higher score, best first."""
    best: dict[str, Evidence] = {}
    for items in lists:
        for item in items:
            if item.chunk_id not in best or item.score > best[item.chunk_id].score:
                best[item.chunk_id] = item
    return sorted(best.values(), key=lambda item: (-item.score, item.chunk_id))

def select_evidence(ranked: list[Evidence]) -> tuple[list[Evidence], bool]:
    """Relative cutoff and count/char caps, then guarantee one note if any note passed MIN_SCORE.

    Returns (evidence, note_guaranteed); note_guaranteed is true only when the guarantee added a note."""
    settings = get_settings()
    max_count = min(12, settings.max_evidence)
    max_chars = min(8000, settings.max_evidence_chars)
    result, length = [], 0
    if ranked:
        cutoff = ranked[0].score - settings.relative_margin
        for item in ranked:
            if item.score < cutoff or len(result) >= max_count:
                break
            remaining = max_chars - length
            if remaining <= 0:
                break
            item = replace(item, text=item.text[:remaining])
            result.append(item)
            length += len(item.text)
    best_note = next((item for item in ranked if item.source_type == 'note'), None)
    if best_note is None or any(item.source_type == 'note' for item in result):
        return result, False
    # result holds only PDF evidence here: drop the lowest-ranked ones until the note fits.
    while result and (len(result) >= max_count or sum(len(item.text) for item in result) >= max_chars):
        result.pop()
    remaining = max_chars - sum(len(item.text) for item in result)
    result.append(replace(best_note, text=best_note.text[:remaining]))
    return result, True

def retrieve(workspace_id: str, query: str, include_notes: bool = True, *, deadline=None) -> list[Evidence]:
    return retrieve_detailed(workspace_id, query, include_notes, deadline=deadline)['evidence']

def retrieve_detailed(workspace_id: str, query: str, include_notes: bool = True, *, deadline=None, metadata=None) -> dict:
    """One traced search: {'evidence', 'ranked', 'candidate_count', 'note_guaranteed'}."""
    with observe('retrieve', as_type='retriever', input={'workspace_id': workspace_id, 'query': query, 'include_notes': include_notes},
                 metadata=metadata or {}) as span:
        ranked, count = search_candidates(workspace_id, query, include_notes, deadline=deadline)
        evidence, guaranteed = select_evidence(ranked)
        span.update(output=[asdict(item) for item in evidence],
                    metadata={**(metadata or {}), 'candidate_count': count, 'above_min_score': len(ranked), 'note_guaranteed': guaranteed})
        return {'evidence': evidence, 'ranked': ranked, 'candidate_count': count, 'note_guaranteed': guaranteed}
