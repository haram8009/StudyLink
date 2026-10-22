"""PDF ingestion publishes all chunks and ready atomically after embedding."""
from collections import Counter
import math
import re
from uuid import uuid4
import numpy as np
import pymupdf
from ..adapters.gms import embed, ProviderUnavailable
from ..config import get_settings
from ..db import get_connection
from .documents import get_document

class UnsupportedPDF(ValueError):
    pass

def extract_chunks(path):
    with pymupdf.open(path) as pdf:
        if pdf.needs_pass:
            raise UnsupportedPDF('암호화된 PDF는 지원하지 않습니다')
        if not pdf.page_count:
            raise UnsupportedPDF('페이지가 없는 PDF입니다')
        pages = [[line.strip() for line in page.get_text().splitlines() if line.strip()] for page in pdf]
        # A page with fewer than 20 non-whitespace characters is nearly empty.
        empty = sum(len(''.join(lines)) < 20 for lines in pages)
        if empty / len(pages) > .5:
            raise UnsupportedPDF('스캔 PDF는 지원하지 않습니다: 절반 넘는 페이지의 추출 텍스트가 20자 미만입니다')
    # Exported PDFs commonly have title and page number on separate footer lines.
    page_number_pattern = r'(?:page\s*)?\d+(?:\s*/\s*\d+)?'
    pages = [lines[:-1] if lines and re.fullmatch(page_number_pattern, lines[-1], re.I) else lines for lines in pages]
    def footer_key(line):
        return re.sub(r'\s+\d+(?:\s*/\s*\d+)?$', ' #', line)
    headers = Counter(lines[0] for lines in pages if lines)
    footers = Counter(footer_key(lines[-1]) for lines in pages if lines)
    threshold = max(2, math.ceil(len(pages) * .6))
    chunks = []
    for page_number, lines in enumerate(pages, start=1):
        if lines and len(pages) > 1 and headers[lines[0]] >= threshold:
            lines = lines[1:]
        if lines and len(pages) > 1 and footers[footer_key(lines[-1])] >= threshold:
            lines = lines[:-1]
        text = '\n'.join(lines).strip()
        for start in range(0, len(text), 800):
            chunk = text[start:start + 800].strip()
            if chunk:
                chunks.append((page_number, chunk))
    if not chunks:
        raise UnsupportedPDF('검색할 텍스트가 없는 PDF입니다')
    return len(pages), chunks

def ingest_document(document_id: str) -> None:
    document = get_document(document_id, internal=True)
    if document['status'] != 'processing':
        return
    try:
        page_count, chunks = extract_chunks(document['path'])
        settings = get_settings()
        records = []
        for start in range(0, len(chunks), 64):
            batch = chunks[start:start + 64]
            embeddings = np.asarray(embed([text for _, text in batch]), dtype=np.float32)
            if embeddings.shape != (len(batch), settings.embedding_dim) or not np.isfinite(embeddings).all():
                raise ValueError('Invalid embedding dimensions or values')
            for (page, text), vector in zip(batch, embeddings):
                records.append((str(uuid4()), 'doc', document_id, page, text, vector.tobytes(), settings.embedding_model, settings.embedding_dim))
        with get_connection() as db:
            db.execute("DELETE FROM chunks WHERE source_type='doc' AND source_id=?", (document_id,))
            db.executemany('INSERT INTO chunks(id,source_type,source_id,page,text,embedding,embedding_model,embedding_dim) VALUES (?,?,?,?,?,?,?,?)', records)
            db.execute("UPDATE documents SET status='ready',page_count=?,error=NULL WHERE id=?", (page_count, document_id))
    except Exception as exc:
        if isinstance(exc, UnsupportedPDF):
            error = str(exc)
        elif isinstance(exc, ProviderUnavailable):
            error = '임베딩 서비스에 연결할 수 없습니다. 잠시 후 재시도하세요'
        else:
            error = 'PDF 처리에 실패했습니다. 자료 형식과 임베딩 설정을 확인하세요'
        with get_connection() as db:
            db.execute("DELETE FROM chunks WHERE source_type='doc' AND source_id=?", (document_id,))
            db.execute("UPDATE documents SET status='failed',error=? WHERE id=?", (error, document_id))
