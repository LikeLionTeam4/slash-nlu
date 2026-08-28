"""작업 유형별 필수 인자와 되묻기 문구, 슬래시 명령 별칭.

분석기(`analyzer.py`)가 "이 요청에 무엇이 빠졌는지"와 "그때 뭐라고 물을지"를 여기서
읽는다. 규칙을 코드에 흩지 않고 한곳에 모아, 명령을 추가할 때 이 파일만 보면 되게 했다.

되묻기 문구를 여기 두는 이유
    사용자가 실제로 보는 문장이라 표현이 흩어지면 명령마다 말투가 달라진다. 또한
    문구가 곧 "무엇을 더 달라는 요청"이라, 필수 인자 목록 바로 옆에 있어야 둘이
    어긋나지 않는다.

서버가 채우는 인자는 여기 넣지 않는다
    `searchFolderId`(`/file`)와 `workspaceId`(`/code`)는 사용자가 미리 등록한
    목록에서 `slash-api`가 고르는 값이다. 자연어에서 뽑을 수 없으므로 NLU의 필수
    인자가 아니다. 넣으면 서버가 채울 수 있는 값을 두고 사용자에게 되묻게 된다.
"""


from dataclasses import dataclass
from typing import Dict, Tuple

from models import TaskType


# 요약 최소 입력 길이(공백 제외). 이보다 짧으면 요약이 원문보다 길어지기 쉬워
# 분석 단계에서 미리 되묻는다. `summary.py`·`slash-llm`·`slash-web`(WebLLM)이
# 같은 값을 쓴다 — 어느 실행 위치로 가든 사용자가 보는 기준이 같아야 한다.
SUMMARY_MIN_CHARS = 150


@dataclass(frozen=True)
class IntentDefinition:
    """작업 유형 하나의 분석 규칙.

    `required_parameters`  NLU가 반드시 채워야 하는 인자. 빠지면 `CLARIFY`
    `question`             그때 사용자에게 보여줄 되묻기 문구

    `SYSTEM_STATUS`처럼 인자가 없는 작업은 둘 다 비운다 — 되물을 것이 없다.
    """

    task_type: TaskType
    required_parameters: Tuple[str, ...]
    question: str


# 작업 유형 7종의 분석 규칙. `slash-api`의 `TaskType.requiredParameters` 중
# NLU 몫(= 서버가 채우는 값을 뺀 것)과 일치해야 한다.
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


# 슬래시 명령 별칭 → 작업 유형. 한글·영문을 모두 받는다.
#
# 한 유형에 여러 별칭을 두는 이유는 사용자가 `/파일`과 `/file` 중 무엇을 칠지
# 알 수 없기 때문이다. 화면이 안내하는 것은 한글 명령이지만, 영문 입력을 막으면
# 오타가 아니라 미지원 명령으로 처리돼 사용자가 원인을 알기 어렵다.
#
# `status_com`은 화면 명령 트리에서 넘어오는 내부 경로값이라 함께 받는다.
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
