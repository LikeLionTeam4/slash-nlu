# Backend 연동 계약

`slash-api`의 2026-08-06 `dev`를 기준으로 한 내부 연동 경계다. 공개 API의
`{data, meta}`·`{error, meta}` envelope와 Task 상태 저장은 Backend가 담당한다.

## 호출

| 항목 | 값 |
|---|---|
| Endpoint | `POST /internal/v1/nlu/analyze` |
| 로컬 주소 | `http://localhost:8001/internal/v1/nlu/analyze` |
| Backend 설정 | `NLU_BASE_URL=http://localhost:8001` |
| Backend timeout | 전체 2초, 자동 재시도 없음 |
| 본문 | `requestId`와 `text` 또는 `command` 중 하나 |

운영에서는 Service가 FastAPI targetPort로 변환하므로 포트를 코드에 고정하지 않는다.
Kiwi는 애플리케이션 시작 시 한 번 생성하고, Backend timeout은 warm 요청을 기준으로
검증한다.

## 결과 매핑

| NLU `decision` | Backend 권장 처리 |
|---|---|
| `TASK` | `taskType` 검증 후 Backend가 `processingRoute` 결정 |
| `CLARIFY` | Task를 `NEEDS_CLARIFICATION`으로 전이하고 `question` 표시 |
| `UNSUPPORTED` | 실행하지 않고 Backend의 미지원 요청 오류로 정규화 |

NLU 응답은 평탄 JSON이다. Backend가 공개 응답 envelope와 Task 이벤트로 변환한다.

## 소유권

| 값 | 소유자 |
|---|---|
| `taskType`, 의미 파라미터, 누락값 | NLU |
| `processingRoute`, Task 상태, 공개 envelope | Backend |
| `selectedDeviceId`, `searchFolderId` | Backend/Agent |
| 사용자/IP Rate Limit | Backend |

`FILE_SEARCH`에서 NLU는 `query`와 자연어에서 명시된 날짜 범위만 반환한다.
`searchFolderId`는 Agent의 `READY.searchFolders`를 바탕으로 Backend가 주입하며,
NLU의 `parameters` 또는 `missingRequiredParameters`에 포함하지 않는다.

## 지원 범위

P0는 `FILE_SEARCH`, `SYSTEM_STATUS`, `WEATHER_LOOKUP`, `TEXT_SUMMARY` 네 가지다.
검증 전용 PR의 `COMMAND`와 향후 후보인 `WEB_SEARCH`, `GENERAL_CHAT`은 반환하지 않는다.

## 기존 초안과의 관계

`slash-docs/api/nlu.md`의 2026-08-03 문서는 팀 합의 전 초안이다. 현재 계약은
Backend `TaskType.p0Values()`와 NLU OpenAPI를 기준으로 하며, 초안 필드는 다음처럼
구체화했다.

| 기존 초안 | 현재 계약 | 이유 |
|---|---|---|
| `intent` | `decision` + `taskType` | 실행 후보와 `CLARIFY`·`UNSUPPORTED` 제어 결과를 분리 |
| `args` | `parameters` | Task 파라미터 명칭과 통일 |
| `matchedBy` | `analyzer` | 분석기 종류를 string enum으로 제한 |
| 없음 | `requestId` | 요청·응답 추적 ID 왕복 보존 |
| `args.question` | `missingRequiredParameters` + `question` | Backend가 누락값을 구조적으로 처리 가능 |

Backend P0는 `WEATHER_LOOKUP`, `FILE_SEARCH`, `SYSTEM_STATUS`, `TEXT_SUMMARY`이며
NLU도 이 네 값만 반환한다. Backend의 P1 `CODE_ANALYSIS`, `AI_AGENT_USAGE`는 이번
NLU 범위가 아니고, 공통 초안의 `WEATHER` 표기는 `WEATHER_LOOKUP`으로 정규화한다.

## TaskType 목록 계약 확인

Backend는 인증이 필요한 `GET /api/v1/task-types`로 P0와 P1 전체 목록을 반환한다.
NLU의 opt-in 계약 테스트는 `NLU_CONTRACT_BASE_URL`과 `NLU_CONTRACT_TOKEN`이 모두
설정된 경우에만 이 endpoint를 호출한다. 기본 단위 테스트는 실행 중인 Backend에
의존하지 않는다.

NLU는 `priority=P0`인 네 TaskType과 각 항목의 `nluRequiredParameters`만 비교한다.
`requiredParameters` 전체, `backendProvidedParameters`, `processingRoute`는 NLU 소유가
아니다. 특히 `FILE_SEARCH.searchFolderId`는 Backend가 채우는 값이며 NLU의
`parameters` 또는 `missingRequiredParameters`에 넣지 않는다. P1 목록은 NLU의 MVP
지원 범위를 결정하지 않는다.
