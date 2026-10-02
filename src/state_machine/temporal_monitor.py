"""
Temporal Logic (LTL) Runtime Monitor over finite traces.

A trace is a list of {"state": <state reached>, "event": <event that caused it>}.
Past-time operators (P = "at some earlier point") are evaluated inside the current
intake cycle, i.e. since the most recent entry into S1 (a clarification loop T21
restarts the cycle, so checks from an older cycle do not count).

Safety invariants (a violation on any prefix is final):
  LTL_1  G(Approved -> P(Policy_Checked))
  LTL_2  G(Approved -> P(Z3_SAT | Officer_Approved))
  LTL_3  G(Violation_Event -> Rejected)            (the violation event must land in S15)
  LTL_4  G(Sensitive & External -> (!Approved U DPA_Signed))
  LTL_5  G(Completed -> P(Audit_Logged))
Liveness (3-valued on a finite prefix: HOLDS / PENDING, never finally violated):
  LTL_6  G(Escalated -> F(Officer_Decision))

The monitor is used twice by the machine:
  * at S9, on the executed prefix + the route the orchestrator is about to take, so a
    bad route is refused before it happens (T17);
  * on every transition into S14, as a last line of defence that cannot be skipped.
"""
from typing import List, Dict, Any, Tuple

from .states import State, Event

HOLDS, VIOLATED, PENDING = "HOLDS", "VIOLATED", "PENDING"

VIOLATION_EVENTS = {
    Event.OPA_DENY.value, Event.Z3_SOLVER_UNSAT.value,
    Event.LTL_VIOLATION_DETECTED.value, Event.ROUTE_TO_REJECTED.value,
}
OFFICER_DECISIONS = {
    Event.OFFICER_APPROVES.value, Event.OFFICER_REJECTS.value, Event.OFFICER_REQUESTS_MORE_INFO.value,
}


def _v(x) -> str:
    return x.value if hasattr(x, "value") else str(x)


class TemporalTraceVerifier:

    RULES = [
        ("LTL_1", "G(Approved → P(Policy_Checked))", "safety",
         "אי אפשר להגיע לאישור בלי בדיקת OPA קודמת באותו מחזור."),
        ("LTL_2", "G(Approved → P(Z3_SAT ∨ Officer_Approved))", "safety",
         "אישור דורש הוכחת SAT ב-Z3, או חתימת קצין ציות."),
        ("LTL_3", "G(Violation → Rejected)", "safety",
         "אירוע הפרה חייב להוביל ישירות ל-S15."),
        ("LTL_4", "G(Sensitive ∧ External → ¬Approved U DPA_Signed)", "safety",
         "מידע רגיש שיוצא לספק לא יאושר עד שיש DPA חתום ומאומת."),
        ("LTL_5", "G(Completed → P(Audit_Logged))", "safety",
         "אין סיום בלי בלוק ביקורת."),
        ("LTL_6", "G(Escalated → F(Officer_Decision))", "liveness",
         "כל הסלמה תסתיים בהחלטת קצין (על עקבה סופית: PENDING עד שמתקבלת)."),
    ]

    def evaluate(self, trace: List[Dict[str, Any]], context: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        context keys: is_sensitive (bool), external (bool), dpa_claimed (bool), dpa_verified (bool)
        Returns one report row per rule: {id, formula, kind, status, detail}.
        """
        states = [_v(e["state"]) for e in trace]
        events = [_v(e.get("event", "")) for e in trace]
        results: Dict[str, Tuple[str, str]] = {r[0]: (HOLDS, "") for r in self.RULES}

        def cycle_start(i: int) -> int:
            for j in range(i, -1, -1):
                if states[j] == State.S1_REQUEST_INTAKE.value:
                    return j
            return 0

        for i, st in enumerate(states):
            ev = events[i]
            start = cycle_start(i)
            prefix_states = states[start:i]
            prefix_events = events[start:i + 1]

            if st == State.S14_APPROVED.value:
                if State.S4_DETERMINISTIC_RULE_CHECKING.value not in prefix_states:
                    results["LTL_1"] = (VIOLATED, f"step {i + 1}: Approved without S4 (OPA) in this cycle")
                if Event.Z3_SOLVER_SAT.value not in prefix_events and Event.OFFICER_APPROVES.value not in prefix_events:
                    results["LTL_2"] = (VIOLATED, f"step {i + 1}: Approved without Z3 SAT or officer sign-off")
                dpa_signed = context.get("dpa_claimed", False) and (
                    context.get("dpa_verified", False) or Event.OFFICER_APPROVES.value in prefix_events)
                if context.get("is_sensitive") and context.get("external") and not dpa_signed:
                    results["LTL_4"] = (VIOLATED, f"step {i + 1}: sensitive data to external vendor approved before DPA_Signed")

            if ev in VIOLATION_EVENTS and st != State.S15_REJECTED.value:
                results["LTL_3"] = (VIOLATED, f"step {i + 1}: {ev} led to {st} instead of S15")

            if st == State.S17_COMPLETED.value and State.S16_AUDIT_LOGGING.value not in states[start:i]:
                results["LTL_5"] = (VIOLATED, f"step {i + 1}: Completed without S16")

        # Liveness: every escalation must eventually be followed by an officer decision.
        for i, st in enumerate(states):
            if st == State.S12_AWAITING_COMPLIANCE_REVIEW.value and not any(e in OFFICER_DECISIONS for e in events[i + 1:]):
                results["LTL_6"] = (PENDING, f"step {i + 1}: escalation awaiting officer decision")

        return [
            {"id": rid, "formula": formula, "kind": kind, "status": results[rid][0],
             "detail": results[rid][1] or desc}
            for rid, formula, kind, desc in self.RULES
        ]

    def verify_trace(self, trace: List[Dict[str, Any]], context: Dict[str, Any]) -> Tuple[bool, List[Dict[str, str]]]:
        """True when no safety invariant is violated (PENDING liveness is not a violation)."""
        report = self.evaluate(trace, context)
        return all(r["status"] != VIOLATED for r in report), report

    @staticmethod
    def violations(report: List[Dict[str, str]]) -> List[str]:
        return [f"LTL_VIOLATION [{r['id']}] {r['formula']}: {r['detail']}" for r in report if r["status"] == VIOLATED]
