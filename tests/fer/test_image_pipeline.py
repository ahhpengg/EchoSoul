"""Tests for src.fer.image_pipeline.

The pure helpers (decode, crop, quality, tensor) run with no heavy deps. The
face-dependent branches are exercised by monkeypatching ``detect_faces`` so no
real face image or MediaPipe install is required.
"""

from __future__ import annotations

import base64
import io

import numpy as np
import pytest
from PIL import Image

from src.fer import image_pipeline as ip

# --- helpers ---------------------------------------------------------------


def _png_b64(rgb: np.ndarray) -> str:
    buf = io.BytesIO()
    Image.fromarray(rgb.astype(np.uint8), "RGB").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _noise_rgb(h: int = 400, w: int = 400) -> np.ndarray:
    return np.random.default_rng(0).integers(80, 180, (h, w, 3), dtype=np.uint8)


def _checkerboard(lo: int, hi: int, n: int = 300) -> np.ndarray:
    a = np.full((n, n), hi, dtype=np.uint8)
    a[::2, ::2] = lo
    a[1::2, 1::2] = lo
    return a


def _fake_landmarks() -> np.ndarray:
    """A plausible 468-point FaceMesh landmark set: level eyes, spread face oval."""
    pts = np.full((468, 2), 200.0, dtype=np.float32)
    oval = ip.FACE_OVAL_IDS
    for i, idx in enumerate(oval):
        t = i / (len(oval) - 1)
        pts[idx] = [130 + 140 * t, 140 + 150 * t]
    pts[33], pts[133] = [170, 180], [185, 180]  # left eye corners
    pts[362], pts[263] = [230, 180], [245, 180]  # right eye corners
    return pts


# --- Stage 1: decode -------------------------------------------------------


def test_decode_valid_png_returns_rgb():
    rgb = np.random.default_rng(1).integers(0, 256, (8, 8, 3), dtype=np.uint8)
    out = ip.decode_image(_png_b64(rgb))
    assert out.shape == (8, 8, 3)
    assert out.dtype == np.uint8


def test_decode_invalid_base64_raises():
    with pytest.raises(ValueError):
        ip.decode_image("this is not base64!!!")


def test_decode_valid_base64_but_not_image_raises():
    not_an_image = base64.b64encode(b"hello world").decode()
    with pytest.raises(ValueError):
        ip.decode_image(not_an_image)


def test_process_decode_failed():
    assert ip.process("not base64 @@@") == {"status": "error", "error": "decode_failed"}


# --- Stage 3 helper: crop_square -------------------------------------------


def test_crop_square_inside_bounds():
    gray = np.full((100, 100), 50, dtype=np.uint8)
    out = ip.crop_square(gray, 50, 50, 40)
    assert out.shape == (40, 40)
    assert np.all(out == 50)


def test_crop_square_pads_oob_with_white():
    gray = np.full((100, 100), 50, dtype=np.uint8)
    out = ip.crop_square(gray, 0, 0, 40)  # centred at origin -> half out of bounds
    assert out.shape == (40, 40)
    assert out[0, 0] == ip.PAD_WHITE  # top-left corner is out of bounds
    assert out[39, 39] == 50  # bottom-right corner is inside the image


# --- Stage 4: quality check ------------------------------------------------


def test_quality_blur_rejected():
    flat = np.full((300, 300), 128, dtype=np.uint8)  # zero Laplacian variance
    assert ip.check_quality(flat) == {"error": "low_quality_blur"}


def test_quality_dark_rejected():
    dark = _checkerboard(0, 30)  # sharp (passes blur) but mean ~15
    assert ip.check_quality(dark) == {"error": "low_quality_dark"}


def test_quality_bright_rejected():
    bright = _checkerboard(225, 255)  # sharp but mean ~240
    assert ip.check_quality(bright) == {"error": "low_quality_bright"}


def test_quality_pass_returns_none():
    ok = np.random.default_rng(2).integers(80, 180, (300, 300)).astype(np.uint8)
    assert ip.check_quality(ok) is None


# --- Stage 5: tensor -------------------------------------------------------


def test_to_model_tensor_shape_and_range():
    gray = np.full((300, 300), 100, dtype=np.uint8)
    t = ip.to_model_tensor(gray)
    assert t.shape == (300, 300, 1)
    assert t.dtype == np.float32
    assert t.min() == 100.0 and t.max() == 100.0  # values NOT scaled to [0,1]


# --- Face-count gate (mocked detector) -------------------------------------


def test_process_no_face(monkeypatch):
    monkeypatch.setattr(ip, "detect_faces", lambda rgb: [])
    res = ip.process(_png_b64(_noise_rgb()))
    assert res == {"status": "error", "error": "no_face"}


def test_process_multiple_faces(monkeypatch):
    two = [np.zeros((468, 2), np.float32), np.zeros((468, 2), np.float32)]
    monkeypatch.setattr(ip, "detect_faces", lambda rgb: two)
    res = ip.process(_png_b64(_noise_rgb()))
    assert res["status"] == "error"
    assert res["error"] == "multiple_faces"
    assert res["count"] == 2


def test_process_one_face_ok(monkeypatch):
    monkeypatch.setattr(ip, "detect_faces", lambda rgb: [_fake_landmarks()])
    res = ip.process(_png_b64(_noise_rgb()))
    assert res["status"] == "ok"
    assert res["tensor"].shape == (300, 300, 1)
    assert res["tensor"].dtype == np.float32


def test_align_and_crop_output_shape():
    rgb = _noise_rgb()
    out = ip.align_and_crop(rgb, _fake_landmarks())
    assert out.shape == (ip.OUT_SIZE, ip.OUT_SIZE)
    assert out.dtype == np.uint8
