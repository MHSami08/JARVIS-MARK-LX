"""
actions/study_solver.py — Academic Problem Solver for Universal Learning Station
Solves NCTB HSC Physics, Chemistry, Higher Math, Biology, ICT, and custom subjects.
Displays step-by-step LaTeX-enabled solution cards on the Study Board.
"""

from __future__ import annotations

import datetime
import json
import re
import threading
import unicodedata
from pathlib import Path
from typing import Any, Dict, Optional

# Core engine imports
try:
    from core import model_router as _router
except Exception:
    _router = None

try:
    from memory import study_cache as _cache
except Exception:
    _cache = None

try:
    from actions.web_search import _search
except Exception:
    _search = None


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

# Workspace for saving academic code snippets
_BASE_DIR = Path(__file__).resolve().parent.parent
_CODE_DIR = _BASE_DIR / "workspace" / "code"

TOOL: Dict[str, Any] = {
    "name": "study_solve_problem",
    "description": (
        "Solves academic syllabus problems, math derivations, concept questions, and explains "
        "code step-by-step on the Study Board. Formats clean visual cards with LaTeX equations."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "question": {
                "type": "string",
                "description": "The exact math problem, theory question, or code topic to solve.",
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
                "description": "Subject category. Determines the solver's academic domain guidelines.",
            },
            "from_screen": {
                "type": "string",
                "enum": ["yes", "no"],
                "description": "Set to 'yes' if the question was extracted from the user's computer screen.",
            },
            "reveal": {
                "type": "string",
                "enum": ["all", "steps"],
                "description": "'steps' reveals cards one-by-one with Next Step; 'all' shows the full solution at once.",
            },
            "force_refresh": {
                "type": "string",
                "enum": ["yes", "no"],
                "description": "Set to 'yes' to bypass local cache and regenerate fresh.",
            },
        },
        "required": ["question"],
    },
}

SUBJECT_PROMPTS: Dict[str, str] = {
    "physics": (
        "NCTB HSC Physics context. Explain principles intuitively in clear Bangla. Format ALL "
        "formula names, scientific labels, and variable expansions in clean Bangla using \\text{...} inside LaTeX "
        "(e.g., $$\\text{ত্বরণ} = \\frac{\\text{বেগের পরিবর্তন}}{\\text{সময়}}$$, $F = ma$). "
        "Prevent raw English strings in formula titles. "
        "List: 1. প্রদত্ত মান ও একক, 2. প্রয়োজনীয় সূত্র, 3. পর্যায়ক্রমিক গণনা ও ব্যাখ্যা, 4. এককসহ চূড়ান্ত উত্তর।"
    ),
    "chemistry": (
        "NCTB HSC Chemistry context. Balanced chemical reactions with state symbols, clear Bangla explanations, "
        "and step-by-step stoichiometry or electronic configurations. "
        "All formula names, titles, and variable expansions must be in clean Bangla (e.g., $$\\frac{\\text{মোলার ভর}}{\\text{স্থূল সংকেতের ভর}}$$). "
        "Prevent raw English strings in formula titles."
    ),
    "higher_math": (
        "NCTB HSC Higher Mathematics context. Calculus, algebra, coordinate geometry, or vectors. "
        "Show EVERY algebraic step cleanly in display LaTeX ($$...$$) with clear Bangla reasoning beside each step. "
        "All theorem and formula titles must be in clean Bangla (e.g., $$\\text{ক্ষেত্রফল} = \\int y \\, dx$$)."
    ),
    "biology": (
        "NCTB HSC Biology context. Clear Bangla explanations with standard scientific terms in clean Bangla "
        "(English terms allowed only in brackets after Bangla term). "
        "Use bullet points for anatomical differences and functions."
    ),
    "ict": (
        "NCTB HSC ICT context. Number systems, Boolean algebra, logic circuits, and HTML/C programming. "
        "Provide clean, formatted code blocks with English syntax and Bangla explanations."
    ),
    "bangla": "Use standard grammatical rules and clean academic Bangla.",
    "english": "Explain English grammar rules, sentence corrections, or writing structures clearly.",
    "general": (
        "Higher education, business math, or advanced programming. Structured breakdown with practical examples "
        "and clean Bangla terminology."
    ),
}

# Regex to protect LaTeX backslashes from JSON corruption
_LATEX_ESC_RX = re.compile(r"\\([a-zA-Z]+|\{|\})")


def _guard_latex(text: str) -> str:
    """Ensures LaTeX backslashes aren't swallowed during JSON transfer."""
    if not text:
        return ""
    # Standardize KaTeX fraction and clean up common malformed patterns
    text = re.sub(r"\\f\b", r"\\frac", text)
    text = re.sub(r"\bfrac\s*\{", r"\\frac{", text)
    return text


