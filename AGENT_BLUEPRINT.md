# 🛠️ JARVIS / MARK LX — AI Agent Developer Blueprint

> **Notice for AI Assistants & Coding Agents:**
> This blueprint is the authoritative technical reference and operating manual for **JARVIS (MARK LX)**.
> Before making changes, adding actions, implementing plugins, modifying UI, or debugging, review the architectural contracts, thread boundaries, and recipes documented below.

---

## 1. System Overview & Core Stack

JARVIS is a cross-platform, voice-first desktop AI assistant and **Universal Learning Station** (specialized for NCTB HSC Science & advanced computer science/mathematics).

- **Runtime**: Python 3.12+ (Windows, macOS, Linux).
- **Core LLM Engine**: Google Gemini Live API (`google-genai`) for real-time bidirectional audio/video streaming.
- **Auxiliary LLM Engine**: `core/model_router.py` (Groq, OpenRouter, Gemini REST) with key pools, health tracking, and throwaway Gemini Live fallback.
- **GUI**: PyQt6 + PyQt6-WebEngine (`QWebChannel` for JS $\leftrightarrow$ Python bridge).
- **Audio Pipeline**: `sounddevice` + `numpy` + RMS `NoiseGate` + `EchoGuard` + `BargeInDetector` + `openWakeWord`.
- **HUD Centerpiece**: Reactive Arc Reactor Core rendered via `QPainter` with state rotations and real-time audio waveform amplitude pulsation.
- **OS Automation**: Windows UIA, RapidOCR / Windows Media OCR, `pyautogui`, `playwright`.
- **Remote Dashboard**: FastAPI + WebSocket on port 8000 with AES-256-CBC encryption.

---

## 2. The Three-Layer Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│  LAYER 1: AGENT & RUNTIME SPINE           (main.py & ui.py)            │
│  • JarvisLive (main.py): Gemini Live bidirectional streaming session   │
│  • Audio pipeline: openWakeWord, NoiseGate, EchoGuard, BargeInDetector │
│  • Threaded Qt6 HUD (ui.py): Arc Reactor Core, visual logs, canvas     │
└───────────────────┬────────────────────────────────┬───────────────────┘
                    │ Tool Invocations               │ Direct REST / Routing
                    ▼                                ▼
┌────────────────────────────────────────┐   ┌───────────────────────────┐
│  LAYER 2: ACTIONS & PLUGINS EXTENSION  │   │  LAYER 3: MULTI-TIER LLM  │
│  • Auto-discovered actions/ (*.py)     │──▶│  • core/gemini.py         │
│  • Auto-discovered plugins/ (*.py)     │   │    (Live fallback ladder) │
│  • Universal Study Station             │──▶│  • core/model_router.py   │
│    (plugins/study_mentor.py)           │   │    (Groq, OpenRouter,     │
└────────────────────────────────────────┘   │     Gemini REST ladders)  │
                                             └───────────────────────────┘
```

---

## 3. Critical Architectural Contracts & Invariants

### 1. Thread Boundaries & Concurrency
- **The Golden Rule**: The Qt GUI runs on the main thread; `JarvisLive` runs an `asyncio` event loop on a dedicated thread; audio I/O runs in `sounddevice` callbacks.
- **NEVER** call Qt widget methods directly from an `async` function or worker thread.
- Always use the thread-safe facade `JarvisUI` or Qt signals (`pyqtSignal`) to mutate UI state.
- **NEVER** perform blocking network I/O or heavy computation inside the `asyncio` event loop; use `asyncio.to_thread(...)` or `loop.run_in_executor(...)`.

### 2. Tool Extensibility Contract (Auto-Discovery)
- Tools are placed in `actions/` or `plugins/`.
- **No manual registration** in `main.py` is needed. `core/action_loader.py` and `core/plugin_loader.py` auto-discover any module exposing `TOOL` or `PLUGIN`.
- **Handler Signature Introspection**: The loader inspects the function signature. The handler can accept `parameters` (dict) plus any of:
  - `player` (the UI player facade)
  - `speak` (function to enqueue speech)
  - `response` (live response callback)
  - `session_memory` (short-term session context)
- Handlers should return a human-readable string summary of the result for the agent to communicate.

### 3. LLM Call Hygiene (Zero Unbounded Calls)
- **NEVER** instantiate an untimed `genai.Client(...)` inline.
- All auxiliary tasks (grading, quizzes, mindmaps, code analysis, summary) must call:
  ```python
  from core import model_router
  result = model_router.call(prompt, task="study", system=sys_prompt, timeout=45.0)
  # Or for structured JSON:
  data = model_router.as_json(prompt, task="study_fast", system=sys_prompt)
  ```
- Tasks map to fallback ladders (`groq` $\rightarrow$ `openrouter` $\rightarrow$ `gemini REST` $\rightarrow$ `gemini Live throwaway`).

### 4. Study Mode Safety & Privacy Lock
- When Study Mode is active (`study_guard.study_active() == True`):
  - Physical webcam capture is **strictly blocked** (calls to `_capture_camera()` raise `CameraLocked` or return `study_guard.CAMERA_REFUSAL`).
  - Screen capture / OCR (`screen_process(angle='screen')`) **remains enabled** to allow reading textbooks, PDFs, and exam questions.
- Always verify `study_guard.require_camera()` before accessing camera devices.

### 5. Study Content & LaTeX Notation Rules
- Target curriculum: NCTB HSC Bangladesh Science (Physics, Chemistry, Higher Math, Biology, ICT, Bangla, English) + General Advanced topics.
- **Bilingual Rule**: Textual explanations and pedagogy are in natural Bangla; **all** mathematical expressions, equations, SI units, chemical reactions, and code blocks **must** be standard English / LaTeX.
- **Stacked Fractions Rule**: Always use `\frac{a}{b}` or `\frac{numerator}{denominator}`. Never output slash fractions like `a/b` in formulas.
- Wrap inline math in `$...$` and display math in `$$...$$`.

### 6. Process & Platform Rules
- On Windows, all child processes must be spawned with `creationflags=subprocess.CREATE_NO_WINDOW` (patched globally in `main.py`).
- Console output must survive non-UTF-8 locales (`sys.stdout.reconfigure(encoding="utf-8", errors="replace")`).

---

## 4. Key Recipes for AI Agents

### Recipe A: Adding a New Action
Create `actions/<action_name>.py`:
```python
"""
actions/my_new_tool.py — Brief description of what the tool does.
"""
from __future__ import annotations

