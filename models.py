"""slash-api ↔ slash-nlu 요청·응답 계약.

이 파일이 **저장소 경계를 넘는 계약의 원본**이다. 필드 이름·타입·허용값이 바뀌면
`slash-api` 쪽 DTO와 동시에 맞춰야 한다(계약 변경 절차는 AGENTS.md 참고).

담는 것은 두 갈래다.

분석 계약 (`POST /internal/v1/nlu/analyze`)
    사용자 입력을 작업 유형과 인자로 바꾼 결과. `slash-api`가 이 응답을 보고
    처리 경로를 정한다.

추출 요약 계약 (`POST /internal/v1/nlu/summary`)
    GPU 없이 도는 CPU 요약 결과. 클라우드 LLM 제거(`slash-docs#3`) 이후
    `/summary`의 서버 실행 경로가 이쪽으로 바뀌었다.

JSON 필드명은 camelCase다 — 파이썬 관례(snake_case)와 다르지만 `slash-api`·
`slash-web`이 쓰는 표기에 맞춘 것이라 그대로 둔다.
"""


from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# 분석 결과의 처리 방향. `slash-api`가 다음 단계를 이 값으로 가른다.
#
# `TASK`         작업 유형과 인자를 확정했다 — 실행으로 넘긴다
# `CLARIFY`      필수 인자가 빠졌다 — `question`을 사용자에게 되묻는다
# `UNSUPPORTED`  지원하는 작업으로 분류할 수 없다 — 실행하지 않는다
class Decision(str, Enum):
    TASK = "TASK"
    CLARIFY = "CLARIFY"
    UNSUPPORTED = "UNSUPPORTED"


# 지원하는 작업 유형 7종. 슬래시 명령과 1:1 대응한다.
#
# `slash-api`의 `TaskType` 열거형과 **값이 정확히 같아야 한다.** 한쪽에만 추가하면
# 서버가 "허용 목록에 없는 taskType"으로 판단해 실행을 거부한다.
#
# `FILE_SEARCH`     `/file`     등록 검색 폴더에서 파일 찾기
# `FILE_OPEN`       `/open`     검색 결과 파일의 위치 열기
# `SYSTEM_STATUS`   `/status`   PC의 CPU·메모리·디스크 조회
# `WEATHER_LOOKUP`  `/weather`  지역 날씨 조회
# `TEXT_SUMMARY`    `/summary`  텍스트 요약
# `CODE_ANALYSIS`   `/code`     등록 프로젝트 폴더 읽기 전용 분석
# `AI_AGENT_USAGE`  `/usage`    로컬 CLI 토큰 사용량 조회
class TaskType(str, Enum):
    FILE_SEARCH = "FILE_SEARCH"
    FILE_OPEN = "FILE_OPEN"
    SYSTEM_STATUS = "SYSTEM_STATUS"
    WEATHER_LOOKUP = "WEATHER_LOOKUP"
    TEXT_SUMMARY = "TEXT_SUMMARY"
    CODE_ANALYSIS = "CODE_ANALYSIS"
    AI_AGENT_USAGE = "AI_AGENT_USAGE"


# 어느 분석기가 결론을 냈는지. 오분류를 추적할 때 어디를 볼지 알려 준다.
#
# `SLASH`      `/`로 시작하는 입력을 구문 파싱 — 결정적이라 신뢰도가 높다
# `RULE_KIWI`  자연어를 규칙 + Kiwi 형태소 분석으로 분류
class AnalyzerType(str, Enum):
    SLASH = "SLASH"
    RULE_KIWI = "RULE_KIWI"


# `GET /health` 응답. `analyzerReady`가 거짓이면 Kiwi 초기화가 끝나지 않은 것이다.
#
# Kiwi는 첫 로딩에 시간이 걸려, 기동 직후 요청이 지연될 수 있다. Kubernetes
# readiness가 이 값을 보고 준비 전 트래픽을 막는다.
class HealthResponse(BaseModel):
    status: Literal["UP", "NOT_READY"]
    analyzerReady: bool


