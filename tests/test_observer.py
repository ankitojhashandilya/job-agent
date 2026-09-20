"""Manual observer test — navigate to any ATS page and inspect the snapshot.

Usage:
    python -m tests.test_observer

This opens a persistent Chrome session (reusing any existing LinkedIn
login). Navigate to any job application page manually, then press
Enter in the terminal. The script calls observe_page() three times and
prints the full PageSnapshot as formatted JSON, plus a summary and
stability report.

Requirements:
    - Run from the project root.
    - The venv must have playwright installed.
"""

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import BrowserContext, sync_playwright

# Ensure the project root is on sys.path so that local imports resolve.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from browser_session import launch_linkedin_context
from agent.observe import observe_page


# ── Page selection ─────────────────────────────────────────────────

def _select_active_page(context: BrowserContext):
    """Select the page the user is actually viewing.

    Preference order:

    1. Ignore pages whose URL is ``about:blank``, ``chrome://*``,
       ``chrome-extension://*``, or empty.
    2. Prefer pages where ``document.visibilityState == 'visible'``
       AND ``document.hasFocus() == true``.
    3. If multiple focused pages, pick the most recently created one
       (last in the context.pages list — Playwright's order).
    4. If no focused page exists, fall back to the last valid page.
    5. If no valid page exists at all, create a new one.

    Prints the selected page's URL and title before returning.
    """
    valid_pages = []
    for p in context.pages:
        try:
            url = p.url
        except Exception:
            continue
        if not url or url.startswith("about:") or url.startswith("chrome"):
            continue
        valid_pages.append(p)

    if not valid_pages:
        page = context.new_page()
        print(f"  No valid page found — created new tab: {page.url}")
        return page

    # Prefer focused / visible pages
    focused_pages = []
    for p in valid_pages:
        try:
            has_focus = p.evaluate(
                "document.visibilityState === 'visible' && document.hasFocus()"
            )
            if has_focus:
                focused_pages.append(p)
        except Exception:
            continue

    if focused_pages:
        page = focused_pages[-1]
    else:
        page = valid_pages[-1]

    try:
        url = page.url
    except Exception:
        url = "(unknown)"
    try:
        title = page.title()
    except Exception:
        title = "(unknown)"

    print(f"\n  Selected Page: {url}")
    print(f"  Title:         {title}")

    return page


# ── Diff formatting ───────────────────────────────────────────────

def _format_id_diff(first_ids: list[str], second_ids: list[str]) -> str:
    if first_ids == second_ids:
        return ""

    changed: list[str] = []
    for f_id, s_id in zip(first_ids, second_ids, strict=False):
        if f_id != s_id:
            changed.append(f"  {f_id}  \u2192  {s_id}")

    if len(first_ids) > len(second_ids):
        for f_id in first_ids[len(second_ids):]:
            changed.append(f"  {f_id}  \u2192  (removed)")
    elif len(second_ids) > len(first_ids):
        for s_id in second_ids[len(first_ids):]:
            changed.append(f"  (new)  \u2192  {s_id}")

    return "\n".join(changed)


def _ids_ordered_match(first: list[str], second: list[str]) -> bool:
    """True if IDs are identical element-by-element."""
    return first == second


def _ids_unordered_match(first: list[str], second: list[str]) -> bool:
    """True if the same set of IDs appears (order may differ)."""
    return set(first) == set(second)


