"""
Internal Enterprise Server for the AI Compliance & Policy Workflow.

Environment:
  AUDIT_LEDGER_PATH  JSONL file for the audit ledger (default: data/audit_ledger.jsonl)
  AUDIT_HMAC_KEY     secret for signing audit blocks (a dev key is used when unset)
  API_TOKEN          when set, officer decisions and the audit ledger require header X-API-Token
  ALLOWED_ORIGINS    comma-separated CORS origins (default: same-origin only)
  PORT               listen port (default 8000)
"""
import hmac
import os
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.audit.audit_log import AuditTrail
from src.state_machine.machine import ComplianceStateMachine, IllegalTransitionError, SeparationOfDutiesError
from src.state_machine.states import (
    RequestDocument, ComplianceDecision, OfficerDecisionInput, ClarificationInput, State, WAITING_STATES,
)
from src.state_machine.temporal_monitor import TemporalTraceVerifier
from src.state_machine.transitions import TRANSITIONS, STATE_LAYOUT

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(
    title="Enterprise AI Compliance & Policy Workflow",
    description="Internal governance server for AI tool onboarding",
    version="2.0.0",
)

origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins else ["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Token", "*"]
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


ledger_path = os.environ.get("AUDIT_LEDGER_PATH", os.path.join(BASE_DIR, "data", "audit_ledger.jsonl"))
state_machine = ComplianceStateMachine(audit=AuditTrail(path=ledger_path))

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def require_token(x_api_token: Optional[str] = Header(None)):
    expected = os.environ.get("API_TOKEN")
    if expected and not hmac.compare_digest(expected, x_api_token or ""):
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Token.")


def _run(fn, *args):
    try:
        return fn(*args)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown request id.")
    except SeparationOfDutiesError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except IllegalTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.get("/")
def serve_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/styles.css")
def serve_styles():
    return FileResponse(os.path.join(STATIC_DIR, "styles.css"))


@app.get("/app.js")
def serve_app_js():
    return FileResponse(os.path.join(STATIC_DIR, "app.js"))


@app.get("/presentation")
def serve_presentation():
    return FileResponse(os.path.join(BASE_DIR, "docs", "presentation.html"))


@app.get("/business-presentation")
def serve_business_presentation():
    return FileResponse(os.path.join(BASE_DIR, "docs", "business_presentation.html"))


@app.get("/api/health")
def health_check():
    return {
        "status": "healthy",
        "service": "AI Compliance & Policy Workflow",
        "environment": "Internal Corporate Server (On-Premises/Private VPC)",
        "efsm": {"states": len(State), "transitions": len(TRANSITIONS)},
        "ltl_invariants": len(TemporalTraceVerifier.RULES),
        "pending_requests": len(state_machine.pending()),
        "audit_blocks": len(state_machine.audit.chain),
        "audit_persistent": bool(state_machine.audit.path),
    }


@app.get("/api/state-machine")
def state_machine_definition():
    """States, layout and the transition table: the single source for the UI table and diagram."""
    return {
        "states": [{"id": s.value.split(":")[0], "name": s.value, "col": STATE_LAYOUT[s][0], "row": STATE_LAYOUT[s][1],
                    "waiting": s in WAITING_STATES} for s in State],
        "transitions": [{"code": t.code, "from": t.source.value, "event": t.event.value, "to": t.target.value,
                         "layer": t.layer.value, "guard": t.guard, "side_effect": t.side_effect, "example": t.example}
                        for t in TRANSITIONS],
        "ltl": [{"id": r[0], "formula": r[1], "kind": r[2], "description": r[3]} for r in TemporalTraceVerifier.RULES],
    }


@app.post("/api/evaluate", response_model=ComplianceDecision)
def evaluate_request(request: RequestDocument):
    return _run(state_machine.process_request, request)


@app.get("/api/requests/{request_id}", response_model=ComplianceDecision)
def get_request(request_id: str):
    return _run(state_machine.decision_of, request_id)


@app.get("/api/pending")
def pending_requests():
    return [d.model_dump() for d in state_machine.pending()]


@app.post("/api/requests/{request_id}/officer-decision", response_model=ComplianceDecision,
          dependencies=[Depends(require_token)])
def officer_decision(request_id: str, decision: OfficerDecisionInput):
    return _run(state_machine.officer_decide, request_id, decision)


@app.post("/api/requests/{request_id}/clarify", response_model=ComplianceDecision)
def clarify_request(request_id: str, info: ClarificationInput):
    return _run(state_machine.clarify, request_id, info)


@app.post("/api/demo/bypass-attempt")
def bypass_attempt():
    return state_machine.demonstrate_bypass()


@app.get("/api/audit-trail", dependencies=[Depends(require_token)])
def get_audit_trail():
    problems = state_machine.audit.find_tampering()
    return {
        "integrity_verified": not problems,
        "problems": problems,
        "total_records": len(state_machine.audit.chain),
        "genesis_hash": state_machine.audit._genesis_hash,
        "latest_block_hash": state_machine.audit.get_last_hash(),
        "ledger": state_machine.audit.chain,
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"Starting Internal Corporate Server on http://127.0.0.1:{port} ...")
    uvicorn.run("server:app", host="127.0.0.1", port=port, reload=os.environ.get("RELOAD") == "1")
