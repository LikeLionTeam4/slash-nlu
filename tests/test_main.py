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


@pytest.mark.parametrize(
    ("path", "operands", "task_type", "parameters"),
    [
        (["file"], ["report.pdf"], "FILE_SEARCH", {"query": "report.pdf"}),
        (["open"], ["opaque-file-ref"], "FILE_OPEN", {"fileRef": "opaque-file-ref"}),
        (["status_com"], [], "SYSTEM_STATUS", {}),
        (["날씨"], ["부산"], "WEATHER_LOOKUP", {"location": "부산"}),
        (["summary"], ["가" * 150], "TEXT_SUMMARY", {"text": "가" * 150}),
        (["code"], ["이", "프로젝트", "분석해줘"], "CODE_ANALYSIS", {"query": "이 프로젝트 분석해줘"}),
        (["usage"], ["claude-code"], "AI_AGENT_USAGE", {"provider": "CLAUDE_CODE"}),
    ],
)
def test_all_slash_tasks(client, path, operands, task_type, parameters):
    body = post(client, {"requestId": "req-slash", "command": {"path": path, "operands": operands}}).json()
    assert body["decision"] == "TASK"
    assert body["taskType"] == task_type
    assert body["parameters"] == parameters
    assert body["missingRequiredParameters"] == []
    assert body["analyzer"] == "SLASH"


@pytest.mark.parametrize(
    ("path", "missing"),
    [
        (["파일"], ["query"]),
        (["열기"], ["fileRef"]),
        (["날씨"], ["location"]),
        (["요약"], ["text"]),
        (["코드"], ["query"]),
        (["사용량"], ["provider"]),
    ],
)
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


@pytest.mark.parametrize(
    ("text", "location"),
    [
        ("오늘 서울 날씨 어때?", "서울"),
        ("서울 기온 알려줘", "서울"),
        ("서울 weather", "서울"),
        ("weather 서울", "서울"),
    ],
)
def test_weather_expressions_extract_only_the_location(client, text, location):
    body = post(client, {"requestId": "req-weather-expression", "text": text}).json()

    assert body["decision"] == "TASK"
    assert body["taskType"] == "WEATHER_LOOKUP"
    assert body["parameters"] == {"location": location}


@pytest.mark.parametrize("text", ["기온 알려줘", "날씨 알려줘"])
def test_weather_without_location_clarifies(client, text):
    body = post(client, {"requestId": "req-weather-missing", "text": text}).json()

    assert body["decision"] == "CLARIFY"
    assert body["taskType"] == "WEATHER_LOOKUP"
    assert body["missingRequiredParameters"] == ["location"]


def test_misspelled_weather_slash_command_is_unsupported(client):
    body = post(client, {"requestId": "req-weather-typo", "text": "/weathr 서울"}).json()

    assert body["decision"] == "UNSUPPORTED"
    assert body["taskType"] is None


@pytest.mark.parametrize(
    ("operands", "provider"),
    [
        (["CLAUDE_CODE"], "CLAUDE_CODE"),
        (["claude-code"], "CLAUDE_CODE"),
        (["claude", "code"], "CLAUDE_CODE"),
        (["claude"], "CLAUDE_CODE"),
        (["클로드"], "CLAUDE_CODE"),
        (["CODEX"], "CODEX"),
        (["코덱스"], "CODEX"),
    ],
)
def test_usage_provider_aliases_are_normalized(client, operands, provider):
    body = post(
        client,
        {"requestId": "req-usage-provider", "command": {"path": ["usage"], "operands": operands}},
    ).json()

    assert body["decision"] == "TASK"
    assert body["taskType"] == "AI_AGENT_USAGE"
    assert body["parameters"] == {"provider": provider}


def test_unknown_usage_provider_clarifies_without_guessing(client):
    body = post(
        client,
        {"requestId": "req-usage-unknown", "command": {"path": ["usage"], "operands": ["gpt"]}},
    ).json()

    assert body["decision"] == "CLARIFY"
    assert body["taskType"] == "AI_AGENT_USAGE"
    assert body["parameters"] == {}
    assert body["missingRequiredParameters"] == ["provider"]


def test_file_open_preserves_opaque_reference(client):
    file_ref = "f62dfe8a-8525-4ba9-a0b5-7f6d70ebfedd"
    body = post(
        client,
        {"requestId": "req-file-open", "command": {"path": ["open"], "operands": [file_ref]}},
    ).json()

    assert body["decision"] == "TASK"
    assert body["taskType"] == "FILE_OPEN"
    assert body["parameters"] == {"fileRef": file_ref}


