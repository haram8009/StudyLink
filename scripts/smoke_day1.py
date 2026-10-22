"""Exercise actual API/ingestion/provider integration against the approved demo PDF.

Run from repo root: .venv/Scripts/python scripts/smoke_day1.py --pdf PATH [--real] [--trace]
Uses a separate local data directory and makes provider calls only with --real.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--pdf', type=Path, required=True)
parser.add_argument('--real', action='store_true')
parser.add_argument('--trace', action='store_true')
args = parser.parse_args()
os.environ['MOCK_LLM'] = '0' if args.real else '1'
os.environ['LANGFUSE_ENABLED'] = '1' if args.trace else '0'
os.environ.setdefault('LANGFUSE_TRACING_ENVIRONMENT', 'development')
os.environ['DATA_DIR'] = str(root / 'backend' / 'data' / ('smoke-real' if args.real else 'smoke-mock'))
sys.path.insert(0, str(root / 'backend'))

from fastapi.testclient import TestClient
from app.main import app
from app.adapters.telemetry import flush
from app.db import get_connection

report = {'mode': 'real' if args.real else 'mock', 'trace_enabled': args.trace}
with TestClient(app) as client:
    response = client.post('/api/workspaces', json={'title': '1일차 통합 확인', 'goal': '페이지 근거 확인'})
    assert response.status_code == 201, response.text
    workspace = response.json()['id']
    report['workspace_id'] = workspace
    empty = client.post(f'/api/workspaces/{workspace}/ask', json={'question': 'test', 'include_notes': False})
    assert empty.status_code == 400, empty.text
    with args.pdf.open('rb') as source:
        response = client.post(f'/api/workspaces/{workspace}/documents', files={'file': (args.pdf.name, source, 'application/pdf')})
    assert response.status_code == 202, response.text
    document = response.json()['id']
    status = client.get(f'/api/documents/{document}').json()
    assert status['status'] == 'ready', status
    report['document_id'] = document
    report['page_count'] = status['page_count']
    pdf = client.get(f'/api/documents/{document}/file')
    assert pdf.status_code == 200 and pdf.content.startswith(b'%PDF')
    question = 'Vanishing gradient가 뭐야?' if args.real else '임베딩'
    started = time.monotonic()
    response = client.post(f'/api/workspaces/{workspace}/ask', json={'question': question, 'include_notes': False})
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer['status'] == 'grounded', answer
    ids = {item['id'] for item in answer['citations']}
    assert all(segment['citation_ids'] and set(segment['citation_ids']) <= ids for segment in answer['segments'])
    assert all(item['document_id'] == document and 1 <= item['page'] <= status['page_count'] for item in answer['citations'])
    report['answer_seconds'] = round(time.monotonic() - started, 2)
    report['answer'] = answer
    with get_connection() as connection:
        stored = json.loads(connection.execute('SELECT body_json FROM answers WHERE id=?', (answer['answer_id'],)).fetchone()[0])
    report['trace_id'] = stored.get('trace_id')
    report['retrieved_chunk_count'] = len(stored.get('retrieval', []))
    if args.real:
        response = client.post(f'/api/workspaces/{workspace}/ask', json={'question': '이 자료에 나온 제주도 내일 날씨와 강수확률을 알려줘', 'include_notes': False})
        assert response.status_code == 200, response.text
        report['absent_question_status'] = response.json()['status']
        assert report['absent_question_status'] == 'insufficient_evidence', response.text
with TestClient(app) as client:
    assert client.get(f'/api/workspaces/{workspace}').status_code == 200
    assert client.get(f'/api/documents/{document}').json()['status'] == 'ready'
report['restart_persistence'] = True
flush()
destination = Path(os.environ['DATA_DIR']) / 'smoke-report.json'
destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
print(f'Report: {destination}')
