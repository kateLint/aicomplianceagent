# OPA policy: hard rules evaluated at S4 (Deterministic_Rule_Checking).
# Same semantics as src/reasoning/opa_engine.py. Unknown facts (null) never fire a rule;
# they lower the C_score and are escalated at S6 instead.
#
# Query: POST /v1/data/compliance/deny  with input = {request, facts}
package compliance

import rego.v1

non_public := {"INTERNAL", "CONFIDENTIAL", "RESTRICTED_PII"}

# EU-US Privacy Shield was invalidated in 2020 (Schrems II); US transfers use the Data Privacy Framework.
adequate_pii_residency := {"EU", "IL", "US_DPF", "LOCAL"}

external if input.request.deployment_type != "ON_PREMISES"

deny contains "Rule 101 - Model Training" if {
	input.facts.vendor_trains_on_data == true
	input.request.data_sensitivity in non_public
}

deny contains "Rule 204 - GDPR Art. 28 / DPA" if {
	input.request.data_sensitivity == "RESTRICTED_PII"
	external
	not input.request.has_signed_dpa
}

deny contains "Rule 305 - Encryption" if {
	input.request.deployment_type == "PUBLIC_SAAS"
	input.request.data_sensitivity != "PUBLIC"
	input.facts.encryption_at_rest == false
}

deny contains "Rule 402 - Data Sovereignty" if {
	input.request.data_sensitivity == "RESTRICTED_PII"
	input.facts.data_residency != null
	not input.facts.data_residency in adequate_pii_residency
}

allow if count(deny) == 0
