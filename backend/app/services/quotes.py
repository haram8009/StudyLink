"""Short quotes cut from a cited chunk, and their highlight boxes on the PDF page.

A quote is always an exact run of 1-3 consecutive chunk lines (PDF text lines), so the viewer can find it on the
page again. It is chosen by character-bigram overlap with the text that cites it; no model call is involved."""
import re
import pymupdf
from fastapi import HTTPException
from .documents import document_path, get_document

MAX_QUOTE_CHARS = 160
MAX_LINES = 3


def _bigrams(text: str) -> set[str]:
    compact = re.sub(r'\s+', '', text.lower())
    return {compact[i:i + 2] for i in range(len(compact) - 1)}


def pick_quote(text: str, reference: str, limit: int = MAX_QUOTE_CHARS) -> str:
    """Return the run of chunk lines closest to reference, at most `limit` characters."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ''
    target = _bigrams(reference)
    best, best_score = lines[0][:limit], -1.0
    for start in range(len(lines)):
        for end in range(start + 1, min(start + MAX_LINES, len(lines)) + 1):
            candidate = '\n'.join(lines[start:end])
            if end > start + 1 and len(candidate) > limit:
                break
            candidate = candidate[:limit]
            grams = _bigrams(candidate)
            if not grams:
                continue
            # Recall of the reference with a small precision term so a tight match beats a long run.
            shared = len(grams & target)
            score = shared / max(len(target), 1) + 0.25 * shared / len(grams)
            if score > best_score:
                best, best_score = candidate, score
    return best


def _merge_by_line(rects: list) -> list:
    """search_for splits one hit at font changes (Hangul/Latin); join boxes that sit on the same text line."""
    merged: list = []
    for rect in sorted(rects, key=lambda r: r.x0):
        for i, box in enumerate(merged):
            same_line = min(box.y1, rect.y1) - max(box.y0, rect.y0) > 0.5 * min(box.height, rect.height)
            if same_line and rect.x0 - box.x1 < 6:
                merged[i] = box | rect
                break
        else:
            merged.append(pymupdf.Rect(rect))
    return sorted(merged, key=lambda r: (r.y0, r.x0))


def find_highlights(document_id: str, page: int, quote: str) -> dict:
    """Boxes for quote on page, in PDF points from the top-left. Missing text yields no boxes, not an error."""
    document = get_document(document_id)
    if document['status'] != 'ready':
        raise HTTPException(409, '처리가 끝난 자료만 열 수 있습니다')
    path, _ = document_path(document_id)
    with pymupdf.open(path) as pdf:
        if not 1 <= page <= pdf.page_count:
            raise HTTPException(404, '페이지를 찾을 수 없습니다')
        target = pdf[page - 1]
        rects = []
        for line in (part.strip() for part in quote.splitlines()):
            if not line:
                continue
            found = target.search_for(line)
            if not found and len(line) > 24:
                # Line breaks inside the quote may not match the PDF; fall back to the line's opening words.
                found = target.search_for(line[:24])
            hits = _merge_by_line(found)
            if len(hits) > 1:
                # A short line can occur several times; keep the hit nearest the previous quote line.
                hits = [min(hits, key=lambda r: abs(r.y0 - rects[-1].y1))] if rects else hits[:1]
            rects.extend(hits)
        return {'page': page, 'width': target.rect.width, 'height': target.rect.height,
                'rects': [[round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2)] for r in rects]}
