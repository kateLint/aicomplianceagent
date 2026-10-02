"""
Z3 SMT Solver for First-Order Formal Constraint Verification.

What Z3 adds on top of OPA (which only matches individual rules):
  1. Joint consistency: approval must satisfy *all* axioms together, including numeric ones
     (retention limit) and cross-cutting ones (sensitive data leaving the perimeter must be encrypted).
  2. UNSAT core: the minimal set of axioms + facts that makes approval impossible (explainability).
  3. Remediation: for each vendor/contract fact in the core, Z3 checks whether changing only that
     fact would make approval satisfiable, and reports the value it would need (counter-model).
  4. Policy sanity: check_policy_consistency() proves the axiom set is not vacuous (some compliant
     world exists), so the policy itself has no contradiction.

Every call uses its own z3.Context: Z3's shared default context is not thread-safe, and the API
server evaluates requests on a thread pool.
"""
from typing import Dict, Any, Tuple, List
try:
    import z3
    Z3_AVAILABLE = True
except ImportError:
    Z3_AVAILABLE = False

from ..state_machine.states import RequestDocument, DataSensitivity

MAX_RETENTION_DAYS_SENSITIVE = 30

# Facts that a vendor or the legal team can change; everything else is a property of the request.
REMEDIABLE_FACTS = {
    "FACT_HAS_DPA": ("has_dpa", "sign a DPA with the vendor"),
    "FACT_VENDOR_TRAINS": ("vendor_trains", "obtain a contractual no-training commitment"),
    "FACT_RETENTION_DAYS": ("data_retention_days", "negotiate retention of at most {v} days"),
    "FACT_ENCRYPTED": ("encrypted", "require encryption at rest"),
}


