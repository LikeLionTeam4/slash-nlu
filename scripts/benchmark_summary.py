"""CPU 추출 요약의 반복·동시 실행 성능을 재현 가능한 JSON으로 출력한다."""

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
from typing import Callable, Iterable, Optional, Sequence

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analyzer import NluAnalyzer  # noqa: E402
from summary import ExtractiveSummarizer, SUMMARY_MAX_CHARS, SUMMARY_MIN_CHARS  # noqa: E402


SUMMARY_PATH = "/internal/v1/nlu/summaries/extractive"

_SENTENCES = (
    "프로젝트 팀은 자연어 요청을 빠르게 분류하는 서비스를 개발했습니다.",
    "명확한 명령은 규칙으로 먼저 처리해 불필요한 모델 호출을 줄입니다.",
    "파일 검색은 로컬 절대 경로를 서버에 노출하지 않고 검색 결과만 반환합니다.",
    "The backend validates every result before storing the task history.",
    "CPU 요약은 Kiwi 문장 분리와 TF-IDF 중심도 점수를 사용합니다.",
    "Mixed Korean and English documents must keep stable trace identifiers.",
    "팀은 실패 사례를 회귀 테스트로 남겨 같은 문제가 반복되지 않게 관리합니다.",
    "동시 요청에서는 처리 시간과 메모리 사용량을 함께 확인해야 합니다.",
)


@dataclass(frozen=True)
class BenchmarkReport:
    mode: str
    resourceScope: str
    inputChars: int
    requests: int
    warmupRequests: int
    concurrency: int
    failures: int
    wallTimeSeconds: float
    cpuTimeSeconds: float
    throughputRps: float
    p50Ms: float
    p95Ms: float
    maxMs: float
    peakRssMb: float


def build_document(target_chars: int) -> str:
    if not SUMMARY_MIN_CHARS <= target_chars <= SUMMARY_MAX_CHARS:
        raise ValueError(
            f"target_chars must be between {SUMMARY_MIN_CHARS} and {SUMMARY_MAX_CHARS}"
        )

    chunks = []
    index = 0
    while len(" ".join(chunks)) < target_chars:
        chunks.append(_SENTENCES[index % len(_SENTENCES)])
        index += 1
    document = " ".join(chunks)[:target_chars]
    if document[-1].isspace():
        document = document[:-1] + "다"
    return document


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
    # macOS는 byte, Linux는 KiB 단위로 ru_maxrss를 반환한다.
    return raw / (1024 * 1024) if sys.platform == "darwin" else raw / 1024


def run_benchmark(
    invoke: Callable[[int], None],
    *,
    mode: str,
    input_chars: int,
    requests: int,
    concurrency: int,
    warmup_requests: int = 0,
) -> BenchmarkReport:
    if requests < 1:
        raise ValueError("requests must be positive")
    if concurrency < 1:
        raise ValueError("concurrency must be positive")
    if warmup_requests < 0:
        raise ValueError("warmup_requests must not be negative")

    for index in range(warmup_requests):
        invoke(-(index + 1))

    latencies = []
    failures = 0
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
            except Exception:  # 실패 수만 집계하고 원문·응답 본문은 출력하지 않는다.
                failures += 1

    wall_time = max(time.perf_counter() - wall_started, 1e-9)
    cpu_time = max(time.process_time() - cpu_started, 0.0)
    successful = len(latencies)
    if successful == 0:
        raise RuntimeError(f"all {requests} benchmark requests failed")

    return BenchmarkReport(
        mode=mode,
        resourceScope="nlu_process" if mode == "direct" else "load_generator",
        inputChars=input_chars,
        requests=requests,
        warmupRequests=warmup_requests,
        concurrency=concurrency,
        failures=failures,
        wallTimeSeconds=round(wall_time, 4),
        cpuTimeSeconds=round(cpu_time, 4),
        throughputRps=round(successful / wall_time, 2),
        p50Ms=round(percentile(latencies, 0.50), 2),
        p95Ms=round(percentile(latencies, 0.95), 2),
        maxMs=round(max(latencies), 2),
        peakRssMb=round(peak_rss_mb(), 2),
    )


def direct_invoker(summarizer: ExtractiveSummarizer, text: str) -> Callable[[int], None]:
    def invoke(index: int) -> None:
        summarizer.summarize(f"benchmark-request-{index}", f"benchmark-task-{index}", text)

    return invoke


def http_invoker(base_url: str, text: str, timeout_seconds: float) -> tuple[httpx.Client, Callable[[int], None]]:
    client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout_seconds)

    def invoke(index: int) -> None:
        response = client.post(
            SUMMARY_PATH,
            json={
                "requestId": f"benchmark-request-{index}",
                "taskId": f"benchmark-task-{index}",
                "text": text,
            },
        )
        response.raise_for_status()

    return client, invoke


def threshold_failures(
    reports: Iterable[BenchmarkReport],
    *,
    max_p95_ms: Optional[float],
    min_throughput_rps: Optional[float],
) -> list[str]:
    failures = []
    for report in reports:
        prefix = f"{report.mode}/{report.inputChars}chars"
        if report.failures:
            failures.append(f"{prefix}: {report.failures} requests failed")
        if max_p95_ms is not None and report.p95Ms > max_p95_ms:
            failures.append(f"{prefix}: p95 {report.p95Ms}ms exceeds {max_p95_ms}ms")
        if min_throughput_rps is not None and report.throughputRps < min_throughput_rps:
            failures.append(
                f"{prefix}: throughput {report.throughputRps}rps is below {min_throughput_rps}rps"
            )
    return failures


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=positive_int, default=20)
    parser.add_argument("--concurrency", type=positive_int, default=4)
    parser.add_argument("--warmup-requests", type=int, default=2)
    parser.add_argument(
        "--chars",
        type=positive_int,
        nargs="+",
        default=[500, 2000, 8000],
        help="input character lengths (150-8000)",
    )
    parser.add_argument("--base-url", help="running NLU URL; omit for direct Python calls")
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--max-p95-ms", type=float)
    parser.add_argument("--min-throughput-rps", type=float)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.warmup_requests < 0:
        raise SystemExit("--warmup-requests must not be negative")

    reports = []
    direct_summarizer = None
    if not args.base_url:
        analyzer = NluAnalyzer()
        direct_summarizer = ExtractiveSummarizer(analyzer.kiwi)

    for input_chars in args.chars:
        text = build_document(input_chars)
        client = None
        if args.base_url:
            client, invoke = http_invoker(args.base_url, text, args.timeout_seconds)
            mode = "http"
        else:
            invoke = direct_invoker(direct_summarizer, text)
            mode = "direct"
        try:
            reports.append(
                run_benchmark(
                    invoke,
                    mode=mode,
                    input_chars=len(text),
                    requests=args.requests,
                    concurrency=args.concurrency,
                    warmup_requests=args.warmup_requests,
                )
            )
        finally:
            if client is not None:
                client.close()

    print(json.dumps([asdict(report) for report in reports], ensure_ascii=False, indent=2))
    failures = threshold_failures(
        reports,
        max_p95_ms=args.max_p95_ms,
        min_throughput_rps=args.min_throughput_rps,
    )
    for failure in failures:
        print(f"benchmark threshold failed: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
