# 🚀 JARVIS Study Mode — Advanced Features Roadmap

This document outlines the upcoming phases and advanced features to be integrated into the Universal Learning Station (Study Mode).

---

## 📌 Phase 3: Advanced Spaced Repetition & Mistake Bank
* **Status:** Planned / Next
* **Objectives:**
  1. **Mistake Bank Integration:** Automatically capture every incorrect answer from interactive MCQ quizzes and store them locally in `memory/study_mistakes.json`.
  2. **Offline Revision (`review_mistakes`):** Allow the user to practice previously missed questions offline at **0 API cost**.
  3. **Spaced Repetition Logic:** Prioritize questions that the user has missed multiple times in future revision rounds.

---

## 📌 Phase 4: Interactive Notepad Evaluation (Feynman Technique)
* **Status:** Planned
* **Objectives:**
  1. **Notepad-to-AI Check (`check_notes`):** Read the text written by the user in the split-screen Study Notepad (`Ctrl+N`).
  2. **AI Grading & Feedback:** Evaluate the user's rough notes, code, or essay against accurate concepts using `model_router`.
  3. **Side-by-Side Correction:** Display structured feedback on the Study Board highlighting what was correct, what was missing, and the polished version.

---

## 📌 Phase 5: File Drop-to-Study (PDF, DOCX, PPTX)
* **Status:** Planned
* **Objectives:**
  1. **Drag-and-Drop Ingestion:** Support dropping study materials (PDFs, Word documents, PowerPoint slides) directly onto the File Drop Zone during Study Mode.
  2. **Local Text Extraction:** Extract text locally using lightweight Python libraries (`pdfplumber`, `python-docx`, `python-pptx`) to avoid vision token costs.
  3. **Instant Board Generation:** Automatically offer to generate a Concept Mindmap, Summary Flashcards, or Practice Quiz from the dropped document content.

---

## 📌 Phase 6: Session History & One-Click Word (.docx) Export
* **Status:** Planned
* **Objectives:**
  1. **Session Note Aggregation:** Keep an in-memory history of all solutions, mindmaps, and flashcards rendered during the active study session.
  2. **Desktop Export (`export`):** Compile the session notes and personal notepad text into a professional, well-formatted Microsoft Word (`.docx`) file directly on the user's Desktop using `python-docx`.
  3. **Markdown Fallback:** Provide a clean `.md` export option if Word libraries encounter issues.

---

## 📌 Phase 7: Proactive Tutoring & DND / Notification Controls
* **Status:** Future Scope
* **Objectives:**
  1. **Proactive Quizzing:** Allow JARVIS to proactively suggest a quick 2-minute quiz if the user has been studying a topic for a prolonged period.
  2. **Do Not Disturb (DND) Integration:** Automatically mute non-essential system notifications or external messaging distractions when Study Mode is activated.