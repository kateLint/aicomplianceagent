"""
Table-driven Extended Finite State Machine (EFSM): 18 states, 31 transitions, 3 layers.

Every state change goes through `fire(session, event)`, which
  1. looks the (current_state, event) pair up in transitions.TRANSITIONS and raises
     IllegalTransitionError when it is not there (no hidden edges, no skipped states);
  2. for any transition into S14 (Approved), re-runs the LTL safety monitor on the trace
     *including* that transition and refuses it on a violation (runtime shield).

Each request lives in its own RequestSession, so concurrent API calls never share a trace.
Requests routed to a human (S11 / S12) are parked and resumed by `clarify` / `officer_decide`.
"""
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

from .states import (
    State, Event, RequestDocument, ComplianceDecision, DecisionStatus, DataSensitivity,
    GateStatus, OfficerAction, OfficerDecisionInput, ClarificationInput, WAITING_STATES,
)
from .transitions import lookup, Transition
from .temporal_monitor import TemporalTraceVerifier
from ..reasoning.opa_engine import OPAEngine
from ..reasoning.z3_solver import Z3ConstraintVerifier
from ..reasoning.prolog_engine import PrologRBACEngine
from ..reasoning.datalog_engine import DatalogLineageEngine
from ..neural.extractor import NeuralToSExtractor, ExtractionError
from ..audit.audit_log import AuditTrail
from ..knowledge.registries import EmployeeDirectory, ContractRegistry, VendorRegistry

C_SCORE_THRESHOLD = 0.85
MAX_RETRIES = 2
GATES = ["opa", "neuro", "z3", "prolog", "datalog", "ltl"]
VAGUE_USE = re.compile(r"^\s*(general|misc|various|testing|test|stuff|שימוש כללי|כללי|בדיקה|שונות)\W*$", re.IGNORECASE)


class IllegalTransitionError(Exception):
    """A transition that is not in the table, or that the LTL runtime monitor refuses."""


class SeparationOfDutiesError(Exception):
    """An officer decision that violates RBAC / Separation of Duties."""


@dataclass
class RequestSession:
    request: RequestDocument
    state: State = State.S0_IDLE
    trace: List[Dict[str, Any]] = field(default_factory=list)
    layers: set = field(default_factory=set)
    lock: threading.Lock = field(default_factory=threading.Lock)
    # per intake cycle (reset on T21)
    blocking: List[str] = field(default_factory=list)
    satisfied: List[str] = field(default_factory=list)
    remediation: List[str] = field(default_factory=list)
    gates: Dict[str, GateStatus] = field(default_factory=lambda: {g: GateStatus.SKIPPED for g in GATES})
    claims: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    facts: Dict[str, Any] = field(default_factory=dict)
    c_score: Optional[float] = None
    retries: int = 0
    recovered_tos: Optional[str] = None
    chunked: bool = False
    identity: Dict[str, Any] = field(default_factory=dict)
    dpa_verified: bool = False
    # outcome
    status: Optional[DecisionStatus] = None
    final_state: Optional[State] = None
    explanation: str = ""
    pending_action: Optional[str] = None
    audit_hash: str = ""

    def reset_cycle(self):
        fresh = RequestSession(request=self.request)
        for name in ("blocking", "satisfied", "remediation", "gates", "claims", "facts", "c_score",
                     "retries", "recovered_tos", "chunked", "identity", "dpa_verified",
                     "pending_action"):
            setattr(self, name, getattr(fresh, name))

    def ltl_view(self) -> List[Dict[str, str]]:
        return [{"state": t["to"], "event": t["event"]} for t in self.trace]

    def ltl_context(self) -> Dict[str, Any]:
        r = self.request
        return {"is_sensitive": r.is_sensitive, "external": r.uses_external_processor,
                "dpa_claimed": r.has_signed_dpa, "dpa_verified": self.dpa_verified}


