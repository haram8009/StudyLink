# StudyLink 시제품 시스템 아키텍처 v1

작성일: 2026-10-21 (Asia/Seoul)  
상태: 시제품 설계. 1일차 범위의 구현·통합 확인을 마쳤으며 후속 범위는 설계로 남아 있다.  
구현 진행: [1일차 구현·통합 검증 결과](day1-integration.md). 아래 설계 전체가 구현됐다는 의미는 아니다.  
기준 문서: [studylink-implementation-plan-v1.1.md](studylink-implementation-plan-v1.1.md) (구현기획서 v1.1)
문서 점검: [2026-10-21 점검 결과·후속 작업](studylink-design-review-2026-10-21.md) — 항목별 반영 상태는 보고서 상단을 따른다.

이 문서는 v1.1의 기술 선택, 데이터 모델, API 계약을 그대로 전제로 한다. v1.1에 없는 내용을 다룬다. 컴포넌트 경계, 요청 흐름, 팀원 간 내부 인터페이스, 오류 처리, 규모 추정, 트레이드오프다. v1.1을 바꾸자는 항목은 **[변경 제안]**으로 표시했다.

전제(기획서 v1.1 0절): 빈 저장소에서 처음부터 만들며 streamlit_lab 실습 코드는 참고하지 않는다. 에이전트는 LangGraph `StateGraph`로 구성하고 LangChain(체인·모델 래퍼·콜백·prebuilt 에이전트)은 쓰지 않는다. GMS HTTP 어댑터와 Langfuse 직접 계측을 새로 구현한다. 아래 세부 그래프 구성은 이 결정을 구체화한 구현 설계안이다.

## 0. v1.1 변경 제안 요약

| # | 제안 | 이유 |
| --- | --- | --- |
| P1 | 근거를 고정 개수 대신 관련성 기준으로 뽑는다: 최소 점수 → 1등 대비 상대 기준 → 상한(12개 또는 약 8,000자) → 최소 점수를 넘은 노트가 있으면 최고 노트 1개 보장 | 관련 자료 양에 맞춰 근거 수가 달라지고, 짧은 노트가 PDF 청크에 밀려 데모 4단계(노트 인용)가 실패하는 것을 막는다. 처음 안(문서4+노트2 고정 할당)을 대체. **결정됨(2026-10-21)** |
| P2 | 인용의 page·quote·document_id는 서버가 청크에서 채운다. 모델은 근거 ID만 출력한다 | 모델이 페이지 번호를 지어내는 오류를 원천 차단 **결정됨(2026-10-21)** |
| P3 | 서버 시작 시 processing 문서를 failed("서버 재시작으로 중단")로 바꾸고 `POST /api/documents/{id}/retry`를 추가 | 인프로세스 백그라운드 작업은 재시작 시 사라진다 **결정됨(2026-10-21)** |
| P4 | 환경변수 `MOCK_LLM=1`이면 LLM·임베딩이 고정 응답을 반환 | GMS 없이 프런트·백엔드가 1일차부터 병렬 개발·통합 **결정됨(2026-10-21)** |
| P5 | `reviews.question_id` UNIQUE, 조회용 인덱스 3개 추가(5절) | 재제출 시 중복 오답 방지, 범위 조인 성능 **결정됨(2026-10-21)** |
| P6 | 답변 → 노트 초안을 LLM으로 요약하는 전용 API `POST /api/answers/{id}/note-draft`를 추가하고 trace(`note_draft`)를 남긴다. 요약문의 인용은 원 답변의 인용 ID로만 제한한다 | v1.1 C04·C11 그대로. 기획서 v1.1 md 6절에 반영함. **결정됨(2026-10-21)** |
| P7 | 모든 엔드포인트를 동기 `def`로 작성하고, 퀴즈 문항 생성은 LangGraph Send 분기로 병렬화 | async SQLite·async LLM 혼용으로 인한 디버깅 부담 제거 **결정됨(2026-10-21)** |

## 1. 요구사항 정리

**기능**: v1.1 C01~C11. 데모 6단계 흐름이 끊김 없이 동작해야 한다.

**비기능 (가정 포함)**

| 항목 | 목표 | 근거 |
| --- | --- | --- |
| 사용자 | 로컬 단일 사용자, 동시 요청 1~2개 | v1.1 범위 |
| 데이터 규모 | PDF 2~3개(각 ~60쪽), 노트 ~20개, 청크 ~500개 | v1.1 데모 자료 가정 |
| 질의응답 지연 | 10초 이내 (가정) | 데모 체감 기준. 대부분 LLM 응답 시간 |
| 노트 초안 지연 | 10초 이내 (가정) | LLM 호출 1회 |
| 퀴즈 생성 지연 | 30초 이내 (가정) | 5문항 병렬 생성 시 |
| 지속성 | 재시작 후 모든 데이터 유지 | v1.1 완료 기준 |
| 배포 | 없음. 로컬 실행 | v1.1 제외 범위 |

**제약**: 3일, 3명 이상, React+Vite+JS / FastAPI / SQLite / LangGraph / GMS HTTP 어댑터 / Langfuse 클라우드.

## 2. 전체 구성도

```text
┌─────────────── Browser (React + Vite, :5173) ───────────────┐
│  pages/  Home · Workspace · Notes · NoteEdit · Quiz · Review │
│  api.js  (VITE_USE_MOCK=1 이면 목 응답)                        │
│  PDF 패널: <iframe src="/api/documents/{id}/file#page=N">    │
└───────────────────────────┬─────────────────────────────────┘
                            │ /api/* (Vite dev proxy)
┌───────────────────────────▼─────────────────────────────────┐
│ FastAPI (uvicorn, worker 1, :8000)                           │
│  routers/   HTTP ↔ Pydantic 변환, 상태 코드만 담당              │
│     │                                                        │
│  services/                                                   │
│     ingest      PDF 추출·청킹·임베딩 (BackgroundTasks)         │
│     indexing    노트 청크 재생성                               │
│     retrieval   범위 필터 → numpy 코사인 → 관련성 기준 선택     │
│     answer      답변 그래프 호출·결과 저장                    │
│     note_draft  원 답변 로드·초안 그래프 호출                  │
│     quiz        퀴즈 그래프 호출·저장·채점                     │
│  agents/       LangGraph 상태·노드·조건부 엣지                │
│  adapters/     GMS HTTP 호출 · Langfuse 직접 계측             │
│     prompts     프롬프트 상수                                  │
│  db.py      SQLite (WAL, foreign_keys=ON)                    │
└──────┬──────────────────────┬──────────────────┬────────────┘
       │                      │                  │
  data/app.db          data/uploads/        ┌────┴─────┐
                       {doc_id}.pdf         │ GMS      │  Langfuse Cloud
                                            │ chat/emb │  (trace)
                                            └──────────┘
```

