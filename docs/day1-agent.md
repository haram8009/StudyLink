# 1일차 에이전트 구현 기록

2026-10-21. 제품 저장소의 실제 구현 기록이며, 기존 사전 검증과 구분한다.

## 구현한 범위

- `retrieve(workspace_id, query, include_notes)`는 ready 자료, 워크스페이스, 임베딩 모델·차원을 SQL에서 먼저 제한한다. float32 코사인 점수를 최소 점수와 최고 점수 차이로 거르고 최대 12개·8,000자로 제한한다. 노트 검색은 2일차 범위다.
- LangGraph StateGraph가 검색 → 생성 → 인용 검증을 실행한다. 근거 없음은 생성 없이 보류하고, 출력 형식 오류 또는 절반 넘는 문장 제거 시 생성만 1회 재시도한다. 반복 실패는 보류로 끝난다. 공급자 통신 오류는 보류로 바꾸지 않는다. 실제 재검색은 아직 없다.
- 모델 출력은 문장과 근거 ID만 받는다. 제공하지 않은 ID를 제거하고 유효 인용이 없는 문장을 버린다. 문서·페이지·발췌는 서버가 선택 근거로 채우고 최종 결과를 서비스가 한 번 저장한다.
- `embed`는 `(n,dim)` numpy float32, `generate_json`은 Pydantic 모델을 반환한다. httpx 직접 호출이며 20초 HTTP timeout, 30초 질문 deadline과 일시적 통신 오류 최대 1회 재시도를 사용한다. 인증 등 영구 오류는 즉시 실패한다. 이 deadline은 호출 전후의 협력적 검사이며 동기 HTTP의 엄격한 wall-clock 중단을 보장하지는 않는다.
- `MOCK_LLM=1`은 안정적인 토큰 해시 임베딩과 첫 근거 발췌를 반환한다. 의미 검색 품질을 검증하는 모델이 아니다. `MOCK_SCENARIO`는 normal/invalid_json/invalid_citation/insufficient/provider_error를 지원한다. 설정 모듈이 목·실제 DB를 분리한다.
- `LANGFUSE_ENABLED=1`일 때 직접 SDK로 ask 루트, 검색·생성·검증 span, embed/generate generation을 연결한다. 선택 근거·점수, 입력·출력, 모델, 공급자 토큰 사용량을 기록한다. span 시간이 지연을 나타낸다. 관측 초기화·update·exit 실패는 no-op이며 업무 예외는 다시 던진다. 짧은 검증 스크립트는 종료 전 telemetry.flush()를 호출한다.

## 자동 검증

새 제품 가상환경에서 `python -m pytest backend/tests/test_agent.py -q` (PYTHONPATH=backend): **17 passed**.

검증 범위: 워크스페이스·상태·모델 분리, 근거 문자/개수 상한, 처리 중/후보 없음 구분, 무효 인용 제거와 서버 메타데이터·저장, 출력 재시도 2회 후 종료, 근거 부족 생성 생략, 공급자 장애 시 저장 안 함, 계측 실패와 업무 예외 보존, HTTP 인증/일시 장애 재시도 구분, deadline 소진, 목 벡터 결정성·DB 분리, 임베딩 차원 오류.

실제 GMS 호출·데모 PDF 답변 품질·원격 Langfuse trace는 통합 점검 담당자가 별도로 검증한다. 위 단위 테스트가 그 결과를 대신하지 않는다. 의미상 인용이 주장을 뒷받침하는지는 사람이 점검해야 한다.

후속 통합 확인을 마쳤다. 실제 GMS 답변·보류, trace 재조회 및 계측 보강, 완료 답변의 근거·점수·trace ID 저장 결과는 [통합 기록](day1-integration.md)을 따른다.

## 후속

2일차: 연결 노트 검색과 최소 1개 보장, 실제 재검색 최대 1회, 데모 질문셋으로 MIN_SCORE/RELATIVE_MARGIN 보정. 동기 HTTP에서 엄격한 wall-clock deadline이 필요하면 실행 경계를 추가한다.

참고: [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api), [Langfuse 직접 계측](https://langfuse.com/docs/observability/sdk/instrumentation). SDK 버전은 루트 의존성 잠금 파일을 기준으로 한다.
