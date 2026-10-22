# 2일차 백엔드 구현 기록

2026-10-21. [ADR 0002](adr/0002-workspace-chats-shared-resources.md)와 [2일차 PRD](studylink-day2-prd.md)의 B 담당 범위(채팅 저장·조회·이관, 노트 저장·연결, 답변 복구 API)를 구현했다.

## 구현 내용

- **DB**: `chats(id, workspace_id, title, created_at, updated_at)` 추가, `answers.chat_id` 추가. 기존 DB는 `PRAGMA table_info` 검사 후에만 `ALTER TABLE`을 실행한다. `chat_id`가 NULL인 답변은 워크스페이스별 "이전 대화" 채팅으로 옮긴다. 채팅 ID는 워크스페이스 ID에서 결정적으로 만든 uuid5(`db.legacy_chat_id`)이고 `INSERT OR IGNORE`를 써서, 다시 초기화하거나 재시작해도 채팅이 중복되지 않는다.
- **채팅**(`services/chats.py`, `routers/chats.py`): 목록·생성(기본 제목 "새 채팅")·조회·messages·ask를 제공한다. ask는 서버에 저장된 채팅의 workspace_id로 검색 범위를 정한다. 같은 프로세스 안에서 채팅별로 잠가 같은 채팅의 동시 요청은 409로 거절하고, 다른 채팅은 서로 막지 않는다. 성공하면 채팅 `updated_at`을 갱신한다.
- **문맥**: `load_history(chat_id)`는 해당 채팅에서 완료된 대화 중 최근 6쌍까지, 합계 12,000자 이하로 골라 오래된 것부터 반환한다. 한도를 넘으면 오래된 쌍부터 버리고, 최신 1쌍만으로도 넘으면 그 쌍을 잘라 넣는다. 근거 부족 답변은 answer가 빈 문자열로 들어간다.
- **호환 ask**: `POST /api/workspaces/{id}/ask`는 그 워크스페이스에서 가장 최근에 쓴 채팅에 연결한다. 채팅이 없으면 새로 만든다.
- **노트**(`services/notes.py`, `routers/notes.py`): 본문에 남은 `[cN]` 표시에 대응하는 인용만 저장한다. 다음 경우는 문자열 detail과 함께 422로 거절한다. 대응 정보가 없는 `[cN]`, 중복된 인용 번호, 존재하지 않는 자료·노트 인용, 자기 자신 인용, 없는 워크스페이스 연결. 거절되면 같은 트랜잭션 전체를 롤백하므로 일부만 바뀌지 않는다. 저장할 때는 `index_status='failed'`로 바꾸고, 수정이면 기존 노트 청크를 삭제한 뒤 커밋한다. 커밋한 다음 트랜잭션 밖에서 `note_index.index_note`를 호출하고, 응답은 DB에서 다시 읽는다. 연결·해제는 링크만 바꾸며 재임베딩하지 않는다.
- **워크스페이스 상세**: `notes: [{id,title,index_status,updated_at}]`와 `chats`(updated_at 내림차순)를 추가했다. documents는 이전과 같다.
- **답변 복구**: 워크스페이스별 최근 20개 조회와 단건 조회를 추가했다. 항목 형식은 AnswerOut 필드에 question, created_at, chat_id, workspace_id를 더한 것이다.

## 최종 API(백엔드 추가·변경분)

| 메서드·경로 | 비고 |
| --- | --- |
| `GET/POST /api/workspaces/{id}/chats` | POST body `{title?}`, 201 |
| `GET /api/chats/{id}` | 404 |
| `GET /api/chats/{id}/messages` | 시간순 `{question, created_at, chat_id, answer_id, status, segments, citations, workspace_id}` |
| `POST /api/chats/{id}/ask` | body = AskRequest, 응답은 messages 항목과 같은 형식. 400/503/404/409/422 |
| `POST /api/workspaces/{id}/ask` | 호환용. 기본 채팅에 연결 |
| `GET /api/workspaces/{id}/answers`, `GET /api/answers/{id}` | 최근 20개, 단건 |
| `GET /api/notes?q=&workspace_id=` | 제목 부분 일치(대소문자 무시는 ASCII만), 연결 필터. 없는 workspace_id는 404 |
| `POST /api/notes`, `GET/PUT /api/notes/{id}` | 응답에 index_status, workspace_ids, citations(`title`, `missing` 포함)가 들어간다. PUT에서 workspace_ids를 생략하면 기존 연결을 유지하고, 지정하면 연결 전체를 교체한다 |
| `POST/DELETE /api/workspaces/{id}/notes/{note_id}` | 200, 노트 상세 반환. 중복 연결과 미연결 해제는 오류 없이 처리한다 |

노트 초안(`/answers/{id}/note-draft`)과 관련 노트(`/notes/related`)는 이번 범위에서 제외해 만들지 않았다.

## 팀 간 계약

- C: `answer_question(workspace_id, question, include_notes=True, *, chat_id=None, history=())`로 호출하고, answers INSERT에 chat_id를 기록한다. 작업 종료 시점의 C 구현이 이 시그니처와 일치하는 것을 확인했다. 라우터에는 과도기 안전장치 두 가지가 있다. 시그니처에 chat_id가 없으면 history 없이 호출하고, 저장 후 `chat_id IS NULL`이면 채워 넣는다.
- C: `index_note(note_id) -> str`은 청크 교체와 index_status 갱신을 맡고 예외를 던지지 않는다. B는 import 실패나 예외가 생겨도 로그만 남기며, 그 경우 상태는 failed로 남는다.
- A: 채팅 화면은 `/chats/{id}/ask`와 `/messages`를 사용한다. 409는 "이 채팅에서 답변 생성 중"이라는 안내다. 노트 인용 저장 형식은 `{id:'cN', source_type:'doc'|'note', document_id, page, quote, note_id}`이다.

## 검증

- 확인됨: `.venv/Scripts/python -m pytest -q backend/tests/test_day2_api.py backend/tests/test_backend_api.py` → 13 passed. 저장소 루트 `.venv/Scripts/python -m pytest -q` → 48 passed(C의 테스트 포함, 작업 종료 시점 기준).
- 확인됨: 목 모드에서 실제 C의 `index_note`와 `answer_question`으로 노트 저장(index_status ok)과 채팅 ask 2회, messages 2건을 TestClient 스크립트로 확인했다.
- 미확인: 실제 GMS 연동, 기존 `backend/data/app.db`에서 앱을 기동해 마이그레이션하는 경우(임시 DB에서 구 스키마 이관만 테스트), 다중 프로세스 실행 시의 409(잠금이 프로세스 안에서만 동작), 프런트 통합.

## 남은 일

- 노트 초안·관련 노트 HTTP 연결(C의 `draft_note`·`related_notes` 완성 후)
- 기획서·아키텍처 문서에 채팅 API·마이그레이션 반영 여부 확인(이번 작업에서는 수정 권한 범위 밖)
- 실제 데이터 DB로 재시작 이관 확인과 2일차 인수 시나리오 9~11 수동 검증