**계층 규칙**

- routers → services → agents(그래프) → 검색 도구·adapters 순서로 호출한다. DB 저장·채점은 services가 담당하고, 노드는 services의 오케스트레이션 함수를 역호출하지 않는다. router에서 SQL이나 모델을 직접 부르지 않는다.
- GMS 통신은 `adapters/gms.py`, 관측은 `adapters/telemetry.py`에 둔다. 그래프가 업무 재시도와 종료를 결정하며 어댑터는 HTTP 타임아웃과 일시적 통신 오류 재시도만 담당한다.
- 프런트의 서버 호출은 `src/api.js`에서만 한다. 전역 상태 라이브러리는 쓰지 않고 페이지 단위로 fetch한다.

## 3. 팀 간 내부 인터페이스

### 채팅과 공통 자원 보완 (2026-10-21)

[ADR 0002](adr/0002-workspace-chats-shared-resources.md)에 따라 workspace → chats → answers 관계를 추가한다. PDF와 연결 노트의 소유·검색 범위는 workspace에 유지한다. 채팅 서비스는 목록·생성·조회·시간순 완료 대화·기존 답변 이관을 책임진다. 답변 서비스의 내부 계약은 `answer_question(workspace_id, question, include_notes=True, *, chat_id=None, history=())`로 확장한다. 기존 평가 호출은 문맥 없는 호출로 호환한다. 구현(2026-10-21): 답변 그래프는 interpret → retrieve → (근거가 약하면 research 1회) → generate → validate 순서이며, 프롬프트 버전은 answer-v2·query-followup-v1·query-research-v1이다. 답변 생성에는 최근 3쌍·답변당 600자만 넣고 과거 인용 표시는 지운다. 노트 저장 후 색인은 `services/note_index.index_note(note_id)`가 맡고 예외를 밖으로 던지지 않는다. 결과는 [2일차 통합 기록](day2-integration.md)을 따른다.

채팅 HTTP 요청은 서버에서 chat의 workspace를 확인하고, 동일 chat의 생성 요청을 잠가 중복 요청에 409를 반환한다. 최근 완료 대화 최대 6쌍을 읽어 최대 12,000자로 제한한 문맥을 전달한다. 후속 질문 해석 → workspace 자료·연결 노트 검색 → 생성·검증 → chat에 결과 저장 순서다. 과거 답변은 질문 해석을 돕지만 이번 답변의 인용 근거가 아니다. 새 검색에서 선택한 근거 ID만 허용한다. 전체 요청의 30초 예산을 공유한다.

기존 answers에 chat_id를 추가하고 기존 기록은 workspace별 이전 대화로 이관한다. 이관은 멱등이며 원래 답변 ID·본문·인용을 보존한다. 채팅 간 문맥·대화 기록은 섞지 않으며, 답변을 노트로 저장하고 workspace에 연결한 경우에만 다른 채팅의 검색 근거로 재사용된다. 공통 자원 패널은 답변 인용 없이도 PDF·노트를 열 수 있어야 한다.

v1.1의 HTTP 계약(A↔B)에 더해, B(백엔드)와 C(LangGraph·에이전트)가 1일차 오전에 고정할 Python 함수 계약이다. B는 이 시그니처를 목 구현으로 먼저 호출하고, C가 실제 구현을 채운다.

```python
@dataclass
class Evidence:
    chunk_id: str
    source_type: Literal["doc", "note"]
    source_id: str          # document_id 또는 note_id
    page: int | None        # 문서만, 1부터
    title: str              # 파일명 또는 노트 제목
    text: str
    score: float

# services/ingest.py
def ingest_document(document_id: str) -> None        # 상태 갱신까지 책임
# services/indexing.py
def index_note(note_id: str) -> None                 # 기존 청크 삭제 후 재생성
# services/retrieval.py
def retrieve(workspace_id: str, query: str, *,
             include_notes=True) -> list[Evidence]  # 점수순, 4.2절 선택 규칙 적용
def related_notes(text: str, *, exclude_note_id: str | None = None,
                  k=3) -> list[Evidence]           # 전체 노트, note_id당 1개
# services/answer.py
def answer_question(workspace_id: str, question: str,
                    include_notes: bool) -> AnswerOut   # v1.1 6절 응답 형식
# services/note_draft.py
def draft_note(answer_id: str) -> NoteDraftOut         # title, body(Markdown), citations, fallback
# services/quiz.py
def generate_quiz(workspace_id: str, count=5) -> str   # quiz_id
def grade(quiz_id: str, picks: dict[str, str]) -> GradeOut
# adapters/gms.py
def embed(texts: list[str]) -> np.ndarray              # (n, dim) float32
def generate_json(prompt: str, schema: type[BaseModel]) -> BaseModel
# 실패 시 ModelOutputError 또는 ProviderUnavailable로 구분해 그래프에 전달
```

### 3.1 LangGraph 상태·노드 계약

에이전트 실행은 `agents/`의 `StateGraph`로 구현한다. FastAPI 서비스가 컴파일된 그래프의 `invoke`를 호출한다. 컴파일된 그래프는 앱 시작 시 한 번 만들어 공유하고 상태는 요청마다 새로 만든다. 노드는 상태를 받아 갱신할 필드만 dict로 반환하는 일반 함수이며 LangChain 메시지·도구 객체를 쓰지 않는다.

| 상태 | 필드 | 책임 |
| --- | --- | --- |
| 공통 실행 상태 | request_id, workspace_id(해당 시), retry_count, validation_errors, status | 요청 구분·검증 결과·종료 분기. 키·DB 연결·HTTP 클라이언트는 상태에 넣지 않는다 |
| AnswerState | question, include_notes, evidences, draft, result | 허용된 범위의 근거와 답변 초안·최종 결과 |
| NoteDraftState | answer_id, source_answer, draft, result, fallback | 원 답변 인용 범위와 초안 검증 |
| QuizState | count, evidences, question_results | 문항 분배와 결과 취합 |
| QuestionState | question_key, evidence, draft, retry_count, validation_errors, result | 각 병렬 문항의 독립 생성·검증·재시도 |

