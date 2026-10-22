# 연결형 학습 노트 서비스 구현기획서 v1.1

작성일: 2026-10-21 (Asia/Seoul)  
상태: 3일·3명 시제품 실행 계획. 1일차 핵심 흐름을 구현·통합 확인했으며 전체 시제품은 진행 중이다.  
구현 진행: [1일차 구현·통합 검증 결과](day1-integration.md). 아래 표는 원래 계획이며 현재 확인 결과는 통합 기록을 따른다.  
이전 버전: [studylink-implementation-plan.md](studylink-implementation-plan.md) (v1.0, 장기 설계 참고용으로 보존)  
아키텍처: [studylink-architecture.md](studylink-architecture.md)  
문서 점검: [2026-10-21 점검 결과·후속 작업](studylink-design-review-2026-10-21.md) — 항목별 반영 상태는 보고서 상단을 따른다.  
원본: 노션 위키에 있던 같은 제목 페이지에서 옮겼다(노션 페이지는 삭제함). 이후 변경은 이 파일에 반영한다.

## 0. 기본 전제 (2026-10-21 확정)

- **처음부터 새로 만든다.** 빈 저장소·새 가상환경에서 시작한다. streamlit_lab 폴더의 실습 파일(`step0_llm.py`~`step8_wiki_api.py`), README, requirements, venv는 참고하지도 복사하지도 않는다. 이 문서의 어떤 결정도 그 코드를 근거로 삼지 않는다.
- **에이전트는 LangGraph로 구성한다. LangChain은 쓰지 않는다.** `StateGraph`의 상태·노드·조건부 엣지·`Send`로 검색, 생성, 검증, 재시도, 종료를 표현한다.
  - 쓰는 것: `langgraph`의 `StateGraph`, `START`/`END`, `add_conditional_edges`, `Send`, `compile()`/`invoke()`
  - 쓰지 않는 것: LangChain 체인·LCEL·`AgentExecutor`, `ChatOpenAI` 등 `langchain_*` 모델·임베딩 래퍼, 프롬프트 템플릿, LangChain 콜백 기반 Langfuse 연동, LangChain 채팅 모델을 전제로 하는 `langgraph.prebuilt`(`create_react_agent`, `ToolNode`)
  - `langgraph`가 내부 의존성으로 `langchain-core`를 함께 설치하더라도 애플리케이션 코드에서 `langchain*`를 직접 import하지 않는다.
- **모델·임베딩 호출은 직접 만든 GMS HTTP 어댑터(httpx)로 한다.** 그래프 노드는 이 어댑터 함수를 호출하는 일반 Python 함수다. GMS의 실제 엔드포인트·모델·구조화 출력 지원은 첫날 새 환경에서 검증한다.
- 노트 초안은 LLM으로 답변을 요약해 만들고 Langfuse trace(`note_draft`)를 남긴다. 이를 위해 `POST /api/answers/{id}/note-draft`를 둔다(3절 C04, 6절).

## 1. v1.0 대비 변경 요약

| 항목 | v1.0 | v1.1 |
| --- | --- | --- |
| 기간 | 6~8주 MVP + 3일 시제품 | 3일 시제품 하나에 집중 |
| 팀 | 3명 가정 | 3명 이상 확정 |
| 프런트 | Streamlit → React/TS | React + Vite + JavaScript |
| 백엔드 | FastAPI 후보 | FastAPI 확정 |
| LLM 관측 | 미정 | Langfuse |
| P0 | 14개 기능 | 하나의 수직 흐름(아래 3절) |
| 제외 | — | 로그인, Notion·삼성노트 연동, OCR, 비용 한도, 운영 설계 |

v1.0의 권한·버전·삭제·운영 설계는 폐기가 아니라 시제품 이후 단계로 미룬다.

## 2. 만들려는 것과 차별점

PDF 기반 질의응답과 퀴즈는 NotebookLM 등에 이미 있다. 이 시제품이 보여줄 차별점은 두 가지다.

1. **과목을 넘나드는 노트 연결**: 자연어처리 기초 공간에서 쓴 노트를 LLM 공간에 연결하면, 새 노트를 쓸 때 그 노트가 근거로 검색된다.
2. **오답에서 원문으로 복귀**: 틀린 문제에서 바로 근거 PDF 페이지와 관련 노트를 연다.

데모는 이 두 장면이 확실히 동작하는 것을 최우선으로 한다. 나머지 기능은 이 두 장면을 받치는 범위에서만 만든다.

## 3. 범위

