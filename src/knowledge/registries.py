"""
Authoritative organizational registries (Anti-Spoofing ground truth).

The employee form is a set of *claims*. These registries hold the *facts* that override them:
  * EmployeeDirectory  - role per employee (stand-in for Active Directory / Okta).
  * ContractRegistry   - vendors with a countersigned DPA on file (stand-in for the legal CLM).
  * VendorRegistry     - cached, legally reviewed ToS per vendor, used as the T25 recovery fallback.

In production each is a read-only connector; here they are small in-memory demo datasets.
"""
import re
from typing import Dict, Optional


def normalize_tool_name(name: str) -> str:
    return re.sub(r"[\s_]+", "-", (name or "").strip().lower())


def _normalize_person(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


class EmployeeDirectory:
    def __init__(self, employees: Optional[Dict[str, str]] = None):
        seed = employees if employees is not None else {
            # Demo portal personas
            "דן מזרחי": "developer",
            "מיכל רונן": "marketing",
            "יואב ברק": "developer",
            'ד"ר אלון לוי': "data_scientist",
            "נועה אדלר": "product_manager",
            "רונית כהן": "dpo",
            "עמית שלו": "ciso",
            # English aliases used by the automated tests
            "dan": "developer",
            "michal": "marketing",
            "dr. alon": "data_scientist",
            "grace": "developer",
            "ronit": "dpo",
            "amit": "ciso",
        }
        self._roles = {_normalize_person(k): v for k, v in seed.items()}

    def role_of(self, user_name: str) -> Optional[str]:
        return self._roles.get(_normalize_person(user_name))


class ContractRegistry:
    def __init__(self, vendors_with_dpa: Optional[set] = None):
        seed = vendors_with_dpa if vendors_with_dpa is not None else {
            "enterprise-clinical-predictor",
            "enterprise-code-assistant",
            "enterprise-analytics",
        }
        self._dpa = {normalize_tool_name(v) for v in seed}

    def has_dpa_on_file(self, tool_name: str) -> bool:
        return normalize_tool_name(tool_name) in self._dpa


class VendorRegistry:
    def __init__(self, tos_by_vendor: Optional[Dict[str, str]] = None):
        seed = tos_by_vendor if tos_by_vendor is not None else {
            "enterprise-code-assistant": (
                "Enterprise plan. Hosted in the European Union (eu-west). "
                "We do not train our models on customer data. Data retained for 0 days. "
                "Encryption at rest (AES-256) and in transit (TLS 1.3)."
            ),
            "shadow-transcription-service": (
                "Free transcription. We may use your recordings to train our models. "
                "Data retained for 365 days. Processing in China."
            ),
        }
        self._tos = {normalize_tool_name(k): v for k, v in seed.items()}

    def cached_tos(self, tool_name: str) -> Optional[str]:
        return self._tos.get(normalize_tool_name(tool_name))
