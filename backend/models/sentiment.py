from typing import Optional

from pydantic import BaseModel


class NewsArticle(BaseModel):
    title: str
    description: Optional[str] = None
    content: Optional[str] = None
    url: str = ""
    published_at: str = ""
    source: str = ""


class SentimentResult(BaseModel):
    text: str
    positive: float
    negative: float
    neutral: float
    compound_score: float   # positive - negative, range -1 to 1
    label: str              # "positive", "negative", "neutral"


class ArticleSentiment(BaseModel):
    headline: str
    url: str = ""
    published_at: str = ""
    source: str = ""
    positive: float
    negative: float
    neutral: float
    label: str  # "positive" | "negative" | "neutral"


class TickerSentiment(BaseModel):
    symbol: str
    articles_analyzed: int
    avg_positive: float
    avg_negative: float
    avg_neutral: float
    avg_compound: float
    sentiment_label: str    # aggregated dominant label
    sentiment_score: float  # normalized 0-100 (50 = neutral)
    top_headlines: list[str]
    analyzed_at: str
    article_sentiments: list[ArticleSentiment] = []
