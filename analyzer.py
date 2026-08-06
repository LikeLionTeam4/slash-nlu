import re
from datetime import datetime
from typing import Any, Dict, Iterable, List

from kiwipiepy import Kiwi

from intents import INTENTS, SLASH_ALIASES, SUMMARY_MIN_CHARS
from models import AnalyzeResponse, AnalyzerType, CommandInput, Decision, TaskType


_SPACE = re.compile(r"\s+")
_FILE_ACTIONS = re.compile(
    r"(?:파일(?:을|를)?\s*)?(?:찾아\s*줘|찾아줘|찾아|검색해\s*줘|검색해줘|검색|(?<!\w)(?:find|search))$",
    flags=re.IGNORECASE,
)
_FILE_EXTENSION = re.compile(r"\.(?:pdf|ppt)(?!\w)", flags=re.IGNORECASE)
_SUMMARY_ACTIONS = re.compile(r"(?:요약해\s*줘|요약해줘|요약해|요약)$")
_WEATHER_END = re.compile(r"(?:의\s*)?날씨(?:가|는|를|도)?(?:\s*(?:어때|알려\s*줘|알려줘|확인해\s*줘|확인해줘))?[?!.\s]*$")
_TEMPORAL_LOCATION_WORDS = {"오늘", "내일", "현재", "지금", "이번주", "이번 주"}
_SUMMARY_MAX_INPUT_CHARS = 8000


