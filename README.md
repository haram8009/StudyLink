# StudyLink

PDF 자료에서 근거 답변을 찾는 로컬 개인 학습 앱이다. 1일차 구현 범위는 워크스페이스 생성 → PDF 수집 → 질문 → 페이지 인용 답변이다.

## 실행

검증 환경: Windows, Python 3.12, Node.js 24. 기존 실습 가상환경과 독립된 환경을 사용한다.

처음 설치할 때 저장소 루트에서:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.lock.txt
Copy-Item .env.example .env
cd frontend
npm.cmd ci
```

이미 설정한 `.env`가 있다면 복사하지 않는다. GMS 실사용에는 `GMS_KEY`가 필요하다. `GMS_BASE_URL`은 GMS 웹 화면 주소가 아니라 `.env.example`에 있는 OpenAI 호환 API 주소를 사용한다.

터미널 1 — 저장소 루트:

```powershell
.venv/Scripts/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

터미널 2:

```powershell
cd frontend
npm.cmd run dev
```

[앱 열기](http://localhost:5173), [API 문서](http://127.0.0.1:8000/docs). 프런트 개발 서버가 `/api`를 백엔드로 전달한다. 서버는 로컬 주소에만 바인딩한다.

## 외부 모델 없이 실행

백엔드를 시작할 터미널에서 `$env:MOCK_LLM="1"`을 설정하면 실제 API·SQLite·수집·그래프를 유지하면서 모델 어댑터만 목 응답으로 바꾼다. 목 임베딩은 토큰 해시이므로 실제 검색 품질을 평가할 수 없다. `MOCK_SCENARIO`는 `normal`, `invalid_json`, `invalid_citation`, `insufficient`, `provider_error`를 지원한다. 실제 모드 복귀는 해당 터미널에서 `$env:MOCK_LLM="0"`을 설정하고 서버를 다시 시작한다.

화면만 확인하려면 프런트 터미널에서 `$env:VITE_USE_MOCK="true"`를 설정한 뒤 Vite를 시작한다. 이 모드는 브라우저 localStorage를 사용하며 실제 PDF를 분석하지 않는다. 실제 API 연결이 기본이다.

## 데이터와 관측

- 기본 저장 위치는 `backend/data/`다. 실제 DB `app.db`, 목 DB `mock.db`를 분리하며 수집한 PDF는 `uploads/`에 둔다. `DATA_DIR`로 위치를 바꿀 수 있다.
- 서버 재시작 후 워크스페이스·ready 자료·완료 답변은 남는다. processing 자료는 failed로 전환하고 화면에서 다시 처리한다. 답변을 다시 여는 화면은 2일차 이후 작업이다.
- 텍스트 PDF만 지원한다. 업로드 제한은 기본 30MB이며 `MAX_UPLOAD_BYTES`로 설정한다. 절반 넘는 페이지의 추출 텍스트가 20자 미만이면 스캔 PDF로 안내한다.
- 모델·차원이 바뀌면 기존 청크는 검색에서 제외된다. 해당 자료를 새로 업로드해 수집할 수 있다. 일괄 재색인 도구와 노트 색인은 후속 작업이다.
- Langfuse는 `LANGFUSE_ENABLED=1`과 세 인증 설정으로 켠다. 프롬프트의 PDF 발췌·질문·답변이 지정한 클라우드 프로젝트에 저장된다. 현재 허용된 데모 PDF 2개를 기준으로 검증했다. 설정이 없거나 관측이 실패해도 학습 기능은 동작한다.
- 비밀키·DB·업로드 자료·환경·빌드 결과는 Git에서 제외한다.

## 검증

저장소 루트에서:

```powershell
.venv/Scripts/python -m pytest -q
cd frontend
npm.cmd run build
```

실제 GMS·데모 PDF 통합 확인(저장소 루트, 실제 호출 발생):

```powershell
.venv/Scripts/python scripts/smoke_day1.py --pdf D:/SSAFY/demo_pdfs/AI_지식_정리_노트_워드_임베딩.pdf --real --trace
```

`--real`을 빼면 목 모드, `--trace`를 빼면 관측을 끈다. 별도 `backend/data/smoke-real/` 또는 `smoke-mock/`에 검증 데이터를 저장한다. 스크립트는 워크스페이스와 자료를 추가하므로 재실행마다 검증 데이터가 늘어난다.

## 문서

- [1일차 PRD](docs/studylink-day1-prd.md)
- [구현기획서 v1.1](docs/studylink-implementation-plan-v1.1.md)
- [아키텍처](docs/studylink-architecture.md)
- [통합 결과와 후속 작업](docs/day1-integration.md)
- [용어집](CONTEXT.md)

노트 연결·노트 검색·재검색·퀴즈·오답노트는 후속 일차 범위다. 현재 1일차 구현을 전체 시제품 완료로 간주하지 않는다.
