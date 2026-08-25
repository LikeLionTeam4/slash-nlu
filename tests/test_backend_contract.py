import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List

from intents import INTENTS
from models import TaskType


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "backend_task_types.json"
BACKEND_SOURCE_ENV = "BACKEND_TASK_TYPE_SOURCE"
_ENUM_ENTRY = re.compile(
    r"(?P<taskType>[A-Z][A-Z0-9_]*)\s*\(\s*\"/[^\"]+\"\s*,"
    r"(?:\s*[^,\n]+\s*,)?\s*Priority\.(?P<priority>P[01])\s*,"
    r"\s*(?P<required>List\.of\(.*?\)|Collections\.emptyList\(\))\s*,"
    r"\s*(?P<backend>List\.of\(.*?\)|Collections\.emptyList\(\))\s*\)\s*[,;]",
    flags=re.DOTALL,
)

SUPPORTED_PRIORITIES = {
    TaskType.FILE_SEARCH: "P0",
    TaskType.FILE_OPEN: "P0",
    TaskType.SYSTEM_STATUS: "P0",
    TaskType.WEATHER_LOOKUP: "P0",
    TaskType.TEXT_SUMMARY: "P0",
    TaskType.CODE_ANALYSIS: "P0",
    TaskType.AI_AGENT_USAGE: "P0",
}


def _catalog(entries: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(entry["taskType"]): entry for entry in entries}


def _fixture_catalog() -> Dict[str, Dict[str, Any]]:
    return _catalog(json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))


def _strip_java_comments(source: str) -> str:
    result: List[str] = []
    index = 0
    quote = None
    while index < len(source):
        current = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if quote is not None:
            result.append(current)
            if current == "\\" and following:
                result.append(following)
                index += 2
                continue
            if current == quote:
                quote = None
            index += 1
            continue
        if current in {'"', "'"}:
            quote = current
            result.append(current)
            index += 1
            continue
        if current == "/" and following == "/":
            index += 2
            while index < len(source) and source[index] != "\n":
                index += 1
            continue
        if current == "/" and following == "*":
            index += 2
            while index + 1 < len(source) and source[index : index + 2] != "*/":
                if source[index] == "\n":
                    result.append("\n")
                index += 1
            index = min(index + 2, len(source))
            continue
        result.append(current)
        index += 1
    return "".join(result)


def _java_catalog(source_path: Path) -> Dict[str, Dict[str, Any]]:
    source = source_path.read_text(encoding="utf-8")
    source = _strip_java_comments(source)
    entries: List[Dict[str, Any]] = []
    for match in _ENUM_ENTRY.finditer(source):
        required = re.findall(r'\"([^\"]+)\"', match.group("required"))
        backend = re.findall(r'\"([^\"]+)\"', match.group("backend"))
        entries.append(
            {
                "taskType": match.group("taskType"),
                "priority": match.group("priority"),
                "requiredParameters": required,
                "nluRequiredParameters": [value for value in required if value not in backend],
                "backendProvidedParameters": backend,
            }
        )
    assert entries, f"Backend TaskType enum을 파싱하지 못했습니다: {source_path}"
    return _catalog(entries)


def _assert_nlu_contract(catalog: Dict[str, Dict[str, Any]]) -> None:
    expected_p0 = {
        task_type.value
        for task_type, priority in SUPPORTED_PRIORITIES.items()
        if priority == "P0"
    }
    actual_p0 = {
        task_type
        for task_type, entry in catalog.items()
        if entry.get("priority") == "P0"
    }
    assert actual_p0 == expected_p0

    for task_type, definition in INTENTS.items():
        entry = catalog[task_type.value]
        assert entry["priority"] == SUPPORTED_PRIORITIES[task_type]
        assert entry["nluRequiredParameters"] == list(definition.required_parameters)

    file_search = catalog[TaskType.FILE_SEARCH.value]
    assert file_search["requiredParameters"] == ["query", "searchFolderId"]
    assert file_search["backendProvidedParameters"] == ["searchFolderId"]
    assert "searchFolderId" not in file_search["nluRequiredParameters"]

    file_open = catalog[TaskType.FILE_OPEN.value]
    assert file_open["requiredParameters"] == ["fileRef"]
    assert file_open["backendProvidedParameters"] == []

    code_analysis = catalog[TaskType.CODE_ANALYSIS.value]
    assert code_analysis["requiredParameters"] == ["query", "workspaceId"]
    assert code_analysis["nluRequiredParameters"] == ["query"]
    assert code_analysis["backendProvidedParameters"] == ["workspaceId"]

    ai_agent_usage = catalog[TaskType.AI_AGENT_USAGE.value]
    assert ai_agent_usage["requiredParameters"] == ["provider"]
    assert ai_agent_usage["backendProvidedParameters"] == []


def test_backend_task_type_catalog_matches_nlu_contract():
    fixture = _fixture_catalog()
    _assert_nlu_contract(fixture)

    source = os.getenv(BACKEND_SOURCE_ENV)
    if source:
        live_source = _java_catalog(Path(source))
        assert len(live_source) == len(fixture), (
            "Backend TaskType enum 파싱 개수가 계약 fixture와 다릅니다: "
            f"parsed={len(live_source)}, expected={len(fixture)}"
        )
        assert live_source == fixture
        _assert_nlu_contract(live_source)


def test_java_parser_accepts_route_removal_and_empty_list_alternative(tmp_path):
    source = tmp_path / "TaskType.java"
    source.write_text(
        """
        enum TaskType {
          WEATHER_LOOKUP(\"/weather\", Priority.P0, List.of(\"location\"), Collections.emptyList()),
          FILE_SEARCH(\"/file\", ProcessingRoute.PC_AGENT, Priority.P0,
              List.of(\"query\", \"searchFolderId\"), List.of(\"searchFolderId\"));
        }
        """,
        encoding="utf-8",
    )

    assert _java_catalog(source) == {
        "WEATHER_LOOKUP": {
            "taskType": "WEATHER_LOOKUP",
            "priority": "P0",
            "requiredParameters": ["location"],
            "nluRequiredParameters": ["location"],
            "backendProvidedParameters": [],
        },
        "FILE_SEARCH": {
            "taskType": "FILE_SEARCH",
            "priority": "P0",
            "requiredParameters": ["query", "searchFolderId"],
            "nluRequiredParameters": ["query"],
            "backendProvidedParameters": ["searchFolderId"],
        },
    }


def test_java_comment_removal_preserves_markers_inside_strings():
    source = 'WEATHER_LOOKUP("//weather", Priority.P0, List.of("url//path"), List.of()) // note\n'

    assert _strip_java_comments(source) == (
        'WEATHER_LOOKUP("//weather", Priority.P0, List.of("url//path"), List.of()) \n'
    )
