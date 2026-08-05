from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request, status

from analyzer import NluAnalyzer
from models import AnalyzeRequest, AnalyzeResponse


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.analyzer = NluAnalyzer()
    yield


app = FastAPI(title="Slash NLU", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health(request: Request) -> dict:
    return {"status": "UP", "analyzerReady": hasattr(request.app.state, "analyzer")}


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
