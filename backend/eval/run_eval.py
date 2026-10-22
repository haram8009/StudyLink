"""StudyLink retrieval/answer evaluation: question set -> CSV for human judgement.

Run from the repo root (real GMS calls unless --mock):

    .venv/Scripts/python backend/eval/run_eval.py --mock
    .venv/Scripts/python backend/eval/run_eval.py
    .venv/Scripts/python backend/eval/run_eval.py --min-score 0.3 --relative-margin 0.1 --run real-ms030

What it does, each run in a fresh DATA_DIR (default backend/data/eval/<run>, git-ignored):
1. Creates the workspaces "자연어처리 기초" (word-embedding PDF) and "LLM" (Transformer PDF) and ingests the
   demo PDFs through the app's own services (upload_document + ingest_document).
2. Creates the "기울기 소실 정리" note with the note service and links it to both workspaces (index runs on save).
3. Calls services.answer.answer_question(workspace, question) for every question (no history, include_notes=True)
   and reads the stored answer body (retrieval scores, note guarantee, research, search query, trace id).
4. Separately embeds each question once to record raw top scores (doc/note) and the expected page's rank, so
   MIN_SCORE / RELATIVE_MARGIN candidates can be compared without guessing.
5. Writes results.csv (utf-8-sig) and summary.json in the run directory and prints the summary.

The automatic columns (expected_page_cited, withheld, note_cited) are NOT a human verdict: whether a cited page
actually supports each claim must be judged by a person in the human_* columns.

Settings: MIN_SCORE / RELATIVE_MARGIN come from --min-score / --relative-margin, else the environment / .env,
else the app defaults. MOCK_LLM=1 (or --mock) uses the app's deterministic adapter (token-hash embeddings, so
mock numbers say nothing about search quality). Langfuse follows .env for real runs (only trace ids are written);
--no-trace turns it off, mock runs always turn it off. The app code is imported, never modified.
"""
import argparse
import csv
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
parser.add_argument('--questions', type=Path, default=HERE / 'questions.json')
parser.add_argument('--pdf-dir', type=Path, default=Path(os.getenv('DEMO_PDF_DIR', 'D:/SSAFY/demo_pdfs')))
parser.add_argument('--mock', action='store_true', help='same as MOCK_LLM=1')
parser.add_argument('--min-score', type=float, help='overrides MIN_SCORE')
parser.add_argument('--relative-margin', type=float, help='overrides RELATIVE_MARGIN')
parser.add_argument('--run', help='run name (directory under backend/data/eval)')
parser.add_argument('--data-dir', type=Path, help='explicit DATA_DIR (must be new or empty)')
parser.add_argument('--no-trace', action='store_true', help='force LANGFUSE_ENABLED=0')
parser.add_argument('--only', help='comma-separated question ids to run (debugging)')
parser.add_argument('--note-variant', help='diagnostic: use note.variants.<name>.body instead of the default note body')
args = parser.parse_args()

# Settings must be in the environment before the app reads them (get_settings is cached; .env never overrides).
if args.mock:
    os.environ['MOCK_LLM'] = '1'
if args.min_score is not None:
    os.environ['MIN_SCORE'] = str(args.min_score)
if args.relative_margin is not None:
    os.environ['RELATIVE_MARGIN'] = str(args.relative_margin)
sys.path.insert(0, str(ROOT / 'backend'))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / '.env')  # same file the app loads; existing environment wins
mock = os.getenv('MOCK_LLM', '0').lower() in {'1', 'true', 'yes'}
if mock or args.no_trace:
    os.environ['LANGFUSE_ENABLED'] = '0'
os.environ.setdefault('LANGFUSE_TRACING_ENVIRONMENT', 'development')
min_score = float(os.getenv('MIN_SCORE', '0.2'))
margin = float(os.getenv('RELATIVE_MARGIN', '0.15'))
run = args.run or f"{'mock' if mock else 'real'}-ms{min_score:g}-rm{margin:g}-{datetime.now():%Y%m%d-%H%M%S}"
data_dir = (args.data_dir or ROOT / 'backend' / 'data' / 'eval' / run).resolve()
if data_dir.exists() and any(data_dir.iterdir()):
    sys.exit(f'DATA_DIR already has data, choose another --run: {data_dir}')
