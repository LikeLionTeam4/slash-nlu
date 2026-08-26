import pytest
from fastapi.testclient import TestClient

from main import app


SUMMARY_PATH = "/internal/v1/nlu/summaries/extractive"


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def summary_text() -> str:
    return (
        "프로젝트 팀은 사용자 요청을 빠르게 분류하는 자연어 서비스를 개발했습니다. "
        "규칙 분석기는 명확한 명령을 먼저 처리해서 불필요한 모델 호출을 줄입니다. "
        "파일 검색은 검색어와 날짜 범위를 추출하고 실제 파일 경로는 서버로 보내지 않습니다. "
        "날씨 요청은 지역 이름을 추출한 뒤 백엔드가 외부 날씨 서비스를 호출합니다. "
        "긴 문서 요약은 입력 길이와 품질을 검사한 다음 중요한 문장을 선택합니다. "
        "CPU 요약은 GPU 서버가 준비되지 않은 상황에서도 빠른 결과를 제공할 수 있습니다. "
        "모든 결과는 API에서 다시 검증하고 작업 상태와 함께 안전하게 저장합니다. "
        "팀은 실제 실패 사례를 회귀 테스트로 추가해 같은 문제가 반복되지 않도록 관리합니다."
    )


def post_summary(client: TestClient, text: str):
    return client.post(
        SUMMARY_PATH,
        json={"requestId": "correlation-1", "taskId": "task-1", "text": text},
    )


def test_extractive_summary_returns_traceable_deterministic_result(client):
    source = summary_text()
    response = post_summary(client, source)

    assert response.status_code == 200
    body = response.json()
    assert body["requestId"] == "correlation-1"
    assert body["taskId"] == "task-1"
    assert body["engine"] == "EXTRACTIVE"
    assert body["algorithm"] == "TFIDF_CENTROID"
    assert body["algorithmVersion"] == "2"
    assert body["inputSentenceCount"] == 8
    assert 1 <= body["outputSentenceCount"] <= 3
    assert body["durationMs"] >= 0
    assert body["summary"]
    assert body["summary"] in source or all(
        sentence.strip() in source for sentence in body["summary"].split(". ")
    )


def test_extractive_summary_falls_back_to_punctuation_for_english_sentences(client):
    source = (
        "The project team built a natural language service for user commands. "
        "Clear slash commands are handled before complex language analysis. "
        "File searches extract a query without exposing private local paths. "
        "Weather requests extract a location before the backend calls an external provider. "
        "Long documents are summarized by selecting important source sentences. "
        "Every result is validated before it is stored by the backend."
    )

    response = post_summary(client, source)

    assert response.status_code == 200
    assert response.json()["inputSentenceCount"] == 6


def test_extractive_summary_keeps_explicit_decisions_owners_and_deadlines(client):
    source = (
        "오늘 회의에서는 신규 배포 일정과 담당 업무를 논의했습니다. "
        "지난주 테스트에서는 로그인 오류가 두 건 발견되었습니다. "
        "로그인 오류는 인증 토큰 갱신 순서가 잘못된 것이 원인이었습니다. "
        "수정 코드는 수요일까지 반영하기로 결정했습니다. "
        "배포는 금요일 오후 세 시에 진행하기로 확정했습니다. "
        "민수는 배포 체크리스트를 작성하고 지수는 고객 공지를 준비합니다. "
        "다음 회의는 다음 주 월요일 오전 열 시입니다. "
        "배포 이후 한 시간 동안 오류율과 응답 시간을 집중 관찰합니다."
    )

    response = post_summary(client, source)

    assert response.status_code == 200
    summary = response.json()["summary"]
    assert "수요일까지 반영하기로 결정" in summary
    assert "금요일 오후 세 시에 진행하기로 확정" in summary
    assert response.json()["outputSentenceCount"] == 3


@pytest.mark.parametrize(
    ("text", "error_code"),
    [
        ("짧은 요약 대상입니다.", "INPUT_TOO_SHORT"),
        ("가" * 8001, "INPUT_TOO_LONG"),
        (("하하하하하하ㅏㅎ" * 30) + ". " + ("하하하하하하ㅏㅎ" * 30) + ".", "INPUT_NOT_SUMMARIZABLE"),
    ],
)
def test_extractive_summary_rejects_invalid_input_with_stable_error_contract(client, text, error_code):
    response = post_summary(client, text)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == error_code
    assert response.json()["error"]["retryable"] is False
    assert response.json()["requestId"] == "correlation-1"
    assert response.json()["taskId"] == "task-1"


@pytest.mark.parametrize("field", ["requestId", "taskId"])
def test_extractive_summary_rejects_blank_trace_identifiers(client, field):
    payload = {"requestId": "correlation-1", "taskId": "task-1", "text": summary_text()}
    payload[field] = "   "

    assert client.post(SUMMARY_PATH, json=payload).status_code == 422


def test_openapi_exposes_extractive_summary_contract():
    schema = app.openapi()
    operation = schema["paths"][SUMMARY_PATH]["post"]

    assert {"200", "400", "422"} <= set(operation["responses"])
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ExtractiveSummaryResponse"
    )
    assert operation["responses"]["400"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/SummaryErrorResponse"
    )
