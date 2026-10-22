"""Note indexing: title + body paragraphs -> embedded 'note' chunks, replaced as a whole.

The embedding call runs outside any SQLite write transaction. Old chunks are removed before embedding so
a stale body is never searched; the new chunks are published only if the note still has the content that
was embedded (a newer save re-indexes on its own). Errors never escape: failures end as index_status='failed'."""
import logging
import re
from uuid import uuid4
import numpy as np
from ..adapters import gms
from ..adapters.telemetry import observe
from ..config import get_settings
from ..db import get_connection

CHUNK_CHARS = 800
EMBED_BATCH = 64
logger = logging.getLogger(__name__)

def note_chunks(title: str, body: str) -> list[str]:
    """One chunk per body paragraph (split at CHUNK_CHARS), each prefixed by the note title."""
    title = (title or '').strip()
    paragraphs = [part.strip() for part in re.split(r'\n\s*\n', body or '') if part.strip()]
    budget = max(1, CHUNK_CHARS - len(title) - 1) if title else CHUNK_CHARS
    chunks = []
    for paragraph in paragraphs:
        for start in range(0, len(paragraph), budget):
            piece = paragraph[start:start + budget].strip()
            if piece:
                chunks.append(f'{title}\n{piece}' if title else piece)
    if not chunks and title:
        chunks.append(title)
    return chunks

def _embed_all(texts):
    settings = get_settings()
    vectors = []
    for start in range(0, len(texts), EMBED_BATCH):
        batch = texts[start:start + EMBED_BATCH]
        embeddings = np.asarray(gms.embed(batch), dtype=np.float32)
        if embeddings.shape != (len(batch), settings.embedding_dim) or not np.isfinite(embeddings).all():
            raise ValueError('Invalid embedding dimensions or values')
        vectors.extend(embeddings)
    return vectors

def _mark_failed(note_id, snapshot):
    try:
        with get_connection() as db:
            current = db.execute('SELECT title, body FROM notes WHERE id=?', (note_id,)).fetchone()
            if current is None or (snapshot is not None and (current['title'], current['body']) != snapshot):
                return
            db.execute("DELETE FROM chunks WHERE source_type='note' AND source_id=?", (note_id,))
            db.execute("UPDATE notes SET index_status='failed' WHERE id=?", (note_id,))
    except Exception:
        logger.exception('note index failure could not be recorded')

def index_note(note_id: str) -> str:
    """Re-index one note; returns the resulting index_status ('ok' or 'failed'). Never raises."""
    snapshot = None
    with observe('index_note', metadata={'note_id': note_id}) as span:
        try:
            settings = get_settings()
            with get_connection() as db:
                row = db.execute('SELECT title, body FROM notes WHERE id=?', (note_id,)).fetchone()
                if row is None:
                    span.update(output={'status': 'failed', 'reason': 'missing_note'})
                    return 'failed'
                snapshot = (row['title'], row['body'])
                db.execute("DELETE FROM chunks WHERE source_type='note' AND source_id=?", (note_id,))
            texts = note_chunks(*snapshot)
            vectors = _embed_all(texts) if texts else []
            records = [(str(uuid4()), 'note', note_id, None, text, vector.tobytes(), settings.embedding_model, settings.embedding_dim)
                       for text, vector in zip(texts, vectors)]
            with get_connection() as db:
                current = db.execute('SELECT title, body, index_status FROM notes WHERE id=?', (note_id,)).fetchone()
                if current is None:
                    span.update(output={'status': 'failed', 'reason': 'missing_note'})
                    return 'failed'
                if (current['title'], current['body']) != snapshot:
                    span.update(output={'status': current['index_status'], 'reason': 'superseded'})
                    return current['index_status']
                db.execute("DELETE FROM chunks WHERE source_type='note' AND source_id=?", (note_id,))
                db.executemany('INSERT INTO chunks(id,source_type,source_id,page,text,embedding,embedding_model,embedding_dim) VALUES (?,?,?,?,?,?,?,?)', records)
                db.execute("UPDATE notes SET index_status='ok' WHERE id=?", (note_id,))
            span.update(output={'status': 'ok', 'chunks': len(records)})
            return 'ok'
        except Exception as exc:
            logger.warning('note indexing failed for %s: %s', note_id, type(exc).__name__)
            _mark_failed(note_id, snapshot)
            span.update(output={'status': 'failed', 'error': type(exc).__name__})
            return 'failed'