상태는 TypedDict로 명시하고 외부 입력·모델 출력은 Pydantic으로 검증한다. 각 노드는 상태 변경분만 반환한다. 퀴즈 병렬 결과는 question_key별 맵을 병합하는 reducer로 취합하고, 같은 키의 중복 기록을 검출한다. 분기 내부의 retry_count를 부모 그래프에서 공유하지 않는다.

| 그래프 | 노드·조건부 엣지 |
| --- | --- |
| 답변 | START → retrieve → check_evidence. 근거가 충분하면 generate, 약하고 재검색 0회면 rewrite_query → retrieve(1회), 재검색 후에도 약하면 abstain → END. generate → validate. 성공하면 finalize → END, 출력 오류이고 재시도 0회면 retry_count를 증가시켜 generate, 소진하면 abstain → END |
| 초안 | START → check_source → summarize → validate. 원 답변 근거 부족은 422로 종료. 성공하면 finalize → END, 출력 오류는 1회 재생성 후 fallback → END. 공급자 장애는 바로 fallback |
| 퀴즈 | START → select_evidence → Send로 question 서브그래프 실행 → collect → END. 각 서브그래프는 generate → validate → 성공 종료 또는 1회 재생성 후 제외. 취합 후 유효 문항 0개는 422, 공급자 전체 장애는 503 |

- 세 그래프는 고정 흐름이다. 다음 노드는 코드의 검증 결과로만 정하며 LLM이 도구나 경로를 고르지 않는다(2026-10-21 결정). 유일한 예외적 판단 지점은 답변 그래프의 재검색이다.
- 재검색(rewrite_query): 근거가 약하면(후보 0개 또는 최고 점수가 기준 미만) LLM이 질문을 검색용 질의 하나로 다시 쓰고 1회 더 검색한다. 모델은 질의 문자열만 출력하며 검색 범위는 바꾸지 못한다. 두 검색 결과는 chunk_id로 합쳐(같은 청크는 높은 점수) 4.2절 선택 규칙을 다시 적용한다. 생성 프롬프트에는 원 질문을 쓴다. "근거가 약함"은 최소 점수를 넘는 후보가 0개인 경우다. AnswerState에 rewritten_query·research_count를 두고 trace에 재검색 여부를 기록한다.
- 답변 validate(문장 단위, 2026-10-21 결정): 제공하지 않은 인용 ID를 지우고, 유효 인용이 없는 segment를 뺀다. 출력 스키마 오류이거나 segment의 절반 넘게 빠지면 검증 실패로 보고 1회 재생성한다. 재생성 후에는 남은 segment로 확정하고, 0개면 abstain한다. 제거한 segment 수는 trace에 기록하고 3일차 평가 질문으로 절반 기준을 재점검한다. 이 검증은 유효 ID 여부만 보며 근거가 주장을 뒷받침하는지는 사람 평가로 판정한다.
- 검색·근거 확인·인용 검증은 코드 노드이고 생성·요약·질의 재작성은 모델 호출 노드다. 검색 범위는 서버에서 고정하며 모델이 workspace_id나 include_notes를 바꾸지 못한다.
- 그래프의 업무 재시도는 최대 1회다. 그래프 실행에는 별도의 recursion_limit을 지정해 잘못 연결된 순환도 유한하게 끝낸다. GraphRecursionError는 내부 실행 오류로 처리하며 근거 부족으로 위장하지 않는다.
- 성공한 답변·퀴즈는 그래프가 끝난 뒤 서비스에서 한 번 저장한다. 재시도 노드 안에서 DB 쓰기를 하지 않는다. 노트 초안은 반환만 한다. 채점은 모델 호출 없는 서비스 함수다.
- 시제품에서는 실행 중 상태를 메모리에 두고 완료 데이터만 SQLite에 저장한다. 서버 종료 시 실행 중 그래프를 이어서 재개하는 checkpointer는 도입하지 않는다. 중단된 요청은 재요청한다. 완료 데이터는 `GET /api/workspaces/{id}/answers`, `GET /api/answers/{id}`, `GET /api/quizzes/{id}`로 다시 불러온다(점검 R3, 2026-10-21 결정).
- 수집·관련 노트 검색은 일반 서비스로 유지한다. 그래프 내부 검색 노드도 같은 검색 도구를 사용한다.

## 4. 핵심 요청 흐름

### 4.1 PDF 업로드·수집 (C02)

1. `POST /api/workspaces/{id}/documents`: 확장자·MIME 확인(422), 크기 제한 예: 30MB(413).
2. 파일을 `data/uploads/{document_id}.pdf`로 저장하고 documents에 status=processing으로 기록한 뒤 즉시 응답한다.
3. FastAPI BackgroundTasks에서 `ingest_document`를 실행한다.
   1. PyMuPDF로 페이지별 텍스트를 추출한다. 텍스트가 거의 없는 페이지 비율이 높으면 failed("스캔 PDF는 지원하지 않음"). 여러 쪽에서 반복되는 첫·끝 줄(문서 제목·쪽 번호 꼬리말)은 지운다(데모 PDF 확인 결과, 12절).
   2. 페이지 단위로 청크를 만들고, 긴 페이지는 약 800자로 나눈다(v1.1 7절).
   3. 임베딩을 배치(예: 64개)로 호출한다.
   4. chunks insert와 status=ready를 **한 트랜잭션**으로 기록한다. 예외 시 failed + error 메시지.
4. 프런트는 processing인 문서만 2초 간격으로 `GET /api/documents/{id}`를 폴링한다.
5. **[P3 결정]** 서버 시작 시 남은 processing을 failed로 바꾸고 retry API로 다시 수집한다.

### 4.2 근거 질의응답 (C03, C07)

서비스가 answer_graph를 실행한다. 아래는 정상 경로이며 재생성·보류·오류 분기는 3.1절을 따른다.

```text
질문 ─► embed(question)
      ─► 범위 SQL로 후보 청크 로드 (현재 공간 ready 문서 + 연결 노트)
      ─► numpy 코사인 ─► 관련성 기준 선택(아래 규칙) ─► [e1]~[eN]
      ─► generate_json(답변 스키마: segments[text, citation_ids])
      ─► 서버 검증: 제공하지 않은 ID 제거 → 유효 인용 없는 segment 제거
         → 절반 넘게 제거되면 1회 재생성 → 남은 segment 0개면 insufficient_evidence
      ─► 인용 메타(page, quote, document_id/note_id, title)는 서버가 Evidence에서 채움
      ─► answers 저장(body_json + 검색된 chunk_id·점수) ─► 응답
```

범위 필터는 검색 전에 SQL에서 적용한다. 노트는 여러 공간에 연결되므로 chunks에 workspace_id를 두지 않고 조인으로 판정한다.

```sql
SELECT c.* FROM chunks c
  JOIN documents d ON c.source_type = 'doc' AND c.source_id = d.id
 WHERE d.workspace_id = :ws AND d.status = 'ready' AND c.embedding_model = :model
UNION ALL
SELECT c.* FROM chunks c
  JOIN workspace_notes wn ON c.source_type = 'note' AND c.source_id = wn.note_id
 WHERE wn.workspace_id = :ws AND :include_notes = 1 AND c.embedding_model = :model;
```

**근거 선택 규칙(P1, 2026-10-21 결정)**

1. 최소 점수(`MIN_SCORE`) 이상인 후보만 남긴다. 0개면 근거가 약한 것으로 보고 재검색 또는 보류로 간다(3.1절).
2. 1등 점수와의 차이가 `RELATIVE_MARGIN`(초기값 예: 0.1) 이내인 후보만 남긴다.
3. 점수순으로 담다가 `MAX_EVIDENCE`(12개) 또는 근거 텍스트 합 `MAX_EVIDENCE_CHARS`(약 8,000자)에 먼저 닿으면 멈춘다.
4. 1단계를 통과한 노트가 있는데 결과에 노트가 없으면, 최고 점수 노트 1개를 넣는다. 상한을 넘으면 마지막 문서 근거를 빼고 넣는다.

네 값은 설정으로 두고 2일차에 데모 질문으로 정한다. 선택 개수·점수·노트 보장 발동 여부는 trace에 기록해 3일차 평가에서 다시 본다.

### 4.3 노트 초안·저장·연결 (C04~C06, C08)

**[P6] 답변 → 노트 초안 (LLM 요약)**

서비스가 원 답변을 로드해 note_draft_graph를 실행한다. 정상 경로는 아래와 같고 실패 분기는 3.1절을 따른다.

```text
"노트로 만들기" ─► POST /api/answers/{id}/note-draft
   ─► answers.body_json(질문, segments, citations) 로드
   ─► generate_json(초안 스키마: title, body_markdown)   ← Langfuse trace "note_draft"
   ─► 서버 검증: 본문의 [eN] 중 원 답변에 없는 ID 제거
   ─► [eN] → [cN] 번호 변환, 인용 후보 생성(서버가 채움)
      문서 인용: citation_id·source_type=doc·document_id·page·quote
      노트 인용: citation_id·source_type=note·cited_note_id
   ─► 초안 반환(DB 저장 안 함) ─► 사용자가 편집 후 POST /api/notes
```

- 원 답변은 서버가 answers에서 읽는다. 프런트가 답변 내용을 다시 보내지 않으므로 근거가 바뀌어 들어올 여지가 없다.
- 프롬프트는 "답변에 있는 내용만 정리하고 새 사실을 더하지 말 것, 인용은 주어진 [eN]만 쓸 것"으로 제한한다.
- 초안은 저장 전까지 검색 대상이 아니다(v1.1 7절).
- LLM 실패나 출력 파싱 실패가 나면 segments를 문단으로 잇는 결정적 초안을 반환하고 `fallback: true`를 표시한다. GMS 장애로 데모 2단계가 막히지 않게 하기 위해서다.
- insufficient_evidence 답변은 초안 버튼을 비활성화한다(서버는 422).
- trace metadata에 `answer_id`를 넣어 원 `ask` trace와 이어 보고, fallback 여부도 기록한다.

**저장·연결·관련 노트**

- 저장(`POST/PUT /api/notes`): notes 갱신 → `index_note` 동기 실행. 노트는 짧아서 임베딩 1회 호출로 끝난다. 임베딩이 실패해도 노트는 저장하고(노트 내용을 잃지 않는 쪽을 택함) 그 노트의 예전 청크는 지워 검색에서 뺀다. 본문과 어긋난 청크가 검색되지 않게 하기 위해서다. `notes.index_status=failed`를 저장하고 저장·조회 응답에 넣어 화면이 재저장을 안내한다. 다음 저장에서 임베딩이 성공하면 ok로 돌린다(점검 R7, 2026-10-21 결정).
- 연결·해제: workspace_notes 행만 추가·삭제한다. 검색 시점에 조인하므로 **재임베딩이 필요 없다**. "원본 하나, 연결은 관계로" 설계의 핵심 이점이다.
- 관련 노트(C08, 2026-10-21 결정, 점검 R4): 편집 화면이 저장 전 title·body와 선택적 exclude_note_id를 `POST /api/notes/related`로 보낸다. 서비스가 그 텍스트를 1회 임베딩해 전체 노트 청크와 비교하고, note_id별 최고 점수 청크만 남겨 서로 다른 노트 최대 3개를 돌려준다(note_id, title, snippet). `retrieve`와 분리된 `related_notes` 함수로 구현한다. 저장하지 않으므로 검색 대상은 바뀌지 않는다. C08을 실제로 구현할지는 1일차 오전 계약 확정 때 정한다.

### 4.4 퀴즈 생성·채점 (C09, C10)

1. 근거 샘플링: 현재 공간 문서 청크 중 200자 이상인 것을, 가능하면 서로 다른 페이지에서 5개 고른다.
2. 문항 생성: LangGraph `Send`로 근거별 문항 서브그래프에 분기한다(동시 실행 최대 5). 각 분기는 독립 상태로 생성·검증·재시도하며 같은 요청 trace 아래 기록한다. 결과는 question_key 기준으로 취합한다.
3. 검증(코드): 스키마, 선택지 4개·중복 없음, 정답 ID 유효. 실패하면 1회 재생성하고, 그래도 실패하면 제외한다. document_id·page는 모델 출력이 아니라 근거 청크에서 채운다.
4. 응답 분리: Pydantic 응답 모델을 `QuestionPublic`(정답·해설 없음)과 `QuestionGraded`로 나눈다. 정답 누출을 필드 누락 실수가 아니라 타입으로 막는다.
5. 제출(2026-10-21 결정, 점검 R6): 퀴즈당 1회로 확정한다. 입력 검증(전 문항 응답, 해당 퀴즈의 question_id·option_id) 실패는 422이며 아무것도 쓰지 않는다. `quizzes.submitted_at`이 이미 있으면 채점하지 않고 저장된 attempts로 결과를 다시 만들어 200으로 돌려준다. 아니면 한 트랜잭션에서 submitted_at이 NULL인 경우에만 갱신(`UPDATE ... WHERE submitted_at IS NULL`)하고, attempts insert와 오답 reviews insert(question_id UNIQUE, status=open)를 함께 커밋한다. 갱신 행이 0이면 동시 제출로 보고 저장된 결과를 반환한다.
5-1. 부분 생성: 유효 문항이 1~4개면 그대로 저장하고 requested_count·actual_count를 응답에 넣는다. 화면은 "N문항만 만들었습니다"를 표시한다.
6. 오답노트의 관련 노트는 저장하지 않는다. 조회할 때 "문제 + 정답 텍스트"로 노트를 검색해 즉석 계산한다.