# ── Main ──────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 72)
    print("  Observer Test \u2014 Manual ATS Inspection")
    print("=" * 72)

    with sync_playwright() as playwright:
        context = launch_linkedin_context(playwright)

        print("\n  Browser opened.")
        print("  Navigate to any job application page in the Chrome window.")
        print("  Press Enter here when ready to observe the page.\n")
        input("  [Press Enter to observe]")

        # ── Select the active page ──────────────────────────
        page = _select_active_page(context)

        # Re-read for display after selection
        try:
            page_type_pre = observe_page(page).page_type
        except Exception:
            page_type_pre = "(unknown)"
        print(f"  Page Type:      {page_type_pre}")
        print()

        # ── Observation 1 ──────────────────────────────────
        print("  Observing page (pass 1) ...")
        t0 = time.perf_counter()
        snapshot1 = observe_page(page)
        t1 = time.perf_counter()
        obs1_ms = (t1 - t0) * 1000

        print("\n" + "-" * 72)
        print("  PAGESNAPSHOT (pass 1)")
        print("-" * 72)

        snapshot_dict = _to_dict(snapshot1)
        print(json.dumps(snapshot_dict, indent=2, default=str))

        print("\n" + "-" * 72)
        print("  SUMMARY (pass 1)")
        print("-" * 72)
        print(f"  page_type:          {snapshot1.page_type}")
        print(f"  url:                {snapshot1.url}")
        print(f"  page_title:         {snapshot1.page_title}")
        print(f"  domain:             {snapshot1.domain}")
        print(f"  fields:             {len(snapshot1.fields)}")
        print(f"  buttons:            {len(snapshot1.buttons)}")
        print(f"  file_inputs:        {len(snapshot1.file_inputs)}")
        print(f"  error_messages:     {len(snapshot1.error_messages)}")
        print(f"  status_message:     {snapshot1.status_message or '(none)'}")
        print(f"  observation_time:   {obs1_ms:.1f} ms")
        print(f"  observation_id:     {snapshot1.observation_id}")

        # ── Observation 2 ──────────────────────────────────
        print("\n" + "-" * 72)
        print("  STABILITY CHECK \u2014 observing page (pass 2)")
        print("-" * 72)

        t2 = time.perf_counter()
        snapshot2 = observe_page(page)
        t3 = time.perf_counter()
        obs2_ms = (t3 - t2) * 1000

        # ── Observation 3 ──────────────────────────────────
        print("\n" + "-" * 72)
        print("  STABILITY CHECK \u2014 observing page (pass 3)")
        print("-" * 72)

        t4 = time.perf_counter()
        snapshot3 = observe_page(page)
        t5 = time.perf_counter()
        obs3_ms = (t5 - t4) * 1000

        # ── Compile stability results ──────────────────────
        field_ids_1 = [f.id for f in snapshot1.fields]
        field_ids_2 = [f.id for f in snapshot2.fields]
        field_ids_3 = [f.id for f in snapshot3.fields]

        button_ids_1 = [b.id for b in snapshot1.buttons]
        button_ids_2 = [b.id for b in snapshot2.buttons]
        button_ids_3 = [b.id for b in snapshot3.buttons]

        file_ids_1 = [fi.id for fi in snapshot1.file_inputs]
        file_ids_2 = [fi.id for fi in snapshot2.file_inputs]
        file_ids_3 = [fi.id for fi in snapshot3.file_inputs]

        counts_match_12 = (
            len(snapshot1.fields) == len(snapshot2.fields)
            and len(snapshot1.buttons) == len(snapshot2.buttons)
            and len(snapshot1.file_inputs) == len(snapshot2.file_inputs)
        )
        counts_match_13 = (
            len(snapshot1.fields) == len(snapshot3.fields)
            and len(snapshot1.buttons) == len(snapshot3.buttons)
            and len(snapshot1.file_inputs) == len(snapshot3.file_inputs)
        )

        print(f"\n  Timings:  pass 1 = {obs1_ms:.1f} ms"
              f"  |  pass 2 = {obs2_ms:.1f} ms"
              f"  |  pass 3 = {obs3_ms:.1f} ms")
        print()

        # ── Stability report ───────────────────────────────
        print("  STABILITY REPORT")
        print("  " + "-" * 60)

        field_ordered_12 = _ids_ordered_match(field_ids_1, field_ids_2)
        field_ordered_13 = _ids_ordered_match(field_ids_1, field_ids_3)
        field_unordered_12 = _ids_unordered_match(field_ids_1, field_ids_2)
        field_unordered_13 = _ids_unordered_match(field_ids_1, field_ids_3)

        button_ordered_12 = _ids_ordered_match(button_ids_1, button_ids_2)
        button_ordered_13 = _ids_ordered_match(button_ids_1, button_ids_3)
        button_unordered_12 = _ids_unordered_match(button_ids_1, button_ids_2)
        button_unordered_13 = _ids_unordered_match(button_ids_1, button_ids_3)

        file_ordered_12 = _ids_ordered_match(file_ids_1, file_ids_2)
        file_ordered_13 = _ids_ordered_match(file_ids_1, file_ids_3)
        file_unordered_12 = _ids_unordered_match(file_ids_1, file_ids_2)
        file_unordered_13 = _ids_unordered_match(file_ids_1, file_ids_3)

        def _status(ordered_12, ordered_13, unordered_12, unordered_13) -> str:
            if ordered_12 and ordered_13:
                return "STABLE (order+IDs identical across 3 passes)"
            if unordered_12 and unordered_13:
                return "STABLE (same IDs, order changed between passes)"
            if ordered_12 or ordered_13:
                return "PARTIAL STABLE (some drift between passes)"
            return "UNSTABLE (IDs changed between passes)"

        print(f"  Element counts:      "
              f"{'STABLE' if counts_match_12 and counts_match_13 else 'CHANGED'}")
        print(f"    Pass 1→2:          "
              f"{'match' if counts_match_12 else 'mismatch'}"
              f"  |  "
              f"Pass 1→3: {'match' if counts_match_13 else 'mismatch'}")
        print()

        print(f"  Fields:")
        print(f"    Pass 1→2:          "
              f"{'ordered match' if field_ordered_12 else 'changed'}")
        print(f"    Pass 1→3:          "
              f"{'ordered match' if field_ordered_13 else 'changed'}")
        print(f"    Overall:           {_status(field_ordered_12, field_ordered_13, field_unordered_12, field_unordered_13)}")
        if not field_ordered_12:
            print(f"    Diff (1→2):")
            diff = _format_id_diff(field_ids_1, field_ids_2)
            if diff:
                print(diff)

        print()
        print(f"  Buttons:")
        print(f"    Pass 1→2:          "
              f"{'ordered match' if button_ordered_12 else 'changed'}")
        print(f"    Pass 1→3:          "
              f"{'ordered match' if button_ordered_13 else 'changed'}")
        print(f"    Overall:           {_status(button_ordered_12, button_ordered_13, button_unordered_12, button_unordered_13)}")
        if not button_ordered_12:
            print(f"    Diff (1→2):")
            diff = _format_id_diff(button_ids_1, button_ids_2)
            if diff:
                print(diff)

        print()
        print(f"  File inputs:")
        print(f"    Pass 1→2:          "
              f"{'ordered match' if file_ordered_12 else 'changed'}")
        print(f"    Pass 1→3:          "
              f"{'ordered match' if file_ordered_13 else 'changed'}")
        print(f"    Overall:           {_status(file_ordered_12, file_ordered_13, file_unordered_12, file_unordered_13)}")
        if not file_ordered_12:
            print(f"    Diff (1→2):")
            diff = _format_id_diff(file_ids_1, file_ids_2)
            if diff:
                print(diff)

        stable = (
            counts_match_12 and counts_match_13
            and field_ordered_12 and field_ordered_13
            and button_ordered_12 and button_ordered_13
            and file_ordered_12 and file_ordered_13
        )
        if stable:
            print("\n  \u2713 All element IDs and counts are stable across 3 passes.")
        else:
            print("\n  \u26a0 Some element properties changed between observations.")
            print("    (This may be expected if the page content changed.)")

        # ── Cleanup ────────────────────────────────────────
        print("\n" + "-" * 72)
        input("  Press Enter to close the browser and exit.")
        context.close()

    print("  Done. Exiting cleanly.")


def _to_dict(obj):
    """Recursively convert a dataclass instance to a plain dict.

    Handles nested dataclasses, lists, tuples, and basic types.
    """

    if hasattr(obj, "__dataclass_fields__"):
        result = {}
        for field_name in obj.__dataclass_fields__:
            value = getattr(obj, field_name)
            result[field_name] = _to_dict(value)
        return result
    if isinstance(obj, list):
        return [_to_dict(item) for item in obj]
    if isinstance(obj, tuple):
        return tuple(_to_dict(item) for item in obj)
    if isinstance(obj, dict):
        return {key: _to_dict(value) for key, value in obj.items()}
    return obj


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  Interrupted by user.")
        sys.exit(0)
    except Exception as error:
        print(f"\n  Error: {error}")
        sys.exit(1)