2026-10-21 사용자 보완: 하나의 워크스페이스에 여러 채팅을 만든다. PDF·연결 노트는 워크스페이스의 공통 자원이며 모든 채팅에서 열람·검색한다. 각 채팅의 질문·답변 기록과 후속 질문 문맥은 서로 격리한다. [ADR 0002](adr/0002-workspace-chats-shared-resources.md), [2일차 PRD](studylink-day2-prd.md)를 따른다.

### 핵심 흐름 (필수)

PDF 업로드 → 근거 답변(페이지 인용) → 답변을 노트로 저장 → 노트를 다른 워크스페이스에 연결 → 이전 노트 검색 → 객관식 퀴즈 → 오답에서 원문·노트로 이동

| ID | 기능 | 완료 기준 |
| --- | --- | --- |
| C01 | 워크스페이스 생성·목록 | 제목·목표 저장, 재시작 후 유지 |
| C02 | PDF 업로드·텍스트 추출 | 텍스트 PDF, 처리 상태(processing/ready/failed) 표시 |
| C03 | 근거 질의응답 | 답변 문장별 인용 번호, 클릭 시 해당 PDF 페이지 열림. 근거 없으면 "자료에서 확인하지 못함" |
| C04 | 노트 작성·저장 | 제목·본문(Markdown)·인용 저장. 서식 도구·작성/미리보기 전환·크게 쓰기(작성과 미리보기 나란히), 저장된 노트는 Markdown으로 렌더링하고 [cN]은 원본을 여는 칩으로 표시(2026-10-22). 답변에서 LLM 요약 노트 초안 만들기(인용은 원 답변 범위로 제한, LLM 실패 시 답변을 옮긴 초안) |
| C05 | 노트 저장소 | 전체 노트 목록·제목 검색 |
| C06 | 워크스페이스 간 노트 연결 | 노트 원본 하나를 여러 공간에 연결·해제 |
| C07 | 이전 노트 검색 | 질의응답 검색 범위에 연결 노트 포함, 답변에 노트 출처 별도 표시 |
| C08 | 관련 노트 제안 | 노트 편집 중 버튼으로 관련 노트 상위 3개 |
| C09 | 객관식 퀴즈 | 5문항 4지선다, 문항별 근거 페이지, 제출 전 정답 미노출 |
| C10 | 오답노트 | 오답 목록, 내 답·정답·해설, 근거 페이지·관련 노트 열기, 틀린 이유 메모 |
| C11 | Langfuse 추적 | 질의응답·노트 초안·퀴즈 생성 호출이 trace로 남음 |

### 여유 시 (스트레치)

- 오답 재풀이 버튼
- 키워드 검색 결합(BM25)으로 검색 보강
- ~~PDF 뷰어에서 인용 문장 하이라이트~~ → 2026-10-22 구현(4절 PDF 보기, 7절)

### 제외

로그인·다중 사용자, Notion 연동, 삼성노트·필기 OCR, 스캔 PDF, 사용자 간 공유, 자동 관련 노트 갱신, 비용 한도, 배포. 로컬 단일 사용자 데모로 한정하고 공개 배포하지 않는다.

## 4. 기술 구성

| 계층 | 선택 | 이유 |
| --- | --- | --- |
| 프런트 | React 18 + Vite + JavaScript, react-router | 설정이 적고 빠름. API는 FastAPI가 전담 |
| PDF 보기 | pdf.js(`pdfjs-dist`)로 한 쪽을 그리고 인용문 위치에 하이라이트 상자를 겹침 | 인용문을 원문에서 바로 찾게 함. 위치는 서버 PyMuPDF `search_for`로 계산(2026-10-22, 이전: iframe `#page=N`) |
| 백엔드 | FastAPI + Pydantic | HTTP 계약과 입력·출력 검증을 새로 구현 |
| DB | SQLite (SQLAlchemy 또는 sqlite3) | 설치 없음, 파일 하나 |
| 벡터 검색 | 임베딩을 SQLite에 저장, numpy 코사인 전수 검색 | 수천 청크 규모면 충분하고 워크스페이스 필터가 쉬움 |
| PDF 추출 | PyMuPDF | 페이지별 텍스트 추출이 빠르고 단순 |
| 에이전트 구성 | LangGraph `StateGraph` | 상태·도구 실행·조건 분기·제한된 재시도를 명시적으로 구성 |
| LLM | GMS HTTP 어댑터(httpx), `CHAT_MODEL`=gpt-4.1-mini | JSON schema(strict) 구조화 출력 + Pydantic 검증. 긴 근거(약 7,200자)에서 생성 1회 약 1.4초(2026-10-21 실측). HTTP 타임아웃 20초, 요청 한도 질의응답 30초·초안 20초·퀴즈 45초 |
| 임베딩 | GMS HTTP 어댑터, text-embedding-3-small | 1536차원, 배치 호출 동작(2026-10-21 확인) |
| 관측 배치 | Langfuse 클라우드 | 설치 없이 바로 사용 |
| 관측 | Langfuse Python SDK 직접 계측 | 그래프 실행·노드·모델 호출별 프롬프트·응답·토큰·지연 기록 |