data_dir.mkdir(parents=True, exist_ok=True)
os.environ['DATA_DIR'] = str(data_dir)

import numpy as np  # noqa: E402
from starlette.datastructures import Headers, UploadFile  # noqa: E402
from app.adapters import gms  # noqa: E402
from app.adapters.telemetry import flush  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import get_connection, init_db  # noqa: E402
from app.schemas.http import NoteCitationIn  # noqa: E402
from app.services.answer import answer_question  # noqa: E402
from app.services.documents import upload_document  # noqa: E402
from app.services.ingest import ingest_document  # noqa: E402
from app.services.notes import create_note, get_note  # noqa: E402
from app.services.workspaces import create_workspace  # noqa: E402

settings = get_settings()
assert settings.data_dir == data_dir and settings.mock_llm == mock
assert abs(settings.min_score - min_score) < 1e-9 and abs(settings.relative_margin - margin) < 1e-9
spec = json.loads(args.questions.read_text(encoding='utf-8'))
trace_on = os.getenv('LANGFUSE_ENABLED', '0') == '1'
print(f'run={run} mode={"mock" if mock else "real"} MIN_SCORE={min_score:g} RELATIVE_MARGIN={margin:g} '
      f'MAX_EVIDENCE={settings.max_evidence} chat_model={settings.chat_model} embedding={settings.embedding_model} '
      f'langfuse={"on" if trace_on else "off"}')
print(f'data_dir={data_dir}')

# ---- setup: workspaces, documents, note -------------------------------------------------------------
init_db()
workspaces = {key: create_workspace(value['title'], value['goal'])['id'] for key, value in spec['workspaces'].items()}
documents = {}
for key, doc in spec['documents'].items():
    path = args.pdf_dir / doc['filename']
    with path.open('rb') as source:
        upload = UploadFile(file=source, filename=doc['filename'], headers=Headers({'content-type': 'application/pdf'}))
        created = upload_document(workspaces[doc['workspace']], upload)
    ingest_document(created['id'])
    with get_connection() as db:
        row = db.execute('SELECT status,page_count,error FROM documents WHERE id=?', (created['id'],)).fetchone()
    if row['status'] != 'ready':
        sys.exit(f'ingest failed for {doc["filename"]}: {row["error"]}')
    documents[key] = {'id': created['id'], 'filename': doc['filename'], 'page_count': row['page_count']}
    print(f'ingested {doc["filename"]}: {row["page_count"]} pages, workspace={spec["workspaces"][doc["workspace"]]["title"]}')
note_spec = spec['note']
citations = [NoteCitationIn(id=c['id'], source_type=c['source_type'], document_id=documents[c['source']]['id'],
                            page=c['page'], quote=c.get('quote', '')) for c in note_spec['citations']]
note_body = note_spec['variants'][args.note_variant]['body'] if args.note_variant else note_spec['body']
note = create_note(note_spec['title'], note_body, [workspaces[w] for w in note_spec['workspaces']], citations)
note = get_note(note['id'])
print(f'note "{note["title"]}": index_status={note["index_status"]}, linked={len(note["workspace_ids"])} workspaces')
if note['index_status'] != 'ok':
    print('WARNING: note is not indexed; note citation cannot happen in this run')
doc_by_id = {value['id']: key for key, value in documents.items()}

# ---- raw score probe (read-only, mirrors retrieval scope without the MIN_SCORE filter) ------------------
def raw_scores(workspace_id, question):
    with get_connection() as db:
        rows = db.execute('''SELECT c.source_type, c.source_id, c.page, c.embedding FROM chunks c
            JOIN documents d ON c.source_type='doc' AND c.source_id=d.id
            WHERE d.workspace_id=? AND d.status='ready' AND c.embedding_model=? AND c.embedding_dim=?
            UNION ALL SELECT c.source_type, c.source_id, c.page, c.embedding FROM chunks c
            JOIN notes n ON c.source_type='note' AND c.source_id=n.id JOIN workspace_notes w ON w.note_id=n.id
            WHERE w.workspace_id=? AND n.index_status='ok' AND c.embedding_model=? AND c.embedding_dim=?''',
            (workspace_id, settings.embedding_model, settings.embedding_dim) * 2).fetchall()
    query = np.asarray(gms.embed([question])[0], dtype=np.float32)
    scored = []
    for row in rows:
        vector = np.frombuffer(row['embedding'], dtype=np.float32)
        denominator = float(np.linalg.norm(vector) * np.linalg.norm(query))
        if denominator:
            scored.append((float(np.dot(vector, query) / denominator), row['source_type'], row['source_id'], row['page']))
    scored.sort(key=lambda item: -item[0])
    return scored

