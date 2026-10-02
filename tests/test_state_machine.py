"""
EFSM enforcement, LTL runtime monitor, and transition coverage.
"""
import pytest

from src.state_machine.machine import ComplianceStateMachine, IllegalTransitionError, RequestSession
from src.state_machine.states import (
    State, Event, DataSensitivity, DeploymentType, DecisionStatus, OfficerDecisionInput, ClarificationInput,
)
from src.state_machine.temporal_monitor import TemporalTraceVerifier, VIOLATED, PENDING
from src.state_machine.transitions import TRANSITIONS
from tests.conftest import make_request, codes, EU_CLEAN_TOS


def test_complete_approved_lifecycle(sm):
    d = sm.process_request(make_request())
    assert d.status == DecisionStatus.APPROVED
    assert d.final_state == State.S14_APPROVED.value
    assert codes(d) == ["T01", "T02", "T04", "T06", "T07", "T09", "T11", "T13", "T15", "T16", "T18", "T27", "T29", "T30"]
    assert all(r["status"] != VIOLATED for r in d.ltl_report)


def test_every_recorded_step_is_a_table_edge(sm):
    d = sm.process_request(make_request())
    edges = {(t.source.value, t.event.value, t.target.value) for t in TRANSITIONS}
    assert all((s["from"], s["event"], s["to"]) in edges for s in d.trace)
    assert all(a["to"] == b["from"] for a, b in zip(d.trace, d.trace[1:]))


def test_illegal_transition_is_refused(sm):
    s = RequestSession(request=make_request())
    sm.fire(s, Event.USER_SUBMITS_REQUEST)
    with pytest.raises(IllegalTransitionError):
        sm.fire(s, Event.ROUTE_TO_APPROVED)
    assert s.state == State.S1_REQUEST_INTAKE


def test_ltl_runtime_shield_blocks_corrupted_state(sm):
    """Even with a legal (S10, ROUTE_TO_APPROVED) edge, the monitor refuses an approval with no Z3 proof."""
    demo = sm.demonstrate_bypass()
    layers = [a["layer"] for a in demo["attempts"]]
    assert layers == ["EFSM transition table", "LTL runtime monitor"]
    assert "LTL_2" in demo["attempts"][1]["refused"]


def test_ltl_is_checked_on_planned_route_t17(sm):
    """Confidential data to an external vendor without a DPA: all gates pass, LTL_4 refuses the planned approval."""
    d = sm.process_request(make_request(deployment_type=DeploymentType.DEDICATED_CLOUD, tos_text=EU_CLEAN_TOS))
    assert d.status == DecisionStatus.REJECTED
    assert "T17" in codes(d) and "T18" not in codes(d)
    assert any("LTL_4" in r for r in d.blocking_reasons)


def test_ltl_verifier_catches_unauthorized_approval():
    bad_trace = [
        {"state": State.S1_REQUEST_INTAKE, "event": Event.USER_SUBMITS_REQUEST},
        {"state": State.S2_INGESTING_DOCS, "event": Event.FORM_VALIDATED},
        {"state": State.S14_APPROVED, "event": Event.ROUTE_TO_APPROVED},
        {"state": State.S17_COMPLETED, "event": Event.AUDIT_LOGGED},
    ]
    ok, report = TemporalTraceVerifier().verify_trace(
        bad_trace, {"is_sensitive": True, "external": True, "dpa_claimed": False, "dpa_verified": False})
    violated = {r["id"] for r in report if r["status"] == VIOLATED}
    assert not ok
    assert {"LTL_1", "LTL_2", "LTL_4", "LTL_5"} <= violated


def test_ltl_liveness_pending_while_escalated(sm):
    d = sm.process_request(make_request(tool_name="SomeTool", tos_text=None, deployment_type=DeploymentType.DEDICATED_CLOUD))
    assert d.status == DecisionStatus.HUMAN_REVIEW
    assert {r["id"]: r["status"] for r in d.ltl_report}["LTL_6"] == PENDING


def test_ltl_checks_are_per_intake_cycle():
    """An OPA check from a previous cycle does not justify an approval after T21."""
    trace = [
        {"state": State.S1_REQUEST_INTAKE, "event": Event.USER_SUBMITS_REQUEST},
        {"state": State.S4_DETERMINISTIC_RULE_CHECKING, "event": Event.CONTEXT_READY},
        {"state": State.S1_REQUEST_INTAKE, "event": Event.USER_SUBMITS_ADDITIONAL_INFO},
        {"state": State.S14_APPROVED, "event": Event.OFFICER_APPROVES},
    ]
    ok, report = TemporalTraceVerifier().verify_trace(trace, {})
    assert not ok and any(r["id"] == "LTL_1" and r["status"] == VIOLATED for r in report)


def test_all_31_transitions_are_reachable():
    """Drive the machine through every edge of the table at least once."""
    sm = ComplianceStateMachine()
    seen = set()

    def run(**kw):
        d = sm.process_request(make_request(**kw))
        seen.update(codes(d))
        return d

    run()                                                                    # happy path
    run(intended_use=" ")                                                    # T03
    run(user_role="marketing", user_name="Michal", tool_name="Free-Public-AI",
        deployment_type=DeploymentType.PUBLIC_SAAS, tos_text="We train our models on your inputs.")  # T08
    run(deployment_type=DeploymentType.DEDICATED_CLOUD, has_signed_dpa=True, tool_name="Enterprise-Analytics",
        tos_text="Hosted in Germany. No model training. Data retained for 90 days. Encryption at rest.")  # T14
    run(deployment_type=DeploymentType.DEDICATED_CLOUD, tos_text=EU_CLEAN_TOS)  # T17
    run(user_name="Grace", tool_name="untrusted_ai_plugin", data_sensitivity=DataSensitivity.INTERNAL,
        deployment_type=DeploymentType.DEDICATED_CLOUD, tos_text=EU_CLEAN_TOS)  # T31
    run(tool_name="Enterprise Code Assistant", tos_text=None,
        deployment_type=DeploymentType.DEDICATED_CLOUD, has_signed_dpa=True)  # T05 + T25
    run(tos_text="Zero data retention. No model training. " + "x" * 70_000)  # T10 + T25
    run(deployment_type=DeploymentType.DEDICATED_CLOUD, tos_text="Hosted in Germany.")  # T12

    pii = run(user_name="Dr. Alon", user_role="data_scientist", tool_name="Enterprise-Clinical-Predictor",
              data_sensitivity=DataSensitivity.RESTRICTED_PII, deployment_type=DeploymentType.DEDICATED_CLOUD,
              has_signed_dpa=True, tos_text=EU_CLEAN_TOS)                   # T20
    seen.update(codes(sm.officer_decide(pii.request_id, OfficerDecisionInput(officer_name="Ronit", action="APPROVE"))))  # T22

    unknown = run(tool_name="SomeTool", tos_text=None, deployment_type=DeploymentType.DEDICATED_CLOUD)  # T05 + T26
    sm.officer_decide(unknown.request_id, OfficerDecisionInput(officer_name="Amit", action="REQUEST_INFO"))  # T24
    d = sm.clarify(unknown.request_id, ClarificationInput(tos_text=EU_CLEAN_TOS, has_signed_dpa=True))       # T21
    seen.update(codes(sm.officer_decide(d.request_id, OfficerDecisionInput(officer_name="Amit", action="REJECT"))))  # T23

    vague = run(intended_use="general")                                      # T19
    seen.update(codes(vague))

    assert seen == {t.code for t in TRANSITIONS}