개발 서버: Vite(5173)에서 `/api`를 FastAPI(8000)로 프록시해 CORS 설정을 피한다.

엔드포인트는 모두 동기 `def`로 작성하고 퀴즈 문항만 LangGraph `Send`로 병렬 생성한다. `MOCK_LLM=1`이면 GMS 어댑터가 고정 응답을 돌려줘 1일차부터 GMS 없이 프런트·백엔드를 함께 개발한다. 서버 시작 시 processing으로 남은 문서는 failed("서버 재시작으로 중단")로 바꾸고 retry API로 다시 수집한다.

Langfuse 키와 GMS 키는 `.env`에만 두고 `.env.example`에는 이름만 적는다. Langfuse는 클라우드를 쓴다. 프롬프트에 들어간 PDF 발췌가 Langfuse에 저장된다. 데모 자료는 팀원이 정리한 노트 PDF 2개이며, 사용자가 이 발췌가 Langfuse 클라우드(JP 리전)에 저장되는 것을 허용했다(2026-10-21). 다른 개인 자료를 추가할 때는 다시 확인한다. 자체 호스팅은 Docker Compose로 PostgreSQL·ClickHouse·Redis·S3 호환 저장소까지 띄워야 해서 3일 일정에서는 쓰지 않는다. 실제 개인 자료를 다루는 단계에서 다시 검토한다.

### 임베딩 모델 선택

우선 후보는 text-embedding-3-small이다. 기존 문서의 GMS 모델 제공·크레딧 수치는 새 프로젝트의 검증 결과가 아니므로 확정 근거에서 제외한다. 지원 모델과 과금 단위는 첫날 GMS 제공 정보와 실제 호출로 확인한다.

- **3-small**을 먼저 연결하고 데모 자료와 평가 질문으로 품질을 확인한다.
- 한국어 검색이 기준에 못 미치면 GMS 지원과 비용을 확인한 뒤 **3-large**로 전체 재임베딩해 비교한다.
- 다른 임베딩 모델 검토는 시제품 핵심 흐름이 완성된 뒤로 미룬다.
- 모델 이름은 설정값(`EMBEDDING_MODEL`)으로 두고 chunks에 embedding_model을 함께 저장한다. 모델을 바꾸면 전체를 다시 임베딩하고, 서로 다른 모델의 벡터는 섞어 비교하지 않는다(차원도 1536과 3072로 다르다).

### 저장소 구조

별도 `studylink/` 저장소와 Python 가상환경·프런트 패키지 환경을 처음부터 만든다(0절). 백엔드 직접 의존성은 fastapi, uvicorn, pydantic, langgraph, httpx, pymupdf, numpy, langfuse, python-dotenv 수준으로 시작하고 `langchain*` 패키지는 직접 추가하지 않는다. 첫날 검증한 버전을 고정한다.

```text
studylink/
  frontend/        # Vite + React
    src/pages/     # Home, Workspace, Notes, NoteEdit, Quiz, Review
    src/api.js     # fetch 래퍼, API 계약 한 곳에
  backend/
    app/main.py    # FastAPI 라우터 등록
    app/routers/   # workspaces, documents, ask, notes, quizzes, reviews
    app/services/  # ingest, indexing, retrieval, CRUD, 채점, 그래프 호출
    app/agents/    # states, nodes, answer_graph, note_draft_graph, quiz_graph
    app/adapters/  # gms.py: HTTP 호출, telemetry.py: Langfuse 직접 계측
    app/schemas/   # HTTP 응답·모델 출력 검증 스키마
    app/db.py      # SQLite 스키마·세션
    eval/          # questions.yaml(평가 질문·기대 결과), run_eval.py(결과 CSV)
    data/          # uploads/, app.db (git 제외)
  .env.example
  README.md        # 실행 방법
```

### LangGraph 에이전트 설계

질의응답·노트 초안·퀴즈 생성에 각각 그래프를 둔다. HTTP 엔드포인트가 작업 종류를 결정하고 그래프를 실행한다. 검색·검증·분기·재시도는 그래프에, DB 저장과 채점은 서비스에 둔다.

