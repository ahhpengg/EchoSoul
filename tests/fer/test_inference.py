"""Tests for src.fer.inference.

The out-of-scope gate (C6) is tested by monkeypatching ``predict`` so no model
load is needed. A real forward pass is tested only when both TensorFlow and the
trained ``models/fer_model.keras`` are available; otherwise those tests skip
(mirroring how the DB tests skip when MySQL is unreachable).
"""

from __future__ import annotations

import base64
from pathlib import Path

import numpy as np
import pytest

FIXTURE_HAPPY = Path(__file__).resolve().parents[1] / "fixtures" / "images" / "happy_face.png"

# Importing inference pulls in src.fer.model -> tensorflow. Skip the whole
# module cleanly if TF is not installed in this environment.
try:
    from src.fer import inference

    _TF_AVAILABLE = True
except Exception:  # noqa: BLE001
    inference = None
    _TF_AVAILABLE = False

pytestmark = pytest.mark.skipif(not _TF_AVAILABLE, reason="tensorflow not installed")


def _fake_probs(label: str) -> tuple[str, float, dict]:
    from src.fer.model import EMOTION_LABELS

    probs = {lbl: 0.0 for lbl in EMOTION_LABELS}
    probs[label] = 0.87
    return label, 0.87, probs


# --- C6: out-of-scope gate (mocked predict) --------------------------------


def test_in_scope_emotion_returns_ok(monkeypatch):
    monkeypatch.setattr(inference, "predict", lambda t: _fake_probs("happy"))
    res = inference.predict_in_scope(np.zeros((300, 300, 1), np.float32))
    assert res["status"] == "ok"
    assert res["emotion"] == "happy"
    assert res["confidence"] == pytest.approx(0.87)


@pytest.mark.parametrize("label", ["fear", "disgust"])
def test_out_of_scope_emotion_flagged(monkeypatch, label):
    monkeypatch.setattr(inference, "predict", lambda t: _fake_probs(label))
    res = inference.predict_in_scope(np.zeros((300, 300, 1), np.float32))
    assert res["status"] == "out_of_scope"
    assert res["detected"] == label
    assert "emotion" not in res


def test_all_in_scope_labels_pass(monkeypatch):
    for label in inference.IN_SCOPE:
        monkeypatch.setattr(inference, "predict", lambda t, lb=label: _fake_probs(lb))
        assert inference.predict_in_scope(np.zeros((300, 300, 1), np.float32))["status"] == "ok"


# --- C5: real model load + forward pass (needs the trained artefact) -------


@pytest.mark.skipif(
    _TF_AVAILABLE and not inference.MODEL_PATH.exists(),
    reason="models/fer_model.keras not present",
)
def test_real_model_predict_structure():
    tensor = np.zeros((300, 300, 1), dtype="float32")
    label, confidence, all_probs = inference.predict(tensor)

    assert label in inference.EMOTION_LABELS
    assert 0.0 <= confidence <= 1.0
    assert set(all_probs) == set(inference.EMOTION_LABELS)
    # softmax output sums to 1
    assert sum(all_probs.values()) == pytest.approx(1.0, abs=1e-3)
    assert all_probs[label] == pytest.approx(confidence)


@pytest.mark.skipif(
    _TF_AVAILABLE and not inference.MODEL_PATH.exists(),
    reason="models/fer_model.keras not present",
)
def test_warmup_runs():
    inference.warmup()  # should not raise


# --- Full pipeline integration: real happy-face photo -> "happy" ------------


@pytest.mark.skipif(
    _TF_AVAILABLE and (not inference.MODEL_PATH.exists() or not FIXTURE_HAPPY.exists()),
    reason="model or happy_face fixture not present",
)
def test_happy_fixture_end_to_end():
    from src.fer import image_pipeline as ip

    b64 = base64.b64encode(FIXTURE_HAPPY.read_bytes()).decode()
    piped = ip.process(b64)
    assert piped["status"] == "ok", f"pipeline failed: {piped}"

    result = inference.predict_in_scope(piped["tensor"])
    assert result["status"] == "ok", f"expected in-scope, got: {result}"
    assert (
        result["emotion"] == "happy"
    ), f"expected happy, got {result['emotion']} (probs: {result['all_probs']})"