class NluAnalyzer:
    """Deterministic MVP analyzer. Kiwi is constructed once per app instance."""

    def __init__(self) -> None:
        self.kiwi = Kiwi()

    def analyze_slash(self, request_id: str, command: CommandInput, now: datetime) -> AnalyzeResponse:
        alias = "/".join(part.strip().lstrip("/").lower() for part in command.path)
        task_type = SLASH_ALIASES.get(alias)
        if task_type is None:
            return self._unsupported(request_id, AnalyzerType.SLASH, 1.0)

        values = [value.strip() for value in command.operands if value.strip()]
        parameters: Dict[str, Any] = {}
        if task_type == TaskType.FILE_SEARCH and values:
            parameters.update(self._file_parameters(" ".join(values), now))
        elif task_type == TaskType.WEATHER_LOOKUP and values:
            parameters["location"] = " ".join(values)
        elif task_type == TaskType.TEXT_SUMMARY and values:
            parameters["text"] = "\n".join(values)

        return self._task_or_clarify(request_id, task_type, parameters, AnalyzerType.SLASH, 1.0)

    def analyze_text(self, request_id: str, text: str, now: datetime) -> AnalyzeResponse:
        normalized = _SPACE.sub(" ", text.strip())
        surfaces = {token.form.lower() for token in self.kiwi.tokenize(normalized)}
        lowered = normalized.lower()

        if self._has_file_subject(normalized, surfaces) and self._has_file_action(surfaces):
            return self._task_or_clarify(request_id, TaskType.FILE_SEARCH, self._file_parameters(normalized, now), AnalyzerType.RULE_KIWI, 0.88)
        if self._has_any(lowered, surfaces, ("요약", "summary")):
            summary_text = self._extract_summary_text(text.strip())
            return self._task_or_clarify(request_id, TaskType.TEXT_SUMMARY, {"text": summary_text} if summary_text else {}, AnalyzerType.RULE_KIWI, 0.92)
        if self._has_any(lowered, surfaces, ("날씨", "기온", "weather")):
            location = self._extract_location(normalized)
            return self._task_or_clarify(request_id, TaskType.WEATHER_LOOKUP, {"location": location} if location else {}, AnalyzerType.RULE_KIWI, 0.90)
        if self._is_system_status(lowered, surfaces):
            return self._task_or_clarify(request_id, TaskType.SYSTEM_STATUS, {}, AnalyzerType.RULE_KIWI, 0.90)
        if self._has_file_subject(normalized, surfaces):
            return self._task_or_clarify(request_id, TaskType.FILE_SEARCH, {}, AnalyzerType.RULE_KIWI, 0.55)
        return self._unsupported(request_id, AnalyzerType.RULE_KIWI, 0.0)

    @staticmethod
    def _has_any(text: str, surfaces: Iterable[str], candidates: Iterable[str]) -> bool:
        return any(candidate in text or candidate in surfaces for candidate in candidates)

    @staticmethod
    def _has_file_subject(text: str, surfaces: Iterable[str]) -> bool:
        file_words = ("파일", "문서", "회의록", "견적서", "보고서", "자료", "ppt", "pdf", "file")
        return any(word in surfaces for word in file_words) or _FILE_EXTENSION.search(text) is not None

    @staticmethod
    def _has_file_action(surfaces: Iterable[str]) -> bool:
        return any(word in surfaces for word in ("찾", "검색", "find", "search"))

    @staticmethod
    def _is_system_status(text: str, surfaces: Iterable[str]) -> bool:
        status_words = ("상태", "cpu", "메모리", "memory", "디스크", "disk")
        system_words = ("시스템", "컴퓨터", "pc", "노트북")
        return (any(word in text or word in surfaces for word in status_words) and any(word in text or word in surfaces for word in system_words)) or text in {"상태 알려줘", "시스템 상태", "status", "system status"}

    @staticmethod
    def _extract_summary_text(text: str) -> str:
        if ":" in text:
            before, after = text.split(":", 1)
            if "요약" in before or "summary" in before.lower():
                return after.strip()
        cleaned = _SUMMARY_ACTIONS.sub("", text).strip()
        cleaned = re.sub(r"^(?:요약|summary)\s*(?:해\s*줘)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^(?:이\s*(?:글|내용|문서)(?:을|를)?\s*)", "", cleaned).strip()
        return cleaned

    @staticmethod
    def _extract_location(text: str) -> str:
        cleaned = _WEATHER_END.sub("", text).strip()
        cleaned = re.sub(r"^(?:날씨|weather)\s*", "", cleaned, flags=re.IGNORECASE).strip()
        return " ".join(word for word in cleaned.split() if word not in _TEMPORAL_LOCATION_WORDS).strip(" ,")

    @staticmethod
    def _file_parameters(text: str, now: datetime) -> Dict[str, Any]:
        parameters: Dict[str, Any] = {}
        query = text.strip()
        if "작년" in query:
            year = now.year - 1
            parameters.update(after=f"{year:04d}-01-01", before=f"{year:04d}-12-31")
            query = query.replace("작년", " ")
        query = _FILE_ACTIONS.sub("", query).strip()
        query = re.sub(r"^(?:파일(?:을|를)?|file)(?:\s+|$)", "", query, flags=re.IGNORECASE).strip()
        query = _SPACE.sub(" ", query)
        if query:
            parameters["query"] = query
        return parameters

    @staticmethod
    def _task_or_clarify(request_id: str, task_type: TaskType, parameters: Dict[str, Any], analyzer: AnalyzerType, confidence: float) -> AnalyzeResponse:
        definition = INTENTS[task_type]
        missing = [name for name in definition.required_parameters if name not in parameters or parameters[name] in (None, "", [])]
        if task_type == TaskType.TEXT_SUMMARY:
            summary_text = str(parameters.get("text", "")).strip()
            summary_window = summary_text[:_SUMMARY_MAX_INPUT_CHARS]
            if len(_SPACE.sub("", summary_window)) < SUMMARY_MIN_CHARS and "text" not in missing:
                missing.append("text")
        return AnalyzeResponse(requestId=request_id, decision=Decision.CLARIFY if missing else Decision.TASK, taskType=task_type, parameters=parameters, missingRequiredParameters=missing, question=definition.question if missing else None, confidence=confidence, analyzer=analyzer)

    @staticmethod
    def _unsupported(request_id: str, analyzer: AnalyzerType, confidence: float) -> AnalyzeResponse:
        return AnalyzeResponse(requestId=request_id, decision=Decision.UNSUPPORTED, taskType=None, parameters={}, missingRequiredParameters=[], question=None, confidence=confidence, analyzer=analyzer)