| 그래프 | 상태·노드 흐름 | 종료 조건 |
| --- | --- | --- |
| 답변 | 질문·범위 → 검색 도구 → 근거 확인 → (근거가 약하면 질의 재작성 → 재검색) → 생성 → 인용 검증 → 필요 시 재생성 | 유효 답변 또는 근거 부족 보류. 재검색 최대 1회, 재생성 최대 1회 |
| 노트 초안 | 저장된 답변 조회 → 요약 → 원 답변 인용 범위 검증 | 정상 초안 또는 결정적 fallback. 재생성 최대 1회 |
| 퀴즈 | 근거 선택 → 문항별 생성·검증 서브그래프 → 결과 취합 | 유효 문항 반환. 문항별 재생성 최대 1회, 0개면 오류 |

세 그래프 모두 고정 흐름이며 분기는 코드 검증 결과로 정한다. LLM이 도구나 경로를 고르는 루프는 두지 않는다. 답변 그래프는 같은 채팅의 후속 질문을 독립 검색 질의로 해석하고, 근거가 약하면 최대 1회 질의를 재작성해 재검색한다. 노드는 일반 Python 함수로 구현하고 모델 호출은 GMS 어댑터를 사용한다. 요청별 상태는 분리하며 그래프 결과를 서비스에서 저장한다. 시제품은 완료된 데이터의 SQLite 영속화와 채팅별 최근 대화 문맥을 제공한다. 실행 중 그래프 체크포인트 복구와 장기 문맥 요약은 이후 단계다. 구체적인 상태 필드와 오류 분기는 아키텍처 3.1절을 따른다.

## 5. 데이터 모델 (SQLite)

| 테이블 | 필드 |
| --- | --- |
| workspaces | id, title, goal, created_at |
| documents | id, workspace_id, filename, path, page_count, status, error |
| chunks | id, source_type(doc/note), source_id, page(doc만), text, embedding(blob), embedding_model, embedding_dim |
| notes | id, title, body, index_status(ok/failed), created_at, updated_at |
| workspace_notes | workspace_id, note_id (unique 쌍) |
| note_citations | note_id, citation_id(노트 안 고유, c1…), source_type(doc/note), document_id·page·quote(doc), cited_note_id(note) |
| chats | id, workspace_id, title, created_at, updated_at |
| answers | id, workspace_id, chat_id, question, body_json, created_at |
| quizzes | id, workspace_id, requested_count, actual_count, created_at, submitted_at |
| questions | id, quiz_id, stem, options_json, answer_option_id, explanation, document_id, page |
| attempts | id, question_id, selected_option_id, correct, submitted_at |
| reviews | id, question_id(UNIQUE), status(open/reviewed), learner_reason |

- 노트는 원본 하나이고, 연결은 workspace_notes로만 한다. 연결 해제와 삭제는 다른 동작이다.
- 노트 저장 시 해당 노트의 청크를 지우고 다시 만든다(revision 관리는 이후 단계). 임베딩이 실패해도 노트는 저장하되 예전 청크는 지워 검색에서 빼고 `notes.index_status=failed`로 둔다. 노트 저장·조회 응답에 index_status를 넣어 화면이 재저장을 안내한다.
- 조회용 인덱스: `chunks(source_type, source_id)`, `documents(workspace_id)`, `workspace_notes(workspace_id)`.
- 노트 초안은 테이블에 저장하지 않는다. 사용자가 저장한 노트만 영속화한다.
- 노트 인용은 본문의 `[cN]` 표시와 note_citations의 citation_id로 짝짓는다. 저장(POST·PUT) 때 서버는 본문에 남은 `[cN]`의 인용만 보관하고, 본문에 있지만 citations에 없는 표시는 422로 거절한다. 인용된 노트가 삭제되면 인용 행은 남기고 화면에 "삭제된 노트"로 표시한다.
- 사용자 테이블은 두지 않는다. 다중 사용자로 갈 때 owner_id를 추가한다.

## 6. API 계약

1일차 첫 2시간 안에 이 계약을 고정하고, 프런트는 목 데이터로 먼저 개발한다.

