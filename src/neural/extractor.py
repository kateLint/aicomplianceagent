"""
Neural Extraction Layer (Neuro-Symbolic Bridge).

Turns unstructured vendor ToS text into *claims*: each claim has a value, a confidence and
the evidence sentence it came from. It never makes approval decisions.

Prototype note: the extraction is rule-based (regex) so the demo runs offline and deterministically.
In production this stage is an LLM with structured output (e.g. a private-endpoint Claude Sonnet 5
or a local open-weights model), and the confidence comes from the model/verifier. The contract
stays the same: claims + confidence in, symbolic facts out.

Design rules:
  * Fail-closed: a claim that is not stated is UNKNOWN (value None, low confidence), never a
    permissive default.
  * Heuristics may only push a value toward risk (e.g. "free" tools are assumed to train),
    never toward approval.
  * Text that tries to instruct the model (prompt injection) is flagged and forces escalation.
"""
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..state_machine.states import DeploymentType

CONF_EXPLICIT = 0.95
CONF_HEURISTIC = 0.70
CONF_UNKNOWN = 0.40
CONF_INJECTION = 0.20
MAX_CONTEXT_CHARS = 60_000


class ExtractionError(Exception):
    """Raised when the model call fails (timeout, context overflow, unparsable output)."""


@dataclass
class Extraction:
    facts: Dict[str, Any]
    claims: Dict[str, Dict[str, Any]]
    required: List[str]
    c_score: float
    injection_suspected: bool = False
    injection_evidence: List[str] = field(default_factory=list)

    def unknown_claims(self) -> List[str]:
        return [c for c in self.required if self.claims[c]["confidence"] < 0.85]


NEGATIVE_TRAINING = [
    r"\b(do(es)?\s*n[o']t|will\s+not|won't|never|shall\s+not)\s+(use\s+[^.]{0,50}?\s+to\s+)?train",
    r"\bno\s+(model\s+)?training\b",
    r"\btraining\s+(is\s+)?(strictly\s+)?(prohibited|disabled|forbidden|excluded|off)\b",
    r"\bnot\s+(be\s+)?used\s+(for|to)\s+(model\s+)?train",
    r"\bopt(ed)?[\s-]out\s+of\s+(model\s+)?training\b",
]
POSITIVE_TRAINING = [
    r"\btrain(s|ing)?\b[^.]{0,60}\b(models?|ai|algorithms?)\b",
    r"\bimprove\s+our\s+(services|models)\s+using\s+your\b",
    r"\bmachine\s+learning\s+development\b",
    r"\bmodel\s+improvement\b",
]
ZERO_RETENTION = r"\b(zero|no)\s+(data\s+)?retention\b|\bnot\s+retain(ed)?\b|\bretention\s*:\s*none\b"
RETENTION_DAYS = [
    r"\bretain(?:ed|s)?\s+(?:[\w-]+\s+){0,4}?(?:for\s+)?(\d+)\s+days?\b",
    r"\b(\d+)[\s-]*days?\s+(?:of\s+)?retention\b",
    r"\b(\d+)\s+retention\s+days\b",
    r"\bretention(?:\s+period)?(?:\s+of|\s*:)?\s+(\d+)\s+days?\b",
]
NEGATIVE_ENCRYPTION = r"\b(unencrypted|no\s+encryption|not\s+encrypted|without\s+encryption)\b"
POSITIVE_ENCRYPTION = r"\b(encrypt(ed|ion)|aes-?256|tls\s*1\.[23])\b"
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+|any\s+)?(previous|prior|above)\s+instructions",
    r"disregard\s+[^.]{0,30}instructions",
    r"\byou\s+are\s+now\b",
    r"\bsystem\s+prompt\b",
    r"\bapprove\s+this\s+(request|tool|vendor)\b",
    r"<\s*/?\s*system\s*>",
]
SUBPROCESSOR_HINT = r"sub-?processors?|third[\s-]party|subcontractor"

# (pattern, jurisdiction code); order matters: specific before generic.
JURISDICTIONS: List[Tuple[str, str]] = [
    (r"\bon[\s-]?prem(ises)?\b|\bcompany\s+servers\b|\blocal\s+deployment\b", "LOCAL"),
    (r"\bdata\s+privacy\s+framework\b|\bdpf\b", "US_DPF"),
    (r"\bgermany\b|\beuropean\s+union\b|\beu-west\b|\bfrankfurt\b|\bireland\b|\bhosted\s+in\s+(the\s+)?eu\b|\(eu\)", "EU"),
    (r"\bisrael\b|\bil-central\b", "IL"),
    (r"\bchina\b", "CN"),
    (r"\brussia\b", "RU"),
    (r"\biran\b", "IR"),
    (r"\bnorth\s+korea\b", "KP"),
    (r"\boffshore\b|jurisdiction\s*:\s*untrusted", "UNTRUSTED_OFFSHORE"),
    (r"\bunited\s+states\b|\bus-east\b|\bus-west\b", "US"),
]


def _find(patterns, text) -> Optional[re.Match]:
    for p in patterns if isinstance(patterns, list) else [patterns]:
        m = re.search(p, text)
        if m:
            return m
    return None