def fmt(value):
    return '' if value is None else f'{value:.3f}'

# ---- questions ---------------------------------------------------------------------------------------
only = set(args.only.split(',')) if args.only else None
results = []
for item in spec['questions']:
    if only and item['id'] not in only:
        continue
    workspace_id = workspaces[item['workspace']]
    answerable = item['kind'] == 'answerable'
    expected_doc = documents[item['expected_source']] if answerable else None
    expected_pages = item.get('expected_pages', [])
    row = {'run': run, 'qid': item['id'], 'kind': item['kind'], 'workspace': spec['workspaces'][item['workspace']]['title'],
           'question': item['question'],
           'expected_source': expected_doc['filename'] if expected_doc else '',
           'expected_pages': ','.join(map(str, expected_pages)), 'expected_note': item.get('expect_note', ''),
           'unanswerable_reason': item.get('reason', '')}
    started = time.monotonic()
    try:
        answer = answer_question(workspace_id, item['question'])
        row['seconds'] = round(time.monotonic() - started, 2)
        with get_connection() as db:
            stored = json.loads(db.execute('SELECT body_json FROM answers WHERE id=?', (answer.answer_id,)).fetchone()[0])
        retrieval = stored.get('retrieval', [])
        scores = [entry['score'] for entry in retrieval]
        doc_cites = [c for c in answer.citations if c.source_type == 'doc']
        note_cites = [c for c in answer.citations if c.source_type == 'note']
        cited_pages = sorted({(doc_by_id.get(c.document_id, c.document_id), c.page) for c in doc_cites})
        row.update({
            'status': answer.status,
            'evidence_count': len(retrieval),
            'doc_evidence': sum(entry['source_type'] == 'doc' for entry in retrieval),
            'note_evidence': sum(entry['source_type'] == 'note' for entry in retrieval),
            'evidence_scores': ' '.join(f'{entry["source_type"][0]}{score:.3f}' for entry, score in zip(retrieval, scores)),
            'max_evidence_score': fmt(max(scores) if scores else None),
            'min_evidence_score': fmt(min(scores) if scores else None),
            'note_guaranteed': stored.get('note_guaranteed'),
            'research_performed': stored.get('research', {}).get('performed'),
            'search_query': stored.get('search_query', ''),
            'research_query': stored.get('research', {}).get('query') or '',
            'cited_doc_pages': '; '.join(f'{documents[key]["filename"] if key in documents else key} p.{page}' for key, page in cited_pages),
            'cited_notes': '; '.join(sorted({c.title for c in note_cites})),
            'trace_id': stored.get('trace_id') or '',
            'answer_text': ' '.join(f'{s.text} [{",".join(s.citation_ids)}]' for s in answer.segments).replace('\n', ' '),
        })
        if answerable:
            hit = any(c.document_id == expected_doc['id'] and c.page in expected_pages for c in doc_cites)
            row['auto_expected_page_cited'] = 'Y' if hit else 'N'
            if item.get('expect_note'):
                row['auto_note_cited'] = 'Y' if any(c.title == item['expect_note'] for c in note_cites) else 'N'
        else:
            row['auto_withheld'] = 'Y' if answer.status == 'insufficient_evidence' else 'N'
    except Exception as exc:  # record and continue; a provider failure is a result too
        row['seconds'] = round(time.monotonic() - started, 2)
        row['status'] = f'error:{type(exc).__name__}'
        row['answer_text'] = str(getattr(exc, 'detail', exc))[:300]
        if answerable:
            row['auto_expected_page_cited'] = 'N'
            if item.get('expect_note'):
                row['auto_note_cited'] = 'N'
        else:
            row['auto_withheld'] = 'N'
    try:
        scored = raw_scores(workspace_id, item['question'])
        docs = [s for s in scored if s[1] == 'doc']
        notes = [s for s in scored if s[1] == 'note']
        row['raw_top_doc_score'] = fmt(docs[0][0] if docs else None)
        row['raw_top_doc_page'] = docs[0][3] if docs else ''
        row['raw_top_note_score'] = fmt(notes[0][0] if notes else None)
        if expected_doc:
            ranks = [(rank, s) for rank, s in enumerate(docs, 1) if s[2] == expected_doc['id'] and s[3] in expected_pages]
            row['raw_expected_page_rank'] = ranks[0][0] if ranks else ''
            row['raw_expected_page_score'] = fmt(ranks[0][1][0] if ranks else None)
    except Exception as exc:
        row['raw_top_doc_score'] = f'error:{type(exc).__name__}'
    results.append(row)
    flag = row.get('auto_expected_page_cited') or row.get('auto_withheld')
    extra = f' note={row["auto_note_cited"]}' if 'auto_note_cited' in row else ''
    print(f'{row["qid"]} {row["status"]:<22} auto={flag}{extra} ev={row.get("evidence_count", "-")} '
          f'max={row.get("max_evidence_score", "")} raw_doc={row.get("raw_top_doc_score", "")} '
          f'research={row.get("research_performed", "")} cited=[{row.get("cited_doc_pages", "")}|{row.get("cited_notes", "")}] {row["seconds"]}s')

