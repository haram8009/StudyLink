# 2일차 에이전트 구현 기록

2026-10-21. 담당 C. 채팅 문맥 해석·연결 노트 검색·약한 근거 재검색·노트 색인. 결정 배경은 [2일차 PRD](studylink-day2-prd.md), [ADR 0001](adr/0001-langgraph-without-langchain.md), [ADR 0002](adr/0002-workspace-chats-shared-resources.md).

## 구현한 범위

- 그래프: `interpret → retrieve → (근거 없음이면 research 1회) → generate → validate`. 모든 단계가 요청 30초 deadline을 공유한다(협력적 검사 제한은 1일차와 동일).
- 후속 질문 해석(`interpret`): history가 있을 때만 GMS로 독립 검색 질의를 만든다. 검색 질의만 바뀌고, 생성에는 원 질문과 최근 3쌍·답변 600자로 줄인 대화 문맥을 넣는다. 문맥에서 `[eN]`·`[cN]` 표시는 지운다. 모델 출력 오류·빈 질의면 원 질문으로 검색하고, 공급자 장애는 그대로 503 경로로 보낸다.
- 검색(`retrieve`): 현재 워크스페이스 ready 자료 + include_notes면 `workspace_notes`로 연결되고 `index_status='ok'`인 노트 청크만 후보. 임베딩 모델·차원 필터는 둘 다 적용. 후보 전무 시 기존 `NoSearchableContent`(400). 노트만 있는 워크스페이스도 질문 가능. 노트 근거의 제목은 현재 노트 제목, page는 없음.
- 노트 보장: 최소 점수를 넘은 노트가 있는데 상대 기준·상한 선택 결과에 없으면 최고 점수 노트 1개를 넣고, 필요하면 뒤쪽 자료 근거를 빼서 최대 12개·8,000자를 지킨다. 남은 글자 수보다 길면 노트 발췌를 자른다.
- 약한 근거 재검색(`research`): 후보는 있으나 최소 점수를 넘는 근거가 없을 때 1회. 질의를 다시 쓰고 검색해 chunk_id로 병합(높은 점수 유지) 후 선택 규칙을 다시 적용. 재작성 실패·같은 질의면 추가 검색은 생략한다. 그래도 없으면 insufficient_evidence.
- 근거 ID는 이번 요청의 eN만 유효하다(기존 validate 유지). 생성 프롬프트에 이전 답변·인용 번호를 근거로 쓰지 말라고 명시했다.
- 저장: `answers.chat_id`에 채팅 ID 기록. body_json에 `retrieval`(chunk_id·source_type·score), `search_query`, `research{performed,query}`, `note_guaranteed`, `trace_id`.
- 관측: ask 루트 metadata에 chat_id·history_turns. `answer.rewrite_query.followup|research`, `answer.research`, `retrieve`(phase·candidate_count·above_min_score·note_guaranteed), 모델 호출 generation(`rewrite_query`/`generate`)에 prompt_version.
- 노트 색인 `index_note(note_id) -> str`: 제목 + 빈 줄로 나눈 본문 문단(800자 단위)으로 청크. 짧은 트랜잭션에서 본문을 읽고 예전 노트 청크를 지운 뒤, 트랜잭션 밖에서 임베딩한다. 쓰기 직전 제목·본문이 그대로일 때만 새 청크를 넣고 'ok'로 바꾼다(그사이 수정되면 게시하지 않고 다음 색인에 맡긴다). 실패 시 청크 제거·'failed'. 예외를 밖으로 던지지 않는다. 모델·차원은 문서 청크와 같은 설정값을 기록한다.

## 프롬프트 버전

| 이름 | 용도 |
| --- | --- |
| `answer-v2` | 답변 생성. v1에 conversation 사용 범위·과거 인용 금지 문구 추가 |
| `query-followup-v1` | 채팅 문맥으로 후속 질문을 독립 검색 질의로 재작성 |
| `query-research-v1` | 약한 근거 시 개념어·동의어·표기를 보강한 재검색 질의 |

어댑터에 `complete_json(prompt, schema, *, system_prompt, prompt_version, ...)`를 추가했고 `generate_json`은 answer-v2로 이를 호출한다. `MOCK_LLM=1`의 재작성 대역은 followup이면 직전 질문을 앞에 붙이고, research면 원 질문을 돌려준다.

## B와의 계약

- `answer_question(workspace_id, question, include_notes=True, *, chat_id=None, history=())`. history는 B가 해당 채팅에서만 뽑아 6쌍·12,000자 상한을 적용한 `[{'question','answer'}]`(오래된 것부터). 비어 있으면 1일차와 같이 원 질문으로 검색한다. 에이전트는 history 상한을 다시 적용하지 않고, 생성 문맥만 따로 줄인다.
- 답변 INSERT는 B 스키마의 `answers.chat_id`(chats 참조 FK)를 전제로 한다. chat_id=None이면 NULL로 저장한다.
- `index_note`는 노트 저장 후 B가 호출한다. 반환값은 'ok' 또는 'failed'이며, 호출 도중 본문이 바뀐 경우 현재 index_status를 돌려준다.

## 검증

- 확인: 저장소 루트 `.venv\Scripts\python.exe -m pytest -q backend/tests/test_day2_agent.py` → 18 passed, `backend/tests/test_agent.py` → 17 passed(1일차 테스트 수정 없음). 전체 `python -m pytest -q` → 48 passed(B의 테스트 포함, 실행 시점 기준).
- 테스트 범위: history 유무별 검색 질의, 재작성 출력 오류 fallback·공급자 장애 전파, 다른 워크스페이스·미연결·failed 노트 제외와 include_notes=false, 노트만 있는 워크스페이스 답변·노트 인용, 노트 보장의 개수·글자 상한, 재검색 병합과 1회 상한, chat_id·관측 필드 저장, index_note 성공 교체·실패(공급자·출력·기타·차원) 시 청크 제거·failed·예외 미전파, 색인 중 본문 변경 시 게시 생략, 목 모드 후속 질문.
- 미확인: 실제 GMS 재작성 품질, 데모 질문의 실제 노트 인용, 원격 Langfuse trace 모양, MIN_SCORE·RELATIVE_MARGIN 보정. 통합 담당 smoke에서 확인한다.

## 남은 일

- 데모 질문셋으로 재작성·재검색 효과와 점수 기준 보정(평가 도구 포함).
- 노트 초안 그래프 `draft_note`, 관련 노트 `related_notes`(이번 범위 밖).
- 노트 제목만 바뀌어도 전체 재색인한다. 대량 재색인 스크립트는 별도 후속.
