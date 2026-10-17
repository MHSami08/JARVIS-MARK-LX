# 🧭 JARVIS — MARK LX · Architecture Blueprint

> Engineering blueprint. Describes how the current code is wired — not a wish list.
> Every module named here exists in the repo.

---

## 1. One-line model

**JARVIS = one async event loop bridged to a Gemini Live audio session, plus N
callable tools, plus a PyQt6 HUD, plus an embedded Study Board viewed through a
QWebChannel.**

- **Brain / realtime loop:** `main.py` → `class JarvisLive`
- **Face:** `ui.py` → `JarvisUI` (Arc Reactor Core HUD)
- **Hands:** `actions/*.py` (built-ins) + `plugins/*.py` (user drop-ins)
- **Eyes:** `core/screen_agent.py` + `core/ui_grounding.py` + `core/screen_geometry.py`
- **Voice:** Gemini Live in/out, with `core/noise_gate.py`, `core/echo.py`, `core/barge_in.py`
- **Routing:** `core/model_router.py` (one-shot tool calls) + `core/gemini.py` (ladder fallback)
- **Study:** `core/study_canvas.py` ↔ `runtime/study_board.html` ↔ `actions/study_*.py`
- **Memory:** `memory/memory_manager.py`, `memory/study_cache.py`, `memory/config_manager.py`
- **Remote:** `dashboard/server.py` (LAN + Cloudflare tunnel, QR/PIN pairing)

---

## 2. Layer map

| Layer | Dir | Responsibility | Talks to |
|---|---|---|---|
| **Entry / Orchestration** | `main.py`, `setup.py` | Live session, reconnect, wake/sleep, phone relay, task fan-out | all layers |
| **UI / Presentation** | `ui.py`, `runtime/study_board.html` | HUD, settings overlays, video, Study Board | `JarvisLive` via signals |
| **Core services** | `core/` | Gemini, routing, audio DSP, vision, TTS/STT, plugins, undo, confirm | `actions`, `ui` |
| **Actions (built-ins)** | `actions/` | One `TOOL` dict per file, auto-discovered | `core`, `memory` |
| **Plugins** | `plugins/` | Community .py drop-ins, same `TOOL` contract | `core`, `memory` |
| **Memory** | `memory/` | Long-term JSON, study cache, mistake bank, config accessors | `core`, `actions` |
| **Config** | `config/` | `api_keys.json`, OAuth creds, icon, certs, log | every layer |
| **Dashboard** | `dashboard/` | FastAPI + uvicorn, WebSockets, static UI | `JarvisLive` |
| **Runtime assets** | `runtime/` | Study Board HTML + vendored KaTeX/Tailwind/Plotly | `study_canvas` |
| **Dev tools** | `tools/`, `bin/` | Targeting calibration, vendor fetch, `cloudflared.exe` | dev only |

**Rule:** layers only depend downward. `actions/` never import `ui.py`;
`core/*` stays Qt-free where it must be importable by plugins (e.g. `study_guard.py`).

---

## 3. Runtime topology

```text
                    ┌────────────────────────────────────────────┐
                    │                main.py                     │
                    │   _single_instance_or_exit() → main()       │
                    │   JarvisLive(ui)  ·  asyncio loop           │
                    └───────────────┬────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────────┐
        │                           │                               │
   ┌────▼─────┐             ┌───────▼────────┐             ┌────────▼────────┐
   │  ui.py   │  Qt signals │  JarvisLive    │  tool calls │  core/          │
   │ JarvisUI │◄───────────►│  session tasks │◄───────────►│  gemini.py      │
   │ Arc Core │             │  _listen_audio │             │  model_router   │
   │ Study    │             │  _receive_audio│             │  llm_client     │
   │ Board    │             │  _play_audio   │             │  tts · stt      │
   └────┬─────┘             └───────┬────────┘             └────────┬────────┘
        │                           │                               │
        │        ┌──────────────────┴──────────────┐        ┌───────▼────────┐
        │        │                                 │        │  actions/*.py  │
   ┌────▼─────┐  │  ┌───────────────┐  ┌───────────▼──┐     │  plugins/*.py  │
   │ runtime/ │  │  │ dashboard/    │  │ core/screen_ │     └───────┬────────┘
   │ study_   │  │  │ server.py     │  │ agent · ui_  │             │
   │ board.   │  │  │ FastAPI+WSS   │  │ grounding    │     ┌───────▼────────┐
   │ html     │  │  │ phone audio   │  └──────────────┘     │  memory/*.json │
   └──────────┘  │  └───────┬───────┘                       └────────────────┘
                 │          │
                 │   ┌──────▼───────┐
                 │   │ cloud_tunnel │ → https://*.trycloudflare.com
                 │   └──────────────┘
```

