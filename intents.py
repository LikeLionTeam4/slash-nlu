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
    TaskType.FILE_SEARCH: IntentDefinition(TaskType.FILE_SEARCH, ("query",), "어떤 파일을 찾을까요?"),
    TaskType.SYSTEM_STATUS: IntentDefinition(TaskType.SYSTEM_STATUS, (), ""),
    TaskType.WEATHER_LOOKUP: IntentDefinition(TaskType.WEATHER_LOOKUP, ("location",), "어느 지역의 날씨를 확인할까요?"),
    TaskType.TEXT_SUMMARY: IntentDefinition(
        TaskType.TEXT_SUMMARY,
        ("text",),
        f"요약할 내용을 {SUMMARY_MIN_CHARS}자 이상 입력해 주세요.",
    ),
}


SLASH_ALIASES: Dict[str, TaskType] = {
    "파일": TaskType.FILE_SEARCH,
    "file": TaskType.FILE_SEARCH,
    "상태": TaskType.SYSTEM_STATUS,
    "status": TaskType.SYSTEM_STATUS,
    "status_com": TaskType.SYSTEM_STATUS,
    "날씨": TaskType.WEATHER_LOOKUP,
    "weather": TaskType.WEATHER_LOOKUP,
    "요약": TaskType.TEXT_SUMMARY,
    "summary": TaskType.TEXT_SUMMARY,
}
