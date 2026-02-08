"""
Minimal demo feed server for the autonomous AgentPay demo.

GET /feed  -> list of posts (each: id, text, thread_id, created_at)
POST /feed -> body { "text", "thread_id"? } -> appends post, returns { "id", ... }

No Moltbook API key required. Use so two Moltbots (or two terminals) can share
a feed: one posts an offer, the other sees it and replies; then AgentPay runs.

Run: python -m autonomous_adapter.demo_feed_server
Env: AGENTPAY_DEMO_FEED_PORT (default 8765), AGENTPAY_DEMO_FEED_HOST (default 0.0.0.0)
"""

import json
import os
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


FEED: list = []  # in-memory; each item: { id, text, thread_id, created_at }


def _cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }


class FeedHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Keep logs short
        pass

    def _send_json(self, status: int, data: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for k, v in _cors_headers().items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        for k, v in _cors_headers().items():
            self.send_header(k, v)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path.rstrip("/") == "/feed":
            self._send_json(200, {"posts": FEED})
            return
        if self.path.rstrip("/") in ("", "/"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"AgentPay demo feed. GET /feed or POST /feed\n")
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path.rstrip("/") != "/feed":
            self.send_response(404)
            self.end_headers()
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8") if length else "{}"
            data = json.loads(body) if body.strip() else {}
        except (ValueError, json.JSONDecodeError):
            self._send_json(400, {"error": "Invalid JSON"})
            return
        text = (data.get("text") or "").strip()
        if not text:
            self._send_json(400, {"error": "text required"})
            return
        post_id = str(uuid.uuid4())[:8]
        thread_id = data.get("thread_id") or post_id
        now = datetime.now(timezone.utc).isoformat()
        # Optional: store full_text (e.g. article for offers) but don't store in item for GET unless we want to
        full_text = (data.get("full_text") or "").strip()
        item = {"id": post_id, "text": text, "thread_id": thread_id, "created_at": now}
        FEED.append(item)
        # Show in feed terminal: full text if short (so ENS never cut), else preview
        one_line = text.replace("\n", " ").strip()
        if len(one_line) <= 250:
            print(f"[FEED] POST #{post_id}: {one_line}")
        else:
            preview = one_line[:200] + "..."
            print(f"[FEED] POST #{post_id}: {preview}")
        if full_text:
            print(f"[FEED] --- Article / input (for this offer) ---\n{full_text}\n[FEED] ---")
        self._send_json(201, item)


def main():
    port = int(os.getenv("AGENTPAY_DEMO_FEED_PORT", "8765"))
    host = os.getenv("AGENTPAY_DEMO_FEED_HOST", "0.0.0.0")
    server = ThreadingHTTPServer((host, port), FeedHandler)
    print(f"Demo feed: http://{host}:{port}  GET/POST /feed")
    print("Set AGENTPAY_DEMO_FEED_URL to this URL in both Moltbots.")
    server.serve_forever()


if __name__ == "__main__":
    main()
