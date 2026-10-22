# 3일차 백엔드 구현 기록

2026-10-22. [3일차 PRD](studylink-day3-prd.md)의 B 담당 범위(퀴즈 저장·조회·제출·채점, 오답 API, questions 컬럼 이관, 노트 초안·관련 노트 HTTP 연결)를 구현했다.

## 구현 내용

- **DB**(`db.py` `_migrate_quiz_tables`): `questions.quote TEXT`, `questions.chunk_id TEXT`를 `PRAGMA table_info` 검사 후에만 `ALTER TABLE`로 추가한다. 인덱스는 `questions_quiz(quiz_id)`, `quizzes_workspace(workspace_id,created_at)`, `attempts_question(question_id)`이다. options_json은 `[{option_id, text}]`이다. reviews에 created_at 컬럼을 두지 않고 해당 문항 attempt의 submitted_at을 오답 created_at으로 쓴다.
- **퀴즈**(`services/quizzes.py`, `routers/quizzes.py`): 생성 요청이 오면 C의 `generate_quiz_questions`를 호출하고, 결과를 quizzes(requested_count, actual_count=len)와 questions에 한 트랜잭션으로 저장한다. quiz_id·question_id는 B가 uuid4로 부여한다. 같은 워크스페이스에서 생성이 진행 중이면 프로세스 내 잠금으로 409를 돌려준다(채팅 ask와 같은 방식). 다른 워크스페이스는 막지 않는다.
- **정답 누출 차단**(`schemas/quiz.py`): `QuestionPublic`에는 answer_option_id·explanation·quote 필드가 아예 없다. `QuestionGraded`가 이를 상속해 채점 필드를 더한다. `QuizPublic.submitted_at`은 `None` 타입이라 제출 후 응답이 공개 형식으로 직렬화되지 않는다.
- **제출·채점**: 이미 제출한 퀴즈는 입력과 무관하게 저장된 attempts로 결과를 다시 만들어 200으로 돌려준다. 미제출이면 다음 경우 422를 내고 아무것도 저장하지 않는다. 다른 퀴즈의 문항이 들어 있거나, 응답하지 않은 문항이 있거나, 해당 문항에 없는 선택지를 고른 경우다. 검증을 통과하면 한 트랜잭션에서 `UPDATE quizzes SET submitted_at=? WHERE id=? AND submitted_at IS NULL`를 실행하고, attempts와 오답 reviews(status=open)를 함께 저장한다. 갱신된 행이 0이면 동시 제출로 보고 저장된 결과를 반환한다. 모델은 호출하지 않는다.
- **오답**(`services/reviews.py`): 목록·단건 응답에 documents를 LEFT JOIN한 filename을 넣는다. 자료가 없으면 filename은 null이고 기록은 유지한다. 단건 조회에서만 `related_notes(stem + " " + 정답 선택지 텍스트, k=3)`을 호출하고, 각 항목에 퀴즈 워크스페이스와의 연결 여부 `linked`를 붙인다. 관련 노트 검색이 `ProviderUnavailable`이나 import 실패로 끝나도 오답은 그대로 보여 준다. 이때 `related_notes: []`, `related_notes_status: "unavailable"`이다.
- **노트 초안·관련 노트**(`routers/notes.py`): `draft_note` 결과를 그대로 전달하고 DB에 쓰지 않는다. 관련 노트는 `title + "\n" + body`로 검색하며 입력을 저장하지 않는다. 제목과 본문이 모두 비어 있으면 검색하지 않고 `[]`를 돌려준다.

## 최종 API(3일차 추가분)