def test_file_open_rejects_more_than_one_reference_token(client):
    body = post(
        client,
        {"requestId": "req-file-open-invalid", "command": {"path": ["open"], "operands": ["ref-a", "ref-b"]}},
    ).json()

    assert body["decision"] == "CLARIFY"
    assert body["taskType"] == "FILE_OPEN"
    assert body["parameters"] == {}
    assert body["missingRequiredParameters"] == ["fileRef"]


def test_code_analysis_returns_query_but_not_backend_workspace_id(client):
    body = post(
        client,
        {
            "requestId": "req-code-analysis",
            "command": {"path": ["code"], "operands": ["이", "프로젝트", "분석해줘"]},
        },
    ).json()

    assert body["decision"] == "TASK"
    assert body["taskType"] == "CODE_ANALYSIS"
    assert body["parameters"] == {"query": "이 프로젝트 분석해줘"}
    assert "workspaceId" not in body["parameters"]
    assert "workspaceId" not in body["missingRequiredParameters"]


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
    assert body["question"] == "요약할 내용을 공백 제외 150자 이상 입력해 주세요."


@pytest.mark.parametrize(("character_count", "decision"), [(149, "CLARIFY"), (150, "TASK")])
def test_summary_minimum_excludes_whitespace(client, character_count, decision):
    spaced_text = "가 " * character_count
    body = post(client, {"requestId": "req-spaced-summary", "text": f"요약: {spaced_text}"}).json()

    assert body["decision"] == decision
    assert body["taskType"] == "TEXT_SUMMARY"


@pytest.mark.parametrize(
    "payload",
    [
        {"requestId": "req-natural-summary-window", "text": "요약: " + ("가" * 149) + (" " * (8000 - 149)) + "나"},
        {"requestId": "req-slash-summary-window", "command": {"path": ["summary"], "operands": [("가" * 149) + (" " * (8000 - 149)) + "나"]}},
    ],
)
def test_summary_minimum_only_counts_first_8000_input_characters(client, payload):
    body = post(client, payload).json()

    assert body["decision"] == "CLARIFY"
    assert body["taskType"] == "TEXT_SUMMARY"
    assert body["missingRequiredParameters"] == ["text"]


def test_file_word_inside_another_word_is_not_file_search(client):
    body = post(client, {"requestId": "req-pilot", "text": "파일럿 검색해줘"}).json()

    assert body["decision"] == "UNSUPPORTED"
    assert body["taskType"] is None


@pytest.mark.parametrize("text", ["맛집 검색해줘", "보안 찾아줘"])
def test_general_search_is_not_mistaken_for_file_search(client, text):
    body = post(client, {"requestId": "req-general-search", "text": text}).json()

    assert body["decision"] == "UNSUPPORTED"
    assert body["taskType"] is None


@pytest.mark.parametrize(
    ("text", "query"),
    [
        ("예산안 찾아줘", "예산안"),
        ("계약서 찾아줘", "계약서"),
        ("이력서 찾아줘", "이력서"),
        ("제안서 찾아줘", "제안서"),
        ("기획안 찾아줘", "기획안"),
    ],
)
def test_natural_file_search_recognizes_document_name_endings(client, text, query):
    body = post(client, {"requestId": "req-document-name", "text": text}).json()

    assert body["decision"] == "TASK"
    assert body["taskType"] == "FILE_SEARCH"
    assert body["parameters"]["query"] == query


@pytest.mark.parametrize(
    ("text", "query"),
    [
        ("회의록 문서 검색해줘", "회의록"),
        ("예산안이라는 파일 찾아줘", "예산안"),
        ("예산안 파일 좀 찾아줄래", "예산안"),
        ("예산안을 찾아주세요", "예산안"),
    ],
)
def test_natural_file_search_removes_structural_words_and_action_endings(client, text, query):
    body = post(client, {"requestId": "req-natural-file-query", "text": text}).json()

    assert body["decision"] == "TASK"
    assert body["taskType"] == "FILE_SEARCH"
    assert body["parameters"]["query"] == query


def test_file_slash_preserves_query_starting_with_file_syllables(client):
    body = post(
        client,
        {"requestId": "req-pilot-file", "command": {"path": ["file"], "operands": ["파일럿.txt"]}},
    ).json()

    assert body["decision"] == "TASK"
    assert body["parameters"]["query"] == "파일럿.txt"


def test_file_slash_preserves_query_ending_with_english_action_syllables(client):
    body = post(
        client,
        {"requestId": "req-research-file", "command": {"path": ["file"], "operands": ["research"]}},
    ).json()

    assert body["decision"] == "TASK"
    assert body["parameters"]["query"] == "research"


@pytest.mark.parametrize("query", ["파일", "file"])
def test_file_slash_generic_subject_clarifies(client, query):
    body = post(
        client,
        {"requestId": "req-generic-file", "command": {"path": ["file"], "operands": [query]}},
    ).json()

    assert body["decision"] == "CLARIFY"
    assert body["missingRequiredParameters"] == ["query"]


@pytest.mark.parametrize(("text", "query"), [("report.pdf 찾아줘", "report.pdf"), ("report.ppt 찾아줘", "report.ppt")])
def test_natural_file_search_recognizes_filename_extensions(client, text, query):
    body = post(client, {"requestId": "req-file-extension", "text": text}).json()

    assert body["decision"] == "TASK"
    assert body["taskType"] == "FILE_SEARCH"
    assert body["parameters"]["query"] == query


@pytest.mark.parametrize("text", ["file search", "file find", "file research"])
def test_english_file_request_without_query_clarifies(client, text):
    body = post(client, {"requestId": "req-english-file", "text": text}).json()

    assert body["decision"] == "CLARIFY"
    assert body["taskType"] == "FILE_SEARCH"
    assert body["missingRequiredParameters"] == ["query"]


@pytest.mark.parametrize(("text", "query"), [("요약본 파일 찾아줘", "요약본"), ("날씨 보고서 파일 찾아줘", "날씨 보고서")])
def test_explicit_file_search_takes_priority_over_other_keywords(client, text, query):
    body = post(client, {"requestId": "req-file-priority", "text": text}).json()

    assert body["decision"] == "TASK"
    assert body["taskType"] == "FILE_SEARCH"
    assert body["parameters"]["query"] == query


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


def test_health_stays_up_when_analyzer_is_not_ready(client):
    del client.app.state.analyzer

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "UP", "analyzerReady": False}


def test_ready_returns_200_when_analyzer_is_ready(client):
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "UP", "analyzerReady": True}


def test_ready_returns_503_when_analyzer_is_not_ready(client):
    del client.app.state.analyzer

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "NOT_READY", "analyzerReady": False}


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
    assert "/ready" in schema["paths"]
    assert "/internal/v1/nlu/analyze" in schema["paths"]
    properties = schema["components"]["schemas"]["AnalyzeResponse"]["properties"]
    assert {"requestId", "decision", "taskType", "parameters", "missingRequiredParameters", "question", "confidence", "analyzer"} <= set(properties)
    assert "processingRoute" not in properties

    ready_responses = schema["paths"]["/ready"]["get"]["responses"]
    assert {"200", "503"} <= set(ready_responses)
    for status_code in ("200", "503"):
        response_schema = ready_responses[status_code]["content"]["application/json"]["schema"]
        assert response_schema["$ref"].endswith("/HealthResponse")


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
            "FILE_OPEN",
            "SYSTEM_STATUS",
            "WEATHER_LOOKUP",
            "TEXT_SUMMARY",
            "CODE_ANALYSIS",
            "AI_AGENT_USAGE",
        ],
        "title": "TaskType",
    }
    assert schemas["AnalyzerType"] == {
        "type": "string",
        "enum": ["SLASH", "RULE_KIWI"],
        "title": "AnalyzerType",
    }


@pytest.mark.parametrize(
    "path",
    [["command"], ["네이버"], ["web_search"], ["chat"]],
)
def test_non_mvp_slash_commands_are_unsupported(client: TestClient, path):
    body = post(
        client,
        {"requestId": "req-non-mvp", "command": {"path": path, "operands": ["hello"]}},
    ).json()

    assert body["decision"] == "UNSUPPORTED"
    assert body["taskType"] is None
    assert body["parameters"] == {}


@pytest.mark.parametrize(
    "text",
    ["/command hello", "네이버에서 뉴스 검색해줘", "제네릭 어떻게 써?"],
)
def test_non_mvp_natural_inputs_never_create_future_task_types(client: TestClient, text):
    body = post(client, {"requestId": "req-non-mvp-text", "text": text}).json()

    assert body["decision"] == "UNSUPPORTED"
    assert body["taskType"] is None


@pytest.mark.parametrize(
    "text",
    ["코드 분석해줘", "클로드 사용량 알려줘", "이 파일 열어줘"],
)
def test_slash_only_tasks_are_not_guessed_from_natural_language(client: TestClient, text):
    body = post(client, {"requestId": "req-slash-only", "text": text}).json()

    assert body["decision"] == "UNSUPPORTED"
    assert body["taskType"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"requestId": "req-file-slash", "command": {"path": ["file"], "operands": ["회의록"]}},
        {"requestId": "req-file-natural", "text": "회의록 파일 찾아줘"},
    ],
)
def test_file_search_leaves_structural_parameters_to_backend(client: TestClient, payload):
    body = post(client, payload).json()

    assert body["decision"] == "TASK"
    assert body["taskType"] == "FILE_SEARCH"
    assert body["parameters"]["query"] == "회의록"
    assert "searchFolderId" not in body["parameters"]
    assert "searchFolderId" not in body["missingRequiredParameters"]
    assert "processingRoute" not in body