def my_handler(parameters: dict, player=None) -> str:
    query = str(parameters.get("query") or "").strip()
    if not query:
        return "No query provided."
    # Perform logic...
    return f"Successfully processed '{query}'."

TOOL = {
    "name": "my_new_tool",
    "description": "Explains to Gemini when and why to call this tool.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": "Parameter explanation for model routing."
            }
        },
        "required": ["query"],
    },
    "handler": my_handler,
    "behavior": "BLOCKING",      # "BLOCKING" or "NON_BLOCKING"
    "scheduling": "WHEN_IDLE",    # "WHEN_IDLE" | "SILENT" | "INTERRUPT"
}
```

### Recipe B: Interacting with the Study Station Canvas
In `plugins/study_mentor.py` or any study module:
```python
# Deliver cards/markdown to the QWebEngineView board:
player.study_solution(title="Calculus - Limits", markdown=md_content, subject="Higher Math", reveal="steps")

# Deliver an interactive quiz:
player.study_quiz(title="Thermodynamics Quiz", questions=quiz_list, subject="Physics")

# Deliver 3D flashcards:
player.study_flashcards(title="Organic Reactions", cards=card_list, subject="Chemistry")

# Deliver a 2D branching mindmap:
player.study_mindmap(title="Cell Biology", tree=tree_dict, subject="Biology")

# Update status bar:
player.study_status("Calculating solution...")
```

### Recipe C: Saving to Structured Workspace
Never write output files to the root directory or Desktop without structure. Follow workspace conventions:
- Generated study code: `workspace/code/<lang>/<slug>_<timestamp>.<ext>`
- Exported notes: `workspace/exports/JARVIS_Study_Notes_<timestamp>.docx`
- Long-term memory: `memory/long_term.json`
- Study cache: `memory/study_cache.json`

---

## 5. File & Component Directory Map

| Path | Primary Purpose | Maintainer Notes |
| :--- | :--- | :--- |
| `main.py` | Core voice agent, event loop, tool dispatcher | Avoid bloating. Dispatch tools through loaders. |
| `ui.py` | PyQt6 GUI, Arc Reactor Core HUD, layout switching | Keep UI thread-safe. Use signals for cross-thread calls. |
| `core/model_router.py` | Multi-LLM provider fallback router | Add new model fallbacks and providers here. |
| `core/gemini.py` | Gemini REST & Live throwaway sessions | Manages rate limits and key rotation. |
| `core/study_guard.py` | Webcam safety lock for Study Mode | Synchronous lock; zero Qt/GUI dependencies. |
| `core/study_canvas.py` | QtWebEngine bridge for Study Board | Communicates via `QWebChannel` with `study_board.html`. |
| `plugins/study_mentor.py` | Logic for quizzes, mindmaps, flashcards | Handles NCTB HSC reasoning & LaTeX prompts. |
| `memory/study_cache.py` | Disk cache & mistake bank | 0-token instant reload for revisited queries. |
| `runtime/study_board.html` | Frontend canvas for Study Station | Bundled with Tailwind, KaTeX, and Plotly. |
| `dashboard/server.py` | Encrypted web dashboard & API | Port 8000; AES-256-CBC session security. |
| `config/api_keys.json` | API keys storage | Never commit keys. Structured per provider. |

---

## 6. Common Pitfalls to Avoid

1. ❌ **Don't hardcode models in actions**: Always use `model_router.call()` so keys rotate and fallbacks trigger.
2. ❌ **Don't bypass `study_guard`**: Any camera capture code MUST call `study_guard.require_camera()`.
3. ❌ **Don't format math with slash fractions**: NCTB HSC students require stacked fractions (`\frac{a}{b}`).
4. ❌ **Don't touch `ui.py` widgets from worker threads**: Use `JarvisUI` methods or emit a `pyqtSignal`.
5. ❌ **Don't write files to random root folders**: Use `workspace/code/` or `workspace/exports/`.
