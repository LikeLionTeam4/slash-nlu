"""NLU 혼합 분류의 정확도와 반복·동시 실행 성능을 JSON으로 출력한다."""

from __future__ import annotations

import argparse
import json
import math
import resource
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analyzer import NluAnalyzer  # noqa: E402
from models import AnalyzeRequest, AnalyzeResponse  # noqa: E402


ANALYZE_PATH = "/internal/v1/nlu/analyze"
DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "analyzer_benchmark_cases.json"


class ClassificationMismatch(RuntimeError):
    """분류 결과가 fixture의 계약과 다를 때 사용한다."""


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    request: dict[str, Any]
    expected: dict[str, Any]


@dataclass(frozen=True)
class BenchmarkReport:
    mode: str
    resourceScope: str
    cases: int
    requests: int
    warmupRequests: int
    concurrency: int
    failures: int
    mismatches: int
    wallTimeSeconds: float
    cpuTimeSeconds: float
    throughputRps: float
    p50Ms: float
    p95Ms: float
    maxMs: float
    peakRssMb: float


def load_cases(path: Path = DEFAULT_FIXTURE) -> list[BenchmarkCase]:
    raw_cases = json.loads(path.read_text(encoding="utf-8"))
    cases = [BenchmarkCase(**item) for item in raw_cases]
    if not cases:
        raise ValueError("benchmark fixture must not be empty")
    return cases


def percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("values must not be empty")
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be between 0 and 1")
    ordered = sorted(values)
    rank = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[rank]


def peak_rss_mb() -> float:
    raw = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return raw / (1024 * 1024) if sys.platform == "darwin" else raw / 1024


def assert_expected(case: BenchmarkCase, response: dict[str, Any]) -> None:
    mismatched = []
    if response.get("requestId") != case.request.get("requestId"):
        mismatched.append("requestId")
    mismatched.extend(
        key for key, expected_value in case.expected.items() if response.get(key) != expected_value
    )
    if mismatched:
        fields = ", ".join(sorted(mismatched))
        raise ClassificationMismatch(f"{case.name}: mismatched fields: {fields}")


def direct_invoker(analyzer: NluAnalyzer, cases: Sequence[BenchmarkCase]) -> Callable[[int], None]:
    def invoke(index: int) -> None:
        case = cases[index % len(cases)]
        payload = AnalyzeRequest.model_validate(case.request)
        if payload.now is None:
            raise ValueError(f"{case.name}: fixture request must include now")
        if payload.command is not None:
            result = analyzer.analyze_slash(payload.requestId, payload.command, payload.now)
        elif payload.text is not None:
            result = analyzer.analyze_text(payload.requestId, payload.text, payload.now)
        else:
            raise ValueError(f"{case.name}: text or command is required")
        assert_expected(case, result.model_dump(mode="json"))

    return invoke


def http_invoker(
    base_url: str,
    cases: Sequence[BenchmarkCase],
    timeout_seconds: float,
) -> tuple[httpx.Client, Callable[[int], None]]:
    client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout_seconds)

    def invoke(index: int) -> None:
        case = cases[index % len(cases)]
        response = client.post(ANALYZE_PATH, json=case.request)
        response.raise_for_status()
        parsed = AnalyzeResponse.model_validate(response.json()).model_dump(mode="json")
        assert_expected(case, parsed)

    return client, invoke


def run_benchmark(
    invoke: Callable[[int], None],
    *,
    mode: str,
    case_count: int,
    requests: int,
    concurrency: int,
    warmup_requests: int = 0,
) -> BenchmarkReport:
    if requests < 1 or case_count < 1:
        raise ValueError("requests and case_count must be positive")
    if concurrency < 1:
        raise ValueError("concurrency must be positive")
    if warmup_requests < 0:
        raise ValueError("warmup_requests must not be negative")

    for index in range(warmup_requests):
        invoke(index)

    latencies: list[float] = []
    failures = 0
    mismatches = 0
    wall_started = time.perf_counter()
    cpu_started = time.process_time()

    def measured(index: int) -> float:
        started = time.perf_counter()
        invoke(index)
        return (time.perf_counter() - started) * 1000

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(measured, index) for index in range(requests)]
        for future in as_completed(futures):
            try:
                latencies.append(future.result())
            except ClassificationMismatch:
                mismatches += 1
            except Exception:  # 원문·응답 본문은 출력하지 않고 실패 수만 집계한다.
                failures += 1

    wall_time = max(time.perf_counter() - wall_started, 1e-9)
    cpu_time = max(time.process_time() - cpu_started, 0.0)
    successful = len(latencies)
    if successful == 0:
        raise RuntimeError(f"all {requests} benchmark requests failed")

    return BenchmarkReport(
        mode=mode,
        resourceScope="nlu_process" if mode == "direct" else "load_generator",
        cases=case_count,
        requests=requests,
        warmupRequests=warmup_requests,
        concurrency=concurrency,
        failures=failures,
        mismatches=mismatches,
        wallTimeSeconds=round(wall_time, 4),
        cpuTimeSeconds=round(cpu_time, 4),
        throughputRps=round(successful / wall_time, 2),
        p50Ms=round(percentile(latencies, 0.50), 2),
        p95Ms=round(percentile(latencies, 0.95), 2),
        maxMs=round(max(latencies), 2),
        peakRssMb=round(peak_rss_mb(), 2),
    )


def threshold_failures(
    report: BenchmarkReport,
    *,
    max_p95_ms: Optional[float],
    min_throughput_rps: Optional[float],
) -> list[str]:
    failures = []
    if report.failures:
        failures.append(f"{report.failures} requests failed")
    if report.mismatches:
        failures.append(f"{report.mismatches} classification results mismatched")
    if max_p95_ms is not None and report.p95Ms > max_p95_ms:
        failures.append(f"p95 {report.p95Ms}ms exceeds {max_p95_ms}ms")
    if min_throughput_rps is not None and report.throughputRps < min_throughput_rps:
        failures.append(
            f"throughput {report.throughputRps}rps is below {min_throughput_rps}rps"
        )
    return failures


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--requests", type=positive_int, default=100)
    parser.add_argument("--concurrency", type=positive_int, default=8)
    parser.add_argument("--warmup-requests", type=int, default=10)
    parser.add_argument("--base-url", help="running NLU URL; omit for direct Python calls")
    parser.add_argument("--timeout-seconds", type=float, default=2.0)
    parser.add_argument("--max-p95-ms", type=float)
    parser.add_argument("--min-throughput-rps", type=float)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.warmup_requests < 0:
        raise SystemExit("--warmup-requests must not be negative")

    cases = load_cases(args.fixture)
    client = None
    if args.base_url:
        client, invoke = http_invoker(args.base_url, cases, args.timeout_seconds)
        mode = "http"
    else:
        invoke = direct_invoker(NluAnalyzer(), cases)
        mode = "direct"
    try:
        report = run_benchmark(
            invoke,
            mode=mode,
            case_count=len(cases),
            requests=args.requests,
            concurrency=args.concurrency,
            warmup_requests=args.warmup_requests,
        )
    finally:
        if client is not None:
            client.close()

    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    failures = threshold_failures(
        report,
        max_p95_ms=args.max_p95_ms,
        min_throughput_rps=args.min_throughput_rps,
    )
    for failure in failures:
        print(f"benchmark failed: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
