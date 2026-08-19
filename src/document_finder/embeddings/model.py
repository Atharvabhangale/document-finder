"""Lazy, reusable Qwen3-Embedding model wrapper."""

from __future__ import annotations

import json
from collections.abc import Sequence
from functools import lru_cache
from typing import Protocol

import numpy as np


class EmbeddingModel(Protocol):
    model_name: str

    @property
    def configuration(self) -> dict[str, object]: ...

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray: ...

    def embed_queries(self, texts: Sequence[str]) -> np.ndarray: ...


class QwenEmbeddingModel:
    """Qwen3 embedding model, loaded once per process on first use."""

    model_name = "Qwen/Qwen3-Embedding-0.6B"
    query_instruction = "Given a user query, retrieve relevant process-document passages."

    def __init__(self, batch_size: int = 8, max_length: int = 4096):
        self.batch_size = batch_size
        self.max_length = max_length
        self._tokenizer = None
        self._model = None
        self._torch = None

    @property
    def configuration(self) -> dict[str, object]:
        return {
            "model_name": self.model_name,
            "batch_size": self.batch_size,
            "max_length": self.max_length,
            "pooling": "last_token",
            "normalize": True,
            "query_instruction": self.query_instruction,
        }

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            import torch
            import transformers
            from transformers import AutoModel, AutoTokenizer
        except ImportError as error:
            raise RuntimeError(
                "Vector retrieval requires torch, transformers, and faiss-cpu. "
                "Install with: python -m pip install -e '.[vector]'"
            ) from error
        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name, padding_side="left")
        self._model = AutoModel.from_pretrained(self.model_name, torch_dtype="auto")
        self._model.eval()
        self._transformers_version = transformers.__version__

    def _encode(self, texts: Sequence[str]) -> np.ndarray:
        self._load()
        assert self._tokenizer is not None and self._model is not None and self._torch is not None
        embeddings: list[np.ndarray] = []
        with self._torch.inference_mode():
            for offset in range(0, len(texts), self.batch_size):
                batch = list(texts[offset:offset + self.batch_size])
                encoded = self._tokenizer(batch, padding=True, truncation=True, max_length=self.max_length, return_tensors="pt")
                output = self._model(**encoded).last_hidden_state
                attention_mask = encoded["attention_mask"]
                last_positions = attention_mask.sum(dim=1) - 1 if self._tokenizer.padding_side == "right" else -1
                if isinstance(last_positions, int):
                    pooled = output[:, last_positions]
                else:
                    pooled = output[self._torch.arange(output.shape[0]), last_positions]
                pooled = self._torch.nn.functional.normalize(pooled, p=2, dim=1)
                embeddings.append(pooled.float().cpu().numpy())
        return np.vstack(embeddings).astype(np.float32)

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode(texts)

    def embed_queries(self, texts: Sequence[str]) -> np.ndarray:
        prefixed = [f"Instruct: {self.query_instruction}\nQuery: {text}" for text in texts]
        return self._encode(prefixed)


@lru_cache(maxsize=1)
def get_default_model() -> QwenEmbeddingModel:
    return QwenEmbeddingModel()


def configuration_key(model: EmbeddingModel) -> str:
    return json.dumps(model.configuration, sort_keys=True, separators=(",", ":"))