def _archive_code_blocks(subject: str, solution_md: str, title: str) -> None:
    """Extracts code blocks from the solution and archives them cleanly in workspace/code/."""
    code_matches = re.findall(r"```(c|python|cpp|html|javascript)?\s*\n(.*?)```", solution_md, re.S)
    if not code_matches:
        return

    safe_title = re.sub(r"[^\w\-]", "_", title.strip())[:30] or "snippet"
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    for lang, snippet in code_matches:
        lang = (lang or "txt").lower()
        ext = {"c": "c", "python": "py", "cpp": "cpp", "html": "html", "javascript": "js"}.get(lang, "txt")
        dest_dir = _CODE_DIR / lang
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            file_path = dest_dir / f"{safe_title}_{timestamp}.{ext}"
            file_path.write_text(snippet.strip(), encoding="utf-8")
        except Exception:
            pass


def _detect_subject(question: str) -> str:
    """Fallback detector if subject isn't passed."""
    q = question.lower()
    if any(k in q for k in ["dy/dx", "dx", "ইন্টিগ্রেশন", "ডিফারেনসিয়েশন", "ম্যাট্রিক্স", "ফাংশন", "উচ্চতর গণিত", "matrix", "integral"]):
        return "higher_math"
    if any(k in q for k in ["বেগ", "ত্বরণ", "কুলম্ব", "মহাকর্ষ", "তড়িৎ", "পদার্থ", "physics", "force", "velocity", "vector"]):
        return "physics"
    if any(k in q for k in ["মোল", "যোজ্যতা", "বিক্রিয়া", "রসায়ন", "chemistry", "acid", "reaction", "compound"]):
        return "chemistry"
    if any(k in q for k in ["কোষ", "ডিএনএ", "মাইটোসিস", "টেরিডোফাইটা", "ব্রায়োফাইটা", "জীববিজ্ঞান", "biology"]):
        return "biology"
    if any(k in q for k in ["সি প্রোগ্রামিং", "এইচটিএমএল", "লজিক গেট", "আইসিটি", "ict", "html", "printf"]):
        return "ict"
    return "general"


