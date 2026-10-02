"""
Explicit 18 States, Events, and 3 architectural layers for the AI compliance workflow.
Extended Finite State Machine (EFSM) with Pydantic validation.
"""
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class State(str, Enum):
    S0_IDLE = "S0: Idle"
    S1_REQUEST_INTAKE = "S1: Request_Intake"
    S2_INGESTING_DOCS = "S2: Ingesting_Docs"
    S3_POLICY_KNOWLEDGE_RETRIEVAL = "S3: Policy_Knowledge_Retrieval"
    S4_DETERMINISTIC_RULE_CHECKING = "S4: Deterministic_Rule_Checking"
    S5_LLM_NEURO_EVALUATION = "S5: LLM_Neuro_Evaluation"
    S6_EVALUATING_UNCERTAINTY = "S6: Evaluating_Uncertainty"
    S7_Z3_CONSTRAINT_SOLVING = "S7: Z3_Constraint_Solving"
    S8_PROLOG_DATALOG_INFERENCE = "S8: Prolog_Datalog_Inference"
    S9_TEMPORAL_LOGIC_VERIFICATION = "S9: Temporal_Logic_Verification"
    S10_DECISION_ROUTING = "S10: Decision_Routing"
    S11_AWAITING_HUMAN_CLARIFICATION = "S11: Awaiting_Human_Clarification"
    S12_AWAITING_COMPLIANCE_REVIEW = "S12: Awaiting_Compliance_Review"
    S13_ERROR_RECOVERY = "S13: Error_Recovery"
    S14_APPROVED = "S14: Approved"
    S15_REJECTED = "S15: Rejected"
    S16_AUDIT_LOGGING = "S16: Audit_Logging"
    S17_COMPLETED = "S17: Completed"


# States in which a request is parked until an external actor (employee / officer) responds.
WAITING_STATES = {State.S11_AWAITING_HUMAN_CLARIFICATION, State.S12_AWAITING_COMPLIANCE_REVIEW}


class LayerType(str, Enum):
    REQUEST_UNDERSTANDING = "Layer 1: Request Understanding"
    CONTROLLED_DECISION = "Layer 2: Controlled Decision"
    GOVERNANCE_CONTROL = "Layer 3: Governance & Control"


class Event(str, Enum):
    USER_SUBMITS_REQUEST = "USER_SUBMITS_REQUEST"
    FORM_VALIDATED = "FORM_VALIDATED"
    INTAKE_FAILED = "INTAKE_FAILED"
    SCRAPING_COMPLETED = "SCRAPING_COMPLETED"
    SCRAPING_FAILED_WITH_TIMEOUT = "SCRAPING_FAILED_WITH_TIMEOUT"
    CONTEXT_READY = "CONTEXT_READY"
    OPA_ALLOW = "OPA_ALLOW"
    OPA_DENY = "OPA_DENY"
    LLM_EVALUATION_COMPLETED = "LLM_EVALUATION_COMPLETED"
    LLM_TIMEOUT_OR_PARSE_ERROR = "LLM_TIMEOUT_OR_PARSE_ERROR"
    HIGH_CONFIDENCE_DETECTED = "HIGH_CONFIDENCE_DETECTED"
    UNCERTAINTY_ESCALATE = "UNCERTAINTY_ESCALATE"
    Z3_SOLVER_SAT = "Z3_SOLVER_SAT"
    Z3_SOLVER_UNSAT = "Z3_SOLVER_UNSAT"
    INFERENCE_COMPLETED = "INFERENCE_COMPLETED"
    VERIFICATION_SUCCESS = "VERIFICATION_SUCCESS"
    LTL_VIOLATION_DETECTED = "LTL_VIOLATION_DETECTED"
    ROUTE_TO_APPROVED = "ROUTE_TO_APPROVED"
    ROUTE_TO_NEED_INFO = "ROUTE_TO_NEED_INFO"
    ROUTE_TO_ESCALATION = "ROUTE_TO_ESCALATION"
    ROUTE_TO_REJECTED = "ROUTE_TO_REJECTED"
    USER_SUBMITS_ADDITIONAL_INFO = "USER_SUBMITS_ADDITIONAL_INFO"
    OFFICER_APPROVES = "OFFICER_APPROVES"
    OFFICER_REJECTS = "OFFICER_REJECTS"
    OFFICER_REQUESTS_MORE_INFO = "OFFICER_REQUESTS_MORE_INFO"
    RECOVERY_SUCCESSFUL = "RECOVERY_SUCCESSFUL"
    RECOVERY_FAILED_ESCALATE = "RECOVERY_FAILED_ESCALATE"
    REGISTRATION_SUCCESS = "REGISTRATION_SUCCESS"
    REJECTION_COMPLETE = "REJECTION_COMPLETE"
    AUDIT_LOGGED = "AUDIT_LOGGED"
    NOTIFICATION_SENT = "NOTIFICATION_SENT"


