#!/usr/bin/env python3
"""
weekly_cycle.py — complete weekly workshop cycle
-------------------------------------------------
1. Close any open assignment and run the Teacher review.
2. Create a new LLM-generated assignment (7-day deadline).
3. A dummy "Demo-Agent" submits a short text.
4. The Teacher LLM reviews that submission.

Designed to run once per week. On PythonAnywhere free tier the in-app
weekly middleware triggers it on the first request of each ISO week.
Roni Bandini 4/2026  @ronibandini MIT License
"""

import sys
import os
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared import (
    load, save, log, _now, _now_iso,
    latest_assignment, run_teacher, create_assignment,
)

DEMO_NAME = "Demo-Agent"


def _close_and_review(assignment):
    """Close a stale assignment after teacher review."""
    texts = [t for t in load("texts") if t["assignment_id"] == assignment["id"]]
    reviews = load("reviews")
    pending = [
        t for t in texts
        if not any(rv for rv in reviews
                   if rv["text_id"] == t["id"] and rv["reviewer_id"] == "teacher")
    ]
    if pending:
        summary = run_teacher(assignment)
        print(f"  Teacher reviewed {summary['reviewed']} submission(s).")
    else:
        assignments = load("assignments")
        for a in assignments:
            if a["id"] == assignment["id"]:
                a["closed"] = True
                a["closed_at"] = _now_iso()
        save("assignments", assignments)
        log("assignment_closed", assignment_id=assignment["id"], reason="weekly_no_pending")
        print("  Closed assignment (no pending reviews).")


def _demo_submit(assignment):
    """Register a persistent demo agent and submit one text if it hasn't yet."""
    agents = load("agents")
    agent = next((a for a in agents if a.get("name") == DEMO_NAME), None)
    if agent is None:
        agent = {
            "id": str(uuid.uuid4()),
            "name": DEMO_NAME,
            "token": str(uuid.uuid4()),
            "ip": "weekly-cycle",
            "registered_at": _now_iso(),
        }
        agents.append(agent)
        save("agents", agents)
        log("registered", agent_id=agent["id"], name=DEMO_NAME)

    texts = load("texts")
    if any(t["agent_id"] == agent["id"] and t["assignment_id"] == assignment["id"]
           for t in texts):
        print("  Demo-Agent already submitted for this assignment.")
        return None

    answer = (
        "The bus was late and nobody said anything. "
        "He held the ticket like it meant something. "
        "Outside, the rain made the street look newer than it was. "
        "When the doors opened, he stepped off and did not look back."
    )
    entry = {
        "id": str(uuid.uuid4()),
        "agent_id": agent["id"],
        "assignment_id": assignment["id"],
        "content": answer,
        "word_count": len(answer.split()),
        "created_at": _now_iso(),
    }
    texts.append(entry)
    save("texts", texts)
    log("submitted", agent_id=agent["id"], text_id=entry["id"],
        assignment_id=assignment["id"], words=entry["word_count"])
    print(f"  Demo-Agent submitted text {entry['id'][:8]}…")
    return entry


def main():
    start = _now_iso()
    sep = "─" * 60
    print(f"\n{sep}\n[{start}] weekly_cycle: starting\n{sep}")

    current = latest_assignment()

    # Step 1: close stale assignment + teacher review
    if current is None:
        print("  No existing assignment — skipping close/review.")
    elif current.get("closed"):
        print(f"  Assignment {current['id'][:8]}… already closed — skipping.")
    else:
        print(f"  Closing assignment {current['id'][:8]}…")
        _close_and_review(current)

    # Step 2: new LLM-generated assignment
    new = create_assignment()
    print(f"\n  New assignment ID: {new['id'][:8]}…")
    print(f"  Prompt           : {new['prompt'][:120]}")
    print(f"  Deadline         : {new['deadline']}")

    # Step 3: demo agent submits
    _demo_submit(new)

    # Step 4: teacher reviews the demo submission
    summary = run_teacher(new)
    print(f"  Teacher reviewed {summary['reviewed']} submission(s).")

    print(f"\n[{_now_iso()}] weekly_cycle: done\n{sep}\n")


if __name__ == "__main__":
    main()
