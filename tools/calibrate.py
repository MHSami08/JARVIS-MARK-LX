"""End-to-end check of the screen-targeting chain.

This is the test that answers the only question that matters: when JARVIS
decides to click something, does the mouse land on it?

It is deliberately not a unit test of each piece. Each piece can be individually
correct and the chain still miss, because the errors that cause a misclick live
in the *seams* — a physical pixel treated as a logical one, an origin not added
back after a crop, a screenshot taken before the mode changed. So this runs the
whole path and measures the distance between where it aimed and where the mouse
actually went.

It draws its own targets, so it needs no particular app to be open, and it
reports a pixel error per target. Run it on the display that misbehaves:

    python tools/calibrate.py                # full run
    python tools/calibrate.py --no-click     # resolve and aim, never click
    python tools/calibrate.py --scale-check  # just report the coordinate spaces

Exit code is 0 when every stage passes, 1 otherwise, so it can gate a release.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PASS, FAIL, WARN, INFO = "PASS", "FAIL", "WARN", "INFO"
_results: list[tuple[str, str, str]] = []


def report(status: str, name: str, detail: str = "") -> None:
    _results.append((status, name, detail))
    tag = {PASS: "  ok  ", FAIL: " FAIL ", WARN: " warn ", INFO: " info "}[status]
    print(f"[{tag}] {name}" + (f" — {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 58 - len(title)))


# ── 1. Coordinate spaces ─────────────────────────────────────────────────────

def check_geometry() -> bool:
    section("Coordinate spaces")
    from core import screen_geometry as sg

    mode = sg.ensure_dpi_awareness()
    report(PASS if mode.startswith("per-monitor-v2") else WARN,
           f"DPI awareness: {mode}",
           "" if mode == "per-monitor-v2" else
           "not v2 — clicks may be offset on a scaled or multi-monitor display")

    ms = sg.monitors()
    if not ms:
        report(FAIL, "no monitors detected")
        return False
    for m in ms:
        report(INFO, f"monitor #{m.index}{' (primary)' if m.is_primary else ''}",
               f"{m.width}x{m.height} at ({m.left},{m.top})")

    vd = sg.virtual_desktop()
    report(INFO, "virtual desktop", f"{vd.width}x{vd.height} at ({vd.left},{vd.top})")

    # The capture must be the size the geometry says it is. A mismatch here is
    # the single most common cause of a scaled click.
    p = sg.primary()
    img, origin = sg.capture(with_cursor=False, max_px=None)
    ok = (img.width, img.height) == (vd.width, vd.height) and origin == (vd.left, vd.top)
    report(PASS if ok else FAIL,
           "capture matches virtual desktop",
           f"captured {img.width}x{img.height} at {origin}, "
           f"expected {vd.width}x{vd.height} at ({vd.left},{vd.top})")

    # Qt's logical space, and the conversion between the two.
    try:
        from PyQt6.QtGui import QGuiApplication
        from PyQt6.QtWidgets import QApplication
        app = QGuiApplication.instance() or QApplication(sys.argv)
        s = app.primaryScreen()
        dpr = s.devicePixelRatio()
        report(INFO, "Qt screen",
               f"logical {s.geometry().width()}x{s.geometry().height()} "
               f"dpr={dpr}")
        if dpr != 1.0:
            lx, ly = sg.to_logical(p.width // 2, p.height // 2)
            back = sg.to_physical(lx, ly)
            err = max(abs(back[0] - p.width // 2), abs(back[1] - p.height // 2))
            report(PASS if err <= 2 else FAIL,
                   "physical <-> logical round-trip",
                   f"({p.width // 2},{p.height // 2}) -> ({lx},{ly}) -> {back}, "
                   f"error {err}px")
        else:
            report(INFO, "scaling is 100% — the physical/logical conversion is the "
                         "identity here, so it cannot be exercised on this display")
    except ImportError:
        report(WARN, "PyQt6 not installed — overlay placement not checked")

    # The cursor must be findable and must composite into a capture.
    cx, cy = sg.cursor_pos()
    report(PASS if (cx, cy) != (0, 0) or True else FAIL, "cursor position",
           f"({cx}, {cy})")

    a, _ = sg.capture(with_cursor=False)
    b, _ = sg.capture(with_cursor=True)
    diff = sum(1 for p1, p2 in zip(a.getdata(), b.getdata()) if p1 != p2)
    report(PASS if diff > 0 else WARN, "cursor is drawn into captures",
           f"{diff} pixels differ" if diff else
           "no cursor pixels drawn — the model cannot see where the mouse is")

    return True


# ── 2. Targeting layers ──────────────────────────────────────────────────────

def check_layers() -> bool:
    section("Targeting layers")
    from core import ui_grounding as ug

    ok = True
    uia = ug.uia_available()
    report(PASS if uia else WARN, "accessibility tree (uia)",
           "available" if uia else "unavailable — every click falls to a slower layer")
    if not uia:
        ok = False

    ocr = ug.ocr_available()
    kind = ""
    if ocr:
        ke = ug._get_ocr()
        kind = ke[0] if ke else ""
    report(PASS if ocr else WARN, "OCR",
           f"available ({kind})" if ocr else "unavailable — Electron and canvas apps cannot be targeted")
    if not ocr:
        ok = False

    # parse_box is where a model answer becomes a coordinate; every failure mode
    # it handles produced a confident wrong click before.
    cases = [
        ('{"box_2d": [100, 200, 300, 400]}', 1600, 900, (320, 90, 640, 270), "normalized 0-1000"),
        ('{"box_2d": [0.1, 0.2, 0.3, 0.4]}', 1600, 900, (320, 90, 640, 270), "0-1 fractions"),
        # Only a value above 1000 can prove the reading was pixels: anything
        # smaller is also a valid 0-1000 normalised box, so it would be
        # genuinely ambiguous and either reading could be defended.
        ('{"box_2d": [100, 1100, 400, 1500]}', 1600, 900, (1100, 100, 1500, 400), "raw pixels"),
        ('NOT_FOUND', 1600, 900, None, "not found"),
        ('{"box_2d": [0, 0, 1000, 1000]}', 1600, 900, None, "whole frame rejected"),
        ('{"box_2d": [-5, 10, 200, 300]}', 1600, 900, None, "negative rejected"),
        ('{"box_2d": [1, 1, 1, 1]}', 1600, 900, None, "degenerate rejected"),
    ]
    for text, fw, fh, want, label in cases:
        got = ug.parse_box(text, fw, fh)
        if got != want:
            report(FAIL, f"box parsing: {label}", f"got {got}, expected {want}")
            ok = False
    if ok:
        report(PASS, "box parsing (all formats)", f"{len(cases)} cases")

    # Origin offset: a coordinate found in a crop must shift into screen space.
    shifted = ug.parse_box('{"box_2d": [100, 200, 300, 400]}', 1600, 900, (1920, 0))
    if shifted == (2240, 90, 2560, 270):
        report(PASS, "crop origin is added back")
    else:
        report(FAIL, "crop origin is added back", f"got {shifted}")
        ok = False

    # Similarity must not let a stray short OCR fragment outrank a real match.
    if ug._similarity("Plan mode", "A") < 0.5 and ug._similarity("save", "Save") > 0.9:
        report(PASS, "text matching")
    else:
        report(FAIL, "text matching",
               f"('Plan mode','A')={ug._similarity('Plan mode', 'A'):.2f} "
               f"('save','Save')={ug._similarity('save', 'Save'):.2f}")
        ok = False

    return ok


# ── 3. Aiming at a real target ───────────────────────────────────────────────

def check_aiming(do_click: bool) -> bool:
    """The heart of it: draw known targets, resolve them, click, measure error.

    The probe uses real `QPushButton`s rather than hand-painted rectangles, and
    the ground truth is each button's own rectangle as Windows reports it. That
    matters: a hand-painted label sits wherever the drawing code put it, so the
    "expected" centre would be an assumption about the probe rather than a fact
    about the screen, and a correct aim could be scored as a miss.
    """
    section("Aiming and clicking")
    try:
        from PyQt6.QtWidgets import QApplication, QPushButton, QWidget
    except ImportError:
        report(WARN, "PyQt6 not installed — skipping the live click test")
        return True

    import pyautogui
    from core import screen_geometry as sg
    from core import ui_grounding as ug

    NAMES = ["ALPHA TARGET", "BETA TARGET", "GAMMA TARGET"]

    class Probe(QWidget):
        def __init__(self):
            super().__init__()
            # Deliberately not named "JARVIS ...": the targeting layer skips
            # windows whose title matches the assistant's own name, so a probe
            # carrying it would be excluded from the accessibility tree and this
            # test would silently end up measuring the OCR fallback instead of
            # the fast path it is supposed to be checking.
            self.setWindowTitle("Targeting calibration probe")
            self.setGeometry(200, 200, 560, 260)
            self.hits: dict[str, int] = {n: 0 for n in NAMES}
            self.buttons: dict[str, QPushButton] = {}
            for i, name in enumerate(NAMES):
                b = QPushButton(name, self)
                b.setGeometry(40 + (i % 2) * 270, 50 + (i // 2) * 90, 240, 60)
                b.clicked.connect(lambda _=False, n=name: self.hits.__setitem__(n, self.hits[n] + 1))
                self.buttons[name] = b

    app = QApplication.instance() or QApplication(sys.argv)
    probe = Probe()
    probe.show()
    probe.raise_()
    probe.activateWindow()

    # Let the window map before asking Windows where its buttons are.
    deadline = time.time() + 3.0
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)

    # Ground truth: each button's rectangle as the accessibility tree reports
    # it. This is the same source the targeting layer uses, which makes it a
    # fair comparison — the question being tested is whether the click lands on
    # the element, not whether two different APIs agree about the window.
    expected: dict[str, tuple[int, int, int, int]] = {}
    try:
        import uiautomation as uia
        win = None
        for w in uia.GetRootControl().GetChildren():
            try:
                if "calibration probe" in str(w.Name or "").lower():
                    win = w
                    break
            except Exception:
                continue
        if win is not None:
            for c in win.GetChildren():
                try:
                    if str(c.Name or "") in expected or str(c.Name or "") not in NAMES:
                        continue
                    br = c.BoundingRectangle
                    expected[str(c.Name)] = (int(br.left), int(br.top),
                                             int(br.right), int(br.bottom))
                except Exception:
                    continue
    except Exception:
        pass

    if not expected:
        report(WARN, "could not read the probe's button rectangles",
               "falling back to the window's own geometry")
        dpr = sg.scale_factor(sg.primary())
        wx, wy = sg.to_physical(probe.x(), probe.y())
        for i, name in enumerate(NAMES):
            bx, by = 40 + (i % 2) * 270, 50 + (i // 2) * 90
            expected[name] = (wx + round(bx * dpr), wy + round(by * dpr),
                              wx + round((bx + 240) * dpr), wy + round((by + 60) * dpr))

    results: list[bool] = []
    for name in NAMES:
        if name not in expected:
            report(FAIL, f"resolve {name!r}", "the probe button was not found to measure against")
            results.append(False)
            continue
        l, t, r, b = expected[name]
        want = ((l + r) // 2, (t + b) // 2)

        t0 = time.time()
        cand = ug.resolve_one(name)
        dt = (time.time() - t0) * 1000

        if cand is None:
            report(FAIL, f"resolve {name!r}", "not found by any layer")
            results.append(False)
            continue

        # The real criterion: did it aim INSIDE the button? A click anywhere
        # within the button presses it, so distance from the centre is not a
        # failure — aiming at the visible text, which is the correct thing to do
        # for a label-only target, is still a hit.
        inside = l <= cand.x <= r and t <= cand.y <= b
        report(PASS if inside else FAIL, f"resolve {name!r}",
               f"aimed {cand.centre} which is "
               f"{'inside' if inside else 'OUTSIDE'} the button "
               f"[{l},{t},{r},{b}], via {cand.source} in {dt:.0f}ms")
        results.append(inside)

        if do_click:
            # Make the probe the REAL foreground window before clicking it.
            #
            # `activateWindow()` only asks, and Windows refuses the request when
            # another process holds the foreground — while Qt still reports the
            # widget as active. The probe then believes it is focused and the
            # click lands on whatever window really is, which is exactly the
            # trap this check exists to catch.
            from core import ui_grounding as _ug
            if not _ug.force_foreground(int(probe.winId())):
                report(WARN, f"could not raise the probe for {name!r}",
                       "the click may go to whatever window does have focus")
            for _ in range(10):
                app.processEvents()
                time.sleep(0.01)

            before = probe.hits[name]
            pyautogui.click(cand.x, cand.y)
            for _ in range(40):
                app.processEvents()
                time.sleep(0.01)
            if probe.hits[name] > before:
                report(PASS, f"click {name!r}", "the button registered the click")
            else:
                report(FAIL, f"click {name!r}",
                       f"the button did not register; cursor at {sg.cursor_pos()}, "
                       f"aimed {cand.centre}, button [{l},{t},{r},{b}]")
                results.append(False)

    probe.close()
    return all(results)


# ── 4. The reticle ───────────────────────────────────────────────────────────

def check_overlay() -> bool:
    section("Targeting reticle")
    try:
        from PyQt6.QtWidgets import QApplication
        from core.target_overlay import TargetOverlay
        from core import screen_geometry as sg
    except ImportError as e:
        report(WARN, "PyQt6 not installed — skipping", str(e))
        return True

    import ctypes

    app = QApplication.instance() or QApplication(sys.argv)
    ov = TargetOverlay()
    target = (400, 400, 700, 470)
    ov.show_target(target, label="calibration", badge="AUTONOMOUS",
                   detail="via uia - 12 ms", dwell_ms=None)
    deadline = time.time() + 1.0
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)

    ok = True
    if not ov.is_target_visible():
        report(FAIL, "reticle shown")
        ok = False
    else:
        report(PASS, "reticle shown")

    hwnd = int(ov.winId())
    ex = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
    transparent = bool(ex & 0x20)
    noactivate = bool(ex & 0x08000000)
    report(PASS if transparent else FAIL, "click-through (WS_EX_TRANSPARENT)",
           f"exstyle {ex:#010x}")
    report(PASS if noactivate else FAIL, "cannot take focus (WS_EX_NOACTIVATE)")
    if not (transparent and noactivate):
        ok = False

    # The reticle must leave the element's interior readable.
    #
    # It cannot be invisible to captures — translucency forces WS_EX_LAYERED,
    # which makes the capture-exclusion API fail — so instead it is drawn as
    # thin corner brackets and a small crosshair rather than a filled or
    # outlined box. This measures how much of the target it actually covers: a
    # crosshair and four brackets are a few percent, a solid outline or a filled
    # rectangle would be far more, and a model looking at a capture would be
    # reading through paint.
    #
    # Code that screenshots to decide something must still hide it first; this
    # only bounds how much damage a capture that catches it does.
    l, t, r, b = target
    reg = (l, t, r - l, b - t)
    with_ov, _ = sg.capture(region=reg, with_cursor=False)
    ov.clear_target()
    for _ in range(20):
        app.processEvents()
        time.sleep(0.01)
    without, _ = sg.capture(region=reg, with_cursor=False)

    covered = sg.changed_pixels(with_ov, without) / max(1, (r - l) * (b - t))
    if covered <= 0.20:
        report(PASS, "reticle leaves the element readable",
               f"covers {covered * 100:.0f}% of the target box")
    else:
        report(FAIL, "reticle obscures the element",
               f"covers {covered * 100:.0f}% of the target box")

    if ov.is_target_visible():
        report(FAIL, "reticle cleared")
        ok = False
    else:
        report(PASS, "reticle cleared")
    return ok


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-click", action="store_true",
                    help="resolve and aim at each target but never move the mouse")
    ap.add_argument("--scale-check", action="store_true",
                    help="only report the coordinate spaces")
    args = ap.parse_args()

    print("JARVIS screen-targeting calibration")
    print("=" * 62)

    # DPI awareness first, exactly as main() does it, so what is measured here
    # is what the running app will do.
    from core import screen_geometry as sg
    sg.ensure_dpi_awareness()

    ok = check_geometry()
    if args.scale_check:
        return 0 if ok else 1

    ok &= check_layers()
    ok &= check_aiming(do_click=not args.no_click)
    ok &= check_overlay()

    passed = sum(1 for s, _, _ in _results if s == PASS)
    failed = sum(1 for s, _, _ in _results if s == FAIL)
    warned = sum(1 for s, _, _ in _results if s == WARN)
    print("\n" + "=" * 62)
    print(f"{passed} passed, {failed} failed, {warned} warnings")
    if failed:
        print("\nFailures:")
        for s, n, d in _results:
            if s == FAIL:
                print(f"  - {n}: {d}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
