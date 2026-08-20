import os
from typing import Any, Dict, List

import httpx
import pytest

from intents import INTENTS
from models import TaskType


def _catalog_configuration() -> tuple[str, str]:
    base_url = os.getenv("NLU_CONTRACT_BASE_URL", "").rstrip("/")
    token = os.getenv("NLU_CONTRACT_TOKEN", "")
    if not base_url or not token:
        pytest.skip("set NLU_CONTRACT_BASE_URL and NLU_CONTRACT_TOKEN to run the Backend contract check")
    return base_url, token


SUPPORTED_PRIORITIES = {
    TaskType.FILE_SEARCH: "P0",
    TaskType.FILE_OPEN: "P0",
    TaskType.SYSTEM_STATUS: "P0",
    TaskType.WEATHER_LOOKUP: "P0",
    TaskType.TEXT_SUMMARY: "P0",
    TaskType.CODE_ANALYSIS: "P1",
    TaskType.AI_AGENT_USAGE: "P0",
}


def test_backend_task_type_catalog_matches_nlu_contract():
    base_url, token = _catalog_configuration()

    response = httpx.get(
        f"{base_url}/api/v1/task-types",
        headers={"Authorization": f"Bearer {token}"},
        timeout=2.0,
        follow_redirects=False,
    )

    assert response.status_code == 200
    payload = response.json()
    task_types = payload["data"]["taskTypes"]
    catalog = {str(entry["taskType"]): entry for entry in task_types}

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