| 메서드·경로 | 요청 → 응답 |
| --- | --- |
| GET /api/workspaces | → 목록 |
| POST /api/workspaces | title, goal → workspace |
| GET /api/workspaces/{id} | → 상세 + 문서·연결 노트 목록 |
| POST /api/workspaces/{id}/documents | multipart PDF → document(status=processing) |
| GET /api/documents/{id} | → status, page_count, error |
| POST /api/documents/{id}/retry | failed 문서 재수집 → document(status=processing) |
| POST /api/documents/{id}/highlight | page, quote → width, height, rects([x0,y0,x1,y1], PDF 포인트·왼쪽 위 기준). 찾지 못하면 rects=[] |
| GET /api/documents/{id}/file | → PDF 파일 |
| GET/POST /api/workspaces/{id}/chats | → 채팅 목록 / title → 새 채팅 |
| GET /api/chats/{id} | → 채팅 상세(workspace_id 포함) |
| GET /api/chats/{id}/messages | → 해당 채팅의 완료 질문·답변 쌍, 시간순 |
| POST /api/chats/{id}/ask | question, include_notes → answer + chat_id. 같은 채팅의 최근 문맥 사용 |
| POST /api/workspaces/{id}/ask | 호환용: 가장 최근에 사용한 채팅(없으면 새로 생성)에서 question, include_notes → answer |
| GET /api/workspaces/{id}/answers | → 최근 답변 20개(answer_id, question, status, created_at) |
| GET /api/answers/{id} | → 답변 한 건(ask 응답과 같은 형식) |
| POST /api/answers/{id}/note-draft | → title, body(Markdown), citations, fallback (저장하지 않음) |
| GET /api/notes | q, workspace_id → 노트 목록 |
| POST /api/notes | title, body, workspace_ids, citations → note (본문에 쓰인 `[cN]`의 인용만 저장) |
| GET·PUT /api/notes/{id} | 노트 조회·수정 |
| POST /api/workspaces/{id}/notes/{note_id} | 노트 연결 |
| DELETE /api/workspaces/{id}/notes/{note_id} | 연결 해제(노트는 유지) |
| POST /api/notes/related | title, body, exclude_note_id(선택) → 서로 다른 노트 최대 3개(note_id, title, snippet. 점수 미노출). 범위는 전체 노트, 저장 전 내용도 검색 |
| POST /api/workspaces/{id}/quizzes | count=5 → quiz(requested_count, actual_count, 문항. 정답·해설 제외) |
| GET /api/workspaces/{id}/quizzes | → 최근 퀴즈 20개(requested_count, actual_count, created_at, submitted_at, score) |
| GET /api/quizzes/{id} | → 제출 전: 문항(정답·해설 제외), 제출 후: 채점 결과·해설·근거 |
| POST /api/quizzes/{id}/submit | {question_id: option_id} → 채점·해설·근거. 첫 제출로 확정, 재요청은 저장된 결과 반환 |
| GET /api/reviews | workspace_id, status → 오답 목록(관련 노트 제외) |
| GET /api/reviews/{id} | → 오답 단건 + 관련 노트 최대 3개(조회 시 계산) |
| PATCH /api/reviews/{id} | learner_reason, status |

질의응답 응답 형식:

```json
{
  "answer_id": "...",
  "status": "grounded | insufficient_evidence",
  "segments": [
    {"text": "설명 문장", "citation_ids": ["e1"]}
  ],
  "citations": [
    {"id": "e1", "source_type": "doc", "document_id": "...", "page": 3, "quote": "..."},
    {"id": "e2", "source_type": "note", "note_id": "...", "title": "..."}
  ]
}
```

노트 초안 응답 형식:

```json
{
  "title": "기울기 소실 정리",
  "body": "## 기울기 소실\n... [c1]\n... [c2]",
  "citations": [
    {"citation_id": "c1", "source_type": "doc", "document_id": "...", "page": 3, "quote": "..."},
    {"citation_id": "c2", "source_type": "note", "cited_note_id": "...", "title": "..."}
  ],
  "fallback": false
}
```

서버는 원 답변의 `[eN]`을 노트 인용 번호 `[cN]`으로 바꿔 매긴다. 같은 형식의 citations를 `POST /api/notes`·`PUT /api/notes/{id}` 요청과 노트 조회 응답에 그대로 쓴다. title은 조회 시 현재 노트 제목으로 채운다.

insufficient_evidence 답변으로 초안을 요청하면 422를 돌려준다.

페이지는 1부터 시작하는 값으로 통일한다. 오류는 400/404/413/422/500/503과 `{"detail": "..."}` 형식을 쓴다.

채팅 추가 계약: 같은 채팅의 답변 생성 중 중복 질문은 409로 안내한다. 최근 대화 최대 6쌍·12,000자만 모델 문맥으로 사용하며 다른 채팅의 기록은 포함하지 않는다. 과거 답변은 사실 근거로 재사용하지 않고 현재 자원을 다시 검색한다. 기존 답변은 워크스페이스별 이전 대화로 손실 없이 이관하며, 이관은 재실행해도 중복되지 않는다.

## 7. RAG 규칙

