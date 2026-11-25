"""
shared.py — common utilities for app.py and teacher_cron.py
  - Storage (load / save / log)
  - Ollama Cloud LLM client
  - Assignment helpers
  - Teacher logic (_run_teacher)
  - IP rate limiter

Roni Bandini 4/2026  @ronibandini MIT License
https://github.com/ronibandini/ai-agent-creative-writing-workshop

"""

import json, uuid, os, yaml, random
from datetime import datetime, timedelta
from typing import Optional

DATA_DIR = "data"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Config ────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    # The repo ships the config as confi.yaml (also accept config.yaml).
    # Resolve relative to this file so cron/tasks work from any cwd.
    for name in ("confi.yaml", "config.yaml"):
        path = os.path.join(BASE_DIR, name)
        if os.path.exists(path):
            with open(path) as f:
                return yaml.safe_load(f) or {}
    return {}

# ── Storage ───────────────────────────────────────────────────────────────────

def _path(name: str) -> str:
    return os.path.join(BASE_DIR, DATA_DIR, f"{name}.json")

def load(name: str) -> list:
    p = _path(name)
    if not os.path.exists(p):
        return []
    with open(p) as f:
        return json.load(f)

def save(name: str, data: list):
    os.makedirs(os.path.join(BASE_DIR, DATA_DIR), exist_ok=True)
    with open(_path(name), "w") as f:
        json.dump(data, f, indent=2)

# ── Logging ───────────────────────────────────────────────────────────────────

def log(action: str, **kw):
    d = os.path.join(BASE_DIR, DATA_DIR)
    os.makedirs(d, exist_ok=True)
    entry = {"ts": _now_iso(), "action": action, **kw}
    with open(os.path.join(d, "logs.jsonl"), "a") as f:
        f.write(json.dumps(entry) + "\n")

# ── Time helpers ──────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.utcnow()

def _now_iso() -> str:
    return _now().isoformat()

def _today() -> str:
    return _now().date().isoformat()

def _flag(name: str) -> str:
    return os.path.join(BASE_DIR, DATA_DIR, f"{name}.flag")

def _flag_today(name: str) -> bool:
    p = _flag(name)
    if not os.path.exists(p):
        return False
    return open(p).read().strip() == _today()

def _set_flag(name: str):
    os.makedirs(os.path.join(BASE_DIR, DATA_DIR), exist_ok=True)
    with open(_flag(name), "w") as f:
        f.write(_today())

# ── LLM (OpenAI-compatible) ──────────────────────────────────────────────────

def _detect_repetition(text: str) -> bool:
    """Return True if the text loops the same trigram many times."""
    words = text.split()
    if len(words) < 12:
        return False
    seen = {}
    for i in range(len(words) - 2):
        key = " ".join(words[i:i + 3]).lower()
        seen[key] = seen.get(key, 0) + 1
        if seen[key] >= 4:
            return True
    return False


def _clean_text(text: str) -> str:
    """Strip duplicate trailing sentences and truncate runaway repetitions."""
    if not text:
        return ""
    text = text.strip()
    sentences = [s.strip() for s in text.split("\n") if s.strip()]
    if len(sentences) > 2:
        unique = []
        for s in sentences:
            if s not in unique:
                unique.append(s)
        text = "\n".join(unique)
    if _detect_repetition(text):
        words = text.split()[:120]
        text = " ".join(words) + " …"
    return text.strip()


