import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from kiwipiepy import Kiwi

from intents import INTENTS, SLASH_ALIASES, SUMMARY_MIN_CHARS
from models import AnalyzeResponse, AnalyzerType, CommandInput, Decision, TaskType


_SPACE = re.compile(r"\s+")
_FILE_EXTENSION = re.compile(r"\.(?:pdf|ppt)(?!\w)", flags=re.IGNORECASE)
_FILE_ACTION_FORMS = {"찾", "검색", "find", "search"}
_FILE_GENERIC_SUBJECTS = {"파일", "문서", "file"}
_DOCUMENT_NAME_ENDING = re.compile(r"(?:^|\s)[^\s]{2,}(?:안|서|록)$")
_QUOTATIVE_ENDING = re.compile(r"(?:이?라는|라고(?:\s*하는)?)$")
_SUMMARY_ACTIONS = re.compile(r"(?:요약해\s*줘|요약해줘|요약해|요약)$")
_WEATHER_REQUEST = r"(?:어때(?:요)?|알려\s*줘(?:요)?|알려줘(?:요)?|확인해\s*줘(?:요)?|확인해줘(?:요)?)"
_WEATHER_END = re.compile(
    r"(?:의\s*)?(?:날씨|기온|weather)(?:가|는|를|도|은)?"
    rf"(?:\s*{_WEATHER_REQUEST})?"
    r"[?!.\s]*$",
    flags=re.IGNORECASE,
)
_WEATHER_REQUEST_END = re.compile(
    rf"(?:\s*{_WEATHER_REQUEST})"
    r"[?!.\s]*$",
    flags=re.IGNORECASE,
)
_TEMPORAL_LOCATION_WORDS = {"오늘", "내일", "현재", "지금", "이번주", "이번 주"}
_SUMMARY_MAX_INPUT_CHARS = 8000
_USAGE_PROVIDER_ALIASES = {
    "claude": "CLAUDE_CODE",
    "claude code": "CLAUDE_CODE",
    "클로드": "CLAUDE_CODE",
    "클로드 코드": "CLAUDE_CODE",
    "codex": "CODEX",
    "코덱스": "CODEX",
    "코드엑스": "CODEX",
}


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
        elif task_type == TaskType.FILE_OPEN and len(values) == 1:
            # fileRef 는 PC 가 발급한 불투명한 한 토큰이다. 파일 검색어처럼 정리하지 않는다.
            parameters["fileRef"] = values[0]
        elif task_type == TaskType.WEATHER_LOOKUP and values:
            location = self._extract_location(" ".join(values))
            if location:
                parameters["location"] = location
        elif task_type == TaskType.TEXT_SUMMARY and values:
            # Backend는 자유 텍스트를 한 operand로 보내 내부 공백과 줄바꿈을 보존한다.
            # 예전처럼 단어별 operands가 들어와도 임의의 개행을 만들지 않도록 공백으로 잇는다.
            parameters["text"] = " ".join(values)
        elif task_type == TaskType.CODE_ANALYSIS and values:
            # workspaceId 는 등록된 작업 폴더 중에서 Backend 가 선택한다.
            parameters["query"] = " ".join(values)
        elif task_type == TaskType.AI_AGENT_USAGE and values:
            provider = self._usage_provider(" ".join(values))
            if provider:
                parameters["provider"] = provider

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
        if self._has_file_subject(normalized, surfaces) and self._has_any(
            lowered,
            surfaces,
            ("열", "실행", "open"),
        ):
            # FILE_OPEN은 검색 결과의 fileRef를 받는 내부 Slash 경로다. 자연어에서 파일명을
            # fileRef로 추측하거나 FILE_SEARCH로 잘못 되묻지 않는다.
            return self._unsupported(request_id, AnalyzerType.RULE_KIWI, 0.0)
        if self._has_file_subject(normalized, surfaces):
            return self._task_or_clarify(request_id, TaskType.FILE_SEARCH, {}, AnalyzerType.RULE_KIWI, 0.55)
        return self._unsupported(request_id, AnalyzerType.RULE_KIWI, 0.0)

    @staticmethod
    def _has_any(text: str, surfaces: Iterable[str], candidates: Iterable[str]) -> bool:
        return any(candidate in text or candidate in surfaces for candidate in candidates)

    def _has_file_subject(self, text: str, surfaces: Iterable[str]) -> bool:
        file_words = ("파일", "문서", "회의록", "견적서", "보고서", "자료", "ppt", "pdf", "file")
        if any(word in surfaces for word in file_words) or _FILE_EXTENSION.search(text) is not None:
            return True

        # 동작 표현만으로 FILE_SEARCH 를 확정하면 "파일럿 검색해줘", "맛집 찾아줘" 같은
        # 일반 검색까지 파일 검색으로 오인한다. 대신 흔한 문서명 접미사를 독립된 단서로 쓴다.
        # 낱말 전체 목록보다 넓게 예산안/기획안, 계약서/이력서/제안서 등을 포괄한다.
        candidate = self._extract_file_query(text)
        return _DOCUMENT_NAME_ENDING.search(candidate) is not None

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
        cleaned = re.sub(r"^(?:날씨|기온|weather)(?:은|는|를)?\s*", "", cleaned, flags=re.IGNORECASE).strip()
        # 키워드가 문장 앞에 오면 위의 _WEATHER_END가 요청 표현까지 제거하지 못한다.
        # 예: "weather 서울 알려줘"에서 "알려줘"가 지역명에 섞이지 않게 정리한다.
        cleaned = _WEATHER_REQUEST_END.sub("", cleaned).strip()
        return " ".join(word for word in cleaned.split() if word not in _TEMPORAL_LOCATION_WORDS).strip(" ,")

    @staticmethod
    def _usage_provider(text: str) -> Optional[str]:
        normalized = _SPACE.sub(" ", text.strip().lower().replace("_", " ").replace("-", " "))
        return _USAGE_PROVIDER_ALIASES.get(normalized)

    def _file_parameters(self, text: str, now: datetime) -> Dict[str, Any]:
        parameters: Dict[str, Any] = {}
        query = text.strip()
        if "작년" in query:
            year = now.year - 1
            parameters.update(after=f"{year:04d}-01-01", before=f"{year:04d}-12-31")
            query = query.replace("작년", " ")
        query = self._extract_file_query(query)
        if query:
            parameters["query"] = query
        return parameters

    def _extract_file_query(self, text: str) -> str:
        query = text.strip()
        action_start = self._file_action_start(query)
        if action_start is not None:
            query = query[:action_start].strip()

        query = self._strip_trailing_token(query, forms={"좀"})
        query = self._strip_trailing_particle(query)
        query = self._strip_trailing_token(query, forms=_FILE_GENERIC_SUBJECTS)
        query = _QUOTATIVE_ENDING.sub("", query).strip()
        query = self._strip_trailing_particle(query)
        query = re.sub(r"^(?:파일(?:을|를)?|file)(?:\s+|$)", "", query, flags=re.IGNORECASE).strip()
        return _SPACE.sub(" ", query)

    def _file_action_start(self, text: str) -> Optional[int]:
        for token in self.kiwi.tokenize(text):
            if token.form.lower() in _FILE_ACTION_FORMS:
                return token.start
        return None

    def _strip_trailing_token(self, text: str, forms: set[str]) -> str:
        tokens = self.kiwi.tokenize(text)
        if tokens and tokens[-1].form.lower() in forms:
            return text[:tokens[-1].start].strip()
        return text.strip()

    def _strip_trailing_particle(self, text: str) -> str:
        tokens = self.kiwi.tokenize(text)
        if tokens and tokens[-1].tag.startswith("J"):
            return text[:tokens[-1].start].strip()
        return text.strip()

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
