import pytest

from scripts.benchmark_summary import (
    BenchmarkReport,
    build_document,
    percentile,
    run_benchmark,
    threshold_failures,
)


def report(**overrides) -> BenchmarkReport:
    values = {
        "mode": "direct",
        "resourceScope": "nlu_process",
        "inputChars": 500,
        "requests": 4,
        "warmupRequests": 2,
        "concurrency": 2,
        "failures": 0,
        "wallTimeSeconds": 0.1,
        "cpuTimeSeconds": 0.1,
        "throughputRps": 40.0,
        "p50Ms": 2.0,
        "p95Ms": 3.0,
        "maxMs": 3.0,
        "peakRssMb": 100.0,
    }
    values.update(overrides)
    return BenchmarkReport(**values)


@pytest.mark.parametrize("target_chars", [150, 500, 2000, 8000])
def test_build_document_produces_summarizable_bounded_workload(target_chars):
    document = build_document(target_chars)

    assert len(document) == target_chars
    assert "한국어" in document or "프로젝트" in document


@pytest.mark.parametrize(
    ("values", "quantile", "expected"),
    [
        ([1.0, 2.0, 3.0, 4.0], 0.50, 2.0),
        ([1.0, 2.0, 3.0, 4.0], 0.95, 4.0),
        ([7.0], 0.95, 7.0),
    ],
)
def test_percentile_uses_nearest_rank(values, quantile, expected):
    assert percentile(values, quantile) == expected


def test_run_benchmark_counts_success_and_failure_without_logging_payload():
    invoked = []

    def invoke(index: int) -> None:
        invoked.append(index)
        if index == 2:
            raise RuntimeError("sensitive source text")

    measured = run_benchmark(
        invoke,
        mode="direct",
        input_chars=500,
        requests=4,
        concurrency=2,
        warmup_requests=2,
    )

    assert invoked[:2] == [-1, -2]
    assert measured.requests == 4
    assert measured.warmupRequests == 2
    assert measured.resourceScope == "nlu_process"
    assert measured.failures == 1
    assert measured.throughputRps > 0
    assert measured.p95Ms >= measured.p50Ms
    assert measured.peakRssMb > 0


def test_thresholds_are_opt_in_and_report_all_violations():
    measured = report(failures=1, p95Ms=12.0, throughputRps=4.0)

    assert threshold_failures([measured], max_p95_ms=None, min_throughput_rps=None) == [
        "direct/500chars: 1 requests failed"
    ]
    assert threshold_failures([measured], max_p95_ms=10.0, min_throughput_rps=5.0) == [
        "direct/500chars: 1 requests failed",
        "direct/500chars: p95 12.0ms exceeds 10.0ms",
        "direct/500chars: throughput 4.0rps is below 5.0rps",
    ]
