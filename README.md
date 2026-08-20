# Slash | 자연어 분석

Slash(/)는 자연어 질문과 `/` 슬래시 명령어를 한 입력창에서 처리하는 AI 에이전트 서비스입니다.
이 저장소는 그중 **자연어 분석(NLU)** 파트를 담당합니다.

## 역할

- slash 명령 파싱
- 규칙 기반 + [Kiwi](https://github.com/bab2min/Kiwi) 형태소 분석 기반 의도(intent) 분류
- 인자(argument) 추출

## 시작하기

Python 3.9 이상이 필요합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8001
```

프로세스 상태 확인은 `GET /health`, analyzer 준비 확인은 `GET /ready`, 분석은
`POST /internal/v1/nlu/analyze`를 사용합니다. CPU 추출 요약은
`POST /internal/v1/nlu/summaries/extractive`를 사용합니다. Kubernetes에서는 `/health`를
liveness/startup, `/ready`를 readiness probe로 사용합니다.
API 상세 스키마는 실행 후 `/docs` 또는 `/openapi.json`에서 확인할 수 있습니다.
Backend 연동 경계는 [`docs/BACKEND_CONTRACT.md`](docs/BACKEND_CONTRACT.md)에 정리돼 있습니다.

### 컨테이너 실행

```bash
docker build -t slash-nlu:local .
docker run --rm -p 8001:8001 slash-nlu:local
curl http://localhost:8001/health
```

컨테이너는 비루트 사용자로 실행되고 `8001` 포트만 사용합니다. `dev` 또는 `main`
브랜치에 반영되면 GitHub Actions가 `sha-<commit>` 태그로 ECR에 이미지를 게시합니다.
동일 커밋의 이미지가 이미 있으면 immutable 태그를 다시 게시하지 않고 성공 처리합니다.
실제 dev 배포에는 `slash-infra`의 `values-dev.yaml` 이미지 태그 갱신이 별도로 필요합니다.
현재 Helm 기준 Kubernetes Service는 `80`에서 컨테이너 `8001`로 전달하므로, 같은
namespace의 Backend에는 `NLU_BASE_URL=http://slash-nlu`를 주입합니다.

## MVP 계약

- `text` 또는 `command={path, operands}` 중 정확히 하나를 전달합니다.
- 지원 작업은 `FILE_SEARCH`, `FILE_OPEN`, `SYSTEM_STATUS`, `WEATHER_LOOKUP`,
  `TEXT_SUMMARY`, `CODE_ANALYSIS`, `AI_AGENT_USAGE`입니다.
- `decision`, `taskType`, `analyzer`는 JSON에서 문자열로 직렬화되는 **string enum**입니다.
- DB 저장 방식은 Backend 소유입니다. 현재 연동 기준은 `varchar + CHECK`이며 값 추가 시 Flyway migration으로 제약조건을 갱신합니다.
- 사용자/IP별 요청 횟수 제한과 `429 RATE_LIMITED` 응답은 인증 정보를 가진 Backend가 담당합니다.
- NLU는 실행 위치(`processingRoute`)를 결정하거나 반환하지 않습니다.
- `FILE_SEARCH.searchFolderId`는 Backend가 보완하며 NLU의 누락 판정 대상이 아닙니다.
- `FILE_OPEN.fileRef`는 검색 결과에서 받은 불투명한 한 토큰을 변형 없이 전달합니다.
- `TEXT_SUMMARY.text`는 LLM 입력 정책과 동일하게 공백 제거 후 150자 이상이어야 합니다.
- `CODE_ANALYSIS`는 NLU가 `query`만 추출하고 Backend가 `workspaceId`를 보완합니다.
- `AI_AGENT_USAGE.provider`는 `CLAUDE_CODE` 또는 `CODEX`로 정규화합니다.
- `FILE_OPEN`, `CODE_ANALYSIS`, `AI_AGENT_USAGE`는 명시적인 Slash 입력에서만 판정합니다.
- 자연어 분석 순서는 명시 규칙 → Kiwi/키워드 → fallback입니다.

## CPU 추출 요약

GPU 모델을 호출하지 않고 문서의 중요 문장을 최대 3개까지 고르는 내부 API입니다.
Kiwi로 문장을 나누고 TF-IDF 중심도 점수를 계산한 뒤, 선택된 문장을 원문 순서로
반환합니다. 실행 위치 선택과 Task 상태 관리는 계속 Backend가 담당합니다.
정확한 연동 형식은 [`docs/EXTRACTIVE_SUMMARY_CONTRACT.md`](docs/EXTRACTIVE_SUMMARY_CONTRACT.md)를
기준으로 합니다.

```bash
curl -X POST http://localhost:8001/internal/v1/nlu/summaries/extractive \
  -H 'Content-Type: application/json' \
  -d '{"requestId":"request-1","taskId":"task-1","text":"공백 제외 150자 이상의 요약 대상 문서"}'
```

- 공백 제외 150자 미만: `INPUT_TOO_SHORT`
- 8000자 초과: `INPUT_TOO_LONG`
- 반복 문자 또는 의미 있는 문장이 부족한 입력: `INPUT_NOT_SUMMARIZABLE`
- 입력 오류는 재시도하지 않는 `400` 오류로 반환합니다.

## 구조

```text
main.py              FastAPI app과 endpoint
models.py            요청·응답 모델
intents.py           TaskType과 필수 파라미터
analyzer.py          Slash 및 Kiwi 분석 파이프라인
summary.py           CPU 추출 요약과 입력 품질 판정
tests/fixtures/      계약 fixture
tests/test_main.py   단위·계약 테스트
tests/test_summary.py CPU 추출 요약 계약 테스트
```

## 테스트

```bash
python -m compileall .
pytest
```

### 팀 통합 스모크 테스트

`slash-nlu`와 sibling `slash-llm` 저장소를 나란히 둔 환경에서는 LLM 저장소의
데모 스크립트로 NLU → LLM 요약 계약을 확인할 수 있습니다.

```bash
cd ../slash-llm
.venv/bin/python scripts/team_demo.py
```

기본 실행은 fake Ollama를 사용합니다. 실제 로컬 모델까지 확인하려면 Ollama를
준비한 뒤 `--real-ollama`를 추가합니다. 이 스모크 테스트는 NLU와 LLM 사이의
직접 연결만 확인하며 Backend와 Agent를 포함한 전체 E2E 테스트가 아닙니다.

## 관련 저장소

| 저장소 | 역할 |
|---|---|
| [slash-web](https://github.com/LikeLionTeam4/slash-web) | 웹 클라이언트 — React·Vite UI, S3/CloudFront 배포 |
| [slash-api](https://github.com/LikeLionTeam4/slash-api) | 코어 API — 인증, 작업 관리, 실행 위치 결정, DB 연동 |
| **slash-nlu** (현재) | 자연어 분석 — slash 명령 파싱, 규칙·Kiwi 의도 분류, 인자 추출 |
| [slash-llm](https://github.com/LikeLionTeam4/slash-llm) | LLM 서비스 — Gemma 추론, 요약·대화 생성 |
| [slash-runner](https://github.com/LikeLionTeam4/slash-runner) | PC 작업 실행기 — PC 파일 검색, 상태 조회, 로컬 AI 실행·결과 전달 |
| [slash-infra](https://github.com/LikeLionTeam4/slash-infra) | 인프라 — Terraform(AWS), Helm·ArgoCD 배포 |
| [slash-docs](https://github.com/LikeLionTeam4/slash-docs) | 프로젝트 문서 — 아키텍처, API 계약, ERD, 회의록 |
