"""
plugins/study_mentor.py — Lightweight Backend Edition.
All primary tasks (Quiz, Flashcards, Mindmap, Problem Solver) are now handled by 
dedicated action modules in the actions/ folder. This module now only acts as a 
backend for notepad evaluation, export, and mistake review.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

try:
    from memory import study_cache
except Exception:
    study_cache = None

try:
    from core import model_router
except Exception:
    model_router = None

_BASE = Path(__file__).resolve().parent.parent
EXPORT_WORKSPACE_DIR = _BASE / "workspace" / "exports"
_SESSION_HISTORY: list[dict] = []

def _lang(text: str) -> str:
    t = str(text or "").lower()
    if any(k in t for k in ["in english", "english version", "ইংরেজি", "ইংলিশে"]):
        return "en"
    return "bn"

def _run_check_notes(player) -> str:
    notes = (player.get_notepad_text() or "").strip() if hasattr(player, "get_notepad_text") else ""
    if not notes:
        return "[STUDY_BOARD] The Study Notepad is empty. Ask the student to press Ctrl+N and write something first."

    lang = _lang(notes)
    player.study_status("Reviewing your notes…" if lang == "en" else "আপনার নোট পরীক্ষা করা হচ্ছে…")
    sys_p = (
        "You are a supportive academic mentor reviewing a student's rough notes. "
        "Format output in Markdown with `# Note Review` and these exact sections:\n"
        "## ✓ What You Got Right\n"
        "## ⚠ Mistakes or Missing Points\n"
        "## ★ Corrected & Polished Version\n"
        "Write in the same language as the notes. Wrap math in LaTeX."
    )
    raw = model_router.call(f"STUDENT'S NOTES:\n{notes[:3500]}", task="study_fast", system=sys_p, timeout=45.0)
    if not raw:
        return "[STUDY_BOARD] Could not evaluate notes right now."
    
    md = re.sub(r"^```(?:markdown|md)?\s*\n", "", raw.strip(), flags=re.I)
    md = re.sub(r"\n```\s*$", "", md.strip())
    
    _SESSION_HISTORY.append({"title": "Notepad Review", "markdown": md})
    player.study_solution("Notepad Review", md, "Note Check", reveal="all")
    return f"[STUDY_BOARD] Notepad review is on the board. Give 1-2 sentences of spoken feedback.\nSUMMARY:\n{md[:1500]}"

def _run_export(player) -> str:
    notepad_txt = player.get_notepad_text().strip() if hasattr(player, "get_notepad_text") else ""
    if not _SESSION_HISTORY and not notepad_txt:
        return "There are no study notes or solutions to export."

    EXPORT_WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    out_path = EXPORT_WORKSPACE_DIR / f"JARVIS_Study_Notes_{stamp}.md"
    parts = [f"# JARVIS Study Notes ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n"]
    if notepad_txt:
        parts.append(f"## My Notepad\n{notepad_txt}\n")
    for item in _SESSION_HISTORY:
        parts.append(item.get("markdown", ""))
        
    out_path.write_text("\n\n---\n\n".join(parts), encoding="utf-8")
    return f"[STUDY_BOARD] Exported session notes cleanly to structured workspace: {out_path}"

def run(parameters, player=None, **kwargs) -> str:
    action = str((parameters or {}).get("action") or "").lower().strip()
    
    if action == "review_mistakes":
        mistakes = study_cache.get_mistakes("all", limit=10) if study_cache else []
        if not mistakes:
            return "[STUDY_BOARD] Your Mistake Bank is clean — no saved wrong answers found! Congratulate the student."
        player.study_quiz("Mistake Bank Revision", mistakes, "Revision")
        return f"[STUDY_BOARD] Loaded {len(mistakes)} previously missed questions. Tell the user to press 1-4 to practice them."
        
    if action == "check_notes":
        return _run_check_notes(player)
        
    if action == "export":
        return _run_export(player)
        
    return f"Unknown or deprecated action in study_mentor: {action}"

PLUGIN = {
    "name": "study_mode",
    "description": "Backend engine for check_notes, export, and review_mistakes.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "check_notes | export | review_mistakes"
            }
        },
        "required": ["action"],
    },
}
