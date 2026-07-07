"""FER model inference + out-of-scope filtering.

Loads the trained ``models/fer_model.keras`` once and exposes:
    - get_model() / warmup() : lazy singleton load + first-call graph warm-up
    - predict()              : (label, confidence, all_probs) from a model tensor
    - predict_in_scope()     : wraps predict() with the 5-vs-7 scope gate (C6)

The label order (``EMOTION_LABELS``) and input shape are imported from
``src.fer.model`` so there is a single source of truth. The tensor fed to
``predict`` is the ``(300, 300, 1)`` float32 ``[0, 255]`` array produced by
``src.fer.image_pipeline`` — see docs/FER_MODEL.md for the input contract.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from src.fer.model import EMOTION_LABELS, IN_SCOPE, INPUT_SHAPE

MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "fer_model.keras"

_model = None


def get_model():
    """Load and cache the trained model (Keras v3, no optimiser needed for inference).

    Raises:
        FileNotFoundError: if ``models/fer_model.keras`` is missing.
    """
    global _model
    if _model is None:
        import tensorflow as tf

        if not MODEL_PATH.exists():
            raise FileNotFoundError(
                f"Model file not found: {MODEL_PATH}. Train it via "
                "scripts/train_fer_model.py or drop fer_model.keras into models/."
            )
        _model = tf.keras.models.load_model(MODEL_PATH, compile=False)
    return _model


def warmup() -> None:
    """Run one dummy inference to amortise the ~2-3 s first-call graph build.

    Call once at app startup after loading the model.
    """
    dummy = np.zeros((1, *INPUT_SHAPE), dtype="float32")
    get_model().predict(dummy, verbose=0)


def predict(tensor: np.ndarray) -> tuple[str, float, dict[str, float]]:
    """Classify one preprocessed face tensor.

    Args:
        tensor: ``(300, 300, 1)`` float32 array in ``[0, 255]`` (unbatched), as
            returned by ``image_pipeline.to_model_tensor``. No preprocess_input.

    Returns:
        ``(predicted_label, confidence, {label: prob, ...})``.
    """
    batch = np.asarray(tensor, dtype="float32")[np.newaxis, ...]  # (1, 300, 300, 1)
    probs = get_model().predict(batch, verbose=0)[0]  # (7,)
    idx = int(probs.argmax())
    all_probs = {EMOTION_LABELS[i]: float(probs[i]) for i in range(len(EMOTION_LABELS))}
    return EMOTION_LABELS[idx], float(probs[idx]), all_probs


def predict_in_scope(tensor: np.ndarray) -> dict:
    """Predict, then apply the application-layer 5-emotion scope gate.

    fear / disgust are valid model outputs but out of scope for music
    recommendation, so they resolve to an ``out_of_scope`` status the UI routes
    to the error page.
    """
    label, confidence, all_probs = predict(tensor)
    if label not in IN_SCOPE:
        return {
            "status": "out_of_scope",
            "detected": label,
            "confidence": confidence,
            "all_probs": all_probs,
        }
    return {
        "status": "ok",
        "emotion": label,
        "confidence": confidence,
        "all_probs": all_probs,
    }
