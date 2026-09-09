"""The two text scanners input screening runs: the PIGuard model, and Unicode."""

from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Protocol

import numpy as np

try:
    import onnxruntime
    from tokenizers import Tokenizer
except ModuleNotFoundError as missing:
    msg = "assistant-core[screening] is required to run input screening"
    raise ModuleNotFoundError(msg) from missing


class TextScanner(Protocol):
    """Classifies one text. Answers the text, whether it passes, and the risk."""

    def scan(self, text: str) -> tuple[str, bool, float]: ...


# Unicode categories that indicate invisible / control characters.
_INVISIBLE_CATEGORIES = frozenset({"Cf", "Co", "Cn"})


class PIGuardScanner:
    """Prompt-injection detection with the PIGuard ONNX model.

    Inference uses NumPy only. There is no runtime dependency on PyTorch.
    The caller names the directory that holds ``model.onnx`` and
    ``tokenizer.json``.
    """

    def __init__(self, model_dir: Path, threshold: float = 0.70) -> None:
        model_path = model_dir / "model.onnx"
        tokenizer_path = model_dir / "tokenizer.json"

        self._session = onnxruntime.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )
        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self._tokenizer.enable_truncation(max_length=512)
        self._tokenizer.enable_padding(pad_id=0, pad_token="[PAD]", length=512)
        self._threshold = threshold

    def scan(self, text: str) -> tuple[str, bool, float]:
        """Classify the text as benign or as an injection."""
        encoded = self._tokenizer.encode(text)
        input_ids = np.array([encoded.ids], dtype=np.int64)
        attention_mask = np.array([encoded.attention_mask], dtype=np.int64)

        raw_output = self._session.run(
            None,
            {"input_ids": input_ids, "attention_mask": attention_mask},
        )
        logits = np.asarray(raw_output[0])

        # Row-wise softmax gives the injection probability.
        shifted = logits - logits.max(axis=1, keepdims=True)
        exp = np.exp(shifted)
        probs = exp / exp.sum(axis=1, keepdims=True)
        injection_score = round(float(probs[0][1]), 4)
        is_valid = injection_score < self._threshold
        return text, is_valid, injection_score


class InvisibleTextScanner:
    """Detect and remove invisible Unicode characters.

    Format, private-use and unassigned characters count as invisible.
    """

    def scan(self, text: str) -> tuple[str, bool, float]:
        # ASCII text has no invisible characters.
        if text.isascii():
            return text, True, 0.0

        has_invisible = any(
            unicodedata.category(ch) in _INVISIBLE_CATEGORIES for ch in text
        )
        if not has_invisible:
            return text, True, 0.0

        cleaned = "".join(
            ch for ch in text if unicodedata.category(ch) not in _INVISIBLE_CATEGORIES
        )
        return cleaned, False, 1.0
