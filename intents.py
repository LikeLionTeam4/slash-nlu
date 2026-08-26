from dataclasses import dataclass
from typing import Dict, Tuple

from models import TaskType


SUMMARY_MIN_CHARS = 150


@dataclass(frozen=True)
class IntentDefinition:
    task_type: TaskType
    required_parameters: Tuple[str, ...]
    question: str


INTENTS: Dict[TaskType, IntentDefinition] = {
    TaskType.FILE_SEARCH: IntentDefinition(
        TaskType.FILE_SEARCH,
        ("query",),
        "어떤 파일을 찾을까요? 파일명이나 문서 종류를 입력해 주세요.",
    ),
    TaskType.FILE_OPEN: IntentDefinition(
        TaskType.FILE_OPEN,
        ("fileRef",),
        "열 파일을 검색 결과에서 선택해 주세요.",
    ),
    TaskType.SYSTEM_STATUS: IntentDefinition(TaskType.SYSTEM_STATUS, (), ""),
    TaskType.WEATHER_LOOKUP: IntentDefinition(
        TaskType.WEATHER_LOOKUP,
        ("location",),
        "어느 지역의 날씨를 확인할까요? 지역명을 입력해 주세요.",
    ),
    TaskType.TEXT_SUMMARY: IntentDefinition(
        TaskType.TEXT_SUMMARY,
        ("text",),
        f"요약할 내용을 공백 제외 {SUMMARY_MIN_CHARS}자 이상 입력해 주세요.",
    ),
    TaskType.CODE_ANALYSIS: IntentDefinition(
        TaskType.CODE_ANALYSIS,
        ("query",),
        "코드에서 무엇을 분석할까요? 분석할 내용을 입력해 주세요.",
    ),
    TaskType.AI_AGENT_USAGE: IntentDefinition(
        TaskType.AI_AGENT_USAGE,
        ("provider",),
        "Claude Code와 Codex 중 어떤 사용량을 확인할까요? 확인할 대상을 선택해 주세요.",
    ),
}


SLASH_ALIASES: Dict[str, TaskType] = {
    "파일": TaskType.FILE_SEARCH,
    "file": TaskType.FILE_SEARCH,
    "열기": TaskType.FILE_OPEN,
    "open": TaskType.FILE_OPEN,
    "상태": TaskType.SYSTEM_STATUS,
    "status": TaskType.SYSTEM_STATUS,
    "status_com": TaskType.SYSTEM_STATUS,
    "날씨": TaskType.WEATHER_LOOKUP,
    "weather": TaskType.WEATHER_LOOKUP,
    "요약": TaskType.TEXT_SUMMARY,
    "summary": TaskType.TEXT_SUMMARY,
    "코드": TaskType.CODE_ANALYSIS,
    "code": TaskType.CODE_ANALYSIS,
    "사용량": TaskType.AI_AGENT_USAGE,
    "usage": TaskType.AI_AGENT_USAGE,
}