class Z3ConstraintVerifier:

    def __init__(self):
        self.z3_available = Z3_AVAILABLE

    # ---- model -------------------------------------------------------------
    def _vars(self, ctx):
        return {
            "approved": z3.Bool("approved", ctx),
            "is_confidential": z3.Bool("is_confidential", ctx),
            "is_pii": z3.Bool("is_pii", ctx),
            "external": z3.Bool("external", ctx),
            "vendor_trains": z3.Bool("vendor_trains", ctx),
            "has_dpa": z3.Bool("has_dpa", ctx),
            "encrypted": z3.Bool("encrypted", ctx),
            "data_retention_days": z3.Int("data_retention_days", ctx),
        }

    def _axioms(self, v) -> List[Tuple[Any, str]]:
        sensitive = z3.Or(v["is_confidential"], v["is_pii"])
        return [
            (z3.Implies(z3.And(v["approved"], sensitive), z3.Not(v["vendor_trains"])), "AXIOM_SENSITIVE_NO_TRAINING"),
            (z3.Implies(z3.And(v["approved"], v["is_pii"], v["external"]), v["has_dpa"]), "AXIOM_PII_REQUIRES_DPA"),
            (z3.Implies(z3.And(v["approved"], sensitive),
                        v["data_retention_days"] <= MAX_RETENTION_DAYS_SENSITIVE), "AXIOM_RETENTION_LIMIT"),
            (z3.Implies(z3.And(v["approved"], sensitive, v["external"]), v["encrypted"]), "AXIOM_EXTERNAL_ENCRYPTION"),
            (v["data_retention_days"] >= 0, "AXIOM_RETENTION_NON_NEGATIVE"),
        ]

    def _facts(self, v, request: RequestDocument, facts: Dict[str, Any]) -> List[Tuple[Any, str]]:
        out = [
            (v["is_confidential"] == (request.data_sensitivity == DataSensitivity.CONFIDENTIAL), "FACT_CONFIDENTIAL"),
            (v["is_pii"] == (request.data_sensitivity == DataSensitivity.RESTRICTED_PII), "FACT_PII"),
            (v["external"] == request.uses_external_processor, "FACT_EXTERNAL"),
            (v["has_dpa"] == bool(request.has_signed_dpa), "FACT_HAS_DPA"),
        ]
        # Only known facts become ground truth; an unknown fact stays a free variable.
        if facts.get("vendor_trains_on_data") is not None:
            out.append((v["vendor_trains"] == bool(facts["vendor_trains_on_data"]), "FACT_VENDOR_TRAINS"))
        if facts.get("retention_days") is not None:
            out.append((v["data_retention_days"] == int(facts["retention_days"]), "FACT_RETENTION_DAYS"))
        if facts.get("encryption_at_rest") is not None:
            out.append((v["encrypted"] == bool(facts["encryption_at_rest"]), "FACT_ENCRYPTED"))
        return out

    # ---- API ---------------------------------------------------------------
    def verify_constraints(self, request: RequestDocument, facts: Dict[str, Any]) -> Tuple[bool, List[str], List[str], List[str]]:
        """Returns (is_sat, explanations, unsat_core, remediation)."""
        if not self.z3_available:
            return self._fallback_solver(request, facts)

        ctx = z3.Context()
        v = self._vars(ctx)
        s = z3.Solver(ctx=ctx)
        s.set(unsat_core=True)
        axioms, ground = self._axioms(v), self._facts(v, request, facts)
        for f, name in axioms + ground:
            s.assert_and_track(f, name)
        s.assert_and_track(v["approved"] == True, "HYPOTHESIS_APPROVED")  # noqa: E712

        if s.check() == z3.sat:
            return True, ["Z3 SMT Solver: approval is consistent with all axioms (SAT)."], [], []

        core = sorted(str(c) for c in s.unsat_core())
        remediation = self._remediate(ctx, v, axioms, ground, core)
        explanations = [
            "Z3 SMT Solver detected a contradiction (UNSAT): the request cannot be approved without violating an axiom.",
            f"UNSAT Core: {', '.join(core)}",
        ]
        return False, explanations, core, remediation

    def _remediate(self, ctx, v, axioms, ground, core) -> List[str]:
        suggestions = []
        for label in core:
            if label not in REMEDIABLE_FACTS:
                continue
            var_name, template = REMEDIABLE_FACTS[label]
            s = z3.Solver(ctx=ctx)
            for f, name in axioms + ground:
                if name != label:
                    s.add(f)
            s.add(v["approved"] == True)  # noqa: E712
            if s.check() == z3.sat:
                if var_name == "data_retention_days":
                    s2 = z3.Optimize(ctx=ctx)
                    for f, name in axioms + ground:
                        if name != label:
                            s2.add(f)
                    s2.add(v["approved"] == True)  # noqa: E712
                    s2.maximize(v[var_name])
                    s2.check()
                    value = s2.model()[v[var_name]]
                    suggestions.append("Z3 remediation: " + template.format(v=value) + f" ({label} relaxed ⇒ SAT).")
                else:
                    suggestions.append(f"Z3 remediation: {template} ({label} relaxed ⇒ SAT).")
        return suggestions

    def check_policy_consistency(self) -> bool:
        """The axioms admit at least one approved, sensitive, external deployment (policy is not vacuous)."""
        if not self.z3_available:
            return True
        ctx = z3.Context()
        v = self._vars(ctx)
        s = z3.Solver(ctx=ctx)
        for f, _ in self._axioms(v):
            s.add(f)
        s.add(v["approved"], v["is_pii"], v["external"])
        return s.check() == z3.sat

    def _fallback_solver(self, request: RequestDocument, facts: Dict[str, Any]):
        """Pure-Python evaluation of the same axioms when the z3 bindings are missing."""
        violations, core, remediation = [], [], []
        sensitive = request.is_sensitive
        is_pii = request.data_sensitivity == DataSensitivity.RESTRICTED_PII
        external = request.uses_external_processor
        if sensitive and facts.get("vendor_trains_on_data") is True:
            violations.append("Conflict: sensitive data requires vendor_trains == False")
            core += ["AXIOM_SENSITIVE_NO_TRAINING", "FACT_VENDOR_TRAINS"]
            remediation.append("Z3 remediation: " + REMEDIABLE_FACTS["FACT_VENDOR_TRAINS"][1])
        if is_pii and external and not request.has_signed_dpa:
            violations.append("Conflict: PII with an external vendor requires has_dpa == True")
            core += ["AXIOM_PII_REQUIRES_DPA", "FACT_HAS_DPA"]
            remediation.append("Z3 remediation: " + REMEDIABLE_FACTS["FACT_HAS_DPA"][1])
        r = facts.get("retention_days")
        if sensitive and r is not None and r > MAX_RETENTION_DAYS_SENSITIVE:
            violations.append(f"Conflict: retention {r} days exceeds {MAX_RETENTION_DAYS_SENSITIVE}")
            core += ["AXIOM_RETENTION_LIMIT", "FACT_RETENTION_DAYS"]
            remediation.append("Z3 remediation: " + REMEDIABLE_FACTS["FACT_RETENTION_DAYS"][1].format(v=MAX_RETENTION_DAYS_SENSITIVE))
        if sensitive and external and facts.get("encryption_at_rest") is False:
            violations.append("Conflict: sensitive data leaving the perimeter must be encrypted")
            core += ["AXIOM_EXTERNAL_ENCRYPTION", "FACT_ENCRYPTED"]
            remediation.append("Z3 remediation: " + REMEDIABLE_FACTS["FACT_ENCRYPTED"][1])
        if violations:
            return False, violations, sorted(set(core)), remediation
        return True, ["SMT fallback solver: all axioms satisfied."], [], []