- 청크: PDF는 페이지 단위로 자르고, 긴 페이지는 약 800자 단위로 나눈다. 노트는 제목 + 본문 문단 단위.
- 인용문(quote)은 청크 전체가 아니라 청크에서 연속한 1~3줄, 최대 160자다. 서버가 그 인용을 쓴 답변 문장(퀴즈는 문제·정답·해설)과 글자 2-gram이 가장 많이 겹치는 줄을 고른다. 모델 호출은 없고 모델은 계속 근거 ID만 출력한다(P2 유지). PDF 줄을 그대로 쓰므로 하이라이트 위치를 다시 찾을 수 있다(2026-10-22). 이전에 저장된 노트·문항의 긴 인용문은 그대로 남는다.
- 검색 범위: 현재 워크스페이스의 ready 문서 + (include_notes면) 연결된 노트. 범위 밖 청크는 검색 전에 제외한다. 범위 안 후보 청크가 하나라도 있으면 질문을 받는다(노트만 있는 공간 포함). 후보가 없으면 400이며, 처리 중 문서가 있으면 "자료를 처리하는 중입니다", 없으면 "검색할 자료나 노트가 없습니다"로 안내한다(2026-10-21 결정).
- 근거는 개수를 고정하지 않고 관련성 기준으로 고른다: 최소 점수 이상 → 1등 점수 대비 상대 기준 이내 → 최대 12개 또는 약 8,000자에서 멈춤. 최소 점수를 넘은 노트가 있으면 최고 노트 1개는 반드시 넣는다. 기준값은 2일차에 데모 질문으로 정한다(2026-10-21 결정, 아키텍처 4.2절).
- 고른 근거를 `[e1] (문서명 p.3)` 형식으로 프롬프트에 넣고, 모델은 이 ID만 인용하는 JSON을 출력한다.
- 서버가 인용 ID가 실제 제공한 근거인지 확인하고, 없는 ID는 제거한다. 그 뒤 유효 인용이 없는 segment는 응답에서 뺀다. segment의 절반 넘게 빠지면 1회 재생성하고, 남은 segment가 없으면 insufficient_evidence로 돌린다(문장 단위 검증, 2026-10-21 결정).
- 문서와 노트를 구분해 전달하고, 화면에서도 "자료"와 "내 노트" 출처를 다른 표시로 보여준다.
- 노트 초안은 저장된 답변을 LLM으로 요약한 Markdown이다. 원 답변에 없는 사실을 더하지 않고, 인용은 원 답변의 ID만 쓴다. 원 답변에 없는 ID는 서버가 제거한다. LLM이 실패하면 segments를 문단으로 이은 초안을 `fallback: true`로 돌려준다. 사용자가 저장하기 전에는 검색 대상이 아니다.

## 8. 퀴즈 규칙

- 출제 범위: 현재 워크스페이스의 문서 청크에서 무작위로 고른 5개 근거.
- 생성: 근거마다 문제·선택지 4개·정답 option_id·해설을 JSON으로 생성.
- 검증(서버 코드): JSON 스키마, 선택지 4개, 중복 없음, 정답 ID 유효, 근거 페이지 존재. 실패 문항은 한 번 재생성하고 그래도 실패하면 제외한다. 근거 없는 문제로 개수를 채우지 않는다. 1~4문항이면 그대로 내고 requested_count·actual_count로 화면에 안내한다. 0문항이면 422.
- 문제 조회 응답에는 정답·해설을 넣지 않고, 제출 후 채점 응답에서만 보낸다.
- 제출은 퀴즈당 한 번이다. 모든 문항에 답해야 하고, 문항·선택지는 해당 퀴즈의 것이어야 한다. 어긋나면 422로 거절하고 아무것도 저장하지 않는다. 이미 제출한 퀴즈를 다시 제출하면 채점하지 않고 저장된 결과를 200으로 돌려준다. attempts·reviews·quizzes.submitted_at은 한 트랜잭션으로 기록한다(2026-10-21 결정). 오답 재풀이(스트레치)는 같은 퀴즈 재제출이 아니라 새 퀴즈 생성으로 만든다.
- 오답은 reviews에 open으로 쌓고, 근거 페이지와 관련 노트 링크를 함께 보여준다.

## 9. 역할 분담 (3명 기준)

| 역할 | 담당 |
| --- | --- |
| A 프런트 | Vite 셋업, 라우팅, 워크스페이스·학습·노트·퀴즈·오답 화면, 목 데이터 |
| B 백엔드 | FastAPI 골격, SQLite 스키마, 업로드·PDF 추출, CRUD API, 노트 연결 |
| C LangGraph·에이전트 | LangGraph 상태·노드·분기, GMS 어댑터, 검색·생성·검증 그래프, Langfuse 직접 계측, 평가 스크립트 |