| 메서드·경로 | 응답·오류 |
| --- | --- |
| `POST /api/workspaces/{id}/quizzes` body `{count?}`(1~5, 기본 5, body 생략 가능) | 201 `{quiz_id, workspace_id, requested_count, actual_count, created_at, submitted_at:null, questions:[QuestionPublic]}`. 오류: 자료·근거 없음 400, 워크스페이스 없음 404, 생성 중 409, count 범위 밖·유효 문항 0개 422, 공급자 장애 503 |
| `GET /api/workspaces/{id}/quizzes` | 최근 20개 `{quiz_id, requested_count, actual_count, created_at, submitted_at, score}`. 제출 전 score는 null |
| `GET /api/quizzes/{id}` | 제출 전에는 생성 응답과 같은 형식, 제출 후에는 제출 응답과 같은 형식. 404 |
| `POST /api/quizzes/{id}/submit` body `{answers:{question_id: option_id}}` | `{quiz_id, workspace_id, requested_count, actual_count, created_at, submitted_at, score, total, questions:[QuestionGraded]}`. 입력 오류 422(무저장), 재제출 200(저장된 결과), 404 |
| `GET /api/reviews?workspace_id=&status=open\|reviewed` | `[{review_id, workspace_id, quiz_id, question_id, stem, selected_option_id, answer_option_id, options, explanation, document_id, filename, page, quote, status, learner_reason, created_at}]`. 최근 제출 순. workspace_id 필수(없는 ID 404), status 값 오류 422 |
| `GET /api/reviews/{id}` | 목록 항목 + `related_notes:[{note_id,title,snippet,linked}]`(최대 3개) + `related_notes_status: "ok"\|"unavailable"`. 404 |
| `PATCH /api/reviews/{id}` body `{learner_reason?, status?}` | 목록 항목 형식. learner_reason 2,000자 초과·status 값 오류 422, 404 |
| `POST /api/answers/{id}/note-draft` | `{title, body, citations, fallback}`. AnswerNotFound 404, AnswerNotGrounded 422, ProviderUnavailable 503 |
| `POST /api/notes/related` body `{title, body, exclude_note_id?}` | `[{note_id, title, snippet}]` 최대 3개. 503 |

QuestionPublic은 `{question_id, stem, options:[{option_id,text}], document_id, filename, page}`이다. QuestionGraded는 여기에 `{selected_option_id, answer_option_id, correct, explanation, quote}`를 더한다. PRD 계약에 없는 필드는 세 가지를 더했다. 제출 응답의 workspace_id·requested_count·actual_count·created_at, 오답 항목의 workspace_id, 오답 단건의 related_notes_status다.

## 팀 간 계약

- C1: `generate_quiz_questions(workspace_id, count=5) -> {'requested_count', 'questions': [{stem, options, answer_option_id, explanation, document_id, page, quote, chunk_id}]}`를 함수 안에서 지연 import한다. 선택지 섞기와 검증은 C가 끝낸 것으로 보고 B는 다시 검증하지 않는다. 예외는 `NoQuizEvidence`→400, `NoValidQuestions`→422, `ProviderUnavailable`→503으로 바꾼다. 빈 questions가 오면 B도 422로 처리한다. 작업 종료 시점의 C 구현 시그니처가 이와 일치하는 것을 확인했다.
- C2: `related_notes(text, exclude_note_id=None, k=3) -> [{note_id, title, snippet}]`, `draft_note(answer_id) -> {title, body, citations, fallback}`과 `AnswerNotFound`·`AnswerNotGrounded`. 시그니처가 일치하는 것을 확인했다.
- A: 409는 "이 워크스페이스에서 퀴즈를 만드는 중"이라는 안내다. 부분 생성은 `actual_count < requested_count`로 판단한다. 오답 단건의 `related_notes_status == "unavailable"`이면 "관련 노트 없음" 대신 일시적 오류로 안내할 수 있다. `filename == null`이면 "원문을 열 수 없음"이다.

## 검증

- 확인됨: `.venv/Scripts/python -m pytest -q backend/tests/test_day3_api.py` → 9 passed. C 모듈은 `sys.modules` 대역으로 바꿔 검증했다. 대상은 정상 생성, 부분 생성, NoValidQuestions, NoQuizEvidence, ProviderUnavailable, count 범위, 409, 정답 누출, 채점, 422 무저장, 재제출, 4스레드 동시 제출 1회 기록, 오답 필터·수정·관련 노트 linked, 자료 삭제 후 기록 유지, 재시작 후 조회, 구 스키마 이관 멱등, note-draft·related HTTP 매핑이다.
- 확인됨: 저장소 루트 `.venv/Scripts/python -m pytest -q` → 95 passed(다른 담당 테스트 포함, 작업 종료 시점 기준).
- 확인됨: 목 모드에서 실제 C 모듈(`quiz_generation`, `related_notes`)로 TestClient 스크립트를 돌렸다. 임시 DB에 청크를 직접 넣고 퀴즈 생성(201, 5문항), 제출, 오답 목록, 오답 단건, `/notes/related` 200까지 확인했다.
- 미확인: 실제 GMS 연동, 기존 `backend/data/app.db`에서 앱을 기동해 이관하는 경우, 다중 프로세스 실행 시 409, 프런트 통합, 실제 노트 초안 HTTP 경로(대역으로만 확인).

## 남은 일

- 실제 데이터 DB로 재시작 이관 확인과 3일차 인수 시나리오 1~8 수동 검증
- 기획서·아키텍처 문서에 추가 필드(related_notes_status 등)와 reviews created_at 산출 방식 반영 여부 확인(이번 작업의 수정 권한 범위 밖)
- README 실행 방법 갱신
