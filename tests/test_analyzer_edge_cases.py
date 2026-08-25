import json
from collections import Counter
from pathlib import Path

from analyzer import NluAnalyzer
from models import AnalyzeRequest
from scripts.benchmark_analyzer import BenchmarkCase, direct_invoker


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "analyzer_edge_cases.json"
TRIAGE_GROUPS = {"RULE_CANDIDATE", "LLM_EXPERIMENT", "UNSUPPORTED"}


def load_edge_cases():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_edge_case_corpus_has_balanced_unique_triage_groups():
    cases = load_edge_cases()

    assert len(cases) == 30
    assert len({case["name"] for case in cases}) == len(cases)
    assert Counter(case["triage"] for case in cases) == {
        "RULE_CANDIDATE": 10,
        "LLM_EXPERIMENT": 10,
        "UNSUPPORTED": 10,
    }
    assert all(case["proposal"].strip() for case in cases)


def test_edge_case_requests_are_reproducible_natural_language_inputs():
    for case in load_edge_cases():
        payload = AnalyzeRequest.model_validate(case["request"])

        assert payload.text is not None
        assert payload.command is None
        assert payload.now is not None


def test_edge_case_corpus_records_current_analyzer_behavior():
    cases = [
        BenchmarkCase(
            name=case["name"],
            request=case["request"],
            expected=case["expected"],
        )
        for case in load_edge_cases()
    ]
    invoke = direct_invoker(NluAnalyzer(), cases)

    for index in range(len(cases)):
        invoke(index)


def test_explicitly_unsupported_cases_remain_unsupported():
    for case in load_edge_cases():
        if case["triage"] == "UNSUPPORTED":
            assert case["expected"] == {
                "decision": "UNSUPPORTED",
                "taskType": None,
                "parameters": {},
            }
