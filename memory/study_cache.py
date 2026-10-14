"""
Zero-Cost Local Study Cache & Mistake Bank for JARVIS Study Station.

1. Local Study Cache (`memory/study_cache.json`):
   Stores generated solutions, quizzes, flashcards, and mindmaps keyed by
   (action, subject, normalized_query). Revisiting a topic costs 0 API tokens
   and loads in <10ms.
2. Mistake Bank (`memory/study_mistakes.json`):
   Stores MCQ questions the student answered incorrectly during interactive
   quizzes so they can practice them offline anytime via action='review_mistakes'.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from threading import Lock

if getattr(sys, "frozen", False):
    _BASE = Path(sys.executable).parent
else:
    _BASE = Path(__file__).resolve().parent.parent

CACHE_FILE = _BASE / "memory" / "study_cache.json"
MISTAKES_FILE = _BASE / "memory" / "study_mistakes.json"

_lock = Lock()
_MAX_CACHE_ITEMS = 250
_MAX_MISTAKES = 150


def _norm_key(action: str, subject: str, query: str) -> str:
    clean_q = re.sub(r"\s+", " ", (query or "").strip().lower())
    raw = f"{action.lower().strip()}|{subject.lower().strip()}|{clean_q}"
    return hashlib.md5(raw.encode("utf-8", errors="ignore")).hexdigest()[:20]


def _read_json(path: Path, default):
    if not path.exists():
        return default
    with _lock:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        try:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            print(f"[StudyCache] Write failed ({path.name}): {e}")


def get_cached(action: str, subject: str, query: str) -> dict | None:
    """Return cached payload dict if present, else None (0 tokens)."""
    key = _norm_key(action, subject, query)
    store = _read_json(CACHE_FILE, {})
    if not isinstance(store, dict):
        return None
    item = store.get(key)
    return item if isinstance(item, dict) else None


def save_cache(action: str, subject: str, query: str, payload: dict) -> None:
    """Save generated study payload to disk cache."""
    if not query or not isinstance(payload, dict):
        return
    key = _norm_key(action, subject, query)
    store = _read_json(CACHE_FILE, {})
    if not isinstance(store, dict):
        store = {}
    store[key] = {
        **payload,
        "cached_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "query_preview": (query or "")[:100],
    }
    if len(store) > _MAX_CACHE_ITEMS:
        sorted_keys = sorted(store.keys(), key=lambda k: store[k].get("cached_at", ""))
        for k in sorted_keys[: len(store) - _MAX_CACHE_ITEMS]:
            store.pop(k, None)
    _write_json(CACHE_FILE, store)


def add_mistakes(topic: str, mistakes: list[dict]) -> None:
    """Save wrong quiz answers to the Mistake Bank for spaced repetition."""
    if not mistakes:
        return
    bank = _read_json(MISTAKES_FILE, [])
    if not isinstance(bank, list):
        bank = []
    existing_qs = {str(m.get("question", "")).strip().lower() for m in bank}
    now_str = datetime.now().strftime("%Y-%m-%d")

    for m in mistakes:
        q_txt = str(m.get("question") or "").strip()
        opts = m.get("options") or []
        if not q_txt or not opts or q_txt.lower() in existing_qs:
            continue
        ans_idx = m.get("answer_idx")
        if not isinstance(ans_idx, int):
            try:
                ans_idx = opts.index(m.get("answer"))
            except ValueError:
                ans_idx = 0
        bank.append({
            "topic": topic or "General",
            "question": q_txt,
            "options": opts,
            "answer": ans_idx,
            "explain": str(m.get("explain") or ""),
            "added": now_str,
        })
        existing_qs.add(q_txt.lower())

    bank = bank[-_MAX_MISTAKES:]
    _write_json(MISTAKES_FILE, bank)


def get_mistakes(topic_filter: str = "", limit: int = 10) -> list[dict]:
    """Return saved mistake questions for offline practice (0 API cost)."""
    bank = _read_json(MISTAKES_FILE, [])
    if not isinstance(bank, list) or not bank:
        return []
    tf = (topic_filter or "").strip().lower()
    if tf:
        matched = [m for m in bank if tf in str(m.get("topic", "")).lower() or tf in str(m.get("question", "")).lower()]
        if matched:
            bank = matched
    return list(reversed(bank))[: max(1, limit)]