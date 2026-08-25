from dataclasses import replace

import pytest

from analyzer import NluAnalyzer
from models import Decision, TaskType
from scripts.benchmark_analyzer import (
    BenchmarkReport,
    ClassificationMismatch,
    assert_expected,
    direct_invoker,
    load_cases,
    percentile,
    run_benchmark,
    threshold_failures,
)


def report(**overrides) -> BenchmarkReport:
    base = BenchmarkReport(
        mode="direct",
        resourceScope="nlu_process",
        cases=38,
        requests=4,
        warmupRequests=2,
        concurrency=2,
        failures=0,
        mismatches=0,
        wallTimeSeconds=0.1,
        cpuTimeSeconds=0.1,
        throughputRps=40.0,
        p50Ms=2.0,
        p95Ms=3.0,
        maxMs=3.0,
        peakRssMb=100.0,
    )
    return replace(base, **overrides)


def test_fixture_covers_all_contract_types_and_decisions():
    cases = load_cases()

    assert 30 <= len(cases) <= 50
    assert {case.expected.get("taskType") for case in cases if case.expected.get("taskType")} == {
        task_type.value for task_type in TaskType
    }
    assert {case.expected["decision"] for case in cases} == {
        decision.value for decision in Decision
    }


def test_all_fixture_cases_match_direct_analyzer():
    cases = load_cases()
    invoke = direct_invoker(NluAnalyzer(), cases)

    for index in range(len(cases)):
        invoke(index)


def test_expected_contract_reports_only_field_names():
    case = load_cases()[0]

    with pytest.raises(ClassificationMismatch, match="mismatched fields: decision") as exc_info:
        assert_expected(case, {**case.expected, "decision": "UNSUPPORTED"})

    assert case.request["text"] not in str(exc_info.value)


@pytest.mark.parametrize(
    ("values", "quantile", "expected"),
    [([1.0, 2.0, 3.0, 4.0], 0.50, 2.0), ([1.0, 2.0, 3.0, 4.0], 0.95, 4.0)],
)
def test_percentile_uses_nearest_rank(values, quantile, expected):
    assert percentile(values, quantile) == expected


def test_benchmark_counts_mismatch_and_failure_without_logging_payload():
    def invoke(index: int) -> None:
        if index == 1:
            raise ClassificationMismatch("case: mismatched fields: taskType")
        if index == 2:
            raise RuntimeError("sensitive source text")

    measured = run_benchmark(
        invoke,
        mode="direct",
        case_count=38,
        requests=4,
        concurrency=2,
        warmup_requests=1,
    )

    assert measured.failures == 1
    assert measured.mismatches == 1
    assert measured.throughputRps > 0
    assert measured.p95Ms >= measured.p50Ms


def test_thresholds_are_opt_in_but_contract_errors_always_fail():
    measured = report(failures=1, mismatches=2, p95Ms=12.0, throughputRps=4.0)

    assert threshold_failures(
        measured, max_p95_ms=None, min_throughput_rps=None
    ) == [
        "1 requests failed",
        "2 classification results mismatched",
    ]
    assert threshold_failures(
        measured, max_p95_ms=10.0, min_throughput_rps=5.0
    ) == [
        "1 requests failed",
        "2 classification results mismatched",
        "p95 12.0ms exceeds 10.0ms",
        "throughput 4.0rps is below 5.0rps",
    ]
