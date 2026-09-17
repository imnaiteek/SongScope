"""Uniform confidence/certainty vocabulary shared by all analysis modules.

Status semantics:
  detected  - direct measurement of the signal (duration, LUFS, spectrum)
  estimated - statistical estimate from the signal (tempo, key, pitch)
  inferred  - derived from other estimates via musical heuristics (section labels,
              Roman numerals, drum pattern)
  uncertain - any estimate whose confidence is too low to be trusted
"""

from __future__ import annotations

import math

HIGH = 0.75
MEDIUM = 0.5
LOW_CONFIDENCE_NOTE = "Low confidence — verify manually."


def clamp01(x: float) -> float:
    if x is None or not math.isfinite(x):
        return 0.0
    return float(min(1.0, max(0.0, x)))


def level(conf: float) -> str:
    conf = clamp01(conf)
    if conf >= HIGH:
        return "high"
    if conf >= MEDIUM:
        return "medium"
    return "low"


def status_for(conf: float, kind: str) -> str:
    """kind is the nominal status ('detected' | 'estimated' | 'inferred')."""
    if kind == "detected":
        return "detected"
    return "uncertain" if clamp01(conf) < MEDIUM else kind


def annotate(block: dict, conf: float, kind: str, message: str | None = None) -> dict:
    conf = clamp01(conf)
    block["confidence"] = round(conf, 3)
    block["confidence_level"] = level(conf)
    block["status"] = status_for(conf, kind)
    if message is None and block["confidence_level"] == "low" and kind != "detected":
        message = LOW_CONFIDENCE_NOTE
    block["message"] = message
    return block


def unavailable(message: str) -> dict:
    return {
        "available": False,
        "confidence": 0.0,
        "confidence_level": "low",
        "status": "uncertain",
        "message": message,
    }