flush()

# ---- output ------------------------------------------------------------------------------------------
columns = ['run', 'qid', 'kind', 'workspace', 'question', 'expected_source', 'expected_pages', 'expected_note',
           'unanswerable_reason', 'status', 'evidence_count', 'doc_evidence', 'note_evidence', 'evidence_scores',
           'max_evidence_score', 'min_evidence_score', 'note_guaranteed', 'research_performed', 'search_query',
           'research_query', 'cited_doc_pages', 'cited_notes', 'auto_expected_page_cited', 'auto_note_cited',
           'auto_withheld', 'raw_top_doc_score', 'raw_top_doc_page', 'raw_top_note_score', 'raw_expected_page_rank',
           'raw_expected_page_score', 'trace_id', 'seconds', 'answer_text',
           'human_verdict', 'human_supported', 'human_comment']
csv_path = data_dir / 'results.csv'
with csv_path.open('w', encoding='utf-8-sig', newline='') as output:
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction='ignore')
    writer.writeheader()
    for row in results:
        writer.writerow({column: row.get(column, '') for column in columns})

answerable_rows = [r for r in results if r['kind'] == 'answerable']
absent_rows = [r for r in results if r['kind'] != 'answerable']
note_rows = [r for r in results if r.get('expected_note')]
summary = {
    'run': run, 'mode': 'mock' if mock else 'real', 'min_score': min_score, 'relative_margin': margin,
    'max_evidence': settings.max_evidence, 'chat_model': settings.chat_model, 'embedding_model': settings.embedding_model,
    'langfuse': trace_on, 'note_index_status': note['index_status'], 'note_variant': args.note_variant or 'default',
    'only': sorted(only) if only else None,
    'answerable_expected_page': f'{sum(r.get("auto_expected_page_cited") == "Y" for r in answerable_rows)}/{len(answerable_rows)}',
    'unanswerable_withheld': f'{sum(r.get("auto_withheld") == "Y" for r in absent_rows)}/{len(absent_rows)}',
    'note_cited': {r['qid']: r.get('auto_note_cited') for r in note_rows},
    'failed': [r['qid'] for r in results if r.get('auto_expected_page_cited') == 'N' or r.get('auto_withheld') == 'N'],
    'errors': [r['qid'] for r in results if str(r.get('status', '')).startswith('error')],
    'total_seconds': round(sum(r['seconds'] for r in results), 1),
    'csv': str(csv_path),
}
(data_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
print('---- summary (automatic comparison, not a human verdict) ----')
print(f'answerable expected page cited: {summary["answerable_expected_page"]} (target 8/10)')
print(f'unanswerable withheld:          {summary["unanswerable_withheld"]} (target 4/5)')
print(f'note cited: {summary["note_cited"]}')
print(f'failed: {summary["failed"]} errors: {summary["errors"]}')
print(f'CSV: {csv_path}')
