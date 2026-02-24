"""
Batched FinBERT inference for financial text sentiment scoring.
Runs synchronously in a thread pool to avoid blocking the async event loop.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import torch
import torch.nn.functional as F

from backend.models.sentiment import SentimentResult
from backend.sentiment.finbert_loader import LABEL_MAP, FinBERTLoader

logger = logging.getLogger(__name__)

# Single worker — FinBERT is not thread-safe for concurrent forward passes
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="finbert")


class SentimentScorer:
    """
    Async-compatible FinBERT sentiment scorer.

    Usage:
        scorer = SentimentScorer(finbert_loader)
        results = await scorer.score_texts_async(["Apple reported strong earnings..."])
    """

    def __init__(self, loader: FinBERTLoader):
        self.loader = loader

    def _score_batch_sync(self, texts: list[str]) -> list[SentimentResult]:
        """
        Synchronous batch inference. Called in thread pool from async code.
        Processes texts in batches of FINBERT_BATCH_SIZE.
        """
        if not self.loader.is_loaded():
            logger.warning("FinBERT not loaded — returning neutral scores")
            return [_neutral_result(t) for t in texts]

        results: list[SentimentResult] = []
        batch_size = self.loader.settings.FINBERT_BATCH_SIZE
        max_length = self.loader.settings.FINBERT_MAX_LENGTH

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            try:
                encoded = self.loader.tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=max_length,
                    return_tensors="pt",
                )
                encoded = {k: v.to(self.loader.device) for k, v in encoded.items()}

                with torch.no_grad():
                    outputs = self.loader.model(**encoded)
                    probs = F.softmax(outputs.logits, dim=-1)

                for j, text in enumerate(batch):
                    p = probs[j].tolist()
                    pos, neg, neu = p[0], p[1], p[2]
                    compound = round(pos - neg, 4)
                    label = LABEL_MAP[int(torch.argmax(probs[j]).item())]
                    results.append(
                        SentimentResult(
                            text=text[:200],
                            positive=round(pos, 4),
                            negative=round(neg, 4),
                            neutral=round(neu, 4),
                            compound_score=compound,
                            label=label,
                        )
                    )
            except Exception as e:
                logger.error("FinBERT batch inference error: %s", e)
                results.extend([_neutral_result(t) for t in batch])

        return results

    async def score_texts_async(self, texts: list[str]) -> list[SentimentResult]:
        """Async wrapper: runs FinBERT in thread pool, returns SentimentResult list."""
        if not texts:
            return []
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, self._score_batch_sync, texts)

    async def score_single_async(self, text: str) -> SentimentResult:
        """Convenience method for scoring a single text."""
        results = await self.score_texts_async([text])
        return results[0] if results else _neutral_result(text)


def _neutral_result(text: str) -> SentimentResult:
    return SentimentResult(
        text=text[:200],
        positive=0.33,
        negative=0.33,
        neutral=0.34,
        compound_score=0.0,
        label="neutral",
    )
