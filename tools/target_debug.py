"""Show what every targeting layer finds for a description, and why it lost.

calibrate.py answers "does a click land where it was aimed". This answers the
other question, the one that comes up when it lands on the WRONG thing:

    "the WhatsApp icon" -> it clicked the icon to the LEFT of WhatsApp
    "this profile"      -> it clicked the one ABOVE

Both of those are a *ranking* fault, not an aiming fault. Every layer found
something; the wrong candidate came out first. `resolve()` returns the winner
and prints one line about it, which is exactly enough to hide the reason: the
candidates it rejected are never shown, so there is no way to see that the
right answer was second, or that the winner scored 0.82 off a stray "A".

So this prints the whole field, per layer, with the score each candidate got and
the signals behind it — and then runs the real `resolve()` so the winner can be
compared against what a human looking at the screen would have picked.

    python tools/target_debug.py "WhatsApp icon"
    python tools/target_debug.py "profile" --window WhatsApp
    python tools/target_debug.py "Save" --layers uia
    python tools/target_debug.py "green icon" --region 0,600,700,140
    python tools/target_debug.py "WhatsApp icon" --save shot.png

`--region` is `left,top,width,height` in physical pixels — the same convention
`screen_geometry.capture` uses. Passing it reproduces what the vision layer sees
when the caller already narrowed the search, which is the case that matters for
misclicks.

Nothing here clicks. It is read-only by construction, so it is safe to run while
the user is working.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _rule(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 62 - len(title)))


def _fmt_rect(rect) -> str:
    l, t, r, b = rect
    return f"[{l},{t},{r},{b}] {r - l}×{b - t}"


def _show(cands, limit: int = 12) -> None:
    if not cands:
        print("   (nothing)")
        return
    for i, c in enumerate(cands[:limit], 1):
        marker = "→" if i == 1 else " "
        print(f"  {marker} {i}. {c.confidence:.3f}  {c.label!r:<34} "
              f"{_fmt_rect(c.rect)}  centre ({c.x},{c.y})  "
              f"{c.control_type or '-'}  win={c.window[:26]!r}")
    if len(cands) > limit:
        print(f"     … and {len(cands) - limit} more")


def _describe(description: str) -> None:
    """Every signal `_similarity` produces, for the winner and its neighbours."""
    from core import ui_grounding as ug

    _rule(f"Similarity signals for {description!r}")
    print("   how the matcher scores a description against a label:")
    for label in (description, description.lower(), description.title()):
        d, l = ug._norm(description), ug._norm(label)
        print(f"     {label!r:<34} exact/substr/token/char = "
              f"{ug._similarity(description, label):.3f}")
    print(f"   normalised: {ug._norm(description)!r}  "
          f"tokens: {ug._tokens(description)!r}")
    print("   (a label scoring high on a SHORT fragment is the classic "
          "wrong-winner: 'a' inside 'plan' scored 0.82)")


def _layer_uia(description: str, window: str | None) -> None:
    from core import ui_grounding as ug

    _rule("Layer 0 — accessibility tree (uia)")
    t0 = time.monotonic()
    try:
        hits = ug.find_by_uia(description, min_confidence=0.0, max_results=40,
                              window=window)
    except Exception as e:
        print(f"   FAILED: {type(e).__name__}: {e}")
        return
    dt = (time.monotonic() - t0) * 1000
    print(f"   {len(hits)} candidate(s) in {dt:.0f} ms "
          f"(showing all, floor set to 0.0 so the rejects are visible)")
    _show(hits)

    _rule("Layer 0 — windows the tree can see")
    try:
        for w in ug._visible_top_windows(limit=20):
            try:
                br = w.BoundingRectangle
                rect = (int(br.left), int(br.top), int(br.right), int(br.bottom)) \
                    if br else (0, 0, 0, 0)
                own = " [JARVIS'S OWN — skipped by design]" if ug._is_own_window(w) else ""
                print(f"   {str(w.Name or '')[:44]:<46} "
                      f"{str(w.ControlTypeName or ''):<18} {_fmt_rect(rect)}{own}")
            except Exception as e:
                print(f"   <unreadable window: {type(e).__name__}>")
    except Exception as e:
        print(f"   FAILED: {type(e).__name__}: {e}")


def _layer_ocr(description: str, region) -> None:
    from core import ui_grounding as ug

    _rule("Layer 1 — OCR")
    t0 = time.monotonic()
    try:
        hits = ug.find_by_ocr(description, region=region, min_confidence=0.0,
                              max_results=40)
    except Exception as e:
        print(f"   FAILED: {type(e).__name__}: {e}")
        return
    dt = (time.monotonic() - t0) * 1000
    print(f"   {len(hits)} candidate(s) in {dt:.0f} ms")
    _show(hits)


def _layer_vision(description: str, region, save: str | None) -> None:
    from core import ui_grounding as ug
    from core import screen_geometry as sg

    _rule("Layer 2 — vision model")
    try:
        jpeg, origin, (fw, fh) = sg.capture_jpeg(region=region, with_cursor=True,
                                                 max_px=1600, quality=85)
    except Exception as e:
        print(f"   capture FAILED: {type(e).__name__}: {e}")
        return
    print(f"   frame {fw}×{fh} at origin {origin} "
          f"({len(jpeg) // 1024} KB jpeg)")
    if save:
        try:
            Path(save).write_bytes(jpeg)
            print(f"   wrote the exact frame the model sees to {save}")
        except Exception as e:
            print(f"   could not write {save}: {e}")

    t0 = time.monotonic()
    try:
        hits = ug.find_by_vision(description, region=region)
    except Exception as e:
        print(f"   FAILED: {type(e).__name__}: {e}")
        return
    dt = (time.monotonic() - t0) * 1000
    print(f"   {len(hits)} candidate(s) in {dt:.0f} ms "
          f"(this is the SLOW path — every hit here is a model call that the "
          f"layers above failed to avoid)")
    _show(hits)
    if hits:
        print("   NOTE: a single vision candidate at conf 0.60 means the "
              "coarse→fine passes disagreed, or the crop pass never ran "
              "(it is skipped when `region` is already given).")


def _winner(description: str, window: str | None, region, layers) -> None:
    from core import ui_grounding as ug

    _rule("resolve() — what the app would actually click")
    t0 = time.monotonic()
    try:
        hits = ug.resolve(description, window=window, region=region,
                          layers=layers, allow_vision=True)
    except Exception as e:
        print(f"   FAILED: {type(e).__name__}: {e}")
        return
    dt = (time.monotonic() - t0) * 1000
    print(f"   {len(hits)} candidate(s) in {dt:.0f} ms")
    _show(hits)
    if hits:
        w = hits[0]
        print(f"\n   WINNER: {w.label!r} at ({w.x},{w.y}) via {w.source} "
              f"conf={w.confidence:.2f}")
        if len(hits) > 1:
            r = hits[1]
            d = ((w.x - r.x) ** 2 + (w.y - r.y) ** 2) ** 0.5
            print(f"   runner-up: {r.label!r} at ({r.x},{r.y}) — {d:.0f} px away")
            if w.source == r.source and abs(w.confidence - r.confidence) < 0.08:
                print("   ⚠  the top two are within 0.08 of each other on the "
                      "SAME layer: this is a coin toss, and it is the shape of "
                      "a 'clicked the neighbour' bug.")
    else:
        print("\n   NOTHING FOUND — the caller would report "
              "'element not found', not a misclick.")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("description", help="what you would tell the assistant to click")
    ap.add_argument("--window", default=None,
                    help="window title fragment to narrow the search to")
    ap.add_argument("--region", default=None,
                    help="left,top,width,height in physical px (as capture takes it)")
    ap.add_argument("--layers", default="uia,ocr,vision",
                    help="comma-separated subset of uia,ocr,vision")
    ap.add_argument("--save", default=None,
                    help="write the vision frame to this path and keep it")
    ap.add_argument("--no-vision", action="store_true",
                    help="skip the model layer entirely (no API call, no cost)")
    args = ap.parse_args()

    region = None
    if args.region:
        try:
            region = tuple(int(v) for v in args.region.split(","))
            if len(region) != 4:
                raise ValueError("need exactly four numbers")
        except Exception as e:
            print(f"--region must be left,top,width,height — {e}")
            return 2

    layers = tuple(s.strip() for s in args.layers.split(",") if s.strip())
    if args.no_vision:
        layers = tuple(l for l in layers if l != "vision")

    from core import screen_geometry as sg
    mode = sg.ensure_dpi_awareness()

    print(f"target_debug: {args.description!r}")
    print(f"  DPI awareness : {mode}")
    print(f"  window filter : {args.window or '(none)'}")
    print(f"  region        : {region or '(full screen)'}")
    print(f"  layers        : {', '.join(layers)}")

    _describe(args.description)
    if "uia" in layers:
        _layer_uia(args.description, args.window)
    if "ocr" in layers:
        _layer_ocr(args.description, region)
    if "vision" in layers:
        _layer_vision(args.description, region, args.save)
    _winner(args.description, args.window, region, layers)

    print("\nRun calibrate.py as well if the winner LOOKS right but the click "
          "still does nothing — that is an aiming fault, not a ranking one.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
