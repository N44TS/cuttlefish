"""
Parse Moltbook (or feed) posts for AgentPay offers and accepts.

Convention: see agentpay/docs/MOLTBOOK_CONVENTION.md.
"""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class AgentPayOffer:
    """Parsed offer (poster wants to pay for work)."""
    task_type: str
    poster_ens: str
    price: Optional[str] = None
    input_ref: Optional[str] = None
    raw: Optional[str] = None


@dataclass
class AgentPayAccept:
    """Parsed accept (worker agrees, gives their ENS)."""
    worker_ens: str
    raw: Optional[str] = None


# [AGENTPAY_OFFER] block
OFFER_BLOCK_RE = re.compile(
    r"\[AGENTPAY_OFFER\]\s*\n(.*?)(?=\n\[|\n\n\n|\Z)",
    re.DOTALL | re.IGNORECASE
)
KEY_VALUE_RE = re.compile(r"^\s*(\w+)\s*:\s*(.+)$", re.MULTILINE)

# [AGENTPAY_ACCEPT] block
ACCEPT_BLOCK_RE = re.compile(
    r"\[AGENTPAY_ACCEPT\]\s*\n(.*?)(?=\n\[|\n\n\n|\Z)",
    re.DOTALL | re.IGNORECASE
)

# Free-form: "Offering X to Y. AgentPay. My ENS: name.eth"
OFFER_FREEFORM_RE = re.compile(
    r"(?:offering|offers?)\s+([^.]*?)\s+to\s+([^.]*?)\.\s*(?:agentpay|payment\s*:\s*agentpay).*?ens\s*:\s*([\w.-]+\.eth)",
    re.IGNORECASE | re.DOTALL
)
# Loose: "... AgentPay. My ENS: alice.eth"
OFFER_ENS_RE = re.compile(r"agentpay.*?ens\s*:\s*([\w.-]+\.eth)", re.IGNORECASE | re.DOTALL)
OFFER_TASK_RE = re.compile(r"to\s+([^.]*?)\.", re.IGNORECASE)

# Accept: "I'll do it. My ENS: bob.eth" or "ens: bob.eth"
ACCEPT_ENS_RE = re.compile(
    r"(?:my\s+)?ens\s*:\s*([\w.-]+\.eth)|I'll do it\.\s*My ENS:\s*([\w.-]+\.eth)",
    re.IGNORECASE
)


def parse_offer(text: str) -> Optional[AgentPayOffer]:
    """
    Parse text for an AgentPay offer. Returns AgentPayOffer or None.
    Tries structured [AGENTPAY_OFFER] first, then free-form.
    """
    if not text or "agentpay" not in text.lower():
        return None

    # Structured block
    m = OFFER_BLOCK_RE.search(text)
    if m:
        block = m.group(1).strip()
        kv = dict(KEY_VALUE_RE.findall(block))
        task = (kv.get("task") or "").strip()
        ens = (kv.get("ens") or "").strip()
        if ens and not ens.endswith(".eth"):
            ens = ens + ".eth"
        if task and ens:
            return AgentPayOffer(
                task_type=task,
                poster_ens=ens,
                price=(kv.get("price") or "").strip() or None,
                input_ref=(kv.get("input") or "").strip() or None,
                raw=text,
            )

    # Free-form
    m = OFFER_ENS_RE.search(text)
    if m:
        ens = m.group(1).strip()
        if not ens.endswith(".eth"):
            ens = ens + ".eth"
        task = "task"
        t = OFFER_TASK_RE.search(text)
        if t:
            task = t.group(1).strip() or "task"
        return AgentPayOffer(
            task_type=task,
            poster_ens=ens,
            raw=text,
        )
    return None


def parse_accept(text: str) -> Optional[AgentPayAccept]:
    """
    Parse text for an AgentPay accept (worker replying with their ENS).
    Returns AgentPayAccept or None.
    """
    if not text:
        return None

    # Structured block
    m = ACCEPT_BLOCK_RE.search(text)
    if m:
        block = m.group(1).strip()
        kv = dict(KEY_VALUE_RE.findall(block))
        ens = (kv.get("ens") or "").strip()
        if ens and not ens.endswith(".eth"):
            ens = ens + ".eth"
        if ens:
            return AgentPayAccept(worker_ens=ens, raw=text)

    # Free-form
    m = ACCEPT_ENS_RE.search(text)
    if m:
        ens = (m.group(1) or m.group(2) or "").strip()
        if ens and not ens.endswith(".eth"):
            ens = ens + ".eth"
        if ens:
            return AgentPayAccept(worker_ens=ens, raw=text)
    return None