4명 이상이면 D가 평가 질문셋·데모 시나리오·통합 테스트를 맡고 A의 화면 일부를 나눈다.

## 10. 3일 일정

3일차 요구사항·인수 기준: [3일차 PRD](studylink-day3-prd.md). 2일차 미완료(노트 초안·관련 노트·평가)를 이월하고, 퀴즈·오답은 워크스페이스 단위(채팅 무관)로 둔다.

2일차 요구사항·인수 기준: [2일차 PRD](studylink-day2-prd.md). 사용자 결정(2026-10-21)으로 퀴즈 생성 준비·그래프 구현을 3일차로 옮긴다. 2일차는 노트 저장·연결·검색과 초안·검색 품질 보정에 집중한다. 1일차에 완료한 출력 재생성은 유지하고 실제 질의 재작성·재검색을 추가한다.

1일차 요구사항·인수 기준: [1일차 PRD](studylink-day1-prd.md). 기존 일정의 구체화이며 모듈·자동 테스트 범위는 사용자 확인 전 제안이다.

| 시점 | A 프런트 | B 백엔드 | C LangGraph·에이전트 |
| --- | --- | --- | --- |
| 1일 오전 | 저장소·Vite 셋업, API 계약 확정(공동) | FastAPI·DB 스키마, API 계약 확정(공동) | 새 Python 환경, GMS 어댑터 호출 검증, LangGraph 상태·함수 계약 확정(공동) |
| 1일 오후 | 홈·워크스페이스·최소 질문/인용 화면(목 데이터) | 업로드·PyMuPDF 추출·문서 상태 API | 청킹·검색 도구, 답변 그래프(생성·인용 검증·보류), Langfuse 연결 |
| 1일 끝 통합 | PDF 업로드 → ready → 질문 → 페이지 인용 답변 | ← | ← |
| 2일 오전 | 여러 채팅 생성·전환·기록, 공통 자원·PDF 페이지 열기 | 채팅·이력·기존 답변 이관, 노트 CRUD·연결·색인 | 채팅 문맥 해석·재검색, 노트 검색·근거 선택 보정 |
| 2일 오후 | 노트 편집·저장소·연결 화면 | 관련 노트 API, note-draft 엔드포인트 | 초안 그래프, 관련 노트 검색, 평가 도구·검색 기준값 보정 |
| 2일 끝 통합 | 노트 저장 → 다른 공간 연결 → 그 공간 질문에 노트 인용 | ← | ← |
| 3일 오전 | 퀴즈·오답노트 화면 | 퀴즈 저장·조회·제출·채점·reviews API | 퀴즈 생성 준비·그래프 생성·검증·실패 분기 |
| 3일 오후 | 화면 다듬기, 빈 상태·오류 표시 | 버그 수정, README 실행 방법 | 평가 질문셋 최종 판정·프롬프트 조정, Langfuse trace 정리·데모 자료 검증 |
| 3일 끝 | 데모 리허설 2회 (공동) | ← | ← |

매일 끝 통합 시점에 동작하지 않으면 다음 날 오전 첫 작업은 새 기능이 아니라 그 흐름을 고치는 것이다.

## 11. 데모 시나리오와 완료 기준

1. "자연어처리 기초" 워크스페이스에 워드 임베딩 PDF 업로드 → "Vanishing gradient가 뭐야?" 질문 → p.3 인용 클릭 시 해당 페이지 열림.
2. 답변에서 "노트로 만들기" → LLM 요약 초안 확인·편집 → "기울기 소실 정리" 노트 저장.
3. "LLM" 워크스페이스 생성, Transformer PDF 업로드, "기울기 소실 정리" 노트 연결.
4. "Transformer는 RNN의 어떤 문제를 해결했어?" 질문 → 답변에 Transformer p.2 근거와 함께 "내 노트: 기울기 소실 정리"가 인용됨. **(차별점 1)** (2026-10-22 변경: 이전 질문 "Residual connection은 왜 쓰는 거야?"는 p.3과 노트를 잇는 문장이 근거 텍스트에 없어 노트가 인용되지 않았다. [3일차 평가](day3-eval.md))
5. 퀴즈 5문항 풀기 → 오답 선택 → 오답노트에서 근거 페이지와 관련 노트 열기. **(차별점 2)**
6. Langfuse에서 해당 질문의 trace(검색 근거·프롬프트·토큰)와 노트 초안 trace 보여주기.

