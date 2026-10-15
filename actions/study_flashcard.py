"""
actions/study_flashcard.py — Interactive 3D Flashcard Engine
Generates high-yield study flashcards on the Study Board in Bangla.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict

try:
    from core import model_router as _router
except Exception:
    _router = None

try:
    from memory import study_cache as _cache
except Exception:
    _cache = None


def _fix_bangla_unicode(obj: Any) -> Any:
    """Safe NFC normalization without deleting spaces between Bangla words."""
    if isinstance(obj, str):
        if not obj:
            return ""
        text = unicodedata.normalize("NFC", obj)
        text = re.sub(r"[\u200b\u200e\u200f]", "", text)
        # Only collapse accidental space immediately around hasant (্)
        text = re.sub(r"([\u0980-\u09FF])\s*্\s*([\u0980-\u09FF])", r"\1্\2", text)
        return text
    elif isinstance(obj, dict):
        return {k: _fix_bangla_unicode(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_fix_bangla_unicode(item) for item in obj]
    return obj


def _safe_json_loads(raw: str) -> Any:
    """Robustly parse JSON strings from LLMs that may contain LaTeX formulas with unescaped backslashes."""
    if not raw:
        return None
    text = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.I)
    text = re.sub(r"\s*```$", "", text.strip())

    try:
        return json.loads(text)
    except Exception:
        pass

    # Protect LaTeX keywords that collide with JSON escapes (\frac, \text, \tau, etc.)
    fixed = re.sub(r'\\(frac|text|tau|theta|tan|times|beta|bar|binom|bf)', r'\\\\\1', text)
    # Fix unescaped backslashes not followed by valid JSON escape characters
    fixed = re.sub(r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})', r'\\\\', fixed)
    try:
        return json.loads(fixed)
    except Exception:
        pass

    opens = sorted((fixed.find(a), a, b) for a, b in (("{", "}"), ("[", "]")) if a in fixed)
    for i, _a, b in opens:
        j = fixed.rfind(b)
        if i != -1 and j > i:
            try:
                return json.loads(fixed[i:j + 1])
            except Exception:
                pass

    return json.loads(fixed)


TOOL: Dict[str, Any] = {
    "name": "study_generate_flashcards",
    "description": (
        "Generates interactive 3D flipping flashcards on the Study Board. "
        "Use this for quick memorization of formulas, key points, or definitions."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "topic": {
                "type": "string",
                "description": "Topic or concept for the flashcards.",
            },
            "subject": {
                "type": "string",
                "enum": [
                    "physics",
                    "chemistry",
                    "higher_math",
                    "biology",
                    "ict",
                    "bangla",
                    "english",
                    "general",
                ],
                "description": "Academic subject area.",
            },
            "force_refresh": {
                "type": "string",
                "enum": ["yes", "no"],
                "description": "Set to 'yes' to bypass cache and generate fresh cards.",
            },
        },
        "required": ["topic"],
    },
}

def study_generate_flashcards(parameters: Dict[str, Any], player: Any = None, **kwargs) -> str:
    topic = str(parameters.get("topic") or "").strip()
    if not topic:
        return "[STUDY_BOARD] Error: Topic parameter cannot be empty."

    topic = _fix_bangla_unicode(topic)
    subject = str(parameters.get("subject") or "general").strip().lower()
    force_refresh = str(parameters.get("force_refresh") or "no").lower() == "yes"

    try:
        if player and hasattr(player, "set_study_mode"):
            if not getattr(player, "study_mode_active", False):
                player.set_study_mode(True)

        cache_key = f"flashcards_bn_{subject}_{topic}"
        if not force_refresh and _cache and hasattr(_cache, "get_cached"):
            cached = _cache.get_cached("flashcards", query=cache_key)
            if cached and cached.get("cards"):
                c_title = _fix_bangla_unicode(cached.get("title", topic))
                c_cards = _fix_bangla_unicode(cached["cards"])
                if player and hasattr(player, "study_flashcards"):
                    player.study_flashcards(c_title, c_cards, subject)
                return (
                    f"[STUDY_BOARD] (Cached) {len(c_cards)} Flashcards on '{c_title}' are ready. "
                    f"Tell the user in 1 sentence they can press Spacebar to flip cards and Left/Right arrows to move."
                )

        if player and hasattr(player, "study_status"):
            player.study_status(f"ফ্ল্যাশকার্ড তৈরি হচ্ছে ({topic})…")

        sys_prompt = (
            "You are an expert academic tutor for Bangladeshi HSC Science students.\n"
            "Create 6 high-yield study flashcards for quick memorization.\n\n"
            "CRITICAL BANGLA TERMINOLOGY & FORMULA RULES:\n"
            "- The student is BANGLA MEDIUM. The entire content (front and back) MUST be written in clean BANGLA (বাংলা).\n"
            "- Even if the topic was requested in English, translate everything to clean Bangla.\n"
            "- All formula names, scientific terms, and variable expansions inside LaTeX must be in clean Bangla (e.g. $$\\frac{\\text{মোলার ভর}}{\\text{স্থূল সংকেতের ভর}}$$).\n"
            "- Prevent raw English strings in formula titles.\n"
            "- Mathematical variables, formulas, and units must be in LaTeX ($...$ or $$...$$) using \\frac{a}{b}.\n\n"
            "Return valid JSON ONLY with this exact schema (no markdown wrapping):\n"
            "{\n"
            '  "title": "টপিকের নাম (বাংলায়)",\n'
            '  "cards": [\n'
            '    {"front": "বাংলায় কনসেপ্ট বা সূত্র...", "back": "বাংলায় উত্তর বা সমীকরণ ($Formula$)..."}\n'
            '  ]\n'
            "}"
        )

        user_prompt = f"Subject: {subject}\nTopic: {topic}"

        raw_response = ""
        if _router and hasattr(_router, "call"):
            raw_response = _router.call(
                prompt=user_prompt,
                task="study_fast",
                system=sys_prompt,
                timeout=35,
                budget=80,
            )

        if not raw_response:
            try:
                from core import gemini as _gemini
                raw_response = _gemini.text(f"{sys_prompt}\n\n{user_prompt}", tier=_gemini.FAST)
            except Exception:
                pass

        try:
            data = _safe_json_loads(raw_response) or {}
            raw_cards = data.get("cards") or data.get("items") or []
            cards = _fix_bangla_unicode(raw_cards)
        except Exception:
            if player and hasattr(player, "study_status"):
                player.study_status("ফ্ল্যাশকার্ড তৈরি করতে সমস্যা হয়েছে। দয়া করে পুনরায় চেষ্টা করুন।")
            return "[STUDY_BOARD] Failed to parse flashcards JSON."

        title = _fix_bangla_unicode(str(data.get("title") or topic)[:60])
        
        if player and hasattr(player, "study_flashcards"):
            player.study_flashcards(title, cards, subject)

        if _cache and hasattr(_cache, "save_cache"):
            _cache.save_cache("flashcards", query=cache_key, payload={"title": title, "cards": cards})

        return (
            f"[STUDY_BOARD] {len(cards)} Flashcards on '{title}' are now on the Study Board. "
            "Tell the user in 1 sentence they can press Spacebar to flip each card and Left/Right arrows to move."
        )
    except Exception as e:
        if player and hasattr(player, "study_status"):
            player.study_status("ফ্ল্যাশকার্ড তৈরিতে ত্রুটি ঘটেছে।")
        return f"[STUDY_BOARD] Flashcard error: {e}"

TOOL["handler"] = study_generate_flashcards