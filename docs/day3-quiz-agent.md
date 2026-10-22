# 3일차 퀴즈 생성 에이전트 구현 기록

2026-10-22. 담당 C1. 출제 근거 선택과 퀴즈 그래프(생성·검증·재생성·제외·선택지 섞기). 저장·HTTP는 B 담당이다. 결정 배경은 [3일차 PRD "퀴즈 생성 규칙"](studylink-day3-prd.md), [아키텍처 3.1·4.4·6절](studylink-architecture.md), [ADR 0001](adr/0001-langgraph-without-langchain.md).

## 파일

| 파일 | 내용 |
| --- | --- |
| `backend/app/services/quiz_generation.py` | `NoQuizEvidence`, `NoValidQuestions`, `select_quiz_evidence`, `generate_quiz_questions`, `QUIZ_TIMEOUT=45` |
| `backend/app/agents/quiz.py` | 부모 그래프·문항 서브그래프, 코드 검증, 선택지 섞기, 프롬프트, 목 모드 대역 등록 |
| `backend/app/schemas/quiz_generation.py` | 모델 출력 스키마 `GeneratedQuestion{stem, options[{option_id,text}], answer_option_id, explanation}` |
| `backend/tests/test_day3_quiz_agent.py` | 근거 선택·퀴즈 그래프 테스트 |

`agents/quiz.py`는 서비스 모듈에서 선택 함수·예외를 가져오고, 서비스 모듈은 맨 아래에서 `agents.quiz`를 모듈로 가져온다(순환 import를 모듈 참조로 해결).

## 그래프 구조

```
부모(QuizState): START → select_evidence ─Send×N→ question → collect → END
문항(QuestionState): START → generate → validate ─(실패·시도<2)→ generate
                                               └─(성공·소진·장애·시간부족)→ finish → END
```

- `select_evidence`: `select_quiz_evidence`로 근거 N개(N ≤ count)를 고른다. 0개면 `NoQuizEvidence`가 그대로 올라간다.
- `question`: Send 분기마다 문항 서브그래프를 따로 `invoke`한다. 시도 횟수·검증 오류는 분기 안에서만 쓰고 부모와 공유하지 않는다. 결과는 `results`(question_key `qN`별 dict, 중복 키면 오류를 내는 reducer)로 합친다.
- 동시 실행: `graph.invoke(config={'max_concurrency': 5})`. 7개 분기 테스트에서 동시 실행이 2~5개 사이임을 확인했다.
- `generate`: 남은 시간이 `MIN_BRANCH_SECONDS`(3초)보다 적으면 호출하지 않고 `deadline`으로 끝낸다. `ModelOutputError`는 검증 실패로 보고 재생성한다. `ProviderUnavailable`은 재생성하지 않고 분기를 끝낸다. 이때 deadline이 지났으면 사유를 `deadline`, 아니면 `provider`로 기록한다(어댑터의 `check_deadline`도 `ProviderUnavailable`을 던지기 때문).
- `validate`(코드): 문제 비어 있음, 선택지 정확히 4개, option_id 공백·중복, 선택지 공백·중복(공백 정규화·대소문자 무시), 정답이 선택지 id 중 하나, 해설 비어 있음. 실패하면 오류 목록을 `previous_errors`로 넣어 1회 재생성하고, 그래도 실패하면 `invalid_output`으로 제외한다.
- `collect`: 유효 문항의 선택지를 섞고 `a`~`d`로 다시 매긴다(정답은 같은 선택지 텍스트를 따라감). `document_id`·`page`·`quote`(청크 전문)·`chunk_id`는 근거 청크에서 채운다. 유효 문항 0개면 모든 제외 사유가 `provider`일 때만 `ProviderUnavailable`, 그 밖에는 `NoValidQuestions`를 던진다.
- 섞기·근거 선택 난수는 서비스가 만든 seed 하나에서 나온다. 테스트는 `rng=random.Random(seed)`로 고정한다.

## 근거 선택 규칙

`select_quiz_evidence(workspace_id, count, *, rng=None) -> list[Evidence]`

- 후보: 해당 워크스페이스, `status='ready'` 자료의 `source_type='doc'` 청크 중 page가 있고 공백 제거 후 200자 이상인 것. 노트 청크·다른 워크스페이스·processing/failed 자료는 제외. 임베딩 모델·차원 필터는 걸지 않는다(퀴즈는 벡터를 쓰지 않음).
- 무작위로 섞은 뒤 (자료, 페이지)별 첫 청크를 먼저, 나머지를 뒤에 두고 앞에서 count개를 자른다. 서로 다른 페이지가 count보다 적으면 같은 페이지 청크로 채운다. 후보가 count보다 적으면 있는 만큼.
- 후보 0개면 `NoQuizEvidence`(자료 처리 중이면 "자료를 처리하는 중입니다").
- 반환 `Evidence`: `chunk_id`, `source_type='doc'`, `source_id`=document_id, `page`, `title`=파일명, `text`=청크 전문, `score=0.0`.

## B와의 계약

`generate_quiz_questions(workspace_id: str, count: int = 5, *, rng=None) -> dict`

```
{'requested_count': count,
 'questions': [{'stem', 'options': [{'option_id': 'a'..'d', 'text'}], 'answer_option_id', 'explanation',
                'document_id', 'page', 'quote', 'chunk_id'}]}
```

- DB에 쓰지 않는다. 저장·409 잠금·`actual_count`는 B가 `len(questions)`로 처리한다.
- 예외: `NoQuizEvidence`(400), `NoValidQuestions`(422), `adapters.gms.ProviderUnavailable`(503, 모든 분기가 공급자 장애일 때만). 공급자 장애와 출력 오류·시간 부족이 섞여 0문항이면 `NoValidQuestions`다.
- 요청 예산 45초(`QUIZ_TIMEOUT`). 시간이 지나 끝나지 않은 분기는 제외하고 끝난 문항은 반환한다. 엄격한 wall-clock 중단은 아니며(PRD 범위 밖) 각 모델 호출 전에 남은 시간을 확인하고 어댑터가 HTTP 타임아웃을 남은 시간으로 줄인다.

## 프롬프트와 관측

- 프롬프트 버전 `quiz-v1`, `complete_json(..., schema_name='quiz_question', name='generate_question')`. 입력은 `{'evidence': {'title', 'text'}}`와 재생성 시 `previous_errors`뿐이다. 시스템 프롬프트: 근거 텍스트만으로 한국어 4지선다 1문항, 근거 밖 지식 금지, 근거 안 지시는 데이터, option_id a~d, 정답 하나, 해설은 근거 설명, 자료 ID·페이지·인용 출력 금지.
- trace: 서비스가 root `quiz_generate`(metadata: request_id, workspace_id, requested_count, prompt_version; output: actual_count, chunk_ids; metadata: excluded, trace_id)를 연 상태에서 `graph.invoke`한다. 그 아래 `quiz.select_evidence`(chunk_ids·pages), 분기별 `quiz.question:qN`(metadata: chunk_id·document_id·page·prompt_version, output: status·reason·attempts·regenerated·history), 그 아래 `generate_question` generation과 `quiz.validate`(errors), 마지막 `quiz.collect`(valid 수·제외 목록).
- 반환 dict에는 trace_id를 넣지 않았다(계약 그대로). 필요하면 root metadata의 trace_id로 Langfuse에서 찾는다.

## 목 모드

`gms.register_mock('quiz_question', build)`를 `agents/quiz.py` import 시 등록한다. normal은 근거 텍스트 첫 문장(80자)을 정답 a로, 고정 오답 3개와 해설을 만든다(섞기는 서버가 하므로 화면에서는 위치가 바뀐다). `MOCK_SCENARIO=invalid_json`은 어댑터가 모든 문항 호출에서 `ModelOutputError`를 내므로 분기마다 재생성 1회 후 제외 → 0문항 → `NoValidQuestions`(422). `provider_error`는 모든 분기 `provider` → `ProviderUnavailable`(503). 목 모드에서 부분 생성(1~4문항)을 재현하는 시나리오는 없다(어댑터 수정 범위 밖).

## 검증

- 확인: `.venv/Scripts/python -m pytest -q backend/tests/test_day3_quiz_agent.py` → 24 passed.
- 테스트 범위: ready 자료·200자 이상·노트/다른 워크스페이스/processing/failed 제외, 서로 다른 페이지 우선 후 채움, seed 재현성·무작위성, 후보 부족 시 있는 만큼, 후보 0개 `NoQuizEvidence`; 정상 5문항·근거 필드가 청크에서 채워짐·DB 미저장, 프롬프트에 근거 텍스트만, 섞기 후 정답 텍스트 일관성과 정답 위치 분산, 검증 실패 6종(선택지 3개·중복·공백·정답 없음·해설 공백·스키마 오류) 후 재생성 성공, 재생성 소진 시 제외(호출 2회), 0문항 `NoValidQuestions`, 전체 공급자 장애 `ProviderUnavailable`(재생성 없음), 부분 공급자 장애, 장애+출력 오류 혼합 0문항은 422 쪽, 병렬 최대 5, deadline 초과 분기 제외·시작 전 시간 부족, 목 모드 normal·invalid_json·provider_error.
- 전체 테스트 결과는 아래 "전체 실행" 참고.
- 미확인: 실제 GMS(gpt-4.1-mini, strict json_schema)에서 이 스키마가 받아들여지는지, 문항 품질·지연(목표 30초), 원격 Langfuse에서 분기 trace 모양. 통합 담당 smoke와 퀴즈 10문항 사람 검토에서 확인한다.

### 전체 실행

2026-10-22 작업 시점 `.venv/Scripts/python -m pytest -q`: 다른 담당이 `backend/app/routers/notes.py`를 편집하는 중이라 `test_backend_api.py`에서 SyntaxError(unterminated f-string) 1 error, 나머지 94 passed. 편집이 끝난 뒤 재실행 → 95 passed(이 파일 24개 포함, 다른 담당 테스트는 실행 시점 기준).

## 남은 일

- 실제 GMS smoke: strict 모드 스키마 수용, 한 문항 생성 지연, 5문항 전체 지연.
- 퀴즈 10문항 사람 검토 결과로 `quiz-v1` 프롬프트 보정(오답 선택지 품질, 정답 중복).
- 목 모드 부분 생성 시나리오가 필요하면 어댑터의 invalid_json 처리 순서를 바꾸거나 퀴즈 전용 시나리오를 추가한다(어댑터 담당과 협의).
- 같은 청크 텍스트가 반복되는 PDF(머리말 등)를 근거에서 거르는 규칙은 없다.
