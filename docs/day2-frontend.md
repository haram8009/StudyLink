# 2일차 프런트 구현 기록 — 채팅과 공통 자원 패널

2026-10-21. [ADR 0002](adr/0002-workspace-chats-shared-resources.md)와 [2일차 PRD](studylink-day2-prd.md) 사용자 스토리 39~47을 기준으로 워크스페이스 화면을 채팅 구조로 바꿨다.

## 화면 구성

- 왼쪽 **채팅 목록**: 새 채팅 버튼(`새 채팅 N` 제목으로 생성), updated_at 내림차순, 선택 상태, 답변 생성 중 표시. 백엔드가 이관한 "이전 대화"도 일반 채팅으로 보인다. 채팅이 없으면 첫 질문을 보낼 때 질문 앞부분을 제목으로 채팅을 만든다.
- 가운데 **대화**: 선택한 채팅의 messages만 시간순으로 표시하고 질문 입력, 연결 노트 포함 선택(include_notes)을 둔다. 답변 인용은 자료/내 노트 배지로 구분한다.
- 오른쪽 **공통 자원 패널**(워크스페이스 단위, 채팅을 바꿔도 유지): 위쪽 열람 영역(PDF 뷰어 또는 노트 미리보기), 아래 탭 `자료`(업로드·처리 상태·재시도·원문 열기)와 `연결 노트`(목록·열기·연결 해제·기존 노트 검색 후 연결·새 노트 작성). 노트 미리보기에서 수정·다시 저장, 노트 인용 이동, 미연결 노트 연결을 할 수 있다. index_status=failed면 "검색 제외, 다시 저장" 안내를 보인다.
- 요청 상태는 채팅별로 따로 둔다. 답변 생성 중인 채팅은 입력창이 비활성화되고, 다른 채팅으로 바꿔 질문할 수 있다. 실패한 질문은 그 채팅 입력창에 되돌린다.
- 인용 클릭: doc → PDF 뷰어를 해당 자료·페이지로 열며 `document_id-page-요청시각` key로 iframe을 다시 마운트해 같은 PDF의 다른 페이지도 이동한다. note → 노트 미리보기.
- 마지막 선택 채팅은 `localStorage['studylink-last-chat-{workspace_id}']`(try/catch)에 두고, 없거나 사라졌으면 가장 최근 채팅을 연다.
- 1350px 이하에서는 자원 패널이 대화 아래로, 850px 이하에서는 채팅 목록·대화·자원 패널이 한 열로 쌓인다.

파일: `frontend/src/Workspace.jsx`(화면), `frontend/src/workspace.css`(레이아웃), `frontend/src/ui.jsx`(공용 ErrorBox·Spinner), `frontend/src/api.js`(클라이언트·목), `frontend/src/main.jsx`(홈·라우팅).

## 사용 API

`GET /api/workspaces/{id}`(documents·notes·chats; chats가 없으면 `GET /api/workspaces/{id}/chats`로 보완), `POST /api/workspaces/{id}/chats`, `GET /api/chats/{id}/messages`, `POST /api/chats/{id}/ask`, 자료 업로드·상태·재시도·`GET /api/documents/{id}/file`, `GET /api/notes?q=&workspace_id=`, `GET/PUT /api/notes/{id}`, `POST /api/notes`, `POST/DELETE /api/workspaces/{id}/notes/{note_id}`.

- 오류는 문자열 `detail`을 그대로 보이고, 없으면(422 검증 배열 등) 400·404·409·422·503별 기본 문구를 쓴다.
- 가정: 노트 목록 응답 항목에 id·title·index_status·updated_at이 있고, 노트 조회의 citations 항목은 citation_id·source_type·document_id·page·quote·cited_note_id·title·missing 형식이다. 채팅 생성 시 title을 보내며 서버가 그대로 저장한다고 본다. 질문 성공 후 messages를 다시 받지 않고 ask 응답에 question·created_at을 붙여 화면에 추가한다.
- 기존 `api.draft`·`api.related`·`api.answers`는 남겨 두었지만 이번 화면에서는 쓰지 않는다.

## 목 모드

`cd frontend && VITE_USE_MOCK=true npm run dev`. 데이터는 브라우저 localStorage(`studylink-preview-v1*`)에만 저장한다.

- 채팅·메시지 저장, 같은 채팅 동시 질문 409, 자료·노트 없음 400, 없는 채팅 404를 재현한다. 질문에 "근거 없음"을 넣으면 근거 부족, "서비스 오류"를 넣으면 503, 노트 본문에 "[색인 실패]"를 넣으면 index_status=failed, 파일명에 "실패"가 있는 PDF는 첫 처리에서 실패한다.
- 답변 인용은 같은 PDF의 서로 다른 두 페이지와 연결 노트 하나를 준다. 업로드한 PDF는 그 탭에서만 blob URL로 실제 표시되고, 새로고침 후에는 페이지 번호가 보이는 자리표시 화면이 나온다.
- 1일차 목 답변(`studylink-preview-v1-answers`)은 워크스페이스를 열 때 "이전 대화" 채팅으로 한 번만 옮긴다.

## 확인 결과

확인함(2026-10-21):
- `npm run build` 통과.
- 목 모드 dev 서버(127.0.0.1:5199)와 앱 내장 브라우저에서 화면 클릭과 페이지 안 스크립트로 확인했다. 생성한 3페이지 PDF 업로드 → 처리 완료, 새 노트 작성·연결 → 채팅 A 질문 중 채팅 B 생성·질문(두 채팅 모두 "답변 생성 중", 각 입력창만 비활성) → 완료 후 A·B 전환 시 각자 질문만 표시.
- A의 인용 e1→e2 클릭 시 뷰어가 1→2페이지로 바뀌고 iframe이 다시 마운트됨(`#page=1`→`#page=2`), e3 클릭 시 노트 미리보기. B로 전환해도 자원 패널 유지, B에서 같은 PDF 원문 열기·인용 이동 동작.
- 새로고침 후 마지막 선택 채팅(가장 최근 아닌 A) 복원, "이전 대화" 채팅 표시·기록 열람, 재로드해도 이관 중복 없음.
- 목 API 직접 호출로 409·400·404 문구, 후속 질문이 같은 채팅 문맥으로 표시되는 것 확인. 노트 "[색인 실패]" 저장 시 경고와 목록 "검색 제외", 검색 범위 노트 수 0. 연결 해제·기존 노트 연결·미리보기 갱신 확인.
- 1600px에서 3열, 375px에서 한 열로 쌓이고 가로 스크롤 없음. 콘솔 오류 없음.

미확인:
- 실제 FastAPI 백엔드(B 구현 중)와의 연동, 실제 409·503 응답 표시, 실제 PDF 파일 엔드포인트 표시.
- 409·503의 화면 표시는 목 API 호출로만 확인했다(UI는 같은 채팅 중복 전송을 막으므로 화면에서 409가 나오지 않는다).

## 남은 일

- 백엔드 채팅 API가 준비되면 실제 모드로 인수 시나리오 9~11 확인.
- 채팅 이름 변경·삭제는 ADR 범위 밖이라 넣지 않았다. 노트 초안 생성·관련 노트 추천 UI는 이번 범위 밖이다.
- 좁은 화면에서 Chrome PDF 뷰어의 썸네일 패널이 본문 폭을 차지한다. 필요하면 별도 PDF 렌더러를 검토한다.
