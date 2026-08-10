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


def _p0_catalog_entries(task_types: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {
        str(entry["taskType"]): entry
        for entry in task_types
        if entry.get("priority") == "P0"
    }


def test_backend_task_type_catalog_matches_nlu_mvp_contract():
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
    p0_entries = _p0_catalog_entries(task_types)

    expected_task_types = {task_type.value for task_type in INTENTS}
    assert set(p0_entries) == expected_task_types

    for task_type, definition in INTENTS.items():
        assert p0_entries[task_type.value]["nluRequiredParameters"] == list(definition.required_parameters)

    file_search = p0_entries[TaskType.FILE_SEARCH.value]
    assert file_search["requiredParameters"] == ["query", "searchFolderId"]
    assert file_search["backendProvidedParameters"] == ["searchFolderId"]
    assert "searchFolderId" not in file_search["nluRequiredParameters"]