## 5. 데이터 모델 보완

v1.1 5절 테이블을 그대로 쓰고 다음만 더한다.

- **[P5 결정]** 인덱스: `chunks(source_type, source_id)`, `documents(workspace_id)`, `workspace_notes(workspace_id)`. `reviews.question_id` UNIQUE.
- 임베딩 저장: `np.float32` 배열을 `tobytes()`로 BLOB에 저장하고 `embedding_dim` 컬럼을 함께 둔다(3-small 1536, 3-large 3072).
- answers.body_json에 검색된 chunk_id와 점수를 함께 저장한다. 3일차 평가 질문 판정, 디버깅, 노트 초안 생성에 쓴다.
- 노트 초안은 테이블을 두지 않는다. 저장된 노트만 영속화한다.
- note_citations(2026-10-21 결정, 점검 R1): `UNIQUE(note_id, citation_id)`. source_type=doc이면 document_id·page·quote, note면 cited_note_id를 채운다. 저장 시 서비스가 본문의 `[cN]`을 파싱해 쓰인 인용만 보관하고, 본문에 있지만 citations에 없는 표시는 422로 거절한다. cited_note_id는 FK를 걸지 않고, 인용된 노트가 없으면 조회 응답에 `missing: true`를 넣어 "삭제된 노트"로 표시한다. 노트 간 인용 관계는 이후 노트 연결 시각화의 근거 데이터로 쓸 수 있다.
- 삭제 cascade: 문서를 지우면 해당 chunks를, 노트를 지우면 그 노트의 chunks·workspace_notes·note_citations를 지운다. chunks는 다형 참조라 FK cascade가 걸리지 않으므로 서비스 코드에서 지운다.
- 연결 설정: `PRAGMA journal_mode=WAL`, `foreign_keys=ON`. 요청과 백그라운드 작업마다 커넥션을 따로 쓴다. 쓰기 트랜잭션은 짧게 유지한다(임베딩 호출은 트랜잭션 밖에서).
- ID는 uuid4 문자열.

## 6. GMS 어댑터와 Langfuse

HTTP 어댑터는 새로 작성한다. GMS의 채팅·임베딩 경로, 인증 헤더, 요청·응답 형식은 첫날 제공 문서와 실제 호출로 확인한다. JSON schema 지정이 지원되면 사용하고, 지원되지 않으면 JSON 출력 지시와 Pydantic 검증을 사용한다. 모델이 반환한 문서 ID·페이지 번호는 신뢰하지 않고 검색 근거에서 채운다.

| 항목 | 설계 |
| --- | --- |
| 설정값 | `GMS_KEY`, `GMS_BASE_URL`, `CHAT_MODEL`(기본 gpt-4.1-mini), `EMBEDDING_MODEL`(기본 text-embedding-3-small), `LANGFUSE_PUBLIC_KEY`·`LANGFUSE_SECRET_KEY`·`LANGFUSE_BASE_URL`(SDK에서 `LANGFUSE_HOST`는 폐기 예정), `MOCK_LLM`. 어댑터가 설정을 읽으며 비밀 값은 .env에만 둔다 |
| 모델 호출 | httpx 기반 GMS 어댑터. `generate_json(prompt, schema)`와 `embed(texts)`로 제공. LangChain 모델 래퍼를 사용하지 않는다 |
| 출력 검증 | Pydantic 파싱 오류는 ModelOutputError. 그래프가 검증 오류를 상태에 넣고 1회 재생성한 뒤 답변 보류·초안 fallback·문항 제외로 종료 |
| 통신 오류 | HTTP 호출 타임아웃 20초(실측 생성 1회 약 2초 기준, 2026-10-21 결정). 일시적 오류에만 1회 재시도. 인증·잘못된 요청은 즉시 실패. 최종 ProviderUnavailable은 답변 503, 초안 fallback, 퀴즈 전체 공급자 장애 503 |
| 재시도 예산 | 통신 재시도는 어댑터, 출력 재생성·재검색은 그래프 한 곳에서만 수행한다. 출력 생성 2회 × 통신 최대 2회로 생성 호출은 작업당 최대 4회. 답변 그래프는 재검색 1회(질의 재작성 호출 1회 + 임베딩 1회)가 더해질 수 있다. 요청 전체 deadline(2026-10-21 결정): 질의응답 30초 초과 시 503, 노트 초안 20초 초과 시 결정적 fallback, 퀴즈 45초 초과 시 끝나지 않은 문항은 제외하고 부분 생성 규칙 적용. 각 노드는 모델 호출 전에 남은 시간을 확인하고, 남은 시간이 HTTP 타임아웃보다 짧으면 그 시간을 타임아웃으로 쓴다. 목표 지연(질의응답·초안 10초, 퀴즈 30초)은 그대로 둔다 |
| trace 단위 | 그래프 요청 1개 = root trace 1개. `ask`, `note_draft`, `quiz_generate`. 수집·관련 노트 검색도 별도 trace |
| trace 내용 | 그래프 노드는 span, 모델 호출은 generation으로 직접 계측. request_id, workspace_id, 선택 chunk_id·점수, 모델·프롬프트 버전, 재시도·fallback 여부 기록. 토큰 사용량은 공급자가 반환할 때만 기록 |
| 병렬 실행 | 루트 관측(`start_as_current_observation`)을 연 상태에서 `graph.invoke`를 호출하면 `Send` 분기 스레드로 컨텍스트가 전파돼 한 trace로 묶인다(2026-10-21 확인, 12절). 그래프 실행을 루트 관측 밖에서 시작하지 않는다 |
| 목 모드 | 그래프 구조를 유지하고 어댑터만 고정 응답으로 교체한다. 정상·파싱 실패·통신 실패 시나리오를 선택 가능하게 한다. 목 데이터 DB는 실제 임베딩 DB와 분리한다 |
| 관측 장애 | telemetry 어댑터가 no-op으로 전환한다. 계측 실패와 업무 예외를 분리해 업무 오류가 삼켜지지 않게 한다 |