class ComplianceStateMachine:

    def __init__(self, audit: Optional[AuditTrail] = None, directory: Optional[EmployeeDirectory] = None,
                 contracts: Optional[ContractRegistry] = None, vendors: Optional[VendorRegistry] = None):
        self.opa = OPAEngine()
        self.z3 = Z3ConstraintVerifier()
        self.prolog = PrologRBACEngine()
        self.datalog = DatalogLineageEngine()
        self.neural_extractor = NeuralToSExtractor()
        self.temporal_verifier = TemporalTraceVerifier()
        self.audit = audit or AuditTrail()
        self.directory = directory or EmployeeDirectory()
        self.contracts = contracts or ContractRegistry()
        self.vendors = vendors or VendorRegistry()
        self.sessions: Dict[str, RequestSession] = {}
        self._sessions_lock = threading.Lock()
        if not self.z3.check_policy_consistency():
            raise RuntimeError("Policy axioms are contradictory: no compliant approval exists.")

    # ------------------------------------------------------------------ core
    def fire(self, session: RequestSession, event: Event, detail: str = "") -> Transition:
        t = lookup(session.state, event)
        if t is None:
            raise IllegalTransitionError(
                f"Illegal transition refused: no edge '{event.value}' from '{session.state.value}' in the EFSM table.")
        if t.target == State.S14_APPROVED:
            prospective = session.ltl_view() + [{"state": t.target.value, "event": event.value}]
            ok, report = self.temporal_verifier.verify_trace(prospective, session.ltl_context())
            if not ok:
                raise IllegalTransitionError(
                    "LTL runtime monitor refused the transition into S14: "
                    + "; ".join(TemporalTraceVerifier.violations(report)))
        session.layers.add(t.layer.value)
        session.trace.append({
            "step": len(session.trace) + 1,
            "code": t.code,
            "from": session.state.value,
            "event": event.value,
            "to": t.target.value,
            "layer": t.layer.value,
            "guard": t.guard,
            "detail": detail,
            "timestamp": time.time(),
        })
        session.state = t.target
        return t

    # ------------------------------------------------------------------ entry points
    def process_request(self, request: RequestDocument) -> ComplianceDecision:
        session = RequestSession(request=request)
        with self._sessions_lock:
            if request.request_id in self.sessions:
                raise ValueError(f"Request id '{request.request_id}' already exists.")
            self.sessions[request.request_id] = session
        with session.lock:
            self.fire(session, Event.USER_SUBMITS_REQUEST, "Request record opened.")
            self._run_from_intake(session)
            return self._decision(session)

    def get(self, request_id: str) -> RequestSession:
        session = self.sessions.get(request_id)
        if session is None:
            raise KeyError(request_id)
        return session

    def decision_of(self, request_id: str) -> ComplianceDecision:
        session = self.get(request_id)
        with session.lock:
            return self._decision(session)

    def pending(self) -> List[ComplianceDecision]:
        with self._sessions_lock:
            waiting = [s for s in self.sessions.values() if s.state in WAITING_STATES]
        return [self._decision(s) for s in waiting]

    def officer_decide(self, request_id: str, decision: OfficerDecisionInput) -> ComplianceDecision:
        session = self.get(request_id)
        with session.lock:
            if session.state != State.S12_AWAITING_COMPLIANCE_REVIEW:
                raise IllegalTransitionError(f"Request is in '{session.state.value}', not awaiting compliance review.")
            officer_role = self.directory.role_of(decision.officer_name)
            ok, reason = self.prolog.can_decide(decision.officer_name, officer_role, session.request)
            if not ok:
                raise SeparationOfDutiesError(reason)
            session.satisfied.append(reason)
            note = f" Notes: {decision.notes}" if decision.notes else ""

            if decision.action == OfficerAction.APPROVE:
                self.fire(session, Event.OFFICER_APPROVES, f"Signed by {officer_role} {decision.officer_name}.{note}")
                self._close_unrun_gates(session)
                session.satisfied.append(f"OFFICER_SIGNOFF: approved by {officer_role} '{decision.officer_name}'.{note}")
                self._finish(session, DecisionStatus.APPROVED, "Approved by the compliance officer.")
                return self._decision(session)
            if decision.action == OfficerAction.REJECT:
                self.fire(session, Event.OFFICER_REJECTS, f"Rejected by {officer_role} {decision.officer_name}.{note}")
                self._close_unrun_gates(session)
                session.blocking.append(f"OFFICER_DECISION: rejected by {officer_role} '{decision.officer_name}'.{note}")
                self._finish(session, DecisionStatus.REJECTED, "Rejected by the compliance officer.")
                return self._decision(session)
            self.fire(session, Event.OFFICER_REQUESTS_MORE_INFO, f"Question from {decision.officer_name}.{note}")
            self._park(session, DecisionStatus.NEED_INFO,
                       f"The compliance officer requested more information.{note}", "clarification")
            return self._decision(session)

    def clarify(self, request_id: str, info: ClarificationInput) -> ComplianceDecision:
        session = self.get(request_id)
        with session.lock:
            if session.state != State.S11_AWAITING_HUMAN_CLARIFICATION:
                raise IllegalTransitionError(f"Request is in '{session.state.value}', not awaiting clarification.")
            updates = {k: v for k, v in info.model_dump().items() if v is not None}
            if not updates:
                raise ValueError("Clarification is empty.")
            session.request = session.request.model_copy(update=updates)
            self.fire(session, Event.USER_SUBMITS_ADDITIONAL_INFO, f"Updated fields: {', '.join(sorted(updates))}.")
            session.reset_cycle()
            self._run_from_intake(session)
            return self._decision(session)

    def demonstrate_bypass(self) -> Dict[str, Any]:
        """Two bypass attempts, each refused by a different layer (used by the portal demo)."""
        req = RequestDocument(request_id="BYPASS-DEMO", user_name="demo", user_role="developer", department="demo",
                              tool_name="Any-Tool", data_sensitivity=DataSensitivity.CONFIDENTIAL,
                              intended_use="Bypass demonstration", tos_text="demo")
        s = RequestSession(request=req)
        for ev in (Event.USER_SUBMITS_REQUEST, Event.FORM_VALIDATED, Event.SCRAPING_COMPLETED, Event.CONTEXT_READY):
            self.fire(s, ev)
        attempts = []
        try:
            self.fire(s, Event.ROUTE_TO_APPROVED)
        except IllegalTransitionError as e:
            attempts.append({"attempt": "Jump S4 → S14 (skip every gate)", "layer": "EFSM transition table", "refused": str(e)})
        s.state = State.S10_DECISION_ROUTING  # simulate a compromised orchestrator that corrupts its own state
        try:
            self.fire(s, Event.ROUTE_TO_APPROVED)
        except IllegalTransitionError as e:
            attempts.append({"attempt": "Corrupt state to S10, then ROUTE_TO_APPROVED", "layer": "LTL runtime monitor", "refused": str(e)})
        return {"attempts": attempts, "trace": s.trace}

    # ------------------------------------------------------------------ pipeline
    def _run_from_intake(self, session: RequestSession):
        r = session.request
        missing = [name for name in ("user_name", "tool_name", "intended_use") if not getattr(r, name).strip()]
        if missing:
            self.fire(session, Event.INTAKE_FAILED, f"Missing: {', '.join(missing)}.")
            session.blocking.append(f"Missing required fields: {', '.join(missing)}.")
            session.status, session.final_state = DecisionStatus.NEED_INFO, State.S0_IDLE
            session.explanation = "Form validation failed; the request was returned to the employee."
            session.audit_hash = self._write_audit(session, "INTAKE_FAILED")
            return

        self._resolve_identity(session)
        self.fire(session, Event.FORM_VALIDATED, f"Identity: {session.identity['summary']}")
        self._ingest(session)

    def _resolve_identity(self, session: RequestSession):
        r = session.request
        declared = r.user_role.lower().strip()
        directory_role = self.directory.role_of(r.user_name)
        session.identity = {
            "declared_role": declared,
            "directory_role": directory_role,
            "effective_role": directory_role or declared,
            "verified": directory_role is not None,
            "spoofing_detected": directory_role is not None and directory_role != declared,
        }
        if session.identity["spoofing_detected"]:
            session.identity["summary"] = f"declared '{declared}' overridden by directory role '{directory_role}'"
        elif directory_role:
            session.identity["summary"] = f"verified as '{directory_role}'"
        else:
            session.identity["summary"] = f"not in directory; declared role '{declared}' is unverified"
        session.dpa_verified = r.has_signed_dpa and self.contracts.has_dpa_on_file(r.tool_name)

    def _ingest(self, session: RequestSession):
        r = session.request
        document = (r.tos_text or "").strip() or session.recovered_tos
        if not document:
            self.fire(session, Event.SCRAPING_FAILED_WITH_TIMEOUT, "No vendor document supplied or retrievable.")
            return self._recover(session, "no_document")

        extraction = self.neural_extractor.extract(r.tool_name, document, r.deployment_type)
        session.facts, session.claims = extraction.facts, extraction.claims
        source = "vendor registry (cached ToS)" if session.recovered_tos and not (r.tos_text or "").strip() else "submitted ToS"
        self.fire(session, Event.SCRAPING_COMPLETED,
                  f"Source: {source}. Claims: " + ", ".join(f"{k}={v['value']}" for k, v in extraction.claims.items()))

        refs = ["EU AI Act Art. 12 (record-keeping)"]
        if r.uses_external_processor and r.data_sensitivity != DataSensitivity.PUBLIC:
            refs.append("GDPR Art. 28 (processor contracts)")
        if r.data_sensitivity == DataSensitivity.RESTRICTED_PII:
            refs.append("GDPR Art. 44-49 (international transfers)")
        self.fire(session, Event.CONTEXT_READY, "Retrieved: " + "; ".join(refs))

        # S4: OPA
        allowed, violations = self.opa.evaluate(r, session.facts)
        if not allowed:
            session.gates["opa"] = GateStatus.FAIL
            session.blocking.extend(violations)
            self.fire(session, Event.OPA_DENY, f"{len(violations)} hard violation(s).")
            return self._reject(session, "Rejected by the OPA hard-policy gate.")
        session.gates["opa"] = GateStatus.PASS
        session.satisfied.append("OPA: no hard-policy violation on the known facts.")
        self.fire(session, Event.OPA_ALLOW)

        # S5: neuro risk evaluation
        try:
            self.neural_extractor.check_context(document, chunked=session.chunked)
        except ExtractionError as e:
            self.fire(session, Event.LLM_TIMEOUT_OR_PARSE_ERROR, str(e))
            return self._recover(session, "llm_context")
        session.c_score = extraction.c_score
        self.fire(session, Event.LLM_EVALUATION_COMPLETED, f"C_score = min(conf(claim)) = {extraction.c_score:.2f}")

        # S6: uncertainty gate
        if extraction.c_score < C_SCORE_THRESHOLD or extraction.injection_suspected:
            session.gates["neuro"] = GateStatus.ESCALATE
            reasons = []
            if extraction.unknown_claims():
                reasons.append("uncertain claims: " + ", ".join(extraction.unknown_claims()))
            if extraction.injection_suspected:
                reasons.append("possible prompt injection in vendor text: " + " | ".join(extraction.injection_evidence))
                session.blocking.append("NEURO_GUARD: vendor document contains instructions aimed at the AI evaluator.")
            self.fire(session, Event.UNCERTAINTY_ESCALATE, f"C_score {extraction.c_score:.2f}; " + "; ".join(reasons))
            return self._park(session, DecisionStatus.HUMAN_REVIEW,
                              "Escalated to a compliance officer: the vendor terms are not certain enough to decide automatically ("
                              + "; ".join(reasons) + ").", "officer_decision")
        session.gates["neuro"] = GateStatus.PASS
        session.satisfied.append(f"Claim confidence: all required claims certain (C_score = {extraction.c_score:.2f} ≥ {C_SCORE_THRESHOLD}).")
        self.fire(session, Event.HIGH_CONFIDENCE_DETECTED)

        # S7: Z3
        sat, z3_expl, core, remediation = self.z3.verify_constraints(r, session.facts)
        if not sat:
            session.gates["z3"] = GateStatus.FAIL
            session.blocking.extend(z3_expl)
            session.remediation.extend(remediation)
            self.fire(session, Event.Z3_SOLVER_UNSAT, f"UNSAT core: {core}")
            return self._reject(session, "Rejected: approval contradicts the policy axioms (Z3 UNSAT).")
        session.gates["z3"] = GateStatus.PASS
        session.satisfied.extend(z3_expl)
        self.fire(session, Event.Z3_SOLVER_SAT)

        # S8: Prolog + Datalog
        findings = []
        prolog_ok, requires_dpo, prolog_expl = self.prolog.evaluate(r, session.identity["effective_role"])
        if session.identity["spoofing_detected"]:
            prolog_ok = False
            prolog_expl = [f"IDENTITY_SPOOFING: declared role '{session.identity['declared_role']}' but the directory says "
                           f"'{session.identity['directory_role']}'."] + prolog_expl
        (findings if not prolog_ok else session.satisfied).extend(prolog_expl)
        session.gates["prolog"] = GateStatus.PASS if prolog_ok else GateStatus.FAIL
        if prolog_ok and requires_dpo:
            session.gates["prolog"] = GateStatus.ESCALATE

        datalog_ok, datalog_expl = self.datalog.evaluate(r, session.facts)
        (findings if not datalog_ok else session.satisfied).extend(datalog_expl)
        session.gates["datalog"] = GateStatus.PASS if datalog_ok else GateStatus.FAIL
        session.blocking.extend(findings)
        self.fire(session, Event.INFERENCE_COMPLETED, f"RBAC {'ok' if prolog_ok else 'violation'}, lineage {'clean' if datalog_ok else 'tainted'}.")

        # S9: plan the route, then verify prefix + planned route with LTL before executing it
        escalation_reasons = []
        if requires_dpo:
            escalation_reasons.append("RESTRICTED_PII requires DPO sign-off")
        if not session.identity["verified"] and r.is_sensitive:
            escalation_reasons.append("requester identity not verified in the directory")
        if r.has_signed_dpa and not session.dpa_verified and r.is_sensitive and r.uses_external_processor:
            escalation_reasons.append("claimed DPA not found in the contract registry")

        if findings:
            planned = Event.ROUTE_TO_REJECTED
        elif len(r.intended_use.strip()) < 15 or VAGUE_USE.match(r.intended_use):
            planned = Event.ROUTE_TO_NEED_INFO
        elif escalation_reasons:
            planned = Event.ROUTE_TO_ESCALATION
        else:
            planned = Event.ROUTE_TO_APPROVED

        planned_target = lookup(State.S10_DECISION_ROUTING, planned).target
        prospective = session.ltl_view() + [
            {"state": State.S10_DECISION_ROUTING.value, "event": Event.VERIFICATION_SUCCESS.value},
            {"state": planned_target.value, "event": planned.value},
        ]
        ltl_ok, planned_report = self.temporal_verifier.verify_trace(prospective, session.ltl_context())
        if not ltl_ok:
            session.gates["ltl"] = GateStatus.FAIL
            session.blocking.extend(TemporalTraceVerifier.violations(planned_report))
            self.fire(session, Event.LTL_VIOLATION_DETECTED, f"Planned route {planned.value} would violate an invariant.")
            return self._reject(session, "Rejected: the planned approval would violate a temporal safety invariant.")
        session.gates["ltl"] = GateStatus.PASS
        session.satisfied.append(f"LTL: planned route {planned.value} satisfies all safety invariants.")
        self.fire(session, Event.VERIFICATION_SUCCESS, f"Planned route: {planned.value}")

        # S10: routing
        if planned == Event.ROUTE_TO_REJECTED:
            self.fire(session, planned, f"{len(findings)} inference finding(s).")
            return self._reject(session, "Rejected by formal inference (RBAC / supply-chain lineage).")
        if planned == Event.ROUTE_TO_NEED_INFO:
            self.fire(session, planned, "Intended use is too vague to assess data exposure.")
            return self._park(session, DecisionStatus.NEED_INFO,
                              "Please describe the intended use in more detail: which data will be entered and for what purpose.",
                              "clarification")
        if planned == Event.ROUTE_TO_ESCALATION:
            self.fire(session, planned, "; ".join(escalation_reasons))
            return self._park(session, DecisionStatus.HUMAN_REVIEW,
                              "All automated gates passed; human sign-off required: " + "; ".join(escalation_reasons) + ".",
                              "officer_decision")
        self.fire(session, Event.ROUTE_TO_APPROVED)
        return self._finish(session, DecisionStatus.APPROVED, "Approved automatically: every formal gate passed.")

    def _recover(self, session: RequestSession, cause: str):
        session.retries += 1
        r = session.request
        if session.retries <= MAX_RETRIES:
            if cause == "no_document":
                cached = self.vendors.cached_tos(r.tool_name)
                if cached:
                    session.recovered_tos = cached
                    self.fire(session, Event.RECOVERY_SUCCESSFUL, f"Retry {session.retries}: loaded reviewed ToS from the vendor registry.")
                    return self._ingest(session)
            elif cause == "llm_context":
                session.chunked = True
                self.fire(session, Event.RECOVERY_SUCCESSFUL, f"Retry {session.retries}: switching to chunked (map-reduce) evaluation.")
                return self._ingest(session)
        reason = ("no vendor terms available and the vendor is not in the registry"
                  if cause == "no_document" else "the model evaluation kept failing")
        self.fire(session, Event.RECOVERY_FAILED_ESCALATE, f"Fail-closed: {reason}.")
        for g in GATES:
            session.gates[g] = GateStatus.PENDING
        return self._park(session, DecisionStatus.HUMAN_REVIEW,
                          f"Cannot evaluate automatically ({reason}). A compliance officer must request or upload the vendor terms.",
                          "officer_decision")

    # ------------------------------------------------------------------ outcomes
    def _park(self, session: RequestSession, status: DecisionStatus, explanation: str, pending_action: str):
        for g in GATES:
            if session.gates[g] == GateStatus.SKIPPED:
                session.gates[g] = GateStatus.PENDING
        session.status, session.final_state = status, session.state
        session.explanation, session.pending_action = explanation, pending_action
        session.audit_hash = self._write_audit(session, f"PENDING_{pending_action.upper()}")

    def _close_unrun_gates(self, session: RequestSession):
        for g in GATES:
            if session.gates[g] == GateStatus.PENDING:
                session.gates[g] = GateStatus.SKIPPED

    def _reject(self, session: RequestSession, explanation: str):
        return self._finish(session, DecisionStatus.REJECTED, explanation)

    def _finish(self, session: RequestSession, status: DecisionStatus, explanation: str):
        outcome_state = session.state  # S14 or S15
        if status == DecisionStatus.APPROVED:
            self.fire(session, Event.REGISTRATION_SUCCESS, "Tool added to the approved registry.")
        else:
            self.fire(session, Event.REJECTION_COMPLETE, "Tool added to the block list.")
        session.status, session.final_state, session.explanation = status, outcome_state, explanation
        session.pending_action = None
        session.audit_hash = self._write_audit(session, status.value)
        self.fire(session, Event.AUDIT_LOGGED, f"Block {session.audit_hash[:12]}… written and HMAC-signed.")
        self.fire(session, Event.NOTIFICATION_SENT, "Employee notified.")

    def _write_audit(self, session: RequestSession, decision: str) -> str:
        r = session.request
        return self.audit.record_decision(
            request_id=r.request_id, decision=decision, trace=session.trace,
            metadata={"user": r.user_name, "tool": r.tool_name, "sensitivity": r.data_sensitivity.value,
                      "c_score": session.c_score, "identity_verified": session.identity.get("verified")},
        )

    def _decision(self, session: RequestSession) -> ComplianceDecision:
        # Report on the executed trace; a route refused at S9 (T17) appears in blocking_reasons instead.
        _, ltl_report = self.temporal_verifier.verify_trace(session.ltl_view(), session.ltl_context())
        return ComplianceDecision(
            request_id=session.request.request_id,
            status=session.status,
            final_state=session.final_state.value,
            c_score=session.c_score,
            explanation=session.explanation,
            blocking_reasons=list(session.blocking),
            satisfied_checks=list(session.satisfied),
            gates=dict(session.gates),
            claims=session.claims,
            remediation=list(session.remediation),
            identity=session.identity,
            ltl_report=ltl_report,
            pending_action=session.pending_action,
            trace=[{k: v for k, v in t.items() if k != "timestamp"} for t in session.trace],
            active_layers=sorted(session.layers),
            audit_hash=session.audit_hash,
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        )
