"""
FinBERT model loader.
Loads ProsusAI/finbert from HuggingFace Hub once at startup.
Model is cached locally in ~/.cache/huggingface/ after first download (~450MB).

Setup (run once before starting the server):
    pip install torch --index-url https://download.pytorch.org/whl/cpu
    pip install transformers tokenizers
    python -c "from backend.sentiment.finbert_loader import FinBERTLoader; FinBERTLoader().load(); print('OK')"
"""

import logging

import torch
from transformers import BertForSequenceClassification, BertTokenizer

from backend.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

# ProsusAI/finbert label order: index 0=positive, 1=negative, 2=neutral
LABEL_MAP = {0: "positive", 1: "negative", 2: "neutral"}


class FinBERTLoader:
    """
    Manages loading and lifecycle of the ProsusAI/finbert model.
    Call load() once during FastAPI startup (lifespan context manager).
    Holds model in memory for the duration of the application.
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.tokenizer: BertTokenizer | None = None
        self.model: BertForSequenceClassification | None = None
        self.device = torch.device(self.settings.FINBERT_DEVICE)

    def load(self) -> None:
        """
        Download (if needed) and load FinBERT model into memory.
        First run downloads ~450MB to ~/.cache/huggingface/
        Subsequent runs load from local cache (fast).
        """
        model_name = self.settings.FINBERT_MODEL_NAME
        logger.info("Loading FinBERT model: %s (device=%s)", model_name, self.device)

        self.tokenizer = BertTokenizer.from_pretrained(model_name)
        self.model = BertForSequenceClassification.from_pretrained(model_name)
        self.model.to(self.device)
        self.model.eval()

        logger.info("FinBERT loaded successfully — %d parameters", self._param_count())

    def is_loaded(self) -> bool:
        return self.model is not None and self.tokenizer is not None

    def _param_count(self) -> int:
        if self.model is None:
            return 0
        return sum(p.numel() for p in self.model.parameters())

    def unload(self) -> None:
        """Release model memory (call during shutdown)."""
        self.model = None
        self.tokenizer = None
        if self.device.type == "cuda":
            torch.cuda.empty_cache()
        logger.info("FinBERT unloaded")