---

## 4. Voice pipeline (the spine)

```text
Microphone
   │  sounddevice InputStream (core/audio_devices.py picks device)
   ▼
noise_gate.py  ──►  barge_in.py (decision)   echo.py (separate our voice from user)
   │
   ▼
_send_realtime()  ──►  Gemini Live session (bidirectional audio)
   │
   ▼
_receive_audio()  ──►  speaker playback via _play_audio()
   │
   ├──► _pcm_level()    → HUD reactor/waveform reacts to real level
   └──► _pcm_visemes()  → core/viseme.py → avatar mouth shapes
```

| Concern | Module | Note |
|---|---|---|
| Interruption mid-sentence | `core/barge_in.py` | decision half; signal comes from audio level |
| Room noise rejected | `core/noise_gate.py` | config `noise_gate.strength` = low/… |
| Own voice not re-heard | `core/echo.py` | keeps TTS out of the mic path |
| Push-to-talk | `core/hotkey.py` | hold key, speak, release |
| Wake word | `core/wake_word.py` | **opt-in**, offline, installed from ⚙ → WAKE WORD |
| Turn boundaries | config `turn_tuning` | `silence_ms`, `prefix_ms`, sensitivity |
| Reconnect | `main.py` `_watch_reconnect` | `_ReconnectSignal`, context kept or dropped |

**Flow control:** `_send_realtime` / `_receive_audio` / `_play_audio` are the three
concurrent tasks of one session; `_flush_pending_vision` drains screen frames the
vision tools queued.

---

## 5. Tool / action dispatch

```text
Gemini Live emits FunctionCall
        │
        ▼
JarvisLive._execute_tool(fc)
        │
        ├── core/action_loader.py   → auto-discovers actions/*.py with module-level TOOL
        └── core/plugin_loader.py   → discovers plugins/*.py, PluginRegistry
                                         (enable/disable re-read from config each call)
        │
        ▼
   run(tool_name, args)   → returns FunctionResponse
        │
        ▼
   result fed back into the live session → spoken answer
```

**Action contract (built-ins and plugins share it):**

```python
TOOL = {
    "name": "study_solve_problem",
    "description": "...",
    "parameters": {"type": "OBJECT", "properties": {...}},
}
def run(...) -> str: ...
```

Validation, name-collision detection, and traceback capture all live in the two
loaders. A plugin needs a restart of nothing — toggling enable state is enough.

Internal tools registered by the core itself include `study_register_ui`,
`study_unregister_ui`, `_ui_wake_toggle`, `_ui_wake_manual`, `_ui_wake_install`,
and `plugin_say` — these inject live UI state into Gemini's context.

---

## 6. Multi-provider router & key ladder

```text
action wants a one-shot answer
        │
        ▼
core/model_router.py
        │  ordered, fastest-first, NON-THINKING
        ├─ routing_rules[task]  (fast | coding | writing | study | study_fast)
        ▼
  Groq ─► Groq ─► Gemini ─► Gemini ─► Gemini ─► OpenRouter(free)
        │
        ├─ key pool per provider: gemini_api_keys[], groq_api_keys[]
        │     record.number → "Key #2 (gsk_…4f1a)"  ← human-actionable label
        ├─ cooldown_until per (key,model); 429/402/quota ⇒ cooldown, skip, auto-return
        └─ if direct chain exhausted / unconfigured
                 ▼
           core/gemini.py ladder  (flash-lite → flash → 3.1-flash-lite,
                                   + throwaway Live sessions)
                 ▼
           Study Mode never fails while ≥1 Gemini key exists
```

- **Key pools merge** single + list fields (`gemini_api_key` + `gemini_api_keys`).
- **UI writes both**, so the settings overlay and the router never disagree
  (`ui.py` ApiConfigOverlay, `core/model_router.py` `_pools[...].sync(...)`).
- `core/gemini.py` owns timeouts, model cooldown, and the single place a model
  alias is written — 16 files used to build their own `genai.Client`.

**Local fallback:** `core/llm_client.py` can serve the same call through a local
server instead — `llm_provider: "ollama"` (default, port 11434) or `"openai"`
(LM Studio / vLLM / llama.cpp, set `llm_url`).