완료 기준:

- 위 1~6이 앱 재시작 후에도 끊김 없이 동작한다.
- 평가 질문 15개(답 있음 10, 답 없음 5)에서 답 있음은 올바른 페이지 인용 8개 이상, 답 없음은 보류 4개 이상. 사람이 직접 판정한다. 판정은 평가 스크립트(`backend/eval/run_eval.py`)가 만든 CSV로 한다. 스크립트는 `answer_question`을 직접 호출하고 질문별로 근거 수·점수·노트 보장·재검색 여부, 답변 상태, 인용 페이지, Langfuse trace ID를 기록한다. 정답 페이지 일치와 답 없음 보류는 자동 표시하고, 근거가 주장을 뒷받침하는지는 사람이 판정 칸에 적는다. 2일차 근거 선택 기준값 보정에도 같은 스크립트를 쓴다(2026-10-21 결정).
- 퀴즈 10문항을 사람이 검토해 정답·해설이 틀린 문항이 1개 이하.

데모 PDF는 `D:\SSAFY\demo_pdfs`의 2개로 고정한다(2026-10-21 결정): "AI 지식 정리 노트: 워드 임베딩"(5쪽), "AI 지식 정리 노트 - Transformer & LLM 파운데이션 모델"(11쪽). 추출 결과는 아키텍처 12절. 평가 질문 15개도 이 두 자료에서 만든다. 답 없음 질문은 그림에만 있는 내용이나 자료에 없는 주제로 고른다. 4단계의 노트 인용은 근거 선택 기준값을 보정할 때 가장 먼저 확인한다.

## 12. 위험과 축소안

| 위험 | 대응 |
| --- | --- |
| 한국어 검색 품질 부족 | text-embedding-3-large로 교체 후 재임베딩, 필요하면 키워드 검색 결합 |
| 모델이 JSON 형식을 자주 깨뜨림 | GMS 구조화 출력 지원 확인 + Pydantic 검증, 그래프에서 재생성 1회. 최종 실패 시 답변 보류·초안 fallback·퀴즈 문항 제외 |
| 인용 페이지가 자주 틀림 | 청크를 페이지 단위로만 유지, 상위 근거 수 축소 |
| 노트 초안 요약이 근거를 왜곡 | 인용 ID 제한, 사용자가 편집 후 저장, 필요하면 답변 옮기기(fallback)로 고정 |
| 퀴즈 품질 낮음 | 문항 수를 3개로 줄이고 검증 강화 |
| 2일차 통합 지연 | 관련 노트 제안(C08) 제외, 노트 검색은 질의응답 범위 포함만 유지 |
| 3일차 시간 부족 | 오답노트는 목록·근거 이동만, 틀린 이유 메모 제외 |

줄이지 않는 것: 페이지 인용, 노트 연결 후 검색, 오답에서 원문 이동. 이 세 가지가 데모의 핵심이다.

## 13. 1일차 시작 전 체크리스트

- [ ] 새 Git 저장소 생성, frontend/backend 폴더와 .env.example
- [x] GMS 채팅·임베딩 호출과 JSON schema 구조화 출력 지원 확인(2026-10-21, 아키텍처 12절). 새 저장소 어댑터에서 Pydantic 검증 연결은 1일차
- [ ] LangGraph 최소 그래프 실행 및 정상·검증 실패·재시도 소진 분기 확인
- [ ] 빈 환경에서 Python·Node 패키지 설치·실행 확인 후 버전 고정, 코드에 `langchain*` 직접 import 없음 확인
- [x] Langfuse 클라우드 프로젝트 생성(2026-10-21), 키 공유는 .env로만(`LANGFUSE_PUBLIC_KEY`·`LANGFUSE_SECRET_KEY`·`LANGFUSE_BASE_URL`). 병렬 분기 trace 묶임 확인(아키텍처 12절)
- [x] 데모 PDF 2개 PyMuPDF 추출 확인(2026-10-21, 아키텍처 12절). 데모 시나리오를 이 자료 기준으로 다시 씀(11절)
- [ ] 6절 API 계약을 팀원 모두 확인하고 고정

## 14. 이후 단계로 미룬 것

v1.0에서 다음 항목은 시제품 이후에 다시 검토한다: 로그인·사용자 격리(F01), 노트 revision과 버전 고정 인용, 삭제·보관 정책, Notion 연동(F15·F16), 삼성노트·OCR(F13), 비용 한도(F14), 작업 큐, PostgreSQL/pgvector 이전, 정식 평가셋과 출시 기준. 각 항목의 설계 근거는 v1.0 문서를 참고한다.