# 슬래시 명령을 구조화한 입력. 프론트가 명령어와 값을 분리해 보낸다.
#
# `path`      명령 경로. `["파일"]`, `["네이버", "길찾기"]`처럼 계층을 이룬다
# `operands`  이미 확정된 값. 자유 텍스트는 한 원소로 보내 공백·줄바꿈을 보존한다
#
# 빈 문자열 경로 조각을 거부하는 이유는, 그것이 통과하면 명령 경로가 어긋난 채
# 분석기까지 내려가 원인을 찾기 어려운 오분류가 되기 때문이다.
class CommandInput(BaseModel):
    path: List[str] = Field(min_length=1)
    operands: List[str] = Field(default_factory=list)

    @field_validator("path")
    @classmethod
    def path_segments_must_not_be_blank(cls, value: List[str]) -> List[str]:
        if any(not segment.strip() for segment in value):
            raise ValueError("command.path must not contain blank segments")
        return value


# 분석 요청. `text`(자연어)와 `command`(슬래시) 중 하나가 온다.
#
# `now`에 오프셋을 강제하는 이유는 "오늘"·"내일" 같은 상대 날짜를 해석하기
# 때문이다. 오프셋이 없으면 어느 시간대 기준인지 정할 수 없어 하루가 밀린다.
# 프로젝트 전 구간이 한국 시각(+09:00)을 쓴다.
#
# `requestId`는 저장소를 가로지르는 추적 식별자라 응답에 그대로 실어 보낸다.
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


# 분석 결과. `slash-api`가 이 값만 보고 실행 여부와 되묻기를 결정한다.
#
# `missingRequiredParameters`에 **서버가 채우는 값은 넣지 않는다.**
# `searchFolderId`·`workspaceId`는 사용자가 미리 등록한 목록에서 서버가 고르는
# 값이라 자연어에서 뽑을 수 없다. 여기에 넣으면 서버가 채울 수 있는 값을 두고
# 사용자에게 되묻는 일이 생긴다.
#
# `confidence`는 0~1이며 분류 근거의 강도다. 임계값 판단은 서버 몫이다.
class AnalyzeResponse(BaseModel):
    requestId: str
    decision: Decision
    taskType: Optional[TaskType]
    parameters: Dict[str, Any] = Field(default_factory=dict)
    missingRequiredParameters: List[str] = Field(default_factory=list)
    question: Optional[str]
    confidence: float = Field(ge=0.0, le=1.0)
    analyzer: AnalyzerType


# CPU 추출 요약 요청. 길이 검증은 서버(`summary.py`)가 한다.
#
# `requestId`·`taskId` 둘 다 필수인 이유는, 요약이 작업 원장의 한 작업으로
# 실행되기 때문이다. 실패했을 때 어느 작업의 어느 요청인지 특정할 수 있어야 한다.
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


# CPU 추출 요약 결과. 생성이 아니라 **원문 문장 선택**이다.
#
# `engine`·`algorithm`·`algorithmVersion`을 함께 싣는 이유는 "무엇으로 만든
# 결과인지"를 이력에 남기기 위해서다. 실행 위치(`executionTarget`)는 어디서
# 했는지만 나타내므로, 같은 서버 실행 안에서 Gemma와 추출 요약을 가르는 것은
# 이 값들이다. 같은 알고리즘이라도 버전이 다르면 결과가 달라질 수 있어
# `algorithmVersion`을 따로 둔다.
#
# 출력은 최대 3문장이다 — 더 늘리면 요약이 아니라 발췌가 된다.
class ExtractiveSummaryResponse(BaseModel):
    requestId: str
    taskId: str
    summary: str
    engine: Literal["EXTRACTIVE"]
    algorithm: Literal["TFIDF_CENTROID"]
    algorithmVersion: Literal["2"]
    inputSentenceCount: int = Field(ge=1)
    outputSentenceCount: int = Field(ge=1, le=3)
    durationMs: int = Field(ge=0)


# 요약 오류 상세. `retryable`은 호출 측이 재시도해도 되는지를 뜻한다.
#
# 입력이 짧아서 실패한 것은 다시 보내도 같으므로 거짓, 일시적 자원 문제는 참이다.
class SummaryErrorDetail(BaseModel):
    code: str
    message: str
    retryable: bool


# 요약 오류 응답. 성공 응답과 같은 추적 식별자를 실어 보낸다.
class SummaryErrorResponse(BaseModel):
    error: SummaryErrorDetail
    requestId: str
    taskId: str
