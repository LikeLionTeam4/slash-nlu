import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from main import app


FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "analyze_cases.json").read_text(encoding="utf-8"))


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def post(client: TestClient, payload: dict):
    return client.post("/internal/v1/nlu/analyze", json=payload)


@pytest.mark.parametrize("case", FIXTURES, ids=lambda case: case["name"])
def test_contract_fixtures(client: TestClient, case: dict):
    response = post(client, case["request"])
    assert response.status_code == 200
    body = response.json()
    for key, value in case["expected"].items():
        assert body[key] == value
    assert body["requestId"] == case["request"]["requestId"]
    assert 0 <= body["confidence"] <= 1
    assert "processingRoute" not in body


@pytest.mark.parametrize(("path", "operands", "task_type", "parameters"), [(["file"], ["report.pdf"], "FILE_SEARCH", {"query": "report.pdf"}), (["status_com"], [], "SYSTEM_STATUS", {}), (["날씨"], ["부산"], "WEATHER_LOOKUP", {"location": "부산"}), (["summary"], ["가" * 150], "TEXT_SUMMARY", {"text": "가" * 150})])
def test_all_slash_tasks(client, path, operands, task_type, parameters):
    body = post(client, {"requestId": "req-slash", "command": {"path": path, "operands": operands}}).json()
    assert body["decision"] == "TASK"
    assert body["taskType"] == task_type
    assert body["parameters"] == parameters
    assert body["missingRequiredParameters"] == []
    assert body["analyzer"] == "SLASH"


@pytest.mark.parametrize(("path", "missing"), [(["파일"], ["query"]), (["날씨"], ["location"]), (["요약"], ["text"])])
def test_slash_missing_parameters_clarifies(client, path, missing):
    body = post(client, {"requestId": "req-missing", "command": {"path": path, "operands": []}}).json()
    assert body["decision"] == "CLARIFY"
    assert body["taskType"] is not None
    assert body["missingRequiredParameters"] == missing
    assert body["question"]


@pytest.mark.parametrize(("text", "task_type"), [("서울 날씨 알려줘", "WEATHER_LOOKUP"), ("회의록 파일 찾아줘", "FILE_SEARCH"), ("회의록 찾아줘", "FILE_SEARCH"), ("작년 견적서 찾아줘", "FILE_SEARCH"), ("컴퓨터 상태 알려줘", "SYSTEM_STATUS"), ("요약: " + ("가" * 150), "TEXT_SUMMARY")])
def test_natural_language_tasks(client, text, task_type):
    body = post(client, {"requestId": "req-natural", "text": text}).json()
    assert body["decision"] == "TASK"
    assert body["taskType"] == task_type
    assert body["analyzer"] == "RULE_KIWI"


def test_service_candidate_without_parameter_clarifies(client):
    body = post(client, {"requestId": "req-clarify", "text": "파일 찾아줘"}).json()
    assert body["decision"] == "CLARIFY"
    assert body["taskType"] == "FILE_SEARCH"
    assert body["missingRequiredParameters"] == ["query"]


@pytest.mark.parametrize("payload", [
    {"requestId": "req-short-summary", "text": "요약: 짧은 본문"},
    {"requestId": "req-short-summary", "command": {"path": ["요약"], "operands": ["짧은 본문"]}},
])
def test_short_summary_clarifies_before_llm_call(client, payload):
    body = post(client, payload).json()
    assert body["decision"] == "CLARIFY"
    assert body["taskType"] == "TEXT_SUMMARY"
    assert body["missingRequiredParameters"] == ["text"]
    assert "150자" in body["question"]


@pytest.mark.parametrize("payload", [{"requestId": "req-none"}, {"requestId": "req-both", "text": "서울 날씨", "command": {"path": ["날씨"], "operands": ["서울"]}}, {"requestId": "req-empty", "text": "   "}])
def test_business_input_conflicts_are_400(client, payload):
    assert post(client, payload).status_code == 400


def test_schema_errors_are_422(client):
    assert post(client, {"requestId": "", "text": "날씨"}).status_code == 422
    assert post(client, {"requestId": "req", "text": "날씨", "now": "2026-08-05T00:00:00"}).status_code == 422
    assert post(client, {"requestId": "req", "command": {"path": [], "operands": []}}).status_code == 422


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "UP", "analyzerReady": True}


def test_unexpected_analyzer_error_is_500(client, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("internal detail must not leak")

    monkeypatch.setattr(client.app.state.analyzer, "analyze_text", fail)
    response = post(client, {"requestId": "req-error", "text": "서울 날씨"})
    assert response.status_code == 500
    assert response.json() == {"detail": "NLU analysis failed"}


def test_openapi_exposes_contract():
    schema = app.openapi()
    assert "/health" in schema["paths"]
    assert "/internal/v1/nlu/analyze" in schema["paths"]
    properties = schema["components"]["schemas"]["AnalyzeResponse"]["properties"]
    assert {"requestId", "decision", "taskType", "parameters", "missingRequiredParameters", "question", "confidence", "analyzer"} <= set(properties)
    assert "processingRoute" not in properties


def test_openapi_exposes_wire_values_as_string_enums():
    schemas = app.openapi()["components"]["schemas"]

    assert schemas["Decision"] == {
        "type": "string",
        "enum": ["TASK", "CLARIFY", "UNSUPPORTED"],
        "title": "Decision",
    }
    assert schemas["TaskType"] == {
        "type": "string",
        "enum": [
            "FILE_SEARCH",
            "SYSTEM_STATUS",
            "WEATHER_LOOKUP",
            "TEXT_SUMMARY",
        ],
        "title": "TaskType",
    }
    assert schemas["AnalyzerType"] == {
        "type": "string",
        "enum": ["SLASH", "RULE_KIWI"],
        "title": "AnalyzerType",
    }
