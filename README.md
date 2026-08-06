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

상태 확인은 `GET /health`, 분석은 `POST /internal/v1/nlu/analyze`를 사용합니다.
API 상세 스키마는 실행 후 `/docs` 또는 `/openapi.json`에서 확인할 수 있습니다.
Backend 연동 경계는 [`docs/BACKEND_CONTRACT.md`](docs/BACKEND_CONTRACT.md)에 정리돼 있습니다.

## MVP 계약

- `text` 또는 `command={path, operands}` 중 정확히 하나를 전달합니다.
- 지원 작업은 `FILE_SEARCH`, `SYSTEM_STATUS`, `WEATHER_LOOKUP`, `TEXT_SUMMARY`입니다.
- `decision`, `taskType`, `analyzer`는 JSON에서 문자열로 직렬화되는 **string enum**입니다.
- DB 저장 방식은 Backend 소유입니다. 현재 연동 기준은 `varchar + CHECK`이며 값 추가 시 Flyway migration으로 제약조건을 갱신합니다.
- 사용자/IP별 요청 횟수 제한과 `429 RATE_LIMITED` 응답은 인증 정보를 가진 Backend가 담당합니다.
- NLU는 실행 위치(`processingRoute`)를 결정하거나 반환하지 않습니다.
- `FILE_SEARCH.searchFolderId`는 Backend가 보완하며 NLU의 누락 판정 대상이 아닙니다.
- `TEXT_SUMMARY.text`는 LLM 입력 정책과 동일하게 공백 제거 후 150자 이상이어야 합니다.
- 자연어 분석 순서는 명시 규칙 → Kiwi/키워드 → fallback입니다.

## 구조

```text
main.py              FastAPI app과 endpoint
models.py            요청·응답 모델
intents.py           TaskType과 필수 파라미터
analyzer.py          Slash 및 Kiwi 분석 파이프라인
tests/fixtures/      계약 fixture
tests/test_main.py   단위·계약 테스트
```

## 테스트

```bash
python -m compileall .
pytest
```

## 관련 저장소

| 저장소 | 역할 |
|---|---|
| [slash-web](https://github.com/LikeLionTeam4/slash-web) | 웹 클라이언트 — React·Vite UI, S3/CloudFront 배포 |
| [slash-api](https://github.com/LikeLionTeam4/slash-api) | 코어 API — 인증, 작업 관리, 실행 위치 결정, DB 연동 |
| **slash-nlu** (현재) | 자연어 분석 — slash 명령 파싱, 규칙·Kiwi 의도 분류, 인자 추출 |
| [slash-llm](https://github.com/LikeLionTeam4/slash-llm) | LLM 서비스 — Gemma 추론, 요약·대화 생성 |
| [slash-agent](https://github.com/LikeLionTeam4/slash-agent) | 로컬 에이전트 — PC 파일 검색, 상태 조회, 로컬 AI 실행·결과 전달 |
| [slash-infra](https://github.com/LikeLionTeam4/slash-infra) | 인프라 — Terraform(AWS), Helm·ArgoCD 배포 |
| [slash-docs](https://github.com/LikeLionTeam4/slash-docs) | 프로젝트 문서 — 아키텍처, API 계약, ERD, 회의록 |
