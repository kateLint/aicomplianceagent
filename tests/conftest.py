import itertools

import pytest

from src.state_machine.machine import ComplianceStateMachine
from src.state_machine.states import RequestDocument, DataSensitivity, DeploymentType

_ids = itertools.count(1)

EU_CLEAN_TOS = ("Hosted in Germany (EU). We do not train our models on customer data. "
                "Data retained for 14 days. Encryption at rest (AES-256).")
LOCAL_TOS = "All processing is on-premises. Zero data retention. Model training is strictly prohibited."


def make_request(**overrides) -> RequestDocument:
    base = dict(
        request_id=f"REQ-{next(_ids)}",
        user_name="Dan",
        user_role="developer",
        department="R&D",
        tool_name="Secure-Local-Code-LLM",
        deployment_type=DeploymentType.ON_PREMISES,
        data_sensitivity=DataSensitivity.CONFIDENTIAL,
        intended_use="Code review assistance for internal repositories",
        tos_text=LOCAL_TOS,
        has_signed_dpa=False,
    )
    base.update(overrides)
    return RequestDocument(**base)


def codes(decision):
    return [t["code"] for t in decision.trace]


@pytest.fixture
def sm():
    return ComplianceStateMachine()