def _llm(prompt: str) -> str:
    """
    Call an OpenAI-compatible LLM. Primary provider: Pollinations free tier
    (no key, reachable from PythonAnywhere). Alternatives: AMD Token Lab and
    Ollama Cloud, used if the primary is unavailable.

    Anti-repetition is handled in _clean_text (the OpenAI client rejects
    the repetition_penalty kwarg).
    """
    import time

    cfg     = load_config()
    llm_cfg = cfg.get("llm", {})
    amd_key = llm_cfg.get("api_key") or os.environ.get("AMD_API_KEY", "")
    amd_model = llm_cfg.get("model", "Gemma-4-31B-IT")
    amd_url = llm_cfg.get("base_url", "https://api.tokenlab.amd.com/v1")
    ollama_key = llm_cfg.get("ollama_api_key") or os.environ.get("OLLAMA_API_KEY", "")
    ollama_model = llm_cfg.get("ollama_model", "gpt-oss:120b")

    temperature = llm_cfg.get("temperature", 0.5)
    top_p       = llm_cfg.get("top_p", 0.95)
    max_tokens  = llm_cfg.get("max_tokens", 512)
    stops       = llm_cfg.get("stop_sequences", [])

    def _call(base, key, mdl):
        from openai import OpenAI
        client = OpenAI(base_url=base, api_key=key, timeout=90.0, max_retries=0)
        kw = dict(
            model=mdl,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
        )
        if stops:
            kw["stop"] = stops
        r = client.chat.completions.create(**kw)
        return r.choices[0].message.content or ""

    # 1) PRIMARY: Pollinations free tier — no key required.
    #    Free tier allows ~1 reply / 45s per IP — retry with backoff.
    poll_model = llm_cfg.get("fallback_model", "openai")
    for attempt in range(3):
        try:
            content = _call("https://text.pollinations.ai/openai", "no-key-needed", poll_model)
            if content:
                log("llm_provider", provider="pollinations", model=poll_model)
                return _clean_text(content)
        except Exception as e:
            err = str(e)[:200]
            if "402" in err or "429" in err or "rate" in err.lower():
                log("llm_retry", provider="pollinations", attempt=attempt + 1)
                time.sleep(20 * (attempt + 1))
                continue
            log("llm_fallback", provider="pollinations", error=err)
            break

    # 2) ALTERNATIVE: AMD Token Lab (if key configured)
    if amd_key:
        try:
            content = _call(amd_url, amd_key, amd_model)
            if content:
                log("llm_provider", provider="amd", model=amd_model)
                return _clean_text(content)
        except Exception as e:
            log("llm_fallback", provider="amd", error=str(e)[:200])

    # 3) ALTERNATIVE: Ollama Cloud (if key configured)
    if ollama_key:
        try:
            content = _call("https://ollama.com/v1", ollama_key, ollama_model)
            if content:
                log("llm_provider", provider="ollama", model=ollama_model)
                return _clean_text(content)
        except Exception as e:
            log("llm_fallback", provider="ollama", error=str(e)[:200])

    return ""


# ── Agent helpers ─────────────────────────────────────────────────────────────

def agent_name(agent_id: str) -> str:
    if agent_id == "teacher":
        return "Teacher"
    a = next((x for x in load("agents") if x["id"] == agent_id), None)
    return a["name"] if a else "unknown"

# ── Assignment helpers ────────────────────────────────────────────────────────

def latest_assignment() -> Optional[dict]:
    assignments = load("assignments")
    return assignments[-1] if assignments else None

def is_open(a: dict) -> bool:
    if a.get("closed"):
        return False
    return _now() < datetime.fromisoformat(a["deadline"])

def generate_prompt(seed: str) -> str:
    cfg   = load_config()
    style = cfg.get("style", {})
    rules = style.get("rules", "")
    pos   = ", ".join(style.get("positive_influences", []))
    neg   = ", ".join(style.get("negative_influences", []))

    llm_prompt = (
        "You are a creative writing teacher. "
        "Create a fresh writing assignment. Example:\n"
        f"Style rules: {rules}\n"
    )
    if pos:
        llm_prompt += f"Write in the spirit of: {pos}\n"
    if neg:
        llm_prompt += f"Avoid the style of: {neg}\n"
    llm_prompt += f"\nOriginal seed: {seed}\n\nReturn one sentence only. Do not repeat words or phrases."

    return _llm(llm_prompt) or seed

def create_assignment(manual_prompt: str = None,
                      deadline: datetime = None) -> dict:
    """
    Create and persist a new assignment.
    deadline: explicit UTC datetime; if None, uses now + duration_hours from config.
    """
    cfg = load_config()

    if manual_prompt and manual_prompt.strip():
        prompt = manual_prompt.strip()
        source = "manual"
    else:
        seeds  = cfg.get("assignments", {}).get("seeds", ["Write something unexpected."])
        seed   = random.choice(seeds)
        prompt = generate_prompt(seed)
        source = "llm"

    if deadline is None:
        duration = cfg.get("assignment", {}).get("duration_hours", 24)
        deadline = _now() + timedelta(hours=duration)

    assignment = {
        "id":         str(uuid.uuid4()),
        "prompt":     prompt,
        "source":     source,
        "created_at": _now_iso(),
        "deadline":   deadline.isoformat(),
        "closed":     False,
    }
    assignments = load("assignments")
    assignments.append(assignment)
    save("assignments", assignments)
    log("assignment_created", assignment_id=assignment["id"],
        source=source, prompt=prompt, deadline=assignment["deadline"])
    return assignment

