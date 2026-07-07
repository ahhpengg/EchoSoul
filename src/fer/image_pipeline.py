"""Webcam frame -> model-ready tensor pipeline for the FER model.

Stages (see docs/IMAGE_PIPELINE.md):
    1. decode base64 -> RGB
    2. MediaPipe Tasks FaceLandmarker face-count gate -- EXACTLY ONE face required
       (0 faces -> no_face, 2+ faces -> multiple_faces)
    3. align + square crop  (same algorithm/topology as scripts/align_facial_images)
    4. quality check on the 300x300 gray crop (blur / dark / bright)
    5. to (300, 300, 1) float32 tensor in [0, 255]  -- NO preprocess_input

Detection uses the MediaPipe **Tasks** ``FaceLandmarker`` (the legacy
``solutions.face_mesh`` API was removed in mediapipe 0.10.35). It returns the same
468-point face-mesh topology the training preprocessing used, so the eye-corner
and face-oval landmark indices -- and therefore the alignment/crop math -- are
unchanged. Requires the ``models/face_landmarker.task`` asset.

``mediapipe`` is imported lazily inside the detector helpers so the pure helpers
(decode, crop, quality, tensor) can be imported and tested without it.
"""

from __future__ import annotations

import base64
import io
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

# --- Alignment constants (must match scripts/align_facial_images) -----------
OUT_SIZE = 300  # final square size (EfficientNet-B3 native input)
PAD_WHITE = 255  # white for rotation borders and out-of-bounds crop padding
FACE_MARGIN = 0.01  # extra margin around the face-oval box (fraction of box size)

LEFT_EYE_IDS = [33, 133]  # eye centre = mean of the two eye-corner landmarks
RIGHT_EYE_IDS = [362, 263]

# Sorted unique vertices of MediaPipe's canonical FACEMESH_FACE_OVAL (verified to
# match mediapipe's own derivation). Hardcoded because the Tasks FaceLandmarker API
# no longer ships the FACEMESH_* connection constants; also lets align_and_crop()
# run without importing mediapipe (e.g. under mocked-detector tests).
FACE_OVAL_IDS = [
    10, 21, 54, 58, 67, 93, 103, 109, 127, 132, 136, 148, 149, 150, 152, 162,
    172, 176, 234, 251, 284, 288, 297, 323, 332, 338, 356, 361, 365, 377, 378,
    379, 389, 397, 400, 454,
]  # fmt: skip

# MediaPipe Tasks face-landmarker model bundle (see docs/IMAGE_PIPELINE.md).
MODEL_ASSET = Path(__file__).resolve().parents[2] / "models" / "face_landmarker.task"

# --- Quality-check thresholds (tune during CP2) -----------------------------
BLUR_THRESHOLD = 20.0  # Laplacian var; real webcam selfie ~41, heavy blur <10 (retune in CP2)
MIN_BRIGHTNESS = 40.0  # mean intensity (0-255); below this = too dark
MAX_BRIGHTNESS = 230.0  # mean intensity (0-255); above this = too bright


# ---------------------------------------------------------------------------
# Stage 1 - decode
# ---------------------------------------------------------------------------


def decode_image(b64_string: str) -> np.ndarray:
    """Decode a base64 PNG/JPEG into an RGB uint8 array.

    Grayscale is later derived from this RGB image (matching align_facial_images),
    so the training and inference grayscale conversions are identical.

    Raises:
        ValueError: if the string is not valid base64 or not a decodable image.
    """
    try:
        raw = base64.b64decode(b64_string, validate=True)
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        img.load()
    except Exception as exc:  # noqa: BLE001 - any decode failure maps to one error
        raise ValueError("image decode failed") from exc
    return np.asarray(img)


# ---------------------------------------------------------------------------
# Stage 2 - face detection / count gate (MediaPipe Tasks FaceLandmarker)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _get_landmarker():
    """Create (once) and cache the MediaPipe Tasks FaceLandmarker.

    ``num_faces=2`` is enough to tell "one face" from "more than one".

    Raises:
        FileNotFoundError: if the face_landmarker.task asset is missing.
    """
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    if not MODEL_ASSET.exists():
        raise FileNotFoundError(
            f"MediaPipe face landmarker model not found: {MODEL_ASSET}. "
            "Download face_landmarker.task into models/ (see docs/IMAGE_PIPELINE.md)."
        )
    options = vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(MODEL_ASSET)),
        running_mode=vision.RunningMode.IMAGE,
        num_faces=2,
        min_face_detection_confidence=0.5,
    )
    return vision.FaceLandmarker.create_from_options(options)


def detect_faces(rgb: np.ndarray) -> list[np.ndarray]:
    """Detect faces and return one ``(N, 2)`` pixel-coordinate landmark array each.

    Returns an empty list when no face is found.
    """
    import mediapipe as mp

    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
    result = _get_landmarker().detect(mp_image)
    if not result.face_landmarks:
        return []
    h, w = rgb.shape[:2]
    return [
        np.array([[lm.x * w, lm.y * h] for lm in face], dtype=np.float32)
        for face in result.face_landmarks
    ]


