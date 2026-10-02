"""
Open Policy Agent (OPA) / Policy-as-Code Evaluation Engine.

Prototype note: the rules below are evaluated in Python with the same semantics as the Rego
policy in policies/compliance.rego. In production the machine would call an OPA sidecar
(POST /v1/data/compliance/deny) or evaluate the Rego compiled to WebAssembly.

OPA only fires on facts that are *known*. Unknown facts are not violations; they lower the
C_score and are escalated to a human at S6 (fail-closed without false rejections).
"""
from typing import Dict, Any, Tuple, List
from ..state_machine.states import RequestDocument, DataSensitivity, DeploymentType

# Adequate destinations for RESTRICTED_PII. The EU-US Privacy Shield was invalidated in 2020
# (CJEU, Schrems II); US transfers now rely on the EU-US Data Privacy Framework (2023).
APPROVED_PII_RESIDENCY = {"EU", "IL", "US_DPF", "LOCAL"}


class OPAEngine:

    def __init__(self):
        self.prohibited_training_levels = {
            DataSensitivity.INTERNAL,
            DataSensitivity.CONFIDENTIAL,
            DataSensitivity.RESTRICTED_PII,
        }

    def evaluate(self, request: RequestDocument, facts: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Returns (allowed, violations)."""
        violations = []
        vendor_trains = facts.get("vendor_trains_on_data")
        data_residency = facts.get("data_residency")
        encryption_at_rest = facts.get("encryption_at_rest")

        # Rule 101: no vendor model training on non-public data
        if vendor_trains is True and request.data_sensitivity in self.prohibited_training_levels:
            violations.append(
                f"OPA_VIOLATION [Rule 101 - Model Training]: Vendor terms allow model training on user data, "
                f"which violates policy for sensitivity level '{request.data_sensitivity.value}'."
            )

        # Rule 204: RESTRICTED_PII processed by a vendor requires a DPA
        if (request.data_sensitivity == DataSensitivity.RESTRICTED_PII and request.uses_external_processor
                and not request.has_signed_dpa):
            violations.append(
                "OPA_VIOLATION [Rule 204 - GDPR Art. 28 / DPA]: Processing RESTRICTED_PII by an external vendor "
                "requires a countersigned Data Processing Agreement (DPA)."
            )

        # Rule 305: public SaaS with non-public data must encrypt at rest
        if (request.deployment_type == DeploymentType.PUBLIC_SAAS and request.data_sensitivity != DataSensitivity.PUBLIC
                and encryption_at_rest is False):
            violations.append(
                "OPA_VIOLATION [Rule 305 - Encryption]: Public SaaS processing non-public data "
                "must guarantee encryption at rest and in transit."
            )

        # Rule 402: data residency for RESTRICTED_PII
        if (request.data_sensitivity == DataSensitivity.RESTRICTED_PII and data_residency is not None
                and data_residency not in APPROVED_PII_RESIDENCY):
            violations.append(
                f"OPA_VIOLATION [Rule 402 - Data Sovereignty]: Data residency '{data_residency}' is not an adequate "
                f"destination for RESTRICTED_PII (allowed: {sorted(APPROVED_PII_RESIDENCY)})."
            )

        return len(violations) == 0, violations
