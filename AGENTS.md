# slash-nlu agent guide

이 저장소에서 작업하는 메인·서브 에이전트용 지침이다. 수정 범위는 `slash-nlu`로 제한한다.

## 작업 범위

### 이 저장소가 담당한다

- FastAPI 기반 NLU 내부 서비스
- Slash 명령 정규화
- 규칙·Kiwi 기반 자연어 분류
- TaskType 후보와 파라미터 추출
- 필수 파라미터 누락 판정
- NLU 단위 테스트와 계약 fixture

### 이 저장소가 담당하지 않는다

- Task 실행 위치 결정
- Task 상태 저장과 상태 전이
- 로컬 PC 작업 실행
- Ollama/Gemma 텍스트 생성
- Web UI와 명령 자동완성
- 공통 DB·인프라 변경

`slash-api`, `slash-agent`, `slash-web`, `slash-docs`, `slash-infra`는 읽기 전용 참고 대상이다. 사용자 요청 없이 수정하지 않는다.

## 현재 상태

- FastAPI `GET /health`, `POST /internal/v1/nlu/analyze`가 구현돼 있다.
- Pydantic 요청·응답 모델과 P0 TaskType/Slash 별칭이 정의돼 있다.
- 규칙·Kiwi 분석 파이프라인과 계약 fixture·자동 테스트가 있다.
- `slash-docs/api/*.md`와 노션 문서는 설계 예시이며 확정 계약이 아니다.
- API Java enum, Agent TypeScript enum, Web 명령 트리의 작업 목록이 서로 일치하지 않는다.

## 확정된 MVP 계약

| 항목 | 결정 |
|---|---|
| TaskType | `FILE_SEARCH`, `SYSTEM_STATUS`, `WEATHER_LOOKUP`, `TEXT_SUMMARY` |
| JSON enum | `decision`, `taskType`, `analyzer`는 wire에서 string이며 Pydantic `str, Enum`으로 검증 |
| DB 경계 | 저장 표현은 Backend 소유; 연동 기준은 `varchar + CHECK`, 값 추가는 Flyway migration 대상 |
| 사용자 Rate Limit | `slash-api` 소유; NLU는 사용자/IP별 횟수 제한을 구현하지 않음 |
| Slash 입력 | `command={path, operands}` 지원 |
| 자연어 입력 | `text` 지원; `text`와 `command` 중 정확히 하나 |
| NLU 응답 | `decision`, `taskType`, `parameters`, `missingRequiredParameters`, `question`, `confidence`, `analyzer` |
| 누락값 | `decision=CLARIFY`, taskType 유지, 누락 필드 목록 반환 |
| FILE_SEARCH | NLU는 `query`만 추출; `searchFolderId`는 생성·누락 판정하지 않음 |
| TEXT_SUMMARY | `text`가 공백 제거 후 150자 미만이면 `CLARIFY` |
| 미지원 입력 | 명백한 미지원은 `UNSUPPORTED`, 서비스 후보지만 값이 부족하면 `CLARIFY` |
| 라우팅 | `processingRoute`를 결정하거나 반환하지 않음 |

TaskType 추가, 필드명 변경, 일반 대화 fallback은 별도 결정 없이 구현하지 않는다.
NLU에서 DB enum이나 Flyway migration을 생성하지 않는다.

## 권장 내부 구조

초기 구현은 작게 유지한다.

```text
main.py              FastAPI app과 endpoint
models.py            요청·응답 Pydantic 모델
analyzer.py          Slash/rule/Kiwi 분석 파이프라인
intents.py           확정된 TaskType과 인자 규칙
tests/
  fixtures/          입력과 기대 JSON
  test_analyze.py
```

사용자가 실제로 두 파일만 허용하면 `main.py`와 `test_main.py`로 시작하고, 구조 분리는 기능이 안정된 뒤 제안한다.

## 분석 파이프라인 원칙

```text
Slash 또는 명시 규칙
  → Kiwi/키워드 규칙
  → 미지원 또는 clarification
```

- 앞 단계에서 확정되면 뒤 단계를 호출하지 않는다.
- `confidence`는 관측용이다. 실행 위치를 결정하는 값으로 사용하지 않는다.
- 라우팅은 API 소유이므로 NLU 응답에서 임의로 `processingRoute`를 결정하지 않는다.
- 상대 날짜 계산은 요청 기준 시각이 제공되면 그 값을 사용한다.
- 입력 원문, 토큰, 로컬 절대 경로를 불필요하게 로그에 남기지 않는다.

## 메인·서브 에이전트 분할

| 작업 | 담당 가능 |
|---|---|
| 요청·응답 계약과 fixture | 메인 에이전트 단독 |
| Slash 규칙 구현 | 서브 에이전트 |
| Kiwi 분석 구현 | 서브 에이전트 |
| Pydantic 검증·오류 처리 | 서브 에이전트 |
| 전체 fixture 통합 | 메인 에이전트 |

여러 에이전트가 TaskType 목록이나 응답 필드를 동시에 수정하지 않는다.

## 완료 기준

```text
[ ] 빈 입력과 잘못된 요청을 거부한다.
[ ] Slash fixture가 기대 TaskType과 파라미터를 반환한다.
[ ] 자연어 fixture가 기대 결과를 반환한다.
[ ] 누락값과 미지원 입력의 결과가 계약과 일치한다.
[ ] OpenAPI schema가 Pydantic 모델과 일치한다.
[ ] 모든 테스트가 통과한다.
```

권장 검증 명령은 `pytest`와 `python -m compileall .`이다. 의존성이 추가되면 `requirements.txt`에 버전을 고정한다.

## 인수인계 형식

```markdown
### 결과
완료 / 부분 완료 / 차단

### 변경 파일
- 경로와 변경 이유

### 검증
- 실행 명령과 결과

### 계약 가정
- 사용자가 확정한 내용만 기록

### 남은 결정
- 다른 저장소 변경이 필요한 내용
```