# ---------------------------------------------------------------------------
# Stage 3 - align + square crop (same topology as scripts/align_facial_images)
# ---------------------------------------------------------------------------


def crop_square(gray: np.ndarray, cx: float, cy: float, side: float) -> np.ndarray:
    """Crop a ``side x side`` square centred on ``(cx, cy)``, padding OOB with white."""
    size = int(round(side))
    x0 = int(round(cx - side / 2))
    y0 = int(round(cy - side / 2))
    canvas = np.full((size, size), PAD_WHITE, dtype=np.uint8)

    h, w = gray.shape
    sx0, sy0 = max(x0, 0), max(y0, 0)
    sx1, sy1 = min(x0 + size, w), min(y0 + size, h)
    if sx1 > sx0 and sy1 > sy0:
        canvas[sy0 - y0 : sy1 - y0, sx0 - x0 : sx1 - x0] = gray[sy0:sy1, sx0:sx1]
    return canvas


def align_and_crop(rgb: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
    """Grayscale, eye-align, square-crop and resize a face to ``(OUT_SIZE, OUT_SIZE)``.

    Args:
        rgb: full-frame RGB uint8 array.
        landmarks: ``(N, 2)`` pixel-coordinate face-mesh landmarks for the one face.

    Returns:
        A ``(OUT_SIZE, OUT_SIZE)`` uint8 grayscale array (RAF-DB-style aligned crop).
    """
    gray = np.asarray(Image.fromarray(rgb).convert("L"))

    # Align: rotate around the eye midpoint so the eye line is horizontal.
    left_eye = landmarks[LEFT_EYE_IDS].mean(axis=0)
    right_eye = landmarks[RIGHT_EYE_IDS].mean(axis=0)
    if left_eye[0] > right_eye[0]:
        left_eye, right_eye = right_eye, left_eye
    angle = np.degrees(np.arctan2(right_eye[1] - left_eye[1], right_eye[0] - left_eye[0]))
    eyes_center = tuple(((left_eye + right_eye) / 2).astype(float))

    rot = cv2.getRotationMatrix2D(eyes_center, angle, 1.0)
    h, w = gray.shape
    gray = cv2.warpAffine(gray, rot, (w, h), flags=cv2.INTER_CUBIC, borderValue=PAD_WHITE)

    # Square crop around the rotated face oval + margin, then resize.
    oval = landmarks[FACE_OVAL_IDS]
    oval = np.hstack([oval, np.ones((len(oval), 1), dtype=np.float32)]) @ rot.T
    x0, y0 = oval.min(axis=0)
    x1, y1 = oval.max(axis=0)
    side = max(x1 - x0, y1 - y0) * (1 + FACE_MARGIN)
    face = crop_square(gray, (x0 + x1) / 2, (y0 + y1) / 2, side)

    resized = Image.fromarray(face, mode="L").resize((OUT_SIZE, OUT_SIZE), Image.LANCZOS)
    return np.asarray(resized)


# ---------------------------------------------------------------------------
# Stage 4 - quality check
# ---------------------------------------------------------------------------


def check_quality(gray_300: np.ndarray) -> dict | None:
    """Return an error dict if the crop fails a quality gate, else ``None``.

    Blur is checked first (handheld shake is the most common failure) so we fail
    fast. The crop is already single-channel, so no colour conversion is needed.
    """
    if cv2.Laplacian(gray_300, cv2.CV_64F).var() < BLUR_THRESHOLD:
        return {"error": "low_quality_blur"}
    mean = float(gray_300.mean())
    if mean < MIN_BRIGHTNESS:
        return {"error": "low_quality_dark"}
    if mean > MAX_BRIGHTNESS:
        return {"error": "low_quality_bright"}
    return None


# ---------------------------------------------------------------------------
# Stage 5 - to model tensor
# ---------------------------------------------------------------------------


def to_model_tensor(gray_300: np.ndarray) -> np.ndarray:
    """``(300, 300)`` uint8 -> ``(300, 300, 1)`` float32, values left in ``[0, 255]``.

    The FER model expects raw ``[0, 255]`` grayscale; EfficientNet-B3 normalises
    internally, so DO NOT apply preprocess_input or ``/255.0`` here.
    """
    return gray_300.astype("float32")[..., np.newaxis]


# ---------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------


def process(b64_image: str) -> dict:
    """Run the full pipeline on a base64 image.

    Enforces EXACTLY ONE detected face. Returns
    ``{"status": "ok", "tensor": np.ndarray}`` on success, or
    ``{"status": "error", "error": "<code>", ...}`` on any failure. Pure given a
    fixed image: no disk I/O, no randomness, no state mutation.
    """
    try:
        rgb = decode_image(b64_image)
    except ValueError:
        return {"status": "error", "error": "decode_failed"}

    faces = detect_faces(rgb)
    if len(faces) == 0:
        return {"status": "error", "error": "no_face"}
    if len(faces) > 1:
        return {"status": "error", "error": "multiple_faces", "count": len(faces)}

    gray_300 = align_and_crop(rgb, faces[0])

    quality_error = check_quality(gray_300)
    if quality_error is not None:
        return {"status": "error", **quality_error}

    return {"status": "ok", "tensor": to_model_tensor(gray_300)}
