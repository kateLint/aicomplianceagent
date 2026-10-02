"""
Single source of truth for the EFSM transition relation.

The machine refuses any (state, event) pair that is not listed here, the UI renders its
table and diagram from this list (GET /api/state-machine), and docs/TRANSITIONS_TABLE.md
is generated from it (scripts/generate_transitions_doc.py).
"""
from dataclasses import dataclass
from typing import Dict, List, Tuple

from .states import State, Event, LayerType

UNDERSTANDING = LayerType.REQUEST_UNDERSTANDING
DECISION = LayerType.CONTROLLED_DECISION
GOVERNANCE = LayerType.GOVERNANCE_CONTROL

# Compatibility aliases keep the transition table concise while mapping the former
# six responsibility groups into three honest architectural layers.
A1, A6 = GOVERNANCE, GOVERNANCE
A2, A3, A5 = UNDERSTANDING, UNDERSTANDING, UNDERSTANDING
A4 = DECISION


@dataclass(frozen=True)
class Transition:
    code: str
    source: State
    event: Event
    target: State
    layer: LayerType
    guard: str
    side_effect: str
    example: str


S = State
E = Event

TRANSITIONS: List[Transition] = [
    Transition("T01", S.S0_IDLE, E.USER_SUBMITS_REQUEST, S.S1_REQUEST_INTAKE, A1,
               "Payload_Present == TRUE",
               "פתיחת רשומת בקשה עם מזהה ייחודי ואימות זהות העובד מול ספריית העובדים",
               "עובד ממלא בקשה לשימוש בכלי AI לסיכום מסמכים"),
    Transition("T02", S.S1_REQUEST_INTAKE, E.FORM_VALIDATED, S.S2_INGESTING_DOCS, A2,
               "Mandatory_Fields_Present == TRUE && Sensitivity_Classified == TRUE",
               "הקלט תקין: העברת ה-ToS / URL לרכיב האיסוף",
               "מפתח מגיש בקשה עם כל שדות החובה וסיווג Confidential"),
    Transition("T03", S.S1_REQUEST_INTAKE, E.INTAKE_FAILED, S.S0_IDLE, A1,
               "Missing_Mandatory_Fields == TRUE",
               "החזרת רשימת השדות החסרים לעובד, רישום ביומן הביקורת ואיפוס ל-Idle",
               "עובד שלח טופס בלי שם כלי או מטרת שימוש"),
    Transition("T04", S.S2_INGESTING_DOCS, E.SCRAPING_COMPLETED, S.S3_POLICY_KNOWLEDGE_RETRIEVAL, A2,
               "Vendor_Document_Available == TRUE",
               "חילוץ טענות (claims) מתנאי השימוש, כל טענה עם מדד ודאות",
               "תנאי השימוש של הספק נקלטו ופוענחו"),
    Transition("T05", S.S2_INGESTING_DOCS, E.SCRAPING_FAILED_WITH_TIMEOUT, S.S13_ERROR_RECOVERY, A2,
               "Vendor_Document_Available == FALSE || Timeout_Exceeded == TRUE",
               "אין מסמך ספק לניתוח: מעבר למנגנון ההתאוששות (לא מאשרים על בסיס הנחות)",
               "העובד לא צירף ToS ואתר הספק חסום (Cloudflare / CAPTCHA)"),
    Transition("T06", S.S3_POLICY_KNOWLEDGE_RETRIEVAL, E.CONTEXT_READY, S.S4_DETERMINISTIC_RULE_CHECKING, A3,
               "Context_Built == TRUE",
               "שליפת סעיפי המדיניות והרגולציה הרלוונטיים (GDPR, EU AI Act) להקשר",
               "שליפת GDPR Art. 28 עבור כלי שמעבד נתוני לקוחות"),
    Transition("T07", S.S4_DETERMINISTIC_RULE_CHECKING, E.OPA_ALLOW, S.S5_LLM_NEURO_EVALUATION, A4,
               "OPA_Decision == ALLOW && Hard_Violations_Count == 0",
               "חוקי הברזל עברו על העובדות הידועות; מעבר לבדיקת ודאות",
               "כלי עם הצפנה, ללא אימון וריבונות מאושרת"),
    Transition("T08", S.S4_DETERMINISTIC_RULE_CHECKING, E.OPA_DENY, S.S15_REJECTED, A4,
               "OPA_Decision == DENY || Hard_Violations_Count > 0",
               "חסימה קשיחה: רישום החוק שהופר; שלבים יקרים יותר לא מורצים",
               "כלי חינמי שמאמן מודלים על הקלט (Rule 101)"),
    Transition("T09", S.S5_LLM_NEURO_EVALUATION, E.LLM_EVALUATION_COMPLETED, S.S6_EVALUATING_UNCERTAINTY, A5,
               "Neuro_Inference_Done == TRUE && Claims_Extracted_Count > 0",
               "שקלול ודאות הטענות: C_score = min(conf(claim))",
               "חולצו 4 טענות: אימון, שמירה, ריבונות, הצפנה"),
    Transition("T10", S.S5_LLM_NEURO_EVALUATION, E.LLM_TIMEOUT_OR_PARSE_ERROR, S.S13_ERROR_RECOVERY, A5,
               "API_Error == TRUE || Parse_Failed == TRUE",
               "שגיאת מודל (Rate Limit / חריגת הקשר / פלט שבור): מעבר להתאוששות",
               "מסמך ToS ארוך מחלון ההקשר של המודל"),
    Transition("T11", S.S6_EVALUATING_UNCERTAINTY, E.HIGH_CONFIDENCE_DETECTED, S.S7_Z3_CONSTRAINT_SOLVING, A5,
               "C_score >= 0.85 && Injection_Suspected == FALSE",
               "כל הטענות הנדרשות ודאיות: המרה לפסוקים לוגיים ושליחה ל-Z3",
               "ToS מפורש וחד-משמעי, C_score = 0.95"),
    Transition("T12", S.S6_EVALUATING_UNCERTAINTY, E.UNCERTAINTY_ESCALATE, S.S12_AWAITING_COMPLIANCE_REVIEW, A1,
               "C_score < 0.85 || Injection_Suspected == TRUE",
               "אי-ודאות או חשד ל-Prompt Injection: הסלמה לקצין ציות עם סימון הטענות החסרות",
               "ה-ToS לא מציין תקופת שמירת מידע (C_score = 0.50)"),
    Transition("T13", S.S7_Z3_CONSTRAINT_SOLVING, E.Z3_SOLVER_SAT, S.S8_PROLOG_DATALOG_INFERENCE, A4,
               "Z3_Result == SAT",
               "הוכח שאישור עקבי עם כל האקסיומות; מעבר להסקת הרשאות ושרשרת אספקה",
               "דרישות השמירה וההצפנה של הארגון לא סותרות את הצהרות הספק"),
    Transition("T14", S.S7_Z3_CONSTRAINT_SOLVING, E.Z3_SOLVER_UNSAT, S.S15_REJECTED, A4,
               "Z3_Result == UNSAT",
               "חילוץ UNSAT Core מינימלי והצעת תיקון (מה צריך להשתנות כדי לאשר)",
               "מידע סודי, והספק שומר מידע 90 יום (מעל המגבלה של 30)"),
    Transition("T15", S.S8_PROLOG_DATALOG_INFERENCE, E.INFERENCE_COMPLETED, S.S9_TEMPORAL_LOGIC_VERIFICATION, A4,
               "RBAC_Evaluated == TRUE && Lineage_Evaluated == TRUE",
               "RBAC ב-Prolog וסגור טרנזיטיבי של שרשרת האספקה ב-Datalog",
               "מפתח מורשה ל-Confidential; שרשרת תת-הספקים נקייה"),
    Transition("T16", S.S9_TEMPORAL_LOGIC_VERIFICATION, E.VERIFICATION_SUCCESS, S.S10_DECISION_ROUTING, A4,
               "LTL(prefix + planned_route) == VALID",
               "אינווריאנטי ה-LTL נבדקים על העקבה + המסלול המתוכנן, לפני שהוא מתבצע",
               "הוכח שהאישור המתוכנן קודם לו OPA, Z3 ו-DPA"),
    Transition("T17", S.S9_TEMPORAL_LOGIC_VERIFICATION, E.LTL_VIOLATION_DETECTED, S.S15_REJECTED, A4,
               "LTL(prefix + planned_route) == VIOLATED",
               "המסלול המתוכנן היה מפר אינווריאנט: חסימה לפני הביצוע",
               "מידע סודי לספק חיצוני ללא DPA חתום (LTL_4)"),
    Transition("T18", S.S10_DECISION_ROUTING, E.ROUTE_TO_APPROVED, S.S14_APPROVED, A1,
               "All_Gates_Passed && Identity_Verified && Risk_Level == LOW",
               "אישור אוטונומי והקצאת הרשאה לעובד",
               "כלי On-Premises שעבר את כל השערים"),
    Transition("T19", S.S10_DECISION_ROUTING, E.ROUTE_TO_NEED_INFO, S.S11_AWAITING_HUMAN_CLARIFICATION, A1,
               "Intended_Use_Vague == TRUE",
               "ניסוח שאלת הבהרה ממוקדת לעובד",
               "העובד כתב \"שימוש כללי\" בלי לפרט אילו נתונים יוזנו"),
    Transition("T20", S.S10_DECISION_ROUTING, E.ROUTE_TO_ESCALATION, S.S12_AWAITING_COMPLIANCE_REVIEW, A1,
               "Risk_Level == HIGH || Identity_Unverified || DPA_Unverified",
               "יצירת משימה בתור קצין הציות עם תיק הראיות המלא",
               "בקשת PII שמחייבת חתימת DPO"),
    Transition("T21", S.S11_AWAITING_HUMAN_CLARIFICATION, E.USER_SUBMITS_ADDITIONAL_INFO, S.S1_REQUEST_INTAKE, A6,
               "Clarification_Payload_Received == TRUE",
               "מיזוג המידע המשלים לבקשה והרצה מחדש של כל השערים",
               "העובד פירט שלא יוזנו נתונים מזהים"),
    Transition("T22", S.S12_AWAITING_COMPLIANCE_REVIEW, E.OFFICER_APPROVES, S.S14_APPROVED, A6,
               "Officer_Authorized && Officer != Requester && LTL(trace + approve) == VALID",
               "קליטת חתימת הקצין (SoD נאכף) והעברה לרישום",
               "ה-DPO בדק את ה-DPA ואישר בכפוף להצפנת שדות"),
    Transition("T23", S.S12_AWAITING_COMPLIANCE_REVIEW, E.OFFICER_REJECTS, S.S15_REJECTED, A6,
               "Officer_Authorized && Officer != Requester",
               "קליטת נימוקי הדחייה ועדכון יומן הביקורת",
               "הכלי נפסל עקב היעדר ISO 27001"),
    Transition("T24", S.S12_AWAITING_COMPLIANCE_REVIEW, E.OFFICER_REQUESTS_MORE_INFO, S.S11_AWAITING_HUMAN_CLARIFICATION, A6,
               "Officer_Authorized && Officer_Action == REQUEST_INFO",
               "העברת שאלת הקצין לעובד והמתנה",
               "הקצין שואל אם הנתונים עברו התממה"),
    Transition("T25", S.S13_ERROR_RECOVERY, E.RECOVERY_SUCCESSFUL, S.S2_INGESTING_DOCS, A1,
               "Retry_Count < Max_Retries && Fallback_Available == TRUE",
               "Fallback: שליפת ה-ToS ממאגר הספקים המאושר או קיצור מסמך ארוך, וניסיון חוזר",
               "הספק מוכר במאגר הארגוני; ה-ToS השמור נטען"),
    Transition("T26", S.S13_ERROR_RECOVERY, E.RECOVERY_FAILED_ESCALATE, S.S12_AWAITING_COMPLIANCE_REVIEW, A1,
               "Retry_Count >= Max_Retries || Fallback_Available == FALSE",
               "אין דרך להשיג מסמך אמין: הסלמה לבדיקה ידנית (Fail-Closed)",
               "ספק לא מוכר ללא ToS; הקצין צריך להעלות את המסמך"),
    Transition("T27", S.S14_APPROVED, E.REGISTRATION_SUCCESS, S.S16_AUDIT_LOGGING, A6,
               "Tool_Registered == TRUE",
               "הוספת הכלי למאגר הכלים המאושרים",
               "הנפקת רישיון לעובד"),
    Transition("T28", S.S15_REJECTED, E.REJECTION_COMPLETE, S.S16_AUDIT_LOGGING, A6,
               "Tool_Blocked == TRUE",
               "הוספת הכלי לרשימת החסומים",
               "כלי תמלול פומבי נחסם בפיירוול"),
    Transition("T29", S.S16_AUDIT_LOGGING, E.AUDIT_LOGGED, S.S17_COMPLETED, A6,
               "Audit_Block_Written == TRUE && HMAC_Valid == TRUE",
               "כתיבת בלוק ביקורת: hash של כל העקבה, קישור לבלוק הקודם וחתימת HMAC",
               "בלוק #105 נכתב לקובץ ה-ledger"),
    Transition("T30", S.S17_COMPLETED, E.NOTIFICATION_SENT, S.S0_IDLE, A1,
               "User_Notified == TRUE",
               "הודעה לעובד וחזרה ל-Idle",
               "הצגת מסך ההחלטה לעובד"),
    Transition("T31", S.S10_DECISION_ROUTING, E.ROUTE_TO_REJECTED, S.S15_REJECTED, A1,
               "Inference_Violations_Count > 0",
               "הפרת RBAC (Prolog) או שרשרת אספקה נגועה (Datalog): ניתוב לדחייה",
               "תת-ספק של הכלי מאחסן נתונים בסין"),
]

