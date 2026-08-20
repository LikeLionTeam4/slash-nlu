import math
import re
import time
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, List

from kiwipiepy import Kiwi

from models import ExtractiveSummaryResponse


SUMMARY_MIN_CHARS = 150
SUMMARY_MAX_CHARS = 8000
SUMMARY_MAX_SENTENCES = 3

_NON_SPACE = re.compile(r"\s+")
_VISIBLE_CHARACTER = re.compile(r"[0-9A-Za-z가-힣]")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?。！？])\s+|\n+")
_CONTENT_TAG_PREFIXES = ("N", "V", "M", "SL", "SN", "XR")


@dataclass(frozen=True)
class SummaryInputError(ValueError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


class ExtractiveSummarizer:
    """Kiwi 문장 분리와 TF-IDF 중심도 점수를 쓰는 결정적 CPU 요약기."""

    def __init__(self, kiwi: Kiwi) -> None:
        self.kiwi = kiwi

    def summarize(self, request_id: str, task_id: str, text: str) -> ExtractiveSummaryResponse:
        started_at = time.perf_counter()
        normalized = text.strip()
        self._validate_length(normalized)

        sentences = self._sentences(normalized)
        tokenized = [self._content_tokens(sentence) for sentence in sentences]
        self._validate_quality(normalized, sentences, tokenized)

        selected_indexes = self._select_sentence_indexes(tokenized)
        selected = [sentences[index] for index in selected_indexes]
        return ExtractiveSummaryResponse(
            requestId=request_id,
            taskId=task_id,
            summary=" ".join(selected),
            engine="EXTRACTIVE",
            algorithm="TFIDF_CENTROID",
            algorithmVersion="1",
            inputSentenceCount=len(sentences),
            outputSentenceCount=len(selected),
            durationMs=max(0, int((time.perf_counter() - started_at) * 1000)),
        )

    @staticmethod
    def _validate_length(text: str) -> None:
        meaningful_length = len(_NON_SPACE.sub("", text))
        if meaningful_length < SUMMARY_MIN_CHARS:
            raise SummaryInputError(
                "INPUT_TOO_SHORT",
                f"요약할 내용은 공백 제외 {SUMMARY_MIN_CHARS}자 이상이어야 합니다.",
            )
        if len(text) > SUMMARY_MAX_CHARS:
            raise SummaryInputError(
                "INPUT_TOO_LONG",
                f"요약할 내용은 {SUMMARY_MAX_CHARS}자를 넘을 수 없습니다.",
            )

    def _sentences(self, text: str) -> List[str]:
        sentences = [sentence.text.strip() for sentence in self.kiwi.split_into_sents(text)]
        sentences = [sentence for sentence in sentences if sentence]
        if len(sentences) >= 2:
            return sentences

        # Kiwi는 한국어 종결 표현에 강하지만 영문 마침표 문장을 하나로 묶을 수 있다.
        # 혼합 문서까지 요약할 수 있도록 명시적인 문장부호·줄바꿈 경계를 보조로 쓴다.
        fallback = [sentence.strip() for sentence in _SENTENCE_BOUNDARY.split(text) if sentence.strip()]
        return fallback if len(fallback) > len(sentences) else sentences

    def _content_tokens(self, sentence: str) -> List[str]:
        return [
            token.form.lower()
            for token in self.kiwi.tokenize(sentence)
            if token.tag.startswith(_CONTENT_TAG_PREFIXES) and _VISIBLE_CHARACTER.search(token.form)
        ]

    @staticmethod
    def _validate_quality(text: str, sentences: List[str], tokenized: List[List[str]]) -> None:
        visible = [character.lower() for character in text if _VISIBLE_CHARACTER.fullmatch(character)]
        tokens = [token for sentence_tokens in tokenized for token in sentence_tokens]

        if len(sentences) < 2 or len(set(tokens)) < 5:
            raise SummaryInputError(
                "INPUT_NOT_SUMMARIZABLE",
                "요약할 수 있는 문장과 의미 있는 단어가 부족합니다.",
            )

        frequencies = Counter(visible)
        dominant_ratio = max(frequencies.values(), default=0) / max(1, len(visible))
        if len(set(visible)) < 6 or dominant_ratio >= 0.55:
            raise SummaryInputError(
                "INPUT_NOT_SUMMARIZABLE",
                "반복된 문자 위주의 입력은 요약할 수 없습니다.",
            )

    @staticmethod
    def _select_sentence_indexes(tokenized: List[List[str]]) -> List[int]:
        sentence_count = len(tokenized)
        document_frequency = Counter(
            token for sentence_tokens in tokenized for token in set(sentence_tokens)
        )

        scores = []
        for index, sentence_tokens in enumerate(tokenized):
            term_frequency = Counter(sentence_tokens)
            score = sum(
                frequency * (math.log((1 + sentence_count) / (1 + document_frequency[token])) + 1)
                for token, frequency in term_frequency.items()
            ) / math.sqrt(max(1, len(sentence_tokens)))
            scores.append((score, index))

        output_count = min(SUMMARY_MAX_SENTENCES, max(1, math.ceil(sentence_count * 0.3)))
        selected = sorted(scores, key=lambda item: (-item[0], item[1]))[:output_count]
        return sorted(index for _, index in selected)
