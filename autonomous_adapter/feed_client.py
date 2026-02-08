"""
Feed client for the autonomous demo: get posts and post replies/offers.

Works with the demo feed server (autonomous_adapter.demo_feed_server) or any
HTTP endpoint that implements GET /feed and POST /feed. For real Moltbook
feed API (when available), use the same interface with MOLTBOOK_FEED_URL.

Env:
  AGENTPAY_DEMO_FEED_URL — base URL (e.g. http://localhost:8765 or your Codespace URL).
  Optional: MOLTBOOK_API_KEY — for future Moltbook identity on posts.
"""

import os
import urllib.request
import urllib.error
import json
from typing import Any, Dict, List, Optional


def _base_url() -> str:
    url = (os.getenv("AGENTPAY_DEMO_FEED_URL") or "").strip().rstrip("/")
    if not url:
        url = "http://127.0.0.1:8765"
    return url


def get_recent_posts() -> List[Dict[str, Any]]:
    """
    Fetch recent posts from the demo feed (or Moltbook when configured).
    Returns list of dicts with at least: id, text, thread_id, created_at.
    """
    url = f"{_base_url()}/feed"
    try:
        req = urllib.request.Request(url, method="GET")
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError):
        return []
    posts = data.get("posts") if isinstance(data, dict) else []
    if not isinstance(posts, list):
        return []
    # Normalize for adapter: each item needs "text" or "body"
    out = []
    for p in posts:
        if not isinstance(p, dict):
            continue
        text = p.get("text") or p.get("body") or ""
        out.append({
            "id": p.get("id"),
            "text": text,
            "body": text,
            "thread_id": p.get("thread_id") or p.get("id"),
            "created_at": p.get("created_at"),
            **p,
        })
    return out


def post_reply(thread_id: str, text: str) -> Optional[Dict[str, Any]]:
    """Post a reply (e.g. accept) to a thread. Returns created post or None."""
    return _post_feed({"text": text, "thread_id": thread_id})


def post_offer(text: str, full_text: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Post a new offer (new thread). If full_text (e.g. article to summarise), demo feed will print it."""
    payload = {"text": text}
    if full_text and full_text.strip():
        payload["full_text"] = full_text.strip()
    return _post_feed(payload)


def _post_feed(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    url = f"{_base_url()}/feed"
    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError):
        return None