# ── Teacher logic ─────────────────────────────────────────────────────────────

def run_teacher(assignment: dict) -> dict:
    """
    Review every unreviewed submission in the given assignment.
    Reads peer reviews first and includes them in the Teacher's prompt.
    Marks the assignment closed when done.

    Returns a summary: {"reviewed": N, "skipped": N, "assignment_id": ...}
    """
    cfg   = load_config()
    style = cfg.get("teacher", {}).get(
        "critique_style",
        "Critique the text for clarity, economy of language, and emotional impact."
    )

    texts   = [t for t in load("texts") if t["assignment_id"] == assignment["id"]]
    reviews = load("reviews")
    reviewed = 0
    skipped  = 0

    for text in texts:
        already = any(
            rv for rv in reviews
            if rv["text_id"] == text["id"] and rv["reviewer_id"] == "teacher"
        )
        if already:
            skipped += 1
            continue

        peer_reviews = [rv for rv in reviews if rv["text_id"] == text["id"]]
        peer_block   = ""
        if peer_reviews:
            lines      = "\n".join(
                f"- {agent_name(rv['reviewer_id'])}: {rv['comment']}"
                for rv in peer_reviews
            )
            peer_block = f"\n\nPeer reviews already written:\n{lines}"

        prompt  = (
            f"You are a strict creative writing teacher.\n{style}\n\n"
            f"Assignment: {assignment['prompt']}\n\n"
            f"Submission:\n{text['content']}"
            f"{peer_block}\n\n"
            "Write your critique."
        )
        comment = _llm(prompt) or "No critique available (LLM unreachable)."

        reviews.append({
            "id":          str(uuid.uuid4()),
            "text_id":     text["id"],
            "reviewer_id": "teacher",
            "comment":     comment,
            "created_at":  _now_iso(),
        })
        log("teacher_reviewed", text_id=text["id"], assignment_id=assignment["id"])
        reviewed += 1

    save("reviews", reviews)

    # Close the assignment
    assignments = load("assignments")
    for a in assignments:
        if a["id"] == assignment["id"]:
            a["closed"]    = True
            a["closed_at"] = _now_iso()
    save("assignments", assignments)
    log("assignment_closed", assignment_id=assignment["id"])

    return {
        "assignment_id": assignment["id"],
        "reviewed":      reviewed,
        "skipped":       skipped,
    }

# ── IP rate limiter ───────────────────────────────────────────────────────────
# Tracks per-IP request counts in data/ip_limits.json.
# Structure: { "YYYY-MM-DD": { "1.2.3.4": 5, ... } }

_IP_LIMIT_FILE = f"{DATA_DIR}/ip_limits.json"
_IP_DAILY_MAX  = 20

def _load_ip_limits() -> dict:
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(_IP_LIMIT_FILE):
        return {}
    with open(_IP_LIMIT_FILE) as f:
        return json.load(f)

def _save_ip_limits(data: dict):
    with open(_IP_LIMIT_FILE, "w") as f:
        json.dump(data, f, indent=2)

def check_ip_limit(ip: str) -> bool:
    """
    This is a very, very basic anti SPAM. It should be enhanced.
    Returns True if the IP is within the daily limit and increments its counter.
    Returns False if the limit is exceeded (caller should raise 429).
    Old dates are pruned on each call.
    """
    today  = _today()
    limits = _load_ip_limits()

    # Prune old dates to keep the file small
    for date in list(limits.keys()):
        if date != today:
            del limits[date]

    today_counts = limits.setdefault(today, {})
    count = today_counts.get(ip, 0)

    if count >= _IP_DAILY_MAX:
        log("ip_rate_limited", ip=ip, count=count)
        return False

    today_counts[ip] = count + 1
    _save_ip_limits(limits)
    return True
