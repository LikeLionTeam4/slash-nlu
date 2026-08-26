import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from kiwipiepy import Kiwi

from intents import INTENTS, SLASH_ALIASES, SUMMARY_MIN_CHARS
from models import AnalyzeResponse, AnalyzerType, CommandInput, Decision, TaskType


_SPACE = re.compile(r"\s+")
_FILE_EXTENSION = re.compile(r"\.(?:pdf|ppt)(?!\w)", flags=re.IGNORECASE)
_FILE_ACTION_FORMS = {"찾", "검색", "find", "search"}
_FILE_UNSUPPORTED_ACTION_FORMS = {"삭제", "지우", "만들", "생성", "delete", "remove", "create"}
_FILE_GENERIC_SUBJECTS = {"파일", "문서", "file"}
_DOCUMENT_NAME_ENDING = re.compile(r"(?:^|\s)[^\s]{2,}(?:안|서|록)$")
_QUOTATIVE_ENDING = re.compile(r"(?:이?라는|라고(?:\s*하는)?)$")
_SUMMARY_ACTIONS = re.compile(r"(?:요약해\s*줘|요약해줘|요약해|요약)$")
_WEATHER_REQUEST = (
    r"(?:어때(?:요)?|어떤가(?:요)?|궁금해(?:요)?|"
    r"알려\s*(?:줘(?:요)?|주세요|줄래(?:요)?|주시겠어요)|"
    r"확인해\s*(?:줘(?:요)?|주세요)|보여\s*(?:줘(?:요)?|주세요)|"
    r"말해\s*(?:줘(?:요)?|주세요)|부탁해(?:요)?)"
)
_WEATHER_END = re.compile(
    r"(?:의\s*)?(?:날씨|기온|온도|weather)(?:이|가|는|를|도|은)?"
    rf"(?:\s*좀)?(?:\s*{_WEATHER_REQUEST})?"
    r"[?!.\s]*$",
    flags=re.IGNORECASE,
)
_WEATHER_REQUEST_END = re.compile(
    rf"(?:\s*{_WEATHER_REQUEST})"
    r"[?!.\s]*$",
    flags=re.IGNORECASE,
)
_WEATHER_DETAIL_END = re.compile(
    r"(?:의\s*)?(?:"
    r"(?<![0-9A-Za-z가-힣])(?:비|눈)(?:이|가|은|는)?\s*(?:많이\s*)?(?:(?:안\s*)?"
    r"(?:와(?:요)?|오나요|옵니까|내려(?:요)?|내리나요)|"
    r"오고\s*있어(?:요)?|오는\s*중이야)|"
    r"체감\s*온도(?:이|가|은|는|을|를|도)?\s*몇\s*도(?:야|예요|인가요|입니까)?|"
    r"(?:강수량|습도|풍속|체감\s*온도)(?:이|가|은|는|을|를|도)?"
    rf"(?:\s*좀)?(?:\s*{_WEATHER_REQUEST})?|"
    r"바람(?:이|은|는|도)?\s*(?:많이\s*)?(?:불어(?:요)?|부나요|세(?:요)?|강해(?:요)?|"
    rf"{_WEATHER_REQUEST})|"
    r"몇\s*도(?:야|예요|인가요|입니까)?"
    r")[?!.\s]*$"
)
_WEATHER_DETAIL_PREFIX = re.compile(
    r"^(?:강수량|습도|풍속|체감\s*온도|바람)(?:이|가|은|는|을|를|도)?\s+"
)
_WEATHER_NUMERIC_DATE = re.compile(
    r"(?<!\d)(?:(?P<year>\d{4})[./-])?(?P<month>\d{1,2})[./-](?P<day>\d{1,2})(?!\d)"
)
_WEATHER_KOREAN_DATE = re.compile(
    r"(?:(?P<year>\d{4})년\s*)?(?P<month>\d{1,2})월\s*(?P<day>\d{1,2})일"
)
_WEATHER_UNSUPPORTED_TIME = re.compile(
    r"(?:^|\s)(?:어제|내일|모레|글피|지난\s*주|이번\s*주|다음\s*주말?|주말|"
    r"다음\s*(?:월|화|수|목|금|토|일)요일)(?:은|는|의|도)?"
    r"(?=\s|날씨|기온|온도|강수량|습도|풍속|체감\s*온도|바람|비|눈|$)"
)
_WEATHER_UNSUPPORTED_METRIC = re.compile(r"(?:최고|최저)\s*(?:기온|온도)")
_WEATHER_UNSUPPORTED_DETAIL = re.compile(
    r"(?:미세먼지|초미세먼지|자외선)|"
    r"(?<![0-9A-Za-z가-힣])(?:비|눈)(?:이|가|은|는)?\s*"
    r"(?:올까(?:요)?|오겠(?:어|어요|습니까)?|내릴까(?:요)?)"
)
_TEMPORAL_LOCATION_WORDS = {"오늘", "금일", "현재", "지금"}
_WEATHER_LOCATION_CONJUNCTIONS = {"와", "과", "랑", "이랑", "하고", "및"}
_WEATHER_PROVINCE_PREFIXES = {
    "경기",
    "경기도",
    "강원",
    "강원도",
    "강원특별자치도",
    "충북",
    "충청북도",
    "충남",
    "충청남도",
    "전북",
    "전라도",
    "전라북도",
    "전북특별자치도",
    "전남",
    "전라남도",
    "경북",
    "경상북도",
    "경남",
    "경상남도",
    "제주",
    "제주특별자치도",
}
_WEATHER_GYEONGGI_PREFIXES = {"경기", "경기도"}
_WEATHER_GWANGJU_METRO_PREFIXES = {
    "전라도",
    "전북",
    "전라북도",
    "전북특별자치도",
    "전남",
    "전라남도",
}
_WEATHER_COMPACT_LOCATION_ALIASES = {
    "경기광주": "경기도 광주",
    "경기도광주": "경기도 광주",
    "경기광주시": "광주시",
    "경기도광주시": "광주시",
    "전라도광주": "전라도 광주",
}
_WEATHER_TOP_LEVEL_LOCATIONS = {
    "서울",
    "부산",
    "대구",
    "인천",
    "광주",
    "대전",
    "울산",
    "세종",
    "제주",
    "경기",
    "경기도",
    "강원",
    "강원도",
    "충북",
    "충청북도",
    "충남",
    "충청남도",
    "전북",
    "전북특별자치도",
    "전남",
    "전라남도",
    "경북",
    "경상북도",
    "경남",
    "경상남도",
}
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
            weather_text, unsupported_date = self._strip_current_weather_date(" ".join(values), now)
            if unsupported_date:
                return self._unsupported(request_id, AnalyzerType.SLASH, 1.0)
            location = self._normalize_weather_location(self._extract_location(weather_text))
            if location and not self._has_multiple_locations(location):
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
        if self._is_weather_request(lowered, surfaces):
            weather_text, unsupported_date = self._strip_current_weather_date(normalized, now)
            if unsupported_date:
                return self._unsupported(request_id, AnalyzerType.RULE_KIWI, 0.0)
            location = self._normalize_weather_location(self._extract_location(weather_text))
            parameters = (
                {"location": location}
                if location and not self._has_multiple_locations(location)
                else {}
            )
            return self._task_or_clarify(request_id, TaskType.WEATHER_LOOKUP, parameters, AnalyzerType.RULE_KIWI, 0.90)
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
        if self._has_file_subject(normalized, surfaces) and any(
            action in surfaces for action in _FILE_UNSUPPORTED_ACTION_FORMS
        ):
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
        cleaned = _WEATHER_DETAIL_END.sub("", text).strip()
        cleaned = _WEATHER_END.sub("", cleaned).strip()
        cleaned = re.sub(
            r"^(?:날씨|기온|온도|weather)(?:이|가|은|는|를|도)?\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()
        cleaned = _WEATHER_DETAIL_PREFIX.sub("", cleaned).strip()
        # 키워드가 문장 앞에 오면 위의 _WEATHER_END가 요청 표현까지 제거하지 못한다.
        # 예: "weather 서울 알려줘"에서 "알려줘"가 지역명에 섞이지 않게 정리한다.
        cleaned = _WEATHER_REQUEST_END.sub("", cleaned).strip()
        return " ".join(word for word in cleaned.split() if word not in _TEMPORAL_LOCATION_WORDS).strip(" ,")

    @staticmethod
    def _is_weather_request(text: str, surfaces: set[str]) -> bool:
        return (
            any(word in surfaces for word in ("날씨", "기온", "온도", "weather"))
            or _WEATHER_DETAIL_END.search(text) is not None
            or (
                _WEATHER_DETAIL_PREFIX.search(text) is not None
                and _WEATHER_REQUEST_END.search(text) is not None
            )
        )

    @staticmethod
    def _strip_current_weather_date(text: str, now: datetime) -> tuple[str, bool]:
        unsupported_date = bool(
            _WEATHER_UNSUPPORTED_TIME.search(text)
            or _WEATHER_UNSUPPORTED_METRIC.search(text)
            or _WEATHER_UNSUPPORTED_DETAIL.search(text)
        )

        def strip_if_current(match: re.Match[str]) -> str:
            nonlocal unsupported_date
            year_text = match.group("year")
            month = int(match.group("month"))
            day = int(match.group("day"))
            year = int(year_text) if year_text else now.year
            try:
                parsed = datetime(year, month, day, tzinfo=now.tzinfo).date()
            except ValueError:
                unsupported_date = True
                return match.group(0)

            same_day = (
                parsed == now.date()
                if year_text
                else (parsed.month, parsed.day) == (now.month, now.day)
            )
            if not same_day:
                unsupported_date = True
                return match.group(0)
            return " "

        cleaned = _WEATHER_KOREAN_DATE.sub(strip_if_current, text)
        cleaned = _WEATHER_NUMERIC_DATE.sub(strip_if_current, cleaned)
        return _SPACE.sub(" ", cleaned).strip(), unsupported_date

    def _normalize_weather_location(self, location: str) -> str:
        normalized = location.strip()
        while normalized:
            tokens = self.kiwi.tokenize(normalized)
            if not tokens or not tokens[-1].tag.startswith("J"):
                break
            normalized = normalized[:tokens[-1].start].strip()

        normalized = _WEATHER_COMPACT_LOCATION_ALIASES.get(normalized, normalized)
        words = normalized.split()
        if len(words) == 2 and words[0] in _WEATHER_PROVINCE_PREFIXES:
            province, locality = words
            if locality == "광주":
                if province in _WEATHER_GYEONGGI_PREFIXES:
                    return "경기도 광주"
                if province in _WEATHER_GWANGJU_METRO_PREFIXES:
                    return "광주"
                return normalized
            if locality not in _WEATHER_TOP_LEVEL_LOCATIONS:
                # 시·군 접미사는 Backend PlaceName 이 지오코딩 제공자에 맞춰 붙인다.
                return locality
        return normalized

    def _has_multiple_locations(self, location: str) -> bool:
        tokens = self.kiwi.tokenize(location)
        if any(
            token.form in _WEATHER_LOCATION_CONJUNCTIONS and token.tag == "JC"
            for token in tokens
        ):
            return True
        if re.search(r"[,/·&]", location) or any(
            marker in location.split() for marker in {"그리고", "또는", "혹은"}
        ):
            return True

        words = location.split()
        if (
            len(words) == 2
            and words[0] in _WEATHER_PROVINCE_PREFIXES
            and words[1] == "광주"
        ):
            return False
        return (
            len(words) == 2
            and all(word in _WEATHER_TOP_LEVEL_LOCATIONS for word in words)
        )

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
