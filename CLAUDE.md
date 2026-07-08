# CLAUDE.md — Project Context for Claude Code

This file is the entry point for Claude Code when working on this repository. Read this first, then follow links to deeper documentation in `docs/` as needed.

---

## What this project is

**EchoSoul** (full academic title: *AI-Based Emotion-Driven Music Recommendation System Using Face Analysis*) — a desktop application that captures a user's facial photo via webcam, classifies their emotion using a fine-tuned EfficientNet-B3 CNN, then generates a Spotify-streamable playlist that matches the detected emotion.

> **Naming note:** The product is branded **EchoSoul**. The local MySQL database is named **`echosoul`** (set via `DB_NAME` in `.env`). The old name `emotion_music` was swept from the docs and code. **Exception:** the rule **table** is still named `emotion_music_mapping` (and its seed file `data/seed/emotion_music_mapping.sql`) — that is a schema identifier, deliberately left unchanged.

This is a **BSc (Hons) Computer Science capstone project** at Sunway University. The owner is the sole developer. The project has two phases:

- **Capstone Project 1 (CP1):** Planning, research, design — already completed (Sept 2025 – Jan 2026). The full planning document (the source of truth for design decisions) is referenced throughout these docs.
- **Capstone Project 2 (CP2):** Implementation, testing, evaluation — runs May–July 2026. This is what we are building.

The project follows the **Waterfall methodology** with weekly supervisor check-ins. Phases must be completed and documented in order: Requirements → Design → Implementation → Integration & Testing → Operation & Maintenance.

---

## Core user flow (one-paragraph summary)

User launches the desktop app → logs into Spotify (one-time OAuth) → on home screen, chooses either *"Take Photo"* (webcam) or *"Choose Mood Manually"* → if photo, system detects exactly one face, preprocesses the ROI, runs it through the EfficientNet-B3 emotion classifier, and maps the result (happy / surprised / sad / angry / neutral) to a valence–energy–tempo target range → system queries the local MySQL music catalogue for songs matching that range, randomises a subset into a playlist, and displays it → user can play the playlist (Spotify Web Playback SDK streams to the embedded webview), save it, edit it, or re-take the photo.

If detection fails (no face, multiple faces, blurry, dark, or detected emotion is outside the supported scope — e.g. *fear* or *disgust*), the system shows an error page and routes the user back to the home screen.

---

## Tech stack (locked unless noted)

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.11 | Match TensorFlow 2.x stable support; avoid 3.12+ until confirmed. |
| Deep learning | TensorFlow 2.x + Keras API | `tf.keras.applications.EfficientNetB3` with ImageNet weights. |
| Face detection | OpenCV Haar Cascade (`haarcascade_frontalface_default.xml`) | Capstone plan specifies this. Simple and adequate; if accuracy is poor at integration time, swap to MediaPipe Face Detection — but only with supervisor sign-off. |
| FER dataset | RAF-DB (already downloaded by owner) | 7 basic emotion classes; we collapse to 5 (drop fear & disgust) at the application layer, not at training time — see `docs/FER_MODEL.md`. |
| Database | MySQL 8.x | Stores music catalogue, emotion–music mapping rules, user playlists. |
| Music catalogue source | 3 pre-built Kaggle datasets, merged (see `docs/MUSIC_DATA.md`) | Spotify `/audio-features` was deprecated for new apps on **27 Nov 2024**, so we cannot fetch features at runtime. We use static dumps. |
| Music streaming | Spotify Web Playback SDK (JavaScript, in the embedded webview) | **Requires Spotify Premium** for every user. Disclosed in capstone report. |
| Spotify Web API (auxiliary) | Spotipy 2.x | Used only for OAuth flow + artist-genre enrichment script. The deprecated `/audio-features` endpoint is **NOT** used. |
| Desktop wrapper | PyWebView 5.x | Embeds HTML/CSS/JS frontend inside a native window; bridges Python ↔ JavaScript. |
| Frontend | HTML + CSS + vanilla JavaScript | No React/Vue. Keep dependencies minimal for a solo capstone. Spotify Playback SDK is plain JS, so vanilla integrates cleanly. |
| Version control | Git + GitHub (private repo) | |
| IDE | VS Code | |

**Do not introduce new frameworks or libraries without explicit owner approval.** If a task seems to call for one (e.g. "use Flask"), pause and confirm first. The dependency surface is intentionally small.

---

## Repository layout (target)