def _sentence_of(text: str, m: re.Match) -> str:
    start = text.rfind(".", 0, m.start()) + 1
    end = text.find(".", m.end())
    return text[start:end if end != -1 else len(text)].strip()[:200]


class NeuralToSExtractor:

    def check_context(self, tos_text: Optional[str], chunked: bool = False) -> None:
        """S5 model call guard: a single-pass call fails when the document exceeds the context window.
        chunked=True is the T25 recovery path (map-reduce over chunks), which has no such limit."""
        n = len(tos_text or "")
        if n > MAX_CONTEXT_CHARS and not chunked:
            raise ExtractionError(f"ToS length {n} exceeds the model context window ({MAX_CONTEXT_CHARS} chars)")

    def extract(self, tool_name: str, tos_text: Optional[str], deployment: DeploymentType) -> Extraction:
        raw = tos_text or ""
        text = raw.lower()
        tool = tool_name.lower()
        claims: Dict[str, Dict[str, Any]] = {}

        def claim(name, value, conf, evidence=""):
            claims[name] = {"value": value, "confidence": conf, "evidence": evidence}

        # 1. Model training on customer data
        neg = _find(NEGATIVE_TRAINING, text)
        pos = _find(POSITIVE_TRAINING, text)
        if neg:
            claim("vendor_trains_on_data", False, CONF_EXPLICIT, _sentence_of(raw, neg))
        elif pos:
            claim("vendor_trains_on_data", True, CONF_EXPLICIT, _sentence_of(raw, pos))
        elif any(k in tool for k in ("free", "public", "shadow")):
            claim("vendor_trains_on_data", True, CONF_HEURISTIC, "heuristic: free/public tool (risk-side assumption)")
        else:
            claim("vendor_trains_on_data", None, CONF_UNKNOWN, "not stated")

        # 2. Retention period
        zero = re.search(ZERO_RETENTION, text)
        days = _find(RETENTION_DAYS, text)
        if zero:
            claim("retention_days", 0, CONF_EXPLICIT, _sentence_of(raw, zero))
        elif days:
            n = next(g for g in days.groups() if g is not None)
            claim("retention_days", int(n), CONF_EXPLICIT, _sentence_of(raw, days))
        elif deployment == DeploymentType.ON_PREMISES:
            claim("retention_days", 0, CONF_EXPLICIT, "structural: on-premises, vendor retains nothing")
        else:
            claim("retention_days", None, CONF_UNKNOWN, "not stated")

        # 3. Residency and sub-processors (sentence level, so a sub-processor's country
        #    does not overwrite the primary hosting location)
        residency, residency_ev = None, ""
        sub_processors: List[Tuple[str, str]] = []
        for sentence in re.split(r"(?<=[.;\n])\s+", raw):
            s = sentence.lower()
            codes = [code for pat, code in JURISDICTIONS if re.search(pat, s)]
            if not codes:
                continue
            if re.search(SUBPROCESSOR_HINT, s):
                for code in codes:
                    sub_processors.append((f"Subprocessor_{code}", code))
            elif residency is None:
                residency, residency_ev = codes[0], sentence.strip()[:200]
        if residency is None and deployment == DeploymentType.ON_PREMISES:
            residency, residency_ev = "LOCAL", "structural: on-premises deployment"
        claim("data_residency", residency, CONF_EXPLICIT if residency else CONF_UNKNOWN, residency_ev or "not stated")

        # 4. Encryption at rest (only material when data leaves the perimeter)
        enc_neg = re.search(NEGATIVE_ENCRYPTION, text)
        enc_pos = re.search(POSITIVE_ENCRYPTION, text)
        if enc_neg:
            claim("encryption_at_rest", False, CONF_EXPLICIT, _sentence_of(raw, enc_neg))
        elif enc_pos:
            claim("encryption_at_rest", True, CONF_EXPLICIT, _sentence_of(raw, enc_pos))
        elif any(k in tool for k in ("free", "public", "shadow")):
            claim("encryption_at_rest", False, CONF_HEURISTIC, "heuristic: free/public tool (risk-side assumption)")
        else:
            claim("encryption_at_rest", None, CONF_UNKNOWN, "not stated")

        # 5. Prompt-injection screening of the vendor document itself
        injection_evidence = list(dict.fromkeys(
            _sentence_of(raw, m) for p in INJECTION_PATTERNS for m in [re.search(p, text)] if m))

        required = ["vendor_trains_on_data", "retention_days", "data_residency"]
        if deployment != DeploymentType.ON_PREMISES:
            required.append("encryption_at_rest")
        c_score = min(claims[c]["confidence"] for c in required)
        if injection_evidence:
            c_score = min(c_score, CONF_INJECTION)

        facts = {name: c["value"] for name, c in claims.items()}
        facts["sub_processors"] = sub_processors
        return Extraction(facts=facts, claims=claims, required=required, c_score=round(c_score, 2),
                          injection_suspected=bool(injection_evidence), injection_evidence=injection_evidence)