TRANSITION_INDEX: Dict[Tuple[State, Event], Transition] = {(t.source, t.event): t for t in TRANSITIONS}
assert len(TRANSITION_INDEX) == len(TRANSITIONS), "EFSM must be deterministic: duplicate (state, event) pair"


def lookup(state: State, event: Event):
    return TRANSITION_INDEX.get((state, event))


# Diagram layout (column, row) for the UI state diagram.
STATE_LAYOUT: Dict[State, Tuple[float, float]] = {
    S.S0_IDLE: (0, 1), S.S1_REQUEST_INTAKE: (1, 1), S.S2_INGESTING_DOCS: (2, 1),
    S.S3_POLICY_KNOWLEDGE_RETRIEVAL: (3, 1), S.S4_DETERMINISTIC_RULE_CHECKING: (4, 1),
    S.S5_LLM_NEURO_EVALUATION: (5, 1), S.S6_EVALUATING_UNCERTAINTY: (6, 1),
    S.S7_Z3_CONSTRAINT_SOLVING: (7, 1), S.S8_PROLOG_DATALOG_INFERENCE: (8, 1),
    S.S9_TEMPORAL_LOGIC_VERIFICATION: (9, 1), S.S10_DECISION_ROUTING: (9, 3),
    S.S13_ERROR_RECOVERY: (2, 3), S.S11_AWAITING_HUMAN_CLARIFICATION: (4, 3),
    S.S12_AWAITING_COMPLIANCE_REVIEW: (6, 3), S.S14_APPROVED: (8, 5),
    S.S15_REJECTED: (6, 6), S.S16_AUDIT_LOGGING: (4, 5), S.S17_COMPLETED: (2, 5),
}