```
emotion-music-rec/
├── CLAUDE.md                       ← you are here
├── README.md                       ← user-facing project description
├── docs/                           ← supporting documentation; read on demand
│   ├── ARCHITECTURE.md             ← system architecture, components, data flow
│   ├── FER_MODEL.md                ← EfficientNet-B3 training, fine-tuning, inference
│   ├── IMAGE_PIPELINE.md           ← webcam capture → face detection → preprocessing → quality check
│   ├── MUSIC_DATA.md               ← 3-dataset merge strategy, artist-genre enrichment
│   ├── DATABASE.md                 ← MySQL schema, seed data, emotion–music mapping rules
│   ├── RECOMMENDATION.md           ← rule-based recommendation algorithm
│   ├── SPOTIFY_INTEGRATION.md      ← OAuth, Web Playback SDK, scopes, token refresh
│   ├── FRONTEND.md                 ← page layouts, JS bridge to PyWebView, Spotify SDK init
│   ├── BUILD_PLAN.md               ← module-by-module CP2 implementation order
│   ├── CODING_STANDARDS.md         ← naming, formatting, commits, testing conventions
│   └── TESTING.md                  ← unit, integration, and user-study test plans
├── src/
│   ├── main.py                     ← PyWebView app entry point
│   ├── api/                        ← JS-callable bridge methods (Python → JS)
│   ├── fer/                        ← FER pipeline (image processing + model inference)
│   ├── music/                      ← recommendation algorithm, DB queries
│   ├── spotify/                    ← OAuth flow, token management
│   └── db/                         ← MySQL connection, schema migrations, ORM (raw SQL or SQLAlchemy)
├── frontend/                       ← HTML/CSS/JS rendered by PyWebView
│   ├── index.html
│   ├── pages/                      ← home, photo, mood, loading, result, error
│   ├── css/
│   └── js/                         ← Spotify Playback SDK init, UI handlers
├── models/                         ← trained .keras / .h5 files (gitignored if large)
├── data/
│   ├── raw/                        ← gitignored: RAF-DB, raw Kaggle CSVs
│   ├── processed/                  ← gitignored: merged catalogue, train/val/test splits
│   └── seed/                       ← committed: emotion-music mapping rules SQL seed
├── scripts/                        ← one-off scripts (data merge, artist enrichment, DB seed)
├── tests/
├── requirements.txt
├── .env.example                    ← Spotify client ID, DB credentials placeholders
└── .gitignore
```

Create directories on demand; do not pre-create empty ones except where required by the build plan in `docs/BUILD_PLAN.md`.

---

## Critical context — read this before writing any code

### 1. The supported emotion scope is 5, not 7

RAF-DB labels 7 basic emotions: **happy, surprised, sad, angry, neutral, fear, disgust**. The system supports only the first 5 for music recommendation because the user survey (see CP1 planning doc §3.2) showed users rarely listen to music intentionally when feeling fear or disgust.

**Decision: train the model on all 7 classes, then filter at the application layer.** Reasoning:
- More training data per class → better feature learning.
- The "out-of-scope detected" error page (already designed in the planning doc) is the user-facing handler for *fear* and *disgust* predictions.
- Future scope expansion stays low-cost.

Do **not** drop fear/disgust at the dataset level. See `docs/FER_MODEL.md`.

### 2. Spotify `/audio-features` is dead for this project

On **27 November 2024**, Spotify deprecated the `/audio-features`, `/audio-analysis`, `/recommendations`, `/related-artists`, and featured/category playlist endpoints for any new third-party app. New apps registered after that date receive HTTP 403.

Implications:
- We **cannot** call `/audio-features` at runtime to enrich tracks.
- We **must** use pre-built dumps for valence/energy/tempo (see `docs/MUSIC_DATA.md`).
- Spotify Web Playback SDK is **not** affected — playback still works.
- ⚠️ **Update (June 2026):** `/artists` genre data is **also gone** for this app — the batch `/artists?ids=...` endpoint returns 403, and the single-artist object no longer includes a `genres` field at all (verified empirically). Genre enrichment therefore uses **Last.fm** (`artist.getTopTags`, keyed by artist name), not Spotify. See `docs/MUSIC_DATA.md` Stage 3. Needs `LASTFM_API_KEY` in `.env`.
- Do not write code that calls the deprecated endpoints, even in fallback paths.

### 3. Music data is local; playback is remote

The 1.2M-track merged catalogue lives in MySQL on the user's machine. Recommendation logic runs entirely against the local DB. Spotify is contacted **only** to play a track — we pass the `track_id` to the Web Playback SDK, which streams audio from Spotify's servers to the embedded webview.

This means:
- The recommender works offline (after initial DB seed).
- Playback requires internet + Spotify Premium login.
- Every track in our DB must have a valid Spotify `track_id` so playback works.

### 4. Every user needs Spotify Premium

The Web Playback SDK does not stream to Free accounts. This is a hard Spotify policy, not a workaround we can fix. The capstone report discloses this; the app's first-run screen should make it explicit before the user attempts OAuth.

### 5. Privacy-sensitive data — webcam images

Captured facial images:
- Are processed in-memory only.
- Are **never** written to disk except in explicit debug mode (off by default).
- Are **never** transmitted to any external service.
- Are discarded immediately after emotion prediction.

