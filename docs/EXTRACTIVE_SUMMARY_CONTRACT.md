# CPU 추출 요약 내부 계약

GPU 모델 없이 중요한 원문 문장을 선택하는 Backend용 내부 API다. TaskType 판정은
기존 `/internal/v1/nlu/analyze`가 담당하며, 실행 위치와 Task 상태는 Backend가 결정한다.

## 요청

`POST /internal/v1/nlu/summaries/extractive`

```json
{
  "requestId": "correlation-id",
  "taskId": "task-public-id",
  "text": "요약할 원문"
}
```

- `requestId`, `taskId`: 공백이 아닌 추적 식별자
- `text`: 공백 제외 150자 이상, 전체 8000자 이하

## 성공 응답

```json
{
  "requestId": "correlation-id",
  "taskId": "task-public-id",
  "summary": "원문에서 선택한 최대 3문장",
  "engine": "EXTRACTIVE",
  "algorithm": "TFIDF_CENTROID",
  "algorithmVersion": "2",
  "inputSentenceCount": 8,
  "outputSentenceCount": 3,
  "durationMs": 18
}
```

선택된 문장은 점수 순서가 아니라 원문 순서로 반환한다. NLU는 `executionTarget`이나
`processingRoute`를 반환하지 않는다.

## 입력 오류

HTTP `400`이며 기존 slash-llm과 같은 오류 봉투를 사용한다.

```json
{
  "error": {
    "code": "INPUT_NOT_SUMMARIZABLE",
    "message": "요약할 수 있는 문장과 의미 있는 단어가 부족합니다.",
    "retryable": false
  },
  "requestId": "correlation-id",
  "taskId": "task-public-id"
}
```

| 코드 | 조건 |
|---|---|
| `INPUT_TOO_SHORT` | 공백 제외 150자 미만 |
| `INPUT_TOO_LONG` | 전체 8000자 초과 |
| `INPUT_NOT_SUMMARIZABLE` | 반복 문자 위주이거나 문장·의미 단어가 부족함 |

요청 JSON이나 추적 ID 형식이 잘못되면 FastAPI schema 오류인 HTTP `422`를 반환한다.
예상하지 못한 내부 오류는 원문을 노출하지 않고 HTTP `500`으로 처리한다.
