from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from analyzer import NluAnalyzer
from models import AnalyzeRequest, AnalyzeResponse, HealthResponse


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.analyzer = NluAnalyzer()
    yield


app = FastAPI(title="Slash NLU", version="1.0.0", lifespan=lifespan)


def analyzer_is_ready(request: Request) -> bool:
    return getattr(request.app.state, "analyzer", None) is not None


@app.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    return HealthResponse(status="UP", analyzerReady=analyzer_is_ready(request))


@app.get(
    "/ready",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "Analyzer 준비 안 됨"}},
)
async def ready(request: Request):
    if not analyzer_is_ready(request):
        body = HealthResponse(status="NOT_READY", analyzerReady=False)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=body.model_dump(),
        )
    return HealthResponse(status="UP", analyzerReady=True)


@app.post("/internal/v1/nlu/analyze", response_model=AnalyzeResponse)
async def analyze(payload: AnalyzeRequest, request: Request) -> AnalyzeResponse:
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