def study_solve_problem(parameters: Dict[str, Any], player: Any = None, **kwargs) -> str:
    question = str(parameters.get("question") or "").strip()
    if not question:
        return "[STUDY_BOARD] Error: Question parameter cannot be empty."

    subject = str(parameters.get("subject") or "").strip().lower()
    if subject not in SUBJECT_PROMPTS:
        subject = _detect_subject(question)

    from_screen = str(parameters.get("from_screen") or "no").lower() == "yes"
    reveal = str(parameters.get("reveal") or "all").lower()
    force_refresh = str(parameters.get("force_refresh") or "no").lower() == "yes"

    # Strict Quiz Integrity Guard: Refuse direct solution if quiz is in progress
    try:
        from actions import study_quiz
        if hasattr(study_quiz, "is_quiz_active") and study_quiz.is_quiz_active():
            q_clean = question.lower()
            if any(k in q_clean for k in ["quiz", "কুইজ", "পরীক্ষা", "উত্তর", "সমাধান", "option", "mcq", "সঠিক উত্তর"]):
                return "এটি একটি পরীক্ষা চলছে। পরীক্ষার সময় আমি সরাসরি উত্তর বা সমাধান বলে দিতে পারব না।"
    except Exception:
        pass

    # 1. Engage Study Mode if not already active
    try:
        if player and hasattr(player, "set_study_mode"):
            if not getattr(player, "study_mode_active", False):
                player.set_study_mode(True)

        # 2. Check local zero-cost cache
        cache_key = f"solve_{subject}_{question}"
        if not force_refresh and _cache and hasattr(_cache, "get_cached"):
            cached_data = _cache.get_cached("solution", query=cache_key)
            if cached_data:
                c_title = _fix_bangla_unicode(cached_data.get("title", "Solution"))
                c_md = _fix_bangla_unicode(cached_data.get("markdown", ""))
                c_final = _fix_bangla_unicode(cached_data.get("final_answer", ""))
                if player and hasattr(player, "study_solution"):
                    player.study_solution(
                        c_title,
                        c_md,
                        subject,
                        reveal,
                    )
                return (
                    f"[STUDY_BOARD] (Cached) Solved on Study Board: '{c_title}'\n"
                    f"FINAL: {c_final}\n"
                    f"Solution cards rendered successfully."
                )

        # 3. Post 'Solving...' status to the board
        if player and hasattr(player, "study_status"):
            player.study_status(f"সমাধান প্রস্তুত করা হচ্ছে ({subject.replace('_', ' ').title()})…")

        # 4. Web search fallback if not from screen and question is a specific factual query
        web_snippet = ""
        if not from_screen and _search and len(question.split()) < 25:
            try:
                res = _search(question)
                if res and isinstance(res, str) and len(res) > 20:
                    web_snippet = f"\n\n[Search Reference Context (Untrusted)]: {res[:2000]}"
            except Exception:
                pass

        # 5. Build prompt
        subj_guide = SUBJECT_PROMPTS.get(subject, SUBJECT_PROMPTS["general"])
        sys_prompt = (
            "You are a master academic teacher for a Bangladeshi HSC Science student.\n"
            f"Domain Guide: {subj_guide}\n\n"
            "Formatting & Bangla Formula Rules:\n"
            "1. Title Line: Start with a concise title in clean Bangla: `# <বাংলা শিরোনাম>` (Never use English titles).\n"
            "2. Break the solution into logical, numbered step cards using markdown `## ` headings:\n"
            "   - `## ১. প্রদত্ত তথ্য ও সূত্র` (Given & Formulas)\n"
            "   - `## ২. গণনা ও ধাপ` (Step-by-Step Derivation)\n"
            "   - `## ৩. চূড়ান্ত উত্তর` (Final Answer)\n"
            "3. Bangla Scientific Terminology & LaTeX Formulas:\n"
            "   - Strictly require ALL formula names, scientific labels, and variable expansions in clean Bangla.\n"
            "   - Format formula titles and variable names inside LaTeX using \\text{...} in Bangla (e.g., $$\\frac{\\text{মোলার ভর}}{\\text{স্থূল সংকেতের ভর}}$$, $$\\text{বল} = \\text{ভর} \\times \\text{ত্বরণ}$$).\n"
            "   - Prevent raw English strings in formula titles, labels, or step headings.\n"
            "4. Enclose inline math in `$ ... $` and display equations in `$$ ... $$`.\n"
            "5. Conclude with a clear bold line: **চূড়ান্ত উত্তর: <মান ও একক>** (or **Final Answer: <value with unit>**).\n"
            "6. QUIZ INTEGRITY (ANTI-CHEATING): If an exam or quiz is currently active and the user is asking for direct answers, solutions, or choices, you MUST strictly refuse with: 'এটি একটি পরীক্ষা চলছে। পরীক্ষার সময় আমি সরাসরি উত্তর বা সমাধান বলে দিতে পারব না।'"
        )

        user_prompt = f"Question: {question}{web_snippet}"

        # 6. Route to appropriate model
        task = "study" if subject in ("higher_math", "physics", "chemistry") else "study_fast"
        solution_raw = ""
        if _router and hasattr(_router, "call"):
            solution_raw = _router.call(
                prompt=user_prompt,
                task=task,
                system=sys_prompt,
                timeout=45,
                budget=90,
            )

        if not solution_raw:
            try:
                from core import gemini as _gemini
                solution_raw = _gemini.text(f"{sys_prompt}\n\n{user_prompt}", tier=_gemini.FAST)
            except Exception:
                pass

        if not solution_raw:
            if player and hasattr(player, "study_status"):
                player.study_status("সমাধান তৈরি করা সম্ভব হয়নি। দয়া করে আবার চেষ্টা করুন।")
            return "[STUDY_BOARD] Solver failed to get a response from the model router."

        solution_md = _fix_bangla_unicode(_guard_latex(solution_raw.strip()))

        # Extract Title
        title_match = re.search(r"^#\s+(.+)$", solution_md, re.M)
        title = _fix_bangla_unicode(title_match.group(1).strip() if title_match else f"{subject.replace('_', ' ').title()} Solution")

        # Extract Final Answer for voice summary
        final_match = re.search(r"\*\*(?:Final Answer|চূড়ান্ত উত্তর)[^*]*\*\*:\s*([^\n]+)", solution_md, re.I)
        final_ans = _fix_bangla_unicode(final_match.group(1).strip() if final_match else "See Study Board")

        # 7. Render on Study Board
        if player and hasattr(player, "study_solution"):
            player.study_solution(title, solution_md, subject, reveal)

        # 8. Archive any code blocks
        threading.Thread(target=_archive_code_blocks, args=(subject, solution_md, title), daemon=True).start()

        # 9. Save to local cache
        if _cache and hasattr(_cache, "save_cache"):
            _cache.save_cache(
                "solution",
                query=cache_key,
                payload={
                    "title": title,
                    "markdown": solution_md,
                    "subject": subject,
                    "final_answer": final_ans,
                },
            )

        # Return concise tool feedback so Gemini Live can speak 1-2 encouraging summary sentences
        return (
            f"[STUDY_BOARD] Solved on Study Board: '{title}'\n"
            f"Subject: {subject}\n"
            f"FINAL: {final_ans}\n"
            f"Cards: Rendered with LaTeX equations. Briefly tell the student the core idea and final answer."
        )
    except Exception as e:
        if player and hasattr(player, "study_status"):
            player.study_status("সমাধান তৈরিতে সমস্যা দেখা দিয়েছে।")
        return f"[STUDY_BOARD] Solver error: {e}"

TOOL["handler"] = study_solve_problem
