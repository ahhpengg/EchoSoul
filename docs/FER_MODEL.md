# docs/FER_MODEL.md

Facial Emotion Recognition model: training, fine-tuning strategy, and inference.

This doc covers the *model* layer. For the image preprocessing that produces inputs to this model, see `docs/IMAGE_PIPELINE.md`.

> **Status:** the model is **trained and shipped** — `models/fer_model.keras`. Achieved **86.29 %** test accuracy across 7 classes and **86.61 %** on the 5 in-scope classes (targets: ≥ 80 % / ≥ 85 %). The training was done on Google Colab; only the local inference + image pipeline run on the owner's machine. This doc records the **as-built** setup, which diverged from the original CP1 plan in several places (grayscale input, focal loss, MixUp, deeper unfreeze). Those divergences are called out inline.

---

## At a glance

| Aspect | Choice |
|---|---|
| Base architecture | EfficientNet-B3 (TensorFlow / Keras 3, TF 2.21 / Keras 3.15) |
| Pretrained weights | ImageNet (`include_top=False`, `pooling=None`) |
| Training dataset | RAF-DB **+ AffectNet disgust** (~17,360 images) |
| Training classes | 7 (surprise, fear, disgust, happy, sad, angry, neutral) |
| Application-layer scope | 5 (happy, surprised, sad, angry, neutral) — fear & disgust trigger the out-of-scope error |
| Input | **300 × 300 × 1 grayscale**, float32 in **[0, 255]** |
| Input normalisation | **None externally** — EfficientNet-B3 normalises internally; the model also replicates the 1 gray channel to 3 for the RGB backbone |
| Classification head | Global Average Pooling → Dropout(0.3) → Dense(7, softmax) |
| Loss | `CategoricalFocalCrossentropy(gamma=2.0, alpha=0.25, label_smoothing=0.1)` |
| Labels | one-hot (`label_mode="categorical"`) |
| Augmentation | model-layer flip / rotation / zoom / brightness / contrast **+ MixUp (α=0.2)** on the `tf.data` pipeline |
| Training strategy | Two-phase transfer learning (head only, then unfreeze block4→block7) |
| Split | 80 / 10 / 10 stratified, seed 42 (test = 1,736 images) |
| Persisted artefact | **`models/fer_model.keras`** (single-file Keras v3 format) |
| Result | 7-class **0.8629**, 5-in-scope **0.8661** |

**Files:**
- Architecture builder: `src/fer/model.py` (`build_model`, `unfreeze_top_blocks`).
- Training script: `scripts/train_fer_model.py`.
- Inference wrapper: `src/fer/inference.py`.
- Dataset preprocessing (offline, one-off): `scripts/grayscale_facial_image` (RAF-DB), `scripts/align_facial_images` (AffectNet disgust).

---

## Why EfficientNet-B3 (not VGG, ResNet, or B0)

Justified in the CP1 planning doc §2.1.2.2 and §3.8. Summary:

- **Vs. VGG16:** EfficientNet-B3 has fewer parameters, faster inference, higher accuracy on FER benchmarks.
- **Vs. ResNet50:** EfficientNet-B3 outperforms ResNet50 on FER benchmarks in published comparisons.
- **Vs. EfficientNet-B0:** B3 has higher accuracy; B0 is lighter/faster but the accuracy gap matters for a capstone judged on results. CPU inference for B3 still completes in < 1 s — acceptable.
- **Vs. larger (B4–B7):** Diminishing returns for the dataset size; B3 fits well.

If during CP2 the B3 model is genuinely too slow on the target machine, swap to B0 as a fallback and document it in the report.

---

## Dataset

### Composition (as built)

The training set is **RAF-DB plus additional *disgust* images sourced from AffectNet**. Disgust is the rarest RAF-DB class, so it was topped up to give the minority class more signal. All 7 classes are trained; fear & disgust are filtered out **at the application layer**, not at training time (see "Why train 7, serve 5").

