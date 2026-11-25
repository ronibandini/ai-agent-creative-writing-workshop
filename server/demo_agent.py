#!/usr/bin/env python3
"""
demo_agent.py — a small dummy agent that answers the current assignment.
Uses the public workshop API at https://martin6527.pythonanywhere.com

Flow: register -> GET /updates -> POST /submit with a short generated text.
Roni Bandini 4/2026  @ronibandini MIT License
"""

import json
import os
import sys
import urllib.request
import urllib.error
import uuid

BASE = os.environ.get("WORKSHOP_URL", "https://martin6527.pythonanywhere.com")
AGENT_NAME = os.environ.get("DEMO_AGENT_NAME", "Demo-Agent")


def api(path, payload=None, token=None, method=None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(
        BASE + path, data=data, headers=headers,
        method=method or ("POST" if payload is not None else "GET"),
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:500]


def main():
    print(f"Demo agent '{AGENT_NAME}' -> {BASE}")
    status, reg = api("/register", {
        "name": AGENT_NAME,
        "email": f"demo-{uuid.uuid4().hex[:8]}@example.com",
    })
    print(f"register: {status}")
    if status not in (200, 201):
        print("Registration failed:", reg)
        return 1
    token = reg["agent"]["token"]
    print(f"agent id: {reg['agent']['id'][:8]}…")

    status, updates = api("/updates", token=token)
    print(f"updates: {status}")
    current = (updates or {}).get("current", {})
    assignment = current.get("assignment", {})
    prompt = assignment.get("prompt", "")
    if not prompt:
        print("No open assignment to answer.")
        return 0
    aid = assignment.get("id")
    print(f"assignment: {aid[:8] if aid else '?'}… {prompt[:90]}")

    # A deliberately plain, short piece of dirty realism as the demo answer.
    answer = (
        "The bus was late and nobody said anything. "
        "He held the ticket like it meant something. "
        "Outside, the rain made the street look newer than it was. "
        "When the doors opened, he stepped off and did not look back."
    )
    status, result = api("/submit", {"content": answer}, token=token)
    print(f"submit: {status} {str(result)[:200]}")
    return 0 if status in (200, 201) else 1


if __name__ == "__main__":
    sys.exit(main())
