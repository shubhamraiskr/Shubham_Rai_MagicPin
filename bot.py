"""
bot.py — Vera Bot HTTP Server & Composition Endpoint
======================================================

Exposes the 5 HTTP endpoints defined in the challenge testing brief:
- GET  /v1/healthz
- GET  /v1/metadata
- POST /v1/context
- POST /v1/tick
- POST /v1/reply
- POST /v1/teardown (test cleanup)

Also exposes the required Python function:
    compose(category, merchant, trigger, customer?) -> dict
"""

import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, Request, Response, status
from pydantic import BaseModel

from composer import compose as compose_message
from conversation_handlers import conversation_manager

app = FastAPI(title="Vera Merchant AI Bot", version="1.0.0")
START_TIME = time.time()

# In-memory stores
# (scope, context_id) -> {"version": int, "payload": dict}
contexts: Dict[tuple[str, str], Dict[str, Any]] = {}


def compose(
    category: Dict[str, Any],
    merchant: Dict[str, Any],
    trigger: Dict[str, Any],
    customer: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Top-level required composition function."""
    return compose_message(category, merchant, trigger, customer)


@app.get("/v1/healthz")
async def healthz():
    counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
    for (scope, _), _ in contexts.items():
        if scope in counts:
            counts[scope] += 1
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - START_TIME),
        "contexts_loaded": counts
    }


@app.get("/v1/metadata")
async def metadata():
    return {
        "team_name": "Team Vera Elite",
        "team_members": ["Vera Engineer"],
        "model": "deterministic-4-context-composer",
        "approach": "multi-context synthesis with category-specific tone, adaptive injection support, and multi-turn state machine",
        "contact_email": "vera-team@magicpin.in",
        "version": "1.0.0",
        "submitted_at": "2026-04-26T08:00:00Z"
    }


class CtxBody(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: Dict[str, Any]
    delivered_at: Optional[str] = None


@app.post("/v1/context")
async def push_context(body: CtxBody, response: Response):
    key = (body.scope, body.context_id)
    cur = contexts.get(key)
    
    # Idempotent check: strictly lower version returns 409 conflict
    if cur and body.version < cur["version"]:
        response.status_code = status.HTTP_409_CONFLICT
        return {
            "accepted": False,
            "reason": "stale_version",
            "current_version": cur["version"]
        }
    
    # Store or update atomically (same version re-push is accepted as idempotent success)
    contexts[key] = {
        "version": body.version,
        "payload": body.payload
    }
    return {
        "accepted": True,
        "ack_id": f"ack_{body.context_id}_v{body.version}",
        "stored_at": datetime.utcnow().isoformat() + "Z"
    }


class TickBody(BaseModel):
    now: Optional[str] = None
    available_triggers: List[str] = []


@app.post("/v1/tick")
async def tick(body: TickBody):
    actions = []
    
    for trg_id in body.available_triggers:
        trg_ctx = contexts.get(("trigger", trg_id))
        if not trg_ctx:
            continue
        trg = trg_ctx.get("payload", {})
        
        merchant_id = trg.get("merchant_id")
        merchant_ctx = contexts.get(("merchant", merchant_id)) if merchant_id else None
        merchant = merchant_ctx.get("payload") if merchant_ctx else None
        
        # Resolve category
        category_slug = None
        if merchant:
            category_slug = merchant.get("category_slug")
        if not category_slug and "category" in trg.get("payload", {}):
            category_slug = trg.get("payload", {}).get("category")
            
        category_ctx = contexts.get(("category", category_slug)) if category_slug else None
        category = category_ctx.get("payload") if category_ctx else None
        
        # Resolve customer if present
        customer_id = trg.get("customer_id")
        customer = None
        if customer_id:
            cust_ctx = contexts.get(("customer", customer_id))
            if cust_ctx:
                customer = cust_ctx.get("payload")
            else:
                # Check local seed/expanded dataset
                try:
                    import json
                    from pathlib import Path
                    c_path = Path("dataset/expanded/customers") / f"{customer_id}.json"
                    if c_path.exists():
                        with open(c_path) as fp:
                            customer = json.load(fp)
                    else:
                        seed_path = Path("dataset/customers_seed.json")
                        if seed_path.exists():
                            with open(seed_path) as fp:
                                sdata = json.load(fp)
                                for c in sdata.get("customers", []):
                                    if c.get("customer_id") == customer_id:
                                        customer = c
                                        break
                except Exception:
                    pass

        if not (merchant and category):
            continue

        composed = compose(category, merchant, trg, customer)
        
        conv_id = composed.get("conversation_id") or f"conv_{merchant_id}_{trg_id}"
        actions.append({
            "conversation_id": conv_id,
            "merchant_id": merchant_id,
            "customer_id": customer_id,
            "send_as": composed.get("send_as", "vera"),
            "trigger_id": trg_id,
            "template_name": composed.get("template_name", "vera_standard_v1"),
            "template_params": composed.get("template_params", []),
            "body": composed.get("body", ""),
            "cta": composed.get("cta", "open_ended"),
            "suppression_key": composed.get("suppression_key", trg.get("suppression_key", "")),
            "rationale": composed.get("rationale", "")
        })

    return {"actions": actions}


class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str
    message: str
    received_at: Optional[str] = None
    turn_number: int


@app.post("/v1/reply")
async def reply(body: ReplyBody):
    res = conversation_manager.handle_reply(
        conversation_id=body.conversation_id,
        message=body.message,
        turn_number=body.turn_number,
        merchant_id=body.merchant_id,
        customer_id=body.customer_id,
        from_role=body.from_role
    )
    return res


@app.post("/v1/teardown")
async def teardown():
    contexts.clear()
    return {"status": "ok", "message": "all context stores cleared"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("bot:app", host="0.0.0.0", port=port, log_level="info")
