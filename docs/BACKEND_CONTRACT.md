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