---

## 7. Vision & computer control

```text
goal ("click Save in this dialog")
        │
        ▼
core/screen_agent.py   plan → find target → act → observe → verify → retry → ask
        │
        ▼
core/ui_grounding.py   cheapest method first:
        UIA / accessibility tree  ─► OCR (Windows.Media.Ocr via winsdk)  ─► vision model
        │
        ▼
core/screen_geometry.py  one source of truth for coordinates
        │
        ▼
core/target_overlay.py   click-through reticle shown BEFORE the click
        │
        ▼
pyautogui / uiautomation actually click
```

| Task | Module |
|---|---|
| Screen + webcam capture | `actions/screen_processor.py` |
| Element finding / aim | `core/ui_grounding.py`, `core/screen_geometry.py` |
| Autonomous multi-step operation | `core/screen_agent.py` |
| Recoverable state changes | `core/undo.py` (shared undo stack) |
| Un-forgeable confirmation gate | `core/confirm.py` |

**Study Mode lock:** `core/study_guard.py` — while Study Mode is on,
`require_camera()` raises `CameraLocked`. Screen capture stays allowed (that is how
JARVIS reads question papers); the webcam does not.

---

## 8. Study Mode data flow (Universal Learning Station)

```text
voice: "solve this HSC chemistry problem"
        │
        ▼
study_station_control(action="enter")      actions/study_controller.py
        │
        ▼
core/study_canvas.py  (QWebEngineView + QWebChannel bridge: toBoard/ready/event)
        │
        ▼
runtime/study_board.html   ← KaTeX + Tailwind + Plotly (vendored offline)
        │
        ├── study_solve_problem   → actions/study_solver.py   step-by-step solution cards
        ├── quiz engine           → actions/study_quiz.py     MCQ + anti-cheat lock + explanations
        ├── mindmap               → actions/study_mindmap.py  2D concept tree, LaTeX-aware
        └── flashcards            → actions/study_flashcard.py 3D flip cards
        │
        ▼
memory/study_cache.py   →  study_cache.json  (zero-cost reuse of solved Qs)
                        →  mistake_bank / study_mistakes.json (review_mistakes)
        │
        ▼
export → workspace/exports/  (.docx via python-docx, notepad Ctrl+N, session notes)
```

- **Bangla safety:** every study action runs `_fix_bangla_unicode()` — NFC
  normalization, strips ZWSP/RLM/LRM, collapses only accidental spaces around
  hasant — so Bangla text and LaTeX survive the round trip.
- **Subjects solved:** NCTB HSC Physics, Chemistry, Higher Math, Biology, ICT, custom.
- **Plugin shell:** `plugins/study_mentor.py` is now backend-only — notepad
  evaluation, export, mistake review. Primary engines moved to `actions/study_*.py`.
- **Board control actions:** `enter`, `exit`, `next`, `prev`/`back`, `restore`,
  `clear`, `check_notes`, `export`, `review_mistakes`.

---

## 9. HUD (Arc Reactor Core)

| Piece | Location |
|---|---|
| HUD window, overlays, settings | `ui.py` — `JarvisUI` |
| Permanent centerpiece | Arc Reactor Core (`hud_style: "core"`) |
| Reactivity | `_pcm_level()` audio level → ring rotation + breathing base |
| Video-in-the-core | `ui.py` `play_video` renders where the reactor normally sits |
| Readability pass | `core/ui_readability.py` |
| Icon | arc-reactor icon generated with Pillow (`.ico` + `.png`) |
| Style persistence | `memory/config_manager.py` `get_hud_style()/save_hud_style()` (always `"core"`) |

The head avatar is **software-rendered with QPainter + numpy** — no OpenGL, no GPU,
no extra dependency. Mouth shapes come from `core/viseme.py`, fused from both audio
and text.

---

## 10. Remote dashboard & phone bridge

```text
Phone browser
    │  HTTPS / WSS  (LAN or https://*.trycloudflare.com)
    ▼
dashboard/server.py   FastAPI + uvicorn
    ├─ auth:  AES-256-CBC encrypted commands, one-time QR / PIN pairing,
    │         persistent device tokens, self-signed certs in config/certs/
    ├─ WS /ws/phone-audio    phone mic 16 kHz PCM → JarvisLive
    ├─ WS /ws/jarvis-audio   JARVIS 24 kHz PCM → phone speaker
    ├─ /api/upload /api/files /uploads/{name}   file sharing, auto-bound
    └─ static login.html + app.html
    ▲
    └─ core/cloud_tunnel.py  auto-downloads cloudflared, exposes port 8000
```

