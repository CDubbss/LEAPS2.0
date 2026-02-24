"""
Aggregates per-article SentimentResult objects into a single TickerSentiment.
"""

from datetime import datetime

from backend.models.sentiment import ArticleSentiment, NewsArticle, SentimentResult, TickerSentiment


class SentimentAggregator:
    """
    Aggregation strategy:
    - Compute mean of positive / negative / neutral across all articles
    - Compound score = avg_positive - avg_negative (range -1 to 1)
    - Sentiment score normalized to 0-100: ((compound + 1) / 2) * 100
      (maps -1 → 0, 0 → 50, +1 → 100)
    - Dominant label = whichever of pos/neg/neu has the highest average
    """

    def aggregate(
        self,
        symbol: str,
        results: list[SentimentResult],
        articles: list[NewsArticle] | None = None,
        headlines: list[str] | None = None,
    ) -> TickerSentiment:
        if not results:
            return _neutral_ticker_sentiment(symbol, headlines or [])

        n = len(results)
        avg_pos = sum(r.positive for r in results) / n
        avg_neg = sum(r.negative for r in results) / n
        avg_neu = sum(r.neutral for r in results) / n
        avg_compound = avg_pos - avg_neg

        # Dominant label
        scores = {"positive": avg_pos, "negative": avg_neg, "neutral": avg_neu}
        dominant = max(scores, key=lambda k: scores[k])

        # Normalize to 0-100
        sentiment_score = round(((avg_compound + 1) / 2) * 100, 2)

        # Build per-article breakdown
        article_sentiments = []
        for i, result in enumerate(results):
            art = articles[i] if articles and i < len(articles) else None
            article_sentiments.append(ArticleSentiment(
                headline=art.title if art else result.text[:100],
                url=art.url if art else "",
                published_at=art.published_at if art else "",
                source=art.source if art else "",
                positive=round(result.positive, 4),
                negative=round(result.negative, 4),
                neutral=round(result.neutral, 4),
                label=result.label,
            ))

        return TickerSentiment(
            symbol=symbol,
            articles_analyzed=n,
            avg_positive=round(avg_pos, 4),
            avg_negative=round(avg_neg, 4),
            avg_neutral=round(avg_neu, 4),
            avg_compound=round(avg_compound, 4),
            sentiment_label=dominant,
            sentiment_score=sentiment_score,
            top_headlines=(headlines or [])[:5],
            analyzed_at=datetime.utcnow().isoformat(),
            article_sentiments=article_sentiments,
        )

    async def aggregate_batch(
        self,
        symbol_texts: dict[str, list[str]],
        scorer,  # SentimentScorer
    ) -> dict[str, TickerSentiment]:
        """
        Score and aggregate for multiple symbols efficiently.
        Collects all texts, runs one big batch, then splits back by symbol.
        """
        import asyncio

        symbols = list(symbol_texts.keys())
        all_texts = []
        offsets: list[tuple[str, int, int]] = []  # (symbol, start, end)

        for symbol in symbols:
            texts = symbol_texts[symbol]
            start = len(all_texts)
            all_texts.extend(texts)
            offsets.append((symbol, start, len(all_texts)))

        all_results = await scorer.score_texts_async(all_texts)

        output = {}
        for symbol, start, end in offsets:
            slice_results = all_results[start:end]
            output[symbol] = self.aggregate(symbol=symbol, results=slice_results)

        return output


def _neutral_ticker_sentiment(symbol: str, headlines: list[str]) -> TickerSentiment:
    return TickerSentiment(
        symbol=symbol,
        articles_analyzed=0,
        avg_positive=0.33,
        avg_negative=0.33,
        avg_neutral=0.34,
        avg_compound=0.0,
        sentiment_label="neutral",
        sentiment_score=50.0,
        top_headlines=headlines[:5],
        analyzed_at=datetime.utcnow().isoformat(),
    )