This is a hard requirement. Do not add features (analytics, "save photo," cloud backup, telemetry) that would violate it.

---

## Working conventions for Claude Code

### Documentation-first

Before writing code for a module:
1. Read the relevant doc in `docs/` (e.g. `docs/FER_MODEL.md` before touching `src/fer/`).
2. If the doc is silent on a design point, ask the owner — do not invent a convention.
3. If the doc is wrong or out of date, fix the doc first, then the code.

### Small, reviewable changes

The owner is a single developer reviewing every diff. Prefer:
- One concern per commit.
- Working code at every commit (no half-implementations).
- Clear commit messages: `module: short imperative summary` (e.g. `fer: add Haar cascade face detection`).

### No silent dependency additions

If a task seems to require a new pip package, stop and confirm with the owner first. Adding `requests` is fine; adding `fastapi` or `pytorch` is not.

### Style

- Python: PEP 8, formatted with `black`, type hints on public functions, docstrings on non-trivial functions. Line length 100.
- JavaScript: 2-space indent, ES2020+, no transpilation step (PyWebView's embedded webview is Chromium-based, modern JS is fine).
- SQL: uppercase keywords, snake_case identifiers, one statement per line in migrations.

See `docs/CODING_STANDARDS.md` for the full conventions.

### Tests

- Every module in `src/` gets a matching `tests/` file.
- Unit tests use `pytest`.
- The FER model has a fixed test image (a known-happy face) checked into `tests/fixtures/` to verify the inference pipeline end-to-end.
- The recommendation algorithm has a fixed seed for randomised playlist selection so tests are deterministic.

See `docs/TESTING.md`.

### Long-running scripts are background-safe

The artist-genre enrichment script (`scripts/enrich_artist_genres.py`) must:
- Checkpoint progress to disk every 1,000 API batches.
- Resume from the last checkpoint if interrupted.
- Handle Spotify 429 responses by honouring the `Retry-After` header.

Do not write enrichment code that has to complete in one shot. See `docs/MUSIC_DATA.md`.

---

## Where to find things — quick reference

| If the task is about… | Read first |
|---|---|
| Setting up the project, installing deps, first run | `docs/BUILD_PLAN.md` |
| Adding/changing a CNN layer, training, accuracy, dataset prep | `docs/FER_MODEL.md` |
| Webcam, face detection, image quality, OpenCV | `docs/IMAGE_PIPELINE.md` |
| Anything touching the music catalogue, CSVs, merge logic | `docs/MUSIC_DATA.md` |
| Adding a table, a column, an index, a seed row | `docs/DATABASE.md` |
| Changing valence/energy/tempo thresholds, playlist size, randomisation | `docs/RECOMMENDATION.md` |
| OAuth flow, token refresh, Premium check, scopes | `docs/SPOTIFY_INTEGRATION.md` |
| HTML pages, CSS, JS event handlers, PyWebView bridge | `docs/FRONTEND.md` |
| What to build next, in what order | `docs/BUILD_PLAN.md` |
| How to format / commit / name things | `docs/CODING_STANDARDS.md` |
| Writing tests, running them, what coverage is required | `docs/TESTING.md` |
| The big-picture how-it-all-fits-together view | `docs/ARCHITECTURE.md` |

---

## Status (update this section as the project progresses)

- **Phase:** CP2 — Phase 3 (Implementation & Unit Testing), as of July 2026.
- **Completed so far:**
  - **Frontend scaffold (Track F, partial):** pages, CSS, and JS for home / photo / mood / loading / result / error (not yet wired to a Python bridge).
  - **Track C — FER (DONE):** trained EfficientNet-B3 model dropped in (`models/fer_model.keras`, 86.68% 7-class / 87.62% 5-in-scope). Grayscale architecture (`src/fer/model.py`) + training script (`scripts/train_fer_model.py`); runtime image pipeline (`src/fer/image_pipeline.py` — MediaPipe Tasks `FaceLandmarker` eye-alignment + square crop, same landmark topology as `scripts/align_facial_images`, exactly-one-face gate, blur/dark/bright quality checks); inference + out-of-scope wrapper (`src/fer/inference.py`); tests in `tests/fer/`. The as-built training setup diverged from the original plan (grayscale `[0,255]` input, categorical focal loss, MixUp, block4+ unfreeze) — `docs/FER_MODEL.md` and `docs/IMAGE_PIPELINE.md` were rewritten to match. Local inference runs on `tensorflow==2.21.0` + `mediapipe==0.10.35` (installed; `requirements.txt` regenerated). Face detection uses the Tasks `FaceLandmarker` API (needs `models/face_landmarker.task`) because mediapipe 0.10.35 removed the legacy `solutions` API. All 22 `tests/fer` pass, including an end-to-end happy-face photo → "happy" prediction.
  - **Track A — Database (DONE):** migration runner (`src/db/migrate.py`), connection pool (`src/db/connection.py`), schema migrations (`music`, `emotion_music_mapping`, `playlist`, `playlist_song`, `v_in_scope_music`), 5-row rule seed, indexes, passing tests (`tests/db/`). Migrations applied to the local `echosoul` database.
  - **Track B — Music data pipeline (DONE):** the five-stage pipeline (`scripts/download_datasets.py` → `normalise_datasets.py` → `enrich_artist_genres.py` (Last.fm) → `merge_catalogues.py` → `seed_database.py`) is written and has been **run end-to-end**. The merged catalogue is loaded into the local `echosoul` DB: **1,310,164 rows** in `music`, all three indexes present, 5-row rule table populated.
  - **Track D — Recommendation (DONE):** rule lookup + candidate query + random sample (`src/music/recommender.py`) and playlist save/load/delete (`src/music/playlists.py`), with deterministic-seed integration tests against the real catalogue (`tests/music/`). Validated now that Track B data is loaded.
  - **Track E — Spotify integration (DONE):** keyring token cache with file fallback (`src/spotify/keyring_cache.py`, service `EchoSoul`, `WinVaultKeyring` backend on Windows), PKCE auth flow (`src/spotify/auth.py` — `has_spotify_session`, `start_login_flow`, `get_valid_access_token`, `logout`), Premium check + cached profile (`src/spotify/account.py` — `verify_premium`, `get_user_profile`). 27 mocked-Spotipy/keyring unit tests pass (`tests/spotify/`). Added the `keyring==25.7.0` dependency (owner-approved) and regenerated `requirements.txt`. `docs/SPOTIFY_INTEGRATION.md` was corrected to the real spotipy 2.26 API (no `as_dict`; `SPOTIFY_CLIENT_ID` env name). Redirect URI is a **fixed-port loopback with a custom path**, `http://127.0.0.1:8888/echosoul-callback` (Spotify's dashboard rejects `localhost` and port-less forms as "not secure"); login uses our own `_CallbackServer` (branded page + CSRF `state`) rather than Spotipy's built-in server. **Manual E2E OAuth run verified (2026-07-08):** real browser login succeeded end-to-end — token cached in the OS keychain, `get_valid_access_token()` returns a valid token, and `verify_premium()` confirmed the owner's account is **Premium** (required for the Web Playback SDK).
  - **Track F — F1: entry point + bridge (DONE):** PyWebView entry point (`src/main.py` — window over `frontend/index.html`, MySQL fail-fast check at startup, FER warm-up on a `webview.start(func=...)` worker thread, `private_mode=False` so the Spotify SDK's localStorage persists across runs, `ECHOSOUL_DEBUG=1` opens devtools; launch with `python -m src.main`) + the full JS bridge (`src/api/bridge.py`, one flat `BridgeApi` bound as `js_api`): Spotify session/account passthroughs, `detect_emotion` (pipeline → inference; maps the model's RAF-DB label **`surprise` → app vocabulary `surprised`**, which the frontend/rule table/recommender use; a module lock serialises MediaPipe/TF access because PyWebView runs each bridge call on its own thread), `quick_face_check` (≤320 px downscale, decode failure ⇒ `face_count: 0`), `generate_playlist`, and playlist CRUD (save/list/load/rename/delete, with JS float→int coercion). 20 mocked unit tests in `tests/api/` (110 total pass). Installed `pywebview==5.4` (locked-stack item; 6.2.1 exists but the stack table locks 5.x) and regenerated `requirements.txt`.
- **Current focus:** Track F continues — F2 (login + premium-gate pages, `frontend/js/bridge.js` + `auth_gate.js`), then wiring photo/mood/loading/result/error pages and the sidebar to the real bridge, then the Web Playback SDK (`playback.js`).
- **Next milestone:** Track F complete (all pages on the real backend, playback working inside the webview); then Phase 4 integration testing.

---

## Out of scope (do not build these)

The capstone plan explicitly excludes these features. If a task asks for them, push back and confirm with the owner:

- Mobile app (Android/iOS).
- Wearable / physiological sensor emotion detection.
- Lyrics-based emotion analysis.
- Long-term personalisation (user listening-history-based ranking).
- Full music licensing / payment flows.
- Multi-user accounts inside the desktop app (each install is single-user).
- Cloud backup of playlists.
- Real-time continuous emotion tracking (one snapshot per request only).

---

## Owner contact / supervisor

- **Owner:** Lee Peng Haw (student, ID 23098387).
- **Supervisor:** Nurul Aiman Abdul Rahim.
- **Institution:** Sunway University, Department of Smart Computing and Cyber Resilience.

If Claude Code is unsure about a design decision, the default answer is **"ask the owner."** Do not guess for non-trivial decisions.
