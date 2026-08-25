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
| `workspaceId` | Backend/Agent |
| `fileRef` 발급·해석 | Agent |
| 사용자/IP Rate Limit | Backend |

`FILE_SEARCH`에서 NLU는 `query`와 자연어에서 명시된 날짜 범위만 반환한다.
`searchFolderId`는 Agent의 `READY.searchFolders`를 바탕으로 Backend가 주입하며,
NLU의 `parameters` 또는 `missingRequiredParameters`에 포함하지 않는다.

## 지원 범위

| TaskType | 우선순위 | NLU 필수 파라미터 | 입력 경로 |
|---|---|---|---|
| `FILE_SEARCH` | P0 | `query` | Slash·자연어 |
| `FILE_OPEN` | P0 | `fileRef` | Slash 전용 |
| `SYSTEM_STATUS` | P0 | 없음 | Slash·자연어 |
| `WEATHER_LOOKUP` | P0 | `location` | Slash·자연어 |
| `TEXT_SUMMARY` | P0 | `text` | Slash·자연어 |
| `CODE_ANALYSIS` | P0 | `query` | Slash 전용 |
| `AI_AGENT_USAGE` | P0 | `provider` | Slash 전용 |

`FILE_OPEN`의 `fileRef`는 검색 결과에서 받은 불투명한 한 토큰이며 NLU가 정규화하거나
내용을 검증하지 않는다. `CODE_ANALYSIS.workspaceId`는 등록된 작업 폴더 중 Backend가
선택하므로 NLU가 반환하거나 누락으로 보고하지 않는다. `AI_AGENT_USAGE.provider`는
`CLAUDE_CODE` 또는 `CODEX`로 정규화한다.

`TEXT_SUMMARY`의 최소 길이는 공백·탭·줄바꿈을 제외해 계산한다. 공백은 요약할
정보량을 늘리지 않으며, 공백을 반복해 최소 길이 검사를 우회하는 것을 막기 위한
기준이다. 길이 판정과 별개로 요약 대상 원문 내부의 공백과 줄바꿈은 보존한다.

검증 전용 PR의 `COMMAND`와 계약이 없는 `WEB_SEARCH`, `GENERAL_CHAT`은 반환하지 않는다.

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

공통 초안의 `WEATHER` 표기는 `WEATHER_LOOKUP`으로 정규화한다. `CODE_ANALYSIS`는
P0이지만 명시적인 Slash 입력만 분석하고 자연어에서 추측하지 않는다.

## CODE_ANALYSIS 계약

확정된 `CODE_ANALYSIS` 입력 계약은 아래와 같다.

| 필드 | 소유자 | 필수 여부 |
|---|---|---|
| `query` | NLU | 필수 |
| `workspaceId` | Backend/Agent | 필수 |
| `codeAdapter` | Backend/Agent | 선택 |

Backend `TaskType.CODE_ANALYSIS`는 `requiredParameters=[query, workspaceId]`,
`backendProvidedParameters=[workspaceId]`, `nluRequiredParameters=[query]`를 노출한다.
Backend의 `READY.projectWorkspaces` 저장·선택 경로는 slash-api#53에서 반영됐다.
설치된 Agent 트레이 앱이 프로젝트 폴더를 등록·보고하기 전에는 종단 실행이
`WORKSPACE_NOT_FOUND`로 끝날 수 있다.

## TaskType 목록 계약 확인

Backend는 인증이 필요한 `GET /api/v1/task-types`로 전체 TaskType 목록을 반환한다.
NLU CI는 공개 `slash-api` 저장소의 `dev`에서 이 목록의 원본인 `TaskType.java`를
읽기 전용으로 받아, 저장된 계약 fixture와 직접 대조한다. 로컬에서는 같은 fixture로
항상 계약 검사를 실행하므로 Backend 서버나 인증 토큰이 없어도 테스트가 skip되지 않는다.

NLU는 지원하는 TaskType 전체의 `priority`와 `nluRequiredParameters`를 비교한다.
`requiredParameters` 전체, `backendProvidedParameters`, `processingRoute`는 NLU 소유가
아니다. 특히 `FILE_SEARCH.searchFolderId`는 Backend가 채우는 값이며 NLU의
`parameters` 또는 `missingRequiredParameters`에 넣지 않는다. `CODE_ANALYSIS.workspaceId`도
같은 원칙을 적용한다.