class DataSensitivity(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED_PII = "RESTRICTED_PII"


SENSITIVE_LEVELS = {DataSensitivity.CONFIDENTIAL, DataSensitivity.RESTRICTED_PII}


class DeploymentType(str, Enum):
    PUBLIC_SAAS = "PUBLIC_SAAS"
    DEDICATED_CLOUD = "DEDICATED_CLOUD"
    ON_PREMISES = "ON_PREMISES"


class RequestDocument(BaseModel):
    request_id: str = Field(..., max_length=64, description="Unique ID of the request")
    user_name: str = Field(..., max_length=120, description="Full name of employee")
    user_role: str = Field(..., max_length=60, description="Declared role: developer, product_manager, data_scientist, ciso, dpo, marketing")
    department: str = Field(..., max_length=120, description="Department: R&D, Marketing, Finance, Legal, HR")
    tool_name: str = Field(..., max_length=200, description="Name of the AI tool or model")
    tool_url: Optional[str] = Field(None, max_length=500, description="URL of the tool or vendor terms")
    deployment_type: DeploymentType = Field(DeploymentType.PUBLIC_SAAS, description="Hosting deployment model")
    data_sensitivity: DataSensitivity = Field(..., description="Sensitivity of data to be processed")
    intended_use: str = Field(..., max_length=2000, description="Explanation of business objective and use-case")
    tos_text: Optional[str] = Field(None, max_length=200_000, description="Terms of service snippet or uploaded vendor policy")
    has_signed_dpa: bool = Field(False, description="Employee claims a Data Processing Agreement is signed (verified against the contract registry)")

    @property
    def is_sensitive(self) -> bool:
        return self.data_sensitivity in SENSITIVE_LEVELS

    @property
    def uses_external_processor(self) -> bool:
        """Data leaves the company perimeter (a vendor processes it)."""
        return self.deployment_type != DeploymentType.ON_PREMISES


class DecisionStatus(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    NEED_INFO = "NEED_INFO"


class GateStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ESCALATE = "ESCALATE"
    SKIPPED = "SKIPPED"      # not reached because an earlier gate ended the run
    PENDING = "PENDING"      # not reached yet; the request is waiting for a human


class OfficerAction(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_INFO = "REQUEST_INFO"


class OfficerDecisionInput(BaseModel):
    officer_name: str = Field(..., min_length=1, max_length=120)
    action: OfficerAction
    notes: str = Field("", max_length=2000)


class ClarificationInput(BaseModel):
    intended_use: Optional[str] = Field(None, max_length=2000)
    tos_text: Optional[str] = Field(None, max_length=200_000)
    has_signed_dpa: Optional[bool] = None
    data_sensitivity: Optional[DataSensitivity] = None
    deployment_type: Optional[DeploymentType] = None


class ComplianceDecision(BaseModel):
    request_id: str
    status: DecisionStatus
    final_state: str
    c_score: Optional[float] = Field(None, description="Min claim confidence from the Neuro stage; null when that stage was not reached")
    explanation: str
    blocking_reasons: List[str] = []
    satisfied_checks: List[str] = []
    gates: Dict[str, GateStatus] = {}
    claims: Dict[str, Dict[str, Any]] = {}
    remediation: List[str] = []
    identity: Dict[str, Any] = {}
    ltl_report: List[Dict[str, str]] = []
    pending_action: Optional[str] = None
    trace: List[Dict[str, Any]] = []
    active_layers: List[str] = []
    audit_hash: str
    timestamp: str
