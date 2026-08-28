"""slash-nlu HTTP 진입점 — 분석·추출 요약 내부 API.

`slash-api`만 호출하는 내부 서비스다. 사용자에게 직접 열리지 않으며 클러스터 안에서만
접근한다(경로가 `/internal/`로 시작하는 이유).

제공하는 것
    ``GET  /health``                              프로세스 생존 + 분석기 준비 여부
    ``GET  /ready``                               준비 전이면 503 — Kubernetes readiness용
    ``POST /internal/v1/nlu/analyze``             입력을 작업 유형·인자로 분석
    ``POST /internal/v1/nlu/summaries/extractive`` CPU 추출 요약

**분석기는 요청마다 만들지 않고 기동 시 한 번 만든다**(``lifespan``). Kiwi 형태소
분석기 로딩이 무거워 매 요청 생성하면 응답이 크게 느려진다. 요약기도 같은 Kiwi
인스턴스를 넘겨받아 문장 분리에 재사용한다.

``/health``와 ``/ready``를 가른 이유는, 프로세스가 살아 있는 것과 요청을 처리할 수
있는 것이 다르기 때문이다. Kiwi 로딩이 끝나기 전에도 프로세스는 응답하므로,
``/health``만 보면 준비 전 Pod로 트래픽이 흘러 첫 요청이 지연된다.
"""


from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from analyzer import NluAnalyzer
from models import (
    AnalyzeRequest,
    AnalyzeResponse,
    ExtractiveSummaryRequest,
    ExtractiveSummaryResponse,
    HealthResponse,
    SummaryErrorDetail,
    SummaryErrorResponse,
)
from summary import ExtractiveSummarizer, SummaryInputError


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """기동 시 분석기·요약기를 한 번 만들어 앱 상태에 둔다.

    Kiwi 로딩 비용 때문에 요청마다 생성하지 않는다. 요약기는 분석기가 이미 만든
    Kiwi를 넘겨받아 같은 인스턴스를 공유한다.
    """
    app.state.analyzer = NluAnalyzer()
    app.state.summarizer = ExtractiveSummarizer(app.state.analyzer.kiwi)
    yield


app = FastAPI(title="Slash NLU", version="1.0.0", lifespan=lifespan)


def analyzer_is_ready(request: Request) -> bool:
    """분석기 준비 여부. `lifespan`이 끝나기 전에는 앱 상태에 아직 없다."""
    return getattr(request.app.state, "analyzer", None) is not None


@app.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    # 프로세스 생존 확인. 준비 여부와 무관하게 항상 `UP`을 반환한다.
    #
    # Kubernetes liveness·startup probe가 쓴다 — 여기서 실패를 내면 준비 중인
    # Pod가 반복해서 재시작된다.
    return HealthResponse(status="UP", analyzerReady=analyzer_is_ready(request))


@app.get(
    "/ready",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "Analyzer 준비 안 됨"}},
)
async def ready(request: Request):
    # 요청을 처리할 수 있는지 확인. 분석기가 없으면 503을 반환한다.
    #
    # Kubernetes readiness probe가 쓴다 — 준비 전 Pod를 서비스 대상에서 빼기 위한 것이다.
    if not analyzer_is_ready(request):
        body = HealthResponse(status="NOT_READY", analyzerReady=False)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=body.model_dump(),
        )
    return HealthResponse(status="UP", analyzerReady=True)


@app.post("/internal/v1/nlu/analyze", response_model=AnalyzeResponse)
async def analyze(payload: AnalyzeRequest, request: Request) -> AnalyzeResponse:
    # 사용자 입력을 작업 유형과 인자로 분석한다.
    #
    # `text`(자연어)와 `command`(슬래시) 중 **정확히 하나**만 받는다. 둘 다 오거나
    # 둘 다 없으면 400이다 — 어느 쪽으로 분석할지 서버가 임의로 정하면 같은 요청이
    # 호출 시점에 따라 다르게 분류될 수 있다.
    #
    # `now`가 없으면 현재 시각을 쓴다. "오늘"·"내일" 같은 상대 날짜 해석에 쓰인다.
    #
    # 분석 중 예외는 500으로 감싼다 — 내부 예외 메시지를 그대로 노출하지 않는다.
    has_text = payload.text is not None
    has_command = payload.command is not None
    if has_text == has_command:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Exactly one of text or command must be provided")
    if has_text and not payload.text.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="text must not be blank")

    now = payload.now or datetime.now(timezone.utc)
    try:
        analyzer: NluAnalyzer = request.app.state.analyzer
        if payload.command is not None:
            return analyzer.analyze_slash(payload.requestId, payload.command, now)
        return analyzer.analyze_text(payload.requestId, payload.text, now)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="NLU analysis failed") from exc


def summary_error(payload: ExtractiveSummaryRequest, error: SummaryInputError) -> JSONResponse:
    """요약 입력 오류를 계약 형식의 400 응답으로 바꾼다.

    `retryable`을 거짓으로 고정하는 이유는, 입력이 짧거나 요약 불가한 형태여서
    실패한 것이라 같은 입력을 다시 보내도 결과가 같기 때문이다.
    """
    body = SummaryErrorResponse(
        error=SummaryErrorDetail(code=error.code, message=error.message, retryable=False),
        requestId=payload.requestId,
        taskId=payload.taskId,
    )
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=body.model_dump())


@app.post(
    "/internal/v1/nlu/summaries/extractive",
    response_model=ExtractiveSummaryResponse,
    responses={400: {"model": SummaryErrorResponse, "description": "요약할 수 없는 입력"}},
)
async def summarize_extractive(payload: ExtractiveSummaryRequest, request: Request):
    # 원문에서 중요한 문장을 골라 요약한다. 문장을 새로 만들지 않는다.
    #
    # GPU 없이 도는 경로다. 클라우드 LLM 제거(`slash-docs#3`) 이후 `/summary`의
    # 서버 실행이 이쪽으로 바뀌었다.
    #
    # 입력 오류(150자 미만 등)는 400에 오류 코드를 실어 돌려주고, 그 밖의 실패만
    # 500으로 처리한다 — 사용자가 고칠 수 있는 문제와 서버 문제를 구분하기 위한 것이다.
    try:
        summarizer: ExtractiveSummarizer = request.app.state.summarizer
        return summarizer.summarize(payload.requestId, payload.taskId, payload.text)
    except SummaryInputError as exc:
        return summary_error(payload, exc)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Extractive summary failed",
        ) from exc
