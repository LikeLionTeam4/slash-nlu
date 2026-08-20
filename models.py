from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class Decision(str, Enum):
    TASK = "TASK"
    CLARIFY = "CLARIFY"
    UNSUPPORTED = "UNSUPPORTED"


class TaskType(str, Enum):
    FILE_SEARCH = "FILE_SEARCH"
    FILE_OPEN = "FILE_OPEN"
    SYSTEM_STATUS = "SYSTEM_STATUS"
    WEATHER_LOOKUP = "WEATHER_LOOKUP"
    TEXT_SUMMARY = "TEXT_SUMMARY"
    CODE_ANALYSIS = "CODE_ANALYSIS"
    AI_AGENT_USAGE = "AI_AGENT_USAGE"


class AnalyzerType(str, Enum):
    SLASH = "SLASH"
    RULE_KIWI = "RULE_KIWI"


class HealthResponse(BaseModel):
    status: Literal["UP", "NOT_READY"]
    analyzerReady: bool


class CommandInput(BaseModel):
    path: List[str] = Field(min_length=1)
    operands: List[str] = Field(default_factory=list)

    @field_validator("path")
    @classmethod
    def path_segments_must_not_be_blank(cls, value: List[str]) -> List[str]:
        if any(not segment.strip() for segment in value):
            raise ValueError("command.path must not contain blank segments")
        return value


class AnalyzeRequest(BaseModel):
    requestId: str = Field(min_length=1)
    text: Optional[str] = None
    command: Optional[CommandInput] = None
    now: Optional[datetime] = None

    @field_validator("requestId")
    @classmethod
    def request_id_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("requestId must not be blank")
        return value

    @field_validator("now")
    @classmethod
    def now_must_include_offset(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("now must include a UTC offset")
        return value


class AnalyzeResponse(BaseModel):
    requestId: str
    decision: Decision
    taskType: Optional[TaskType]
    parameters: Dict[str, Any] = Field(default_factory=dict)
    missingRequiredParameters: List[str] = Field(default_factory=list)
    question: Optional[str]
    confidence: float = Field(ge=0.0, le=1.0)
    analyzer: AnalyzerType


class ExtractiveSummaryRequest(BaseModel):
    requestId: str = Field(min_length=1)
    taskId: str = Field(min_length=1)
    text: str

    @field_validator("requestId", "taskId")
    @classmethod
    def trace_ids_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("trace identifiers must not be blank")
        return value


class ExtractiveSummaryResponse(BaseModel):
    requestId: str
    taskId: str
    summary: str
    engine: Literal["EXTRACTIVE"]
    algorithm: Literal["TFIDF_CENTROID"]
    algorithmVersion: Literal["1"]
    inputSentenceCount: int = Field(ge=1)
    outputSentenceCount: int = Field(ge=1, le=3)
    durationMs: int = Field(ge=0)


class SummaryErrorDetail(BaseModel):
    code: str
    message: str
    retryable: bool


class SummaryErrorResponse(BaseModel):
    error: SummaryErrorDetail
    requestId: str
    taskId: str