`main.py` bridges this into the session: `_relay_phone_audio`,
`_on_phone_connected`, `_on_phone_file_uploaded`, `_process_dashboard_commands`,
`_phone_blocks_pc_mic`, `_phone_audio_only`, `_make_remote_key`.

---

## 11. Startup sequence

```text
python main.py
 1. Windows: patch subprocess.Popen → CREATE_NO_WINDOW (no console popups)
 2. reconfigure stdout/stderr to UTF-8 (emoji on cp1254/cp1251/cp932 consoles)
 3. no console (pythonw)?  → redirect to config/jarvis.log (rotates at ~2 MB)
 4. _single_instance_or_exit()          ← second launch refuses, focuses first
 5. load config + core/prompt.txt       ← _load_system_prompt(), _get_api_key()
 6. core/installer.py                   ← auto-install missing deps on first run
 7. discover_plugins()                  ← plugin_loader, cached for process life
 8. JarvisUI()                          ← HUD up, Arc Reactor Core live
 9. JarvisLive(ui) → run()              ← asyncio: sender/receiver/player tasks
10. optional concurrent tasks: system monitor, background monitor,
    proactive engine, phone relay, sleep watcher, reconnect watcher
```

---

## 12. Degradation & failure design

| Failure | Behaviour |
|---|---|
| Model/key rate-limited | router puts pair on cooldown, rotates to next rung |
| Whole direct chain dead | falls back to `core/gemini` Live ladder |
| Playwright browsers missing | everything but browser automation still works; warned, not fatal |
| OCR language pack missing | `rapidocr-onnxruntime` fallback layer; missing install = one layer off |
| `PyQt6-WebEngine` missing | Study canvas unavailable + hint; rest of app runs |
| Wake word not installed | feature simply off until installed from settings |
| Vision tool loses target | `screen_agent` retries then **stops and asks** — never blind-clicks |
| Live session drops | `_ReconnectSignal` + `_watch_reconnect`, context kept or dropped by flag |

Principle throughout: **optional things fail in isolation**, never take the session down.

---

## 13. Extension points

| Want to add | Touch this | Contract |
|---|---|---|
| A new tool | drop `actions/<name>.py` | module-level `TOOL` dict + `run()` |
| A community plugin | drop `plugins/<name>.py` | same `TOOL` contract, enable in config |
| A new model rung | `core/model_router.py` `DEFAULT_RULES` (or `config` `routing_rules`) | `(provider, model)` tuple, non-thinking, fastest first |
| A local LLM backend | `config` `llm_provider` / `llm_url` | `core/llm_client.py` |
| A TTS voice | `core/tts.py` | EdgeTTS / Kokoro (offline) / ElevenLabs |
| An STT engine | `core/stt.py` | Whisper (faster-whisper) / Vosk (streaming) |
| A Study Board view | `runtime/study_board.html` + a `study_*.py` action | emits structured JSON to the board bridge |
| Offline study assets | `python tools/fetch_study_vendor.py` | KaTeX, Tailwind, Plotly into `runtime/vendor/` |

---

## 14. Where to look when something breaks

| Symptom | Start here |
|---|---|
| No voice in/out | `core/audio_devices.py` → `main.py` `_listen_audio` / `_play_audio` |
| JARVIS answers itself / re-hears | `core/echo.py`, `core/barge_in.py`, `noise_gate` config |
| "Key #N is cooling" | `core/model_router.py` pool records |
| Clicks land on wrong thing | `python tools/target_debug.py` → `core/ui_grounding.py` |
| Clicks don't land at all | `python tools/calibrate.py` → `core/screen_geometry.py` |
| Study Board blank | `core/study_canvas.py` import check, `runtime/vendor/` populated |
| Phone can't reach JARVIS | `core/cloud_tunnel.py`, `dashboard/server.py`, port 8000 |
| Crash with no console output | `config/jarvis.log` |

---

## 15. Non-negotiables

- **Attribution stays:** original architecture by **FatihMakes**; enhancements and
  the Universal Learning Station by **MH SAMI**.
- **License:** CC BY-NC 4.0 — non-commercial. See `LICENSE`.
- **Secrets:** keys live in `config/api_keys.json` only; user data stays local in
  `memory/` and `workspace/`.
