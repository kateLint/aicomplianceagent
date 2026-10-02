"""
Prolog-style Symbolic Inference Engine for RBAC and Separation of Duties (SoD).

Prototype note: the Horn clauses (see policies/rbac.pl) are evaluated in Python with the same
semantics; production would query SWI-Prolog (e.g. via pyswip / Pengines).

    allowed_to_request(Role, S)  :- clearance(Role, Max), level(S) =< level(Max).
    requires_dpo(Req)            :- sensitivity(Req, restricted_pii).
    can_decide(Officer, Req)     :- approver(Officer), \\+ same_person(Officer, requester(Req)),
                                    ( requires_dpo(Req) -> role(Officer, dpo) ; true ).
"""
from typing import Tuple, List, Optional
from ..state_machine.states import RequestDocument, DataSensitivity

LEVEL = {
    DataSensitivity.PUBLIC: 0,
    DataSensitivity.INTERNAL: 1,
    DataSensitivity.CONFIDENTIAL: 2,
    DataSensitivity.RESTRICTED_PII: 3,
}


def _same_person(a: str, b: str) -> bool:
    return " ".join(a.lower().split()) == " ".join(b.lower().split())


class PrologRBACEngine:

    def __init__(self):
        # clearance(Role, MaxSensitivity)
        self.clearance = {
            "marketing": DataSensitivity.INTERNAL,
            "developer": DataSensitivity.CONFIDENTIAL,
            "product_manager": DataSensitivity.CONFIDENTIAL,
            "data_scientist": DataSensitivity.RESTRICTED_PII,
            "ciso": DataSensitivity.RESTRICTED_PII,
            "dpo": DataSensitivity.RESTRICTED_PII,
        }
        self.approver_roles = {"ciso", "dpo"}

    def evaluate(self, request: RequestDocument, effective_role: Optional[str] = None) -> Tuple[bool, bool, List[str]]:
        """
        effective_role: role from the employee directory when known (overrides the declared role).
        Returns (allowed, requires_dpo_escalation, explanations).
        """
        role = (effective_role or request.user_role).lower().strip()
        if role not in self.clearance:
            return False, False, [f"PROLOG_INFERENCE [RBAC]: Role '{role}' is not recognized in the organizational ontology."]

        max_level = self.clearance[role]
        if LEVEL[request.data_sensitivity] > LEVEL[max_level]:
            return False, False, [
                f"PROLOG_INFERENCE [RBAC Violation]: Role '{role}' lacks clearance for "
                f"'{request.data_sensitivity.value}' data (max: {max_level.value})."
            ]

        explanations = [f"PROLOG_INFERENCE [RBAC OK]: Role '{role}' is cleared for '{request.data_sensitivity.value}'."]
        requires_dpo = request.data_sensitivity == DataSensitivity.RESTRICTED_PII
        if requires_dpo:
            explanations.append(
                "PROLOG_INFERENCE [DPO Escalation]: RESTRICTED_PII requires sign-off by an independent "
                "Data Protection Officer (DPO) under Separation of Duties."
            )
        return True, requires_dpo, explanations

    def can_decide(self, officer_name: str, officer_role: Optional[str], request: RequestDocument) -> Tuple[bool, str]:
        """SoD check for an officer decision (T22/T23/T24)."""
        if officer_role is None:
            return False, f"PROLOG_SOD: '{officer_name}' is not in the employee directory; decision refused."
        if officer_role not in self.approver_roles:
            return False, f"PROLOG_SOD: role '{officer_role}' is not an approver role {sorted(self.approver_roles)}."
        if _same_person(officer_name, request.user_name):
            return False, "PROLOG_SOD [Separation of Duties]: the requester cannot decide on their own request."
        if request.data_sensitivity == DataSensitivity.RESTRICTED_PII and officer_role != "dpo":
            return False, "PROLOG_SOD: RESTRICTED_PII decisions require the DPO role."
        return True, f"PROLOG_SOD OK: {officer_role} '{officer_name}' is independent of the requester."