새 환경에서 검증한 LangGraph·httpx·Pydantic·Langfuse 버전을 고정한다. 공식 근거: [LangGraph 개요](https://docs.langchain.com/oss/python/langgraph/overview), [Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api), [Langfuse 직접 계측](https://langfuse.com/docs/observability/sdk/instrumentation). 이 문서는 연동 성공을 보고하는 문서가 아니다.

## 7. 프런트 구조

| 경로 | 화면 | 주요 API |
| --- | --- | --- |
| `/` | 워크스페이스 목록·생성 | GET·POST workspaces |
| `/w/:id` | 공통 자료·연결 노트, 채팅 목록·새 채팅 | documents, notes, chats |
| `/w/:id/chats/:chatId` | 선택 채팅의 질문·답변 기록, 공통 PDF·노트 패널, 답변별 "노트로 만들기" | chat 조회·messages·ask, documents, notes, note-draft |
| `/notes` | 노트 저장소, 제목 검색 | GET notes |
| `/notes/new`, `/notes/:id` | 노트 편집(초안 불러오기), 공간 연결, 관련 노트 | notes, related, 연결 API |
| `/w/:id/quiz/:quizId` | 퀴즈 풀이·채점 결과. 새로고침 시 GET quizzes/{id}로 복구 | quizzes, submit |
| `/w/:id/reviews` | 오답노트 | reviews |

- "노트로 만들기"를 누르면 note-draft 응답을 편집 화면 초기값으로 넘긴다(router state). `fallback: true`면 "요약 없이 답변을 옮겨 담음"을 표시한다.
- 인용 클릭: 문서 인용이면 PDF 패널 iframe을 `/api/documents/{id}/file#page=N`으로 바꾼다. 같은 파일에서 hash만 바뀌면 브라우저가 페이지를 옮기지 않을 수 있으므로 `key={docId + page}`로 iframe을 다시 마운트한다. 노트 인용이면 노트 미리보기 패널을 연다.
- 파일 응답은 `Content-Disposition: inline`, `application/pdf`로 보내야 iframe에서 열린다.
- 출처 표시: "자료"와 "내 노트" 인용 배지를 색으로 구분한다(v1.1 7절).
- 오래 걸리는 요청(퀴즈 생성, 노트 초안)은 버튼을 비활성화하고 진행 상태를 표시한다. 중복 클릭으로 두 번 생성되지 않게 한다.

## 8. 오류 처리

| 상황 | 서버 | 화면 |
| --- | --- | --- |
| PDF 아님·손상 | 422 | 업로드 영역에 메시지 |
| 파일 과대 | 413 | 제한 크기 안내 |
| 스캔 PDF·추출 실패 | 문서 failed + error | 문서 행에 사유, 재시도 버튼 |
| 검색 가능 근거 없음 | ready 문서만 검색. 범위 SQL 후보 청크(ready 문서 + include_notes면 연결 노트)가 0개면 400. detail로 처리 중 문서 유무를 구분 | "자료를 처리하는 중입니다" 또는 "검색할 자료나 노트가 없습니다". 노트만 있어도 질문 가능 |
| GMS 실패·타임아웃 | 6절 통신 재시도 정책 후 503(노트 초안은 fallback) | 다시 시도 버튼, 입력 내용 유지 |
| 근거 부족 | 200 + insufficient_evidence | "자료에서 확인하지 못함" |
| 근거 부족 답변으로 초안 요청 | 422 | 버튼 비활성화 |
| 노트 초안 LLM 실패 | 200 + 결정적 초안, `fallback: true` | "요약 없이 답변을 옮겨 담음" 안내 |
| 그래프 실행 한도 초과·내부 실행 오류 | 500 + 일반 오류 메시지, 상세는 서버 로그 | 다시 시도 안내 |
| 퀴즈 유효 문항 0개 | 422(전체 공급자 장애는 503) | 범위·자료 확인 안내 |
| Langfuse 실패 | 무시하고 진행(로그만) | 영향 없음 |

관측 도구 장애가 사용자 기능을 막지 않도록 Langfuse 호출 실패는 항상 삼킨다.

## 9. 규모 추정

- 청크 ~500개 × 1536차원 × 4바이트 ≈ 3MB. 질문마다 범위 청크를 읽어 numpy로 전수 계산해도 수십 ms 수준(추정)이다.
- 지연의 대부분은 LLM 응답이다. 따라서 이 범위에서는 캐시·작업 큐·벡터 DB가 이득이 없다.
- 임베딩 비용: 3-small 기준으로 데모 전체를 다시 임베딩해도 미미하다. 3-large로 바꿔도 재임베딩 부담이 작다.
- 노트 초안은 버튼을 누를 때만 LLM을 1회 호출하므로 비용 영향이 작다.
- 전수 검색의 한계는 청크 수만 개 규모부터 체감될 것으로 본다(추정). 그때 메모리 행렬 캐시 → pgvector 순으로 옮긴다.

## 10. 트레이드오프

| 결정 | 택한 것 | 대안 | 택한 이유 | 잃는 것 |
| --- | --- | --- | --- | --- |
| 비동기 수집 | FastAPI BackgroundTasks | Celery·RQ·arq 큐 | 설치·운영 없음 | 재시작 시 작업 유실(P3로 보완), 동시 처리 제어 없음 |
| 벡터 검색 | SQLite BLOB + numpy 전수 | Chroma, pgvector | 범위 필터를 SQL 조인으로 정확히 표현, 의존성 없음 | 대규모 확장성 |
| 노트 공유 | 원본 1개 + 연결 테이블 | 공간별 복제 | 연결·해제 시 재임베딩 없음, 수정 즉시 반영 | 공간별로 다른 노트 버전 불가 |
| 근거 구성 | 관련성 기준 선택(최소 점수·상대 기준·상한) + 노트 1개 보장 | 단일 top-6, 문서4+노트2 고정 할당 | 질문마다 관련 자료 양에 맞춰 근거 수가 달라지고 노트 인용(차별점 1)이 유지됨 | 기준값 세 개를 데모 질문으로 맞춰야 하며, 값에 따라 근거 수가 질문마다 달라 프롬프트 길이·지연이 일정하지 않음(상한으로 완화) |
| 인용 메타 | 서버가 청크에서 채움 | 모델 출력 사용 | 페이지 오류 방지 | 모델이 청크 일부를 정확히 지목할 수 없음(인용은 청크 단위) |
| 노트 초안 | LLM 요약 + 인용 ID 제한 + 결정적 fallback | LLM 없이 답변 옮기기 | 읽기 좋은 노트, trace로 품질 확인 가능(결정됨) | LLM 호출 1회 비용·지연, 요약 중 근거 왜곡 가능성(사람이 편집 후 저장해 완화) |
| 에이전트 구성 | LangGraph StateGraph + GMS HTTP 어댑터 | 프레임워크 없는 함수 조합 | 사용자 지정 기술이며 분기·상태·재시도를 그래프로 표현 | 상태와 노드 계약을 직접 설계해야 함 |
| 퀴즈 생성 | 요청 안에서 병렬 동기 생성 | 비동기 job + 폴링 | API·화면 단순 | 요청이 수십 초 걸릴 수 있음 |
| PDF 보기 | 브라우저 내장 뷰어 iframe | pdf.js | 코드 거의 없음 | 하이라이트 불가, 브라우저마다 동작 차이 |
| 동시성 모델 | 동기 def | async | SQLite·HTTP 어댑터·graph.invoke 호출을 단순하게 연결 | 높은 동시성 처리량 |

## 11. 성장 시 재검토할 것

- 로그인·사용자 격리: 모든 상위 테이블에 owner_id, 검색 범위 SQL에 owner 조건 추가.
- 저장소: SQLite → PostgreSQL + pgvector. 범위 조인 SQL은 거의 그대로 옮겨진다.
- 수집: BackgroundTasks → 작업 큐(재시도·진행률·동시 처리 제한). Notion·OCR 연동이 들어오면 필수.
- 노트 revision과 버전 고정 인용, 퀴즈 근거의 버전 보존(v1.0 설계).
- 검색 품질: 키워드 검색 결합(BM25), 재순위화. 평가셋으로 효과를 측정한 뒤 도입.
- 관측: 실제 개인 자료를 다루면 Langfuse 자체 호스팅 또는 발췌 마스킹.

### 평가 스크립트 (2026-10-21 결정)

- `backend/eval/questions.yaml`: 질문, 답 있음/없음, 기대 document·page 또는 note_id.
- `backend/eval/run_eval.py`: services의 `answer_question`을 HTTP 없이 호출하고 결과를 CSV로 저장한다. 열: 질문, 선택 근거 수·점수, 노트 보장·재검색 발동, status, 인용 페이지·노트, 기대값 일치(자동), 보류 일치(자동), trace_id, 사람 판정.
- 쓰임: 2일차 `MIN_SCORE`·`RELATIVE_MARGIN`·상한 보정, 3일차 완료 판정. `MOCK_LLM=1`로 돌리면 GMS 비용 없이 재검색·보류·재생성 분기를 확인한다.
- 평가 실행도 Langfuse trace에 `eval` 태그로 남겨 데모 trace와 구분한다.

## 12. 1일차 오전에 확인할 것

1일차 구현 범위와 인수 기준은 [1일차 PRD](studylink-day1-prd.md)에 정리했다. [1일차 통합 기록](day1-integration.md)에서 출력 재생성 최대 1회는 완료했고, 실제 질의 재작성·재검색은 2일차에 추가한다. 사전 최소 그래프의 분기 검증과 제품 구현을 구분한다.

2일차 구현 범위·모듈·인수 기준은 [2일차 PRD](studylink-day2-prd.md)를 따른다. 노트 저장·인용·색인, 연결 검색·노트 보장, 초안, 관련 노트, PDF 페이지 이동·답변 복구와 평가 도구를 통합한다. 사용자 결정(2026-10-21)으로 퀴즈 생성 준비·그래프 구현은 3일차로 이동했으며 기획서 10절도 같은 일정으로 조정했다. 퀴즈의 기존 기술 계약은 유지한다.

**로컬 사전 검증 결과(2026-10-21, 임시 가상환경, langgraph 1.2.16 · langchain-core 1.6.12 · pydantic 2.14.1)**: 실제 프로젝트 코드·GMS·Langfuse 없이 LangGraph 동작만 장난감 그래프로 확인했다.

- 동기 `invoke`에서 `Send`로 나눈 5개 분기(각 1초 대기)가 약 1.0초에 끝났다. 분기는 서로 다른 스레드에서 동시에 실행된다. P7(동기 def + Send 병렬) 전제가 성립한다. 동시 실행 수는 config의 `max_concurrency`로 제한한다.
- `invoke` 전에 설정한 `contextvars` 값이 모든 분기 스레드에서 그대로 읽혔다. Langfuse SDK가 contextvars 기반 컨텍스트를 쓴다면 병렬 분기도 같은 trace로 이어질 가능성이 높다. 실제 Langfuse 연결은 아직 확인하지 않았다.
- 분기 안의 재생성(서브그래프), 질문 키별 dict reducer 병합이 동작했다.
- 답변 그래프의 네 경로가 의도대로 갈라졌다: 재검색 후 정상, 재검색 후 재생성 성공, 재생성 소진 후 보류, 재검색 후에도 근거 없음 보류.
- 잘못 연결된 순환은 `recursion_limit`에서 `GraphRecursionError`로 끝났다.
**GMS 호출 확인 결과(2026-10-21, 임시 스크립트, httpx 직접 호출, 채팅 1회·임베딩 1회)**

- 경로: OpenAI 호환 프록시 `https://gms.ssafy.io/gmsapi/api.openai.com/v1`의 `/chat/completions`, `/embeddings`. 인증은 `Authorization: Bearer <GMS_KEY>`.
- 채팅: `gpt-4o-mini`(응답 모델명 gpt-4o-mini-2024-07-18) 200, 약 3.4초. `response_format: {type: "json_schema", strict: true}`가 동작해 답변 스키마(segments[text, citation_ids])대로 파싱됐고 `[e1]`만 인용했다. usage에 토큰 수가 들어온다. 따라서 어댑터는 JSON schema 지정을 기본으로 쓰고, Pydantic 검증은 그대로 둔다.
- 임베딩: `text-embedding-3-small` 200, 약 0.3초, 입력 2개 배치, 차원 1536. usage에 토큰 수가 들어온다.
- 미확인: 3-large 지원, 요청 한도·크레딧 단위. (CHAT_MODEL과 긴 근거 지연은 아래 비교로 확인)

**Langfuse 병렬 분기 trace 확인 결과(2026-10-21, 임시 스크립트, langfuse 5.0.3, 클라우드 JP 리전, 테스트 데이터만 전송)**

- `get_client()`가 `.env`의 `LANGFUSE_PUBLIC_KEY`·`LANGFUSE_SECRET_KEY`·`LANGFUSE_BASE_URL`로 인증됐다(`auth_check` True).
- 루트 span `quiz_generate`을 `start_as_current_observation`으로 연 뒤 `graph.invoke`를 호출했다. `Send` 분기 5개 안에서 연 `question:qN` span과 그 아래 `generate` generation이 **trace 하나로 묶였다**. 분기 span 5개는 모두 루트 span의 자식이고, generation 5개는 각 분기 span의 자식이다(관측 11개).
- generation의 model·usage_details(input/output/total)가 기록됐다.
- 따라서 trace ID를 노드에 직접 넘기는 대체 수단은 필요 없다. 루트 관측을 연 상태에서 `invoke`를 호출하는 규칙만 지킨다.
- SDK 5 조회 API 메모: `api.trace.get`은 없고 `api.observations.get_many(trace_id=..., fields="core,basic,usage,model,io")`로 읽는다. `fields`를 빼면 model·usage가 비어 온다.

**채팅 모델 비교(2026-10-21, 모델당 1회, 참고치)**: 근거 10개 약 7,200자(프롬프트 4,875토큰, 무관 근거 2개 포함), 질문 "경사하강법에서 기울기는 어떻게 구해?", JSON schema strict.

| 모델 | 지연 | JSON | 인용 | 무관 근거 인용 |
| --- | --- | --- | --- | --- |
| gpt-4o-mini | 1.59초 | 정상, segment 2개 | e5, e8(노트) / 무효 ID 없음, 무인용 segment 없음 | 없음 |
| gpt-4.1-mini | 1.36초 | 정상, segment 1개 | e3, e5, e8(노트) / 무효 ID 없음, 무인용 segment 없음 | 없음 |

두 모델 모두 GMS에서 동작하고 노트 근거를 함께 인용했다. **결정(2026-10-21)**: `CHAT_MODEL` 기본값은 gpt-4.1-mini(PDF·노트 근거를 함께 인용, 약간 빠름). 2일차 평가 결과가 나쁘면 gpt-4o-mini로 바꾼다. 긴 근거에서도 생성 1회가 2초 안팎이었다(앞선 짧은 호출의 3.4초는 첫 호출 지연으로 보인다).

**데모 PDF 추출 확인(2026-10-21, PyMuPDF 2.0, `D:\SSAFY\demo_pdfs`)**

| 파일 | 쪽 | 쪽당 글자(최소/중앙/최대) | 전체 글자 | 800자 청크 | 이미지 |
| --- | --- | --- | --- | --- | --- |
| AI 지식 정리 노트 - Transformer & LLM 파운데이션 모델 | 11 | 172 / 620 / 950 | 6,641 | 약 14 | 5 |
| AI 지식 정리 노트: 워드 임베딩 | 5 | 133 / 359 / 658 | 2,064 | 약 5 | 4 |

- 두 파일 모두 텍스트 PDF다. 글자가 50자 미만인 쪽이 없고, 한글 깨짐(대체 문자)도 없다. 노션에서 내보낸 PDF(Skia/PDF)로 보인다.
- 페이지 라벨이 없어 뷰어의 쪽 번호와 추출 순서(1부터)가 같다. `#page=N` 인용 이동에 문제가 없다.
- 모든 쪽 텍스트에 문서 제목과 쪽 번호 꼬리말("AI 지식 정리 노트 - … 1")이 섞여 나온다. 청크와 인용문에 잡음이 되므로, 수집 때 여러 쪽에 반복되는 첫·끝 줄을 지운다.
- 이모지(🤖 등)와 위첨자(X⁽ⁱ⁾)는 그대로 추출된다. 수식 기호는 거의 없다.
- 그림 9개의 내용은 추출되지 않는다. 그림에만 있는 내용은 질문해도 근거가 없다.
- 쪽 경계에서 문장이 끊긴다(예: Transformer p.4가 문장 중간에서 시작). 쪽 단위 청크 규칙상 받아들인다.
- 규모: 두 파일 합쳐 16쪽, 청크 약 19개. 9절 규모 추정(청크 약 500개)보다 훨씬 작다.

- `langgraph` 설치 시 `langchain-core`와 `langsmith`가 함께 설치된다(ADR 0001). LangSmith 추적은 `LANGSMITH_TRACING` 등 환경변수를 켜지 않으면 동작하지 않으므로 .env에 넣지 않는다.

- [x] 새 환경에서 GMS 채팅·임베딩 HTTP 호출과 구조화 출력 지원 검증 (위 결과. CHAT_MODEL=gpt-4.1-mini, 시간 한도 결정)
- [ ] LangGraph 정상·보류·재시도 소진·통신 실패 분기 검증 및 버전 고정 (분기·병렬은 사전 검증함. 실제 노드·통신 실패 분기와 버전 고정은 새 저장소에서)
- [ ] 3절 함수 계약과 v1.1 6절 HTTP 계약(note-draft 포함) 고정, 목 모드(P4)로 양쪽 개발 시작
- [x] 변경 제안 P1~P7 채택 여부 결정 (2026-10-21 모두 결정됨, 0절)
- [x] Langfuse 직접 계측으로 그래프·노드·모델 호출 연결 및 병렬 분기의 trace 확인 (테스트 데이터로 확인. 실제 노드 계측은 새 저장소에서)
- [x] 데모 PDF로 PyMuPDF 추출 품질과 페이지 번호 일치 확인 (위 결과. 반복 꼬리말 제거 필요)
- [ ] 통합 확인(2~3일차): 재시작·새로고침 후 퀴즈·답변 복구, 문서·노트 혼합 인용 노트 저장→재조회→원본 열기, 무인용 문장 제거, 노트만 있는 공간 질문, 1~4문항 부분 퀴즈와 중복 제출
- [ ] 모델 교체 시 전체 재임베딩 관리 스크립트