| Folder | Emotion | Train | Val | Test | Total |
|---|---|---|---|---|---|
| 1 | surprise | 1275 | 160 | 160 | 1595 |
| 2 | fear | 282 | 35 | 35 | 352 |
| 3 | disgust | 2497 | 312 | 312 | 3121 |
| 4 | happy | 4725 | 590 | 590 | 5905 |
| 5 | sad | 1940 | 243 | 243 | 2426 |
| 6 | angry | 689 | 86 | 86 | 861 |
| 7 | neutral | 2480 | 310 | 310 | 3100 |
| | **Total** | **13888** | **1736** | **1736** | **17360** |

- **Split:** 80 / 10 / 10, **stratified by class**, reproducible via seed 42. The three splits are materialised into `train/`, `val/`, and `test/` sub-folders (one class-numbered folder each) so `image_dataset_from_directory` can read them directly.
- **Test split is untouched** during training and used once for final evaluation.

### Label mapping (folder index → our label)

Folder indices 1–7 map to labels **in this fixed order**, which is also the softmax output order:

```python
# src/fer/model.py
EMOTION_LABELS = ["surprise", "fear", "disgust", "happy", "sad", "angry", "neutral"]
IN_SCOPE = {"surprise", "happy", "sad", "angry", "neutral"}
```

| Folder | Our label | In scope for music rec? |
|---|---|---|
| 1 | surprise | ✅ |
| 2 | fear | ❌ out-of-scope |
| 3 | disgust | ❌ out-of-scope |
| 4 | happy | ✅ |
| 5 | sad | ✅ |
| 6 | angry | ✅ |
| 7 | neutral | ✅ |

The order is fixed so the persisted model stays portable. **Do not reorder** without retraining.

### Offline preprocessing of the training images

Both datasets were converted to **grayscale, aligned face crops** so the two sources look alike and match the webcam pipeline at inference time:

- **RAF-DB** — `scripts/grayscale_facial_image`: the RAF-DB "aligned" crops are already face-centred, so this just converts them to grayscale (`PIL.Image.convert("L")`) at their native resolution. `image_dataset_from_directory` resizes to 300 × 300 on load.
- **AffectNet disgust** — `scripts/align_facial_images`: grayscale → **MediaPipe FaceMesh** eye-line alignment (rotate so the eyes are horizontal) → **square crop** around the face-oval landmarks (+1 % margin, out-of-bounds padded white 255) → resize 300 × 300 (LANCZOS). The output deliberately mimics a RAF-DB aligned crop.

> **Why this matters for inference:** the runtime webcam pipeline (`docs/IMAGE_PIPELINE.md`) reuses the `align_facial_images` algorithm exactly, so the images the model sees in production match the ones it was trained on. Earlier a `bg_removal` script flooded the background with gray-128; that was **dropped** because only disgust used it, which would have created a train/inference distribution mismatch (and a spurious "gray background ⇒ disgust" shortcut) for the in-scope classes.

### Input format

The model's input is **grayscale, `(300, 300, 1)`, float32 in `[0, 255]`**:

- `image_dataset_from_directory(..., color_mode="grayscale")` yields `(H, W, 1)` uint8 tensors in `[0, 255]`.
- The model **replicates the single channel to 3** internally (`Concatenate` layer) because the ImageNet backbone expects RGB.
- **No external `preprocess_input`, no `/255.0`.** `tf.keras.applications.EfficientNetB3` includes its own normalisation layer and expects raw `[0, 255]` values. Applying `preprocess_input` or `/255.0` on top would double-normalise and collapse accuracy. (This inverts the original plan, which called for external `preprocess_input` — that was for an RGB `[-1, 1]` setup we no longer use.)

### Class imbalance

RAF-DB is heavily imbalanced (happy: 4,725 vs. fear: 282 in train). Handled with **Categorical Focal Loss**, not class weights:

- `tf.keras.losses.CategoricalFocalCrossentropy(gamma=2.0, alpha=0.25, label_smoothing=0.1)`.
  - **gamma=2.0** — down-weights easy, well-classified examples so the optimiser spends gradient on hard / minority-class samples.
  - **alpha=0.25** — balancing factor offsetting majority-class dominance.
- `model.fit(class_weight=...)` is **deliberately omitted.** Stacking explicit class weights on top of focal loss is redundant (both target the same imbalance signal) and makes the effective per-class weighting hard to reason about.
- Labels are **one-hot** (`label_mode="categorical"`), which `CategoricalFocalCrossentropy` and MixUp both require.

---

## Model architecture

Implemented in `src/fer/model.py`. Outline:

```python
NUM_CLASSES = 7
INPUT_SHAPE = (300, 300, 1)            # grayscale input from the dataset loader
BACKBONE_INPUT_SHAPE = (300, 300, 3)   # EfficientNetB3 needs 3 channels for ImageNet weights

def build_model(dropout: float = 0.3) -> tuple[Model, Model]:
    backbone = tf.keras.applications.EfficientNetB3(
        include_top=False, weights="imagenet",
        input_shape=BACKBONE_INPUT_SHAPE, pooling=None,
    )
    backbone.trainable = False  # frozen for Phase 1

    inputs = layers.Input(shape=INPUT_SHAPE, name="image")
    # Replicate the single gray channel 3× for the RGB-pretrained backbone.
    x = layers.Concatenate(axis=-1, name="gray_to_rgb")([inputs, inputs, inputs])

    # Augmentation — active only when training=True, no-op at inference.
    x = layers.RandomFlip("horizontal")(x)
    x = layers.RandomRotation(0.028)(x)    # ±10°
    x = layers.RandomZoom(0.1)(x)
    x = layers.RandomBrightness(0.1)(x)
    x = layers.RandomContrast(0.1)(x)

    # training=False keeps BatchNorm in inference mode in BOTH phases; unfrozen
    # conv weights still receive gradients (training= only affects BN/Dropout).
    x = backbone(x, training=False)

    x = layers.GlobalAveragePooling2D(name="gap")(x)
    x = layers.Dropout(dropout, name="head_dropout")(x)
    outputs = layers.Dense(NUM_CLASSES, activation="softmax", name="emotion_softmax")(x)
    return Model(inputs, outputs, name="emotion_efficientnetb3"), backbone
```

Notes:
- `build_model()` returns **`(model, backbone)`** — pass `backbone` to `unfreeze_top_blocks()` before Phase 2.
- Augmentation runs as **model layers**, so it's active during `fit()` and automatically disabled at inference. No vertical flip (faces are not vertically symmetric).
- **MixUp** is *not* a model layer — it's applied on the `tf.data` training pipeline (`mixup()` in `scripts/train_fer_model.py`, one `λ ~ Beta(α, α)` per batch). Val/test keep clean labels for honest metrics.

---

## Two-phase fine-tuning strategy

Standard transfer-learning recipe for EfficientNet on a domain-shifted dataset (faces vs. ImageNet objects).

### Phase 1 — head only

- **Frozen:** entire backbone (`backbone.trainable = False`).
- **Trainable:** GAP + Dropout + Dense head only (~13,888 params).
- **Optimiser:** Adam, `learning_rate = 1e-3`.
- **Loss:** categorical focal crossentropy (gamma 2.0, alpha 0.25, label smoothing 0.1).
- **Metrics:** `accuracy`, `top-2 accuracy` (`TopKCategoricalAccuracy(k=2)`) — top-2 is a useful diagnostic since many FER confusions are sad↔neutral.
- **LR schedule:** `ReduceLROnPlateau(monitor="val_loss", factor=0.5, patience=1, min_lr=1e-6)`.
- **Early stop:** `EarlyStopping(monitor="val_loss", patience=3, restore_best_weights=True)`.
- **Max epochs:** 35 (stopped at 22).
- **Purpose:** let the randomly initialised head stabilise before any backbone weights are disturbed.

### Phase 2 — partial unfreeze

- **Unfrozen:** EfficientNet-B3 **block4, 5, 6, 7** (~top 50 % of the backbone) — everything from `block4a_expand_conv` onward. (The original plan unfroze only block6+; the deeper unfreeze was found to train better here.)
- **BatchNorm stays frozen** throughout: `unfreeze_top_blocks()` sets every `BatchNormalization` layer `trainable = False`, **and** the backbone is always called with `training=False`, so BN running stats are never updated on the small dataset.
- **Optimiser:** Adam, `learning_rate = 1e-5` (100× lower than Phase 1 — critical to not corrupt pretrained weights).
- **Loss:** same categorical focal crossentropy.
- **LR schedule:** `ReduceLROnPlateau(monitor="val_loss", factor=0.5, patience=3, min_lr=1e-7)`.
- **Early stop:** `EarlyStopping(monitor="val_loss", patience=6, restore_best_weights=True)`.
- **Max epochs:** 55 (ran the full 55).
- **Starts from** the best Phase 1 checkpoint (`fer_phase1_best.keras`).
- **Purpose:** adapt mid/high-level features to facial expressions while preserving low-level edge/texture features.

### Why two phases (not one-shot)

Unfreezing everything from the start with a high LR lets the random head's large gradients corrupt the pretrained backbone. Two-phase training avoids this. Standard practice per Tan & Le 2019 and the Keras transfer-learning tutorial.

---

## Training script

`scripts/train_fer_model.py` (runs on Colab GPU). It:

1. Parses args: `--data-dir`, `--output-dir`, `--epochs-phase1` (35), `--epochs-phase2` (55), `--batch-size` (32), `--seed` (42), `--mixup-alpha` (0.2), `--label-smoothing` (0.1), `--resume-from`.
2. Sets seeds (`PYTHONHASHSEED`, `random`, `numpy`, `tf.random`).
3. Loads `train/`, `val/`, `test/` via `image_dataset_from_directory(image_size=(300,300), color_mode="grayscale", label_mode="categorical")`; applies MixUp to the training set only.
4. Builds the model (Phase 1: backbone frozen), trains Phase 1, checkpoints best-val-loss weights to `fer_phase1_best.keras`.
5. Reloads best Phase 1 weights, calls `unfreeze_top_blocks(backbone)`, recompiles at LR 1e-5, trains Phase 2 (checkpointing to `fer_model_checkpoint.keras`).
6. Saves the final model to `fer_model.keras`, history to `training_history.json`.
7. Produces evaluation artefacts (below).

**Resuming:** `--resume-from <checkpoint.keras>` skips Phase 1 entirely and continues Phase 2 from a checkpoint (handy when a Colab session disconnects mid-Phase-2).

Example invocations are in the module docstring at the top of the script.

---

## Inference

### Loading the model (at app startup, once)

Implemented in `src/fer/inference.py`. It imports the label constants from `src/fer/model.py` (single source of truth) and loads `models/fer_model.keras`:

```python
# src/fer/inference.py (outline)
MODEL_PATH = <repo>/models/fer_model.keras
from src.fer.model import EMOTION_LABELS, IN_SCOPE

def get_model():
    # lazy singleton; tf.keras.models.load_model(MODEL_PATH, compile=False)
    ...

def warmup():
    # one dummy predict on np.zeros((1, 300, 300, 1), float32) to amortise the
    # first-call graph build (~2–3 s). Call once at startup.
    ...

def predict(tensor_300x300x1) -> tuple[str, float, dict]:
    """tensor: (300, 300, 1) float32 in [0, 255] (from the image pipeline).
    Returns (label, confidence, all_class_probs)."""
    ...
```

**Input contract:** `predict` receives the tensor produced by `docs/IMAGE_PIPELINE.md` — `(300, 300, 1)` float32, **raw `[0, 255]`**, no `preprocess_input`. The wrapper adds the batch dimension. This must match training exactly.

