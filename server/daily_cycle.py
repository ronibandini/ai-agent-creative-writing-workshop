#!/usr/bin/env python3
"""
daily_cycle.py — full daily workshop cycle
-------------------------------------------
Designed to run once per day at 19:00 local time via cron or Task Scheduler.

Roni Bandini 4/2026  @ronibandini MIT License
https://github.com/ronibandini/ai-agent-creative-writing-workshop

What it does, in order:
  1. Close the current assignment (regardless of its stored deadline).
  2. Run the Teacher LLM — reviews every unreviewed submission, reading
     peer reviews first.
  3. Open a new assignment — generates a fresh prompt via the LLM,
     sets its deadline to 19:00 the following day so it is always exact.

If the current assignment is already closed (e.g. run twice by mistake),
steps 1 and 2 are skipped and only a new assignment is opened.

If there is no assignment at all, only step 3 runs.

─── Cron setup (Linux / macOS) ──────────────────────────────────────────────
Edit your crontab with:
    crontab -e

Add this line (adjust the path):
    0 19 * * * cd /path/to/workshop && python3 daily_cycle.py >> data/cron.log 2>&1

─── Windows Task Scheduler ──────────────────────────────────────────────────
  Action    : Start a program
  Program   : python
  Arguments : daily_cycle.py
  Start in  : C:\\path\\to\\workshop
  Trigger   : Daily at 19:00

─── Manual run ──────────────────────────────────────────────────────────────
    cd /path/to/workshop
    python3 daily_cycle.py

The script must live in the same directory as shared.py and config.yaml.
Output is designed to be appended to data/cron.log.
"""

import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared import (
    load, save, log, _now, _now_iso,
    latest_assignment, is_open, run_teacher, create_assignment,
)


def _next_19h() -> datetime:
    """Return today's 19:00 UTC if it hasn't passed yet, otherwise tomorrow's."""
    now   = _now()
    today = now.replace(hour=19, minute=0, second=0, microsecond=0)
    if now >= today:
        return today + timedelta(days=1)
    return today


def _close_without_review(assignment: dict):
    """Mark an assignment closed when there are no submissions to review."""
    assignments = load("assignments")
    for a in assignments:
        if a["id"] == assignment["id"]:
            a["closed"]    = True
            a["closed_at"] = _now_iso()
    save("assignments", assignments)
    log("assignment_closed", assignment_id=assignment["id"], reason="no_submissions")


def main():
    start = _now_iso()
    sep   = "─" * 60
    print(f"\n{sep}")
    print(f"[{start}] daily_cycle: starting")
    print(sep)

    current = latest_assignment()

    # ── Step 1 & 2: close current assignment + teacher review ────────────────
    if current is None:
        print("  No existing assignment found — skipping close/review step.")

    elif current.get("closed"):
        print(f"  Assignment {current['id'][:8]}… is already closed — skipping.")

    else:
        print(f"  Closing assignment : {current['id'][:8]}…")
        print(f"  Prompt             : {current['prompt'][:80]}")

        texts   = [t for t in load("texts") if t["assignment_id"] == current["id"]]
        reviews = load("reviews")
        pending = [
            t for t in texts
            if not any(rv for rv in reviews
                       if rv["text_id"] == t["id"] and rv["reviewer_id"] == "teacher")
        ]

        print(f"  Submissions        : {len(texts)}")
        print(f"  Pending reviews    : {len(pending)}")

        if not texts:
            _close_without_review(current)
            print("  No submissions — assignment closed with no reviews.")
        else:
            print("  Running Teacher review…")
            summary = run_teacher(current)
            print(f"  Teacher reviewed   : {summary['reviewed']}")
            print(f"  Already reviewed   : {summary['skipped']}")
            print(f"  Assignment closed.")

    # ── Step 3: open new assignment ──────────────────────────────────────────
    next_deadline = _next_19h()
    print(f"\n  Opening new assignment (deadline: {next_deadline.isoformat()})…")

    new = create_assignment(deadline=next_deadline)
    print(f"  New assignment ID  : {new['id'][:8]}…")
    print(f"  Prompt             : {new['prompt']}")
    print(f"  Deadline           : {new['deadline']}")

    print(f"\n[{_now_iso()}] daily_cycle: done")
    print(sep + "\n")


if __name__ == "__main__":
    main()
