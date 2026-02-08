"""
Worker "brain": do the job via OpenClaw only (real bot).

The worker calls the OpenClaw bot you chat with (POST /v1/chat/completions).
Requires: gateway endpoint enabled, OPENCLAW_GATEWAY_URL, OPENCLAW_GATEWAY_TOKEN.
Run agentpay setup-openclaw to add these to .env; start openclaw gateway.
"""

import os
from typing import Any, Dict, Optional


def do_task_via_openclaw(task_type: str, input_data: Dict[str, Any]) -> Optional[str]:
    """
    Ask the OpenClaw bot to do the job (same agent you chat with in TUI).
    Returns the bot's reply text, or None if gateway not configured or call failed.
    """
    base_url = (os.getenv("OPENCLAW_GATEWAY_URL") or "").strip() or "http://127.0.0.1:18789"
    token = (os.getenv("OPENCLAW_GATEWAY_TOKEN") or os.getenv("OPENCLAW_GATEWAY_PASSWORD") or "").strip()
    agent_id = (os.getenv("OPENCLAW_AGENT_ID") or "main").strip()

    if not token:
        return None

    query = (input_data.get("query") or input_data.get("text") or "").strip()
    if not query:
        return None

    prompt = _build_prompt(task_type, query)
    url = f"{base_url.rstrip('/')}/v1/chat/completions"

    try:
        import requests
        r = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "x-openclaw-agent-id": agent_id,
            },
            json={
                "model": "openclaw",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1024,
            },
            timeout=90,
        )
        r.raise_for_status()
        data = r.json()
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        if isinstance(content, str) and content.strip():
            return content.strip()
    except Exception:
        return None
    return None


def do_task_with_llm(task_type: str, input_data: Dict[str, Any]) -> str:
    """
    Run the job using an LLM. Returns the model's response text.

    If no API key or the call fails, returns a short fallback message so the
    worker still responds (demo doesn't break).
    """
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("AGENTPAY_LLM_API_KEY")
    base_url = (os.getenv("OPENAI_BASE_URL") or "").strip() or "https://api.openai.com/v1"
    model = os.getenv("AGENTPAY_LLM_MODEL", "gpt-4o-mini")

    if not api_key:
        return _fallback_result(task_type, input_data, reason="No OPENAI_API_KEY or AGENTPAY_LLM_API_KEY set.")

    query = (input_data.get("query") or input_data.get("text") or "").strip()
    if not query:
        return _fallback_result(task_type, input_data, reason="No query in input_data.")

    prompt = _build_prompt(task_type, query)
    url = f"{base_url.rstrip('/')}/chat/completions"

    try:
        import requests
        r = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1024,
            },
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        if isinstance(content, str) and content.strip():
            return content.strip()
    except Exception as e:
        return _fallback_result(task_type, input_data, reason=f"LLM call failed: {e}")

    return _fallback_result(task_type, input_data, reason="Empty LLM response.")


def _build_prompt(task_type: str, query: str) -> str:
    """Build prompt for OpenClaw. Prefix marks this as an AgentPay job (same bot, skill context)."""
    prefix = "[AgentPay job] "
    if "summar" in query.lower() or "summarise" in query.lower() or "summarize" in query.lower():
        return prefix + f"Please summarise the following. Keep it to 2-4 clear sentences.\n\n{query}"
    if "medical" in query.lower() or "article" in query.lower():
        return prefix + f"Summarise this medical/article content in 2-4 clear, accurate sentences.\n\n{query}"
    return prefix + f"Task: {task_type}\n\nPlease complete this task:\n\n{query}"


def _fallback_result(task_type: str, input_data: Dict[str, Any], reason: str) -> str:
    """When LLM is unavailable, return something so the worker still completes."""
    q = (input_data.get("query") or input_data.get("text") or "")[:200]
    return (
        f"[Worker note: {reason}] "
        f"Task was: {task_type}. Input: {q}..."
    )


def do_task(task_type: str, input_data: Dict[str, Any]) -> str:
    """
    Do the job via OpenClaw only. No LLM fallback — the bot must do the work.
    Raises RuntimeError if OpenClaw is not configured or the call fails.
    """
    out = do_task_via_openclaw(task_type, input_data or {})
    if out is not None:
        return out
    token = (os.getenv("OPENCLAW_GATEWAY_TOKEN") or os.getenv("OPENCLAW_GATEWAY_PASSWORD") or "").strip()
    if not token:
        raise RuntimeError(
            "OpenClaw is required. Run 'agentpay setup-openclaw' and add OPENCLAW_GATEWAY_TOKEN to .env, "
            "then start the gateway (openclaw gateway) with chatCompletions enabled."
        )
    raise RuntimeError(
        "OpenClaw gateway call failed (wrong URL, gateway down, or endpoint disabled). "
        "Check OPENCLAW_GATEWAY_URL, run 'openclaw gateway', and enable: "
        "openclaw config set gateway.http.endpoints.chatCompletions.enabled true"
    )