### Out-of-scope handling

Application-layer logic, kept outside the model:

```python
def predict_in_scope(tensor) -> dict:
    label, confidence, all_probs = predict(tensor)
    if label not in IN_SCOPE:   # fear or disgust
        return {"status": "out_of_scope", "detected": label,
                "confidence": confidence, "all_probs": all_probs}
    return {"status": "ok", "emotion": label,
            "confidence": confidence, "all_probs": all_probs}
```

### Confidence threshold (optional, decide during testing)

Initially **no threshold** — always return the argmax. If user testing reveals frequent low-confidence false positives, introduce one (e.g. `confidence < 0.4 → error_low_confidence`). Defer until real test data exists. Default off.

### Inference performance

- **Per-image CPU inference:** ~300–500 ms for B3 at 300 × 300.
- **First inference is slow** (~2–3 s, lazy graph compilation). **Warm up at startup** via `warmup()`.

---

## Evaluation

`scripts/train_fer_model.py` produces these after training (also re-runnable for the report):

1. **Confusion matrix** (7 × 7) on the test set → `confusion_matrix.png`.
2. **Per-class precision / recall / F1** → `classification_report.txt`.
3. **Training curves** (loss + accuracy, both phases) → `training_curves.png`.
4. **7-class accuracy** and **5-in-scope accuracy** printed separately (in-scope is what matters for end users).
5. **Top-2 accuracy** monitored during training.

**Achieved results (test set, 1,736 images, unseen during training):**

| Metric | Target | Achieved |
|---|---|---|
| Test accuracy — 7-class | ≥ 80 % | **86.29 %** |
| Test accuracy — 5 in-scope | ≥ 85 % | **86.61 %** |

Both targets met. If a future retrain drops below 75 %, **stop and investigate** (see Pitfalls) before shipping.

---

## Common pitfalls (read before retraining or touching inference)

1. **Applying `preprocess_input` or `/255.0`.** This setup feeds **raw `[0, 255]`** to EfficientNet-B3, which normalises internally. Adding external normalisation double-normalises and collapses accuracy. Training and inference must both feed `[0, 255]`.

2. **Feeding RGB instead of grayscale.** The input is `(300, 300, 1)`. The model does the gray→3-channel replication itself. Passing a 3-channel image directly will fail the input shape check.

3. **Un-freezing BatchNorm in Phase 2.** BN layers must stay `trainable=False` **and** the backbone must be called `training=False`. Easy to miss, catastrophic when missed.

4. **Reordering `EMOTION_LABELS`.** The softmax output order is baked into the saved model. Changing the order silently mislabels every prediction.

5. **Mixing label encodings.** Focal loss + MixUp require **one-hot** labels (`label_mode="categorical"`). Don't switch to integer labels / sparse loss without changing both.

6. **Training on test data.** `train/`, `val/`, `test/` are distinct folders; never let test images touch `fit()`.

7. **Saving in `.h5`.** Save as `.keras` (Keras v3). `models/*.keras` is gitignored (the file is ~50 MB); distribute it out-of-band or via the model download instructions in the submission package.

8. **Determinism for tests.** Seeds are set, but GPU ops have residual non-determinism. The CPU inference path used in tests is deterministic.

---

## When and how to retrain

Retraining triggers: architecture change (e.g. swap to B0), adding/removing emotion classes, switching/rebalancing datasets, or discovering a data-quality bug. Each run should be versioned (`models/fer_model_v{N}.keras`), documented (a note describing what changed + new metrics), and committed (script + hyperparameter changes + results summary).

---

## Related docs

- `docs/IMAGE_PIPELINE.md` — produces the `(300, 300, 1)` `[0, 255]` tensors this model consumes.
- `docs/ARCHITECTURE.md` — where this fits in the system flow.
- `docs/TESTING.md` — how to test the model end-to-end with a fixture image.
- `docs/BUILD_PLAN.md` — Track C task breakdown.
