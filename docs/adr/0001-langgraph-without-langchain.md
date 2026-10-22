---
status: accepted
date: 2026-10-21
---

# 에이전트는 LangGraph로 구성하고 LangChain은 쓰지 않는다

질의응답·노트 초안·퀴즈 생성 흐름을 LangGraph `StateGraph`(상태·노드·조건부 엣지·`Send`)로 구성한다. 모델·임베딩 호출은 httpx로 직접 만든 GMS 어댑터(`generate_json`, `embed`)로 한다. 관측은 Langfuse SDK로 직접 계측한다. LangChain의 체인·LCEL·에이전트, `langchain_*` 모델 래퍼, 프롬프트 템플릿, 콜백 기반 Langfuse 연동, LangChain 채팅 모델을 전제로 하는 `langgraph.prebuilt`(`create_react_agent`, `ToolNode`)는 쓰지 않는다. 팀이 정한 기술 방향이며, 세 그래프가 고정 흐름이라 LangChain의 추상화는 얻는 것이 적다. 반면 GMS의 요청 규격, 구조화 출력 지원, 재시도 책임은 직접 쥐는 편이 디버깅과 Langfuse 계측에 유리하다.

## Considered Options

- **LangChain + LangGraph prebuilt 에이전트**: 코드가 가장 짧다. 하지만 GMS가 OpenAI 호환 규격을 어디까지 따르는지 확인되지 않았고, 재시도가 래퍼·그래프 두 곳에 나뉘며, 관측이 콜백에 묶인다.
- **프레임워크 없이 함수 조합**: 의존성이 가장 적다. 하지만 재검색·재생성·문항별 병렬 분기를 직접 제어 흐름으로 짜야 해서 상태와 종료 조건이 코드에 흩어진다.

## Consequences

- `langgraph`를 설치하면 `langchain-core`가 함께 설치된다. 그래도 애플리케이션 코드에서 `langchain*`를 직접 import하지 않는다. 1일차 체크리스트에서 확인한다.
- 노드는 상태를 받아 변경분 dict를 돌려주는 일반 함수다. LangChain 메시지·도구 객체를 쓰지 않으므로, LangChain 기반 예제를 그대로 옮겨 쓸 수 없다.
- 재시도 책임이 둘로 나뉜다. 통신 재시도는 어댑터가, 출력 재생성·재검색은 그래프가 맡는다. Langfuse span·generation 연결도 직접 구현한다.
- 나중에 도구 호출 루프형 에이전트로 바꾸려면 어댑터에 도구 호출 규격을 직접 추가해야 한다.

관련 문서: [구현기획서 v1.1 0절](../studylink-implementation-plan-v1.1.md), [아키텍처 3.1·6절](../studylink-architecture.md).
