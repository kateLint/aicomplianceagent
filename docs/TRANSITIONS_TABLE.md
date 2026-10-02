# 📑 טבלת מעברים (Transitions) וארכיטקטורת 3 השכבות

> **קובץ זה נוצר אוטומטית** מ-`src/state_machine/transitions.py` באמצעות `python3 scripts/generate_transitions_doc.py`. אין לערוך ידנית: בדיקה אוטומטית נכשלת אם הוא לא מעודכן.

**EFSM: 18 מצבים · 31 מעברים · 6 אינווריאנטי LTL**. כל זוג (מצב, אירוע) שלא מופיע כאן נדחה בזמן ריצה (`IllegalTransitionError`).

## 1. שלוש השכבות

| שכבה | אחריות | מימוש באב-טיפוס | מימוש בייצור | מצבי מקור | מעברים |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Layer 1** | הבנת הבקשה | קליטה, הקשר וחילוץ טענות עם ודאות | LLM פרטי ומקורות ידע מנוהלים | S1, S2, S3, S5, S6 | T02, T04, T05, T06, T09, T10, T11 |
| **Layer 2** | החלטה מבוקרת | OPA, Z3, Prolog, Datalog ו-LTL | מנועי מדיניות פורמליים כשירותים | S4, S7, S8, S9 | T07, T08, T13, T14, T15, T16, T17 |
| **Layer 3** | ממשל ובקרה | EFSM, HITL, SoD ויומן HMAC | Workflow עמיד, SSO, KMS ו-WORM | S0, S1, S6, S10, S11, S12, S13, S14, S15, S16, S17 | T01, T03, T12, T18, T19, T20, T21, T22, T23, T24, T25, T26, T27, T28, T29, T30, T31 |

## 2. טבלת המעברים

| # | מעבר | שכבה | אירוע | Guard | פעולה / Side Effect | דוגמה |
| :-: | :-: | :-: | :--- | :--- | :--- | :--- |
| **T01** | `S0 → S1` | Layer 3 | `USER_SUBMITS_REQUEST` | `Payload_Present == TRUE` | פתיחת רשומת בקשה עם מזהה ייחודי ואימות זהות העובד מול ספריית העובדים | עובד ממלא בקשה לשימוש בכלי AI לסיכום מסמכים |
| **T02** | `S1 → S2` | Layer 1 | `FORM_VALIDATED` | `Mandatory_Fields_Present == TRUE && Sensitivity_Classified == TRUE` | הקלט תקין: העברת ה-ToS / URL לרכיב האיסוף | מפתח מגיש בקשה עם כל שדות החובה וסיווג Confidential |
| **T03** | `S1 → S0` | Layer 3 | `INTAKE_FAILED` | `Missing_Mandatory_Fields == TRUE` | החזרת רשימת השדות החסרים לעובד, רישום ביומן הביקורת ואיפוס ל-Idle | עובד שלח טופס בלי שם כלי או מטרת שימוש |
| **T04** | `S2 → S3` | Layer 1 | `SCRAPING_COMPLETED` | `Vendor_Document_Available == TRUE` | חילוץ טענות (claims) מתנאי השימוש, כל טענה עם מדד ודאות | תנאי השימוש של הספק נקלטו ופוענחו |
| **T05** | `S2 → S13` | Layer 1 | `SCRAPING_FAILED_WITH_TIMEOUT` | `Vendor_Document_Available == FALSE \|\| Timeout_Exceeded == TRUE` | אין מסמך ספק לניתוח: מעבר למנגנון ההתאוששות (לא מאשרים על בסיס הנחות) | העובד לא צירף ToS ואתר הספק חסום (Cloudflare / CAPTCHA) |
| **T06** | `S3 → S4` | Layer 1 | `CONTEXT_READY` | `Context_Built == TRUE` | שליפת סעיפי המדיניות והרגולציה הרלוונטיים (GDPR, EU AI Act) להקשר | שליפת GDPR Art. 28 עבור כלי שמעבד נתוני לקוחות |
| **T07** | `S4 → S5` | Layer 2 | `OPA_ALLOW` | `OPA_Decision == ALLOW && Hard_Violations_Count == 0` | חוקי הברזל עברו על העובדות הידועות; מעבר לבדיקת ודאות | כלי עם הצפנה, ללא אימון וריבונות מאושרת |
| **T08** | `S4 → S15` | Layer 2 | `OPA_DENY` | `OPA_Decision == DENY \|\| Hard_Violations_Count > 0` | חסימה קשיחה: רישום החוק שהופר; שלבים יקרים יותר לא מורצים | כלי חינמי שמאמן מודלים על הקלט (Rule 101) |
| **T09** | `S5 → S6` | Layer 1 | `LLM_EVALUATION_COMPLETED` | `Neuro_Inference_Done == TRUE && Claims_Extracted_Count > 0` | שקלול ודאות הטענות: C_score = min(conf(claim)) | חולצו 4 טענות: אימון, שמירה, ריבונות, הצפנה |
| **T10** | `S5 → S13` | Layer 1 | `LLM_TIMEOUT_OR_PARSE_ERROR` | `API_Error == TRUE \|\| Parse_Failed == TRUE` | שגיאת מודל (Rate Limit / חריגת הקשר / פלט שבור): מעבר להתאוששות | מסמך ToS ארוך מחלון ההקשר של המודל |
| **T11** | `S6 → S7` | Layer 1 | `HIGH_CONFIDENCE_DETECTED` | `C_score >= 0.85 && Injection_Suspected == FALSE` | כל הטענות הנדרשות ודאיות: המרה לפסוקים לוגיים ושליחה ל-Z3 | ToS מפורש וחד-משמעי, C_score = 0.95 |
| **T12** | `S6 → S12` | Layer 3 | `UNCERTAINTY_ESCALATE` | `C_score < 0.85 \|\| Injection_Suspected == TRUE` | אי-ודאות או חשד ל-Prompt Injection: הסלמה לקצין ציות עם סימון הטענות החסרות | ה-ToS לא מציין תקופת שמירת מידע (C_score = 0.50) |
| **T13** | `S7 → S8` | Layer 2 | `Z3_SOLVER_SAT` | `Z3_Result == SAT` | הוכח שאישור עקבי עם כל האקסיומות; מעבר להסקת הרשאות ושרשרת אספקה | דרישות השמירה וההצפנה של הארגון לא סותרות את הצהרות הספק |
| **T14** | `S7 → S15` | Layer 2 | `Z3_SOLVER_UNSAT` | `Z3_Result == UNSAT` | חילוץ UNSAT Core מינימלי והצעת תיקון (מה צריך להשתנות כדי לאשר) | מידע סודי, והספק שומר מידע 90 יום (מעל המגבלה של 30) |
| **T15** | `S8 → S9` | Layer 2 | `INFERENCE_COMPLETED` | `RBAC_Evaluated == TRUE && Lineage_Evaluated == TRUE` | RBAC ב-Prolog וסגור טרנזיטיבי של שרשרת האספקה ב-Datalog | מפתח מורשה ל-Confidential; שרשרת תת-הספקים נקייה |
| **T16** | `S9 → S10` | Layer 2 | `VERIFICATION_SUCCESS` | `LTL(prefix + planned_route) == VALID` | אינווריאנטי ה-LTL נבדקים על העקבה + המסלול המתוכנן, לפני שהוא מתבצע | הוכח שהאישור המתוכנן קודם לו OPA, Z3 ו-DPA |
| **T17** | `S9 → S15` | Layer 2 | `LTL_VIOLATION_DETECTED` | `LTL(prefix + planned_route) == VIOLATED` | המסלול המתוכנן היה מפר אינווריאנט: חסימה לפני הביצוע | מידע סודי לספק חיצוני ללא DPA חתום (LTL_4) |
| **T18** | `S10 → S14` | Layer 3 | `ROUTE_TO_APPROVED` | `All_Gates_Passed && Identity_Verified && Risk_Level == LOW` | אישור אוטונומי והקצאת הרשאה לעובד | כלי On-Premises שעבר את כל השערים |
| **T19** | `S10 → S11` | Layer 3 | `ROUTE_TO_NEED_INFO` | `Intended_Use_Vague == TRUE` | ניסוח שאלת הבהרה ממוקדת לעובד | העובד כתב "שימוש כללי" בלי לפרט אילו נתונים יוזנו |
| **T20** | `S10 → S12` | Layer 3 | `ROUTE_TO_ESCALATION` | `Risk_Level == HIGH \|\| Identity_Unverified \|\| DPA_Unverified` | יצירת משימה בתור קצין הציות עם תיק הראיות המלא | בקשת PII שמחייבת חתימת DPO |
| **T21** | `S11 → S1` | Layer 3 | `USER_SUBMITS_ADDITIONAL_INFO` | `Clarification_Payload_Received == TRUE` | מיזוג המידע המשלים לבקשה והרצה מחדש של כל השערים | העובד פירט שלא יוזנו נתונים מזהים |
| **T22** | `S12 → S14` | Layer 3 | `OFFICER_APPROVES` | `Officer_Authorized && Officer != Requester && LTL(trace + approve) == VALID` | קליטת חתימת הקצין (SoD נאכף) והעברה לרישום | ה-DPO בדק את ה-DPA ואישר בכפוף להצפנת שדות |
| **T23** | `S12 → S15` | Layer 3 | `OFFICER_REJECTS` | `Officer_Authorized && Officer != Requester` | קליטת נימוקי הדחייה ועדכון יומן הביקורת | הכלי נפסל עקב היעדר ISO 27001 |
| **T24** | `S12 → S11` | Layer 3 | `OFFICER_REQUESTS_MORE_INFO` | `Officer_Authorized && Officer_Action == REQUEST_INFO` | העברת שאלת הקצין לעובד והמתנה | הקצין שואל אם הנתונים עברו התממה |
| **T25** | `S13 → S2` | Layer 3 | `RECOVERY_SUCCESSFUL` | `Retry_Count < Max_Retries && Fallback_Available == TRUE` | Fallback: שליפת ה-ToS ממאגר הספקים המאושר או קיצור מסמך ארוך, וניסיון חוזר | הספק מוכר במאגר הארגוני; ה-ToS השמור נטען |
| **T26** | `S13 → S12` | Layer 3 | `RECOVERY_FAILED_ESCALATE` | `Retry_Count >= Max_Retries \|\| Fallback_Available == FALSE` | אין דרך להשיג מסמך אמין: הסלמה לבדיקה ידנית (Fail-Closed) | ספק לא מוכר ללא ToS; הקצין צריך להעלות את המסמך |
| **T27** | `S14 → S16` | Layer 3 | `REGISTRATION_SUCCESS` | `Tool_Registered == TRUE` | הוספת הכלי למאגר הכלים המאושרים | הנפקת רישיון לעובד |
| **T28** | `S15 → S16` | Layer 3 | `REJECTION_COMPLETE` | `Tool_Blocked == TRUE` | הוספת הכלי לרשימת החסומים | כלי תמלול פומבי נחסם בפיירוול |
| **T29** | `S16 → S17` | Layer 3 | `AUDIT_LOGGED` | `Audit_Block_Written == TRUE && HMAC_Valid == TRUE` | כתיבת בלוק ביקורת: hash של כל העקבה, קישור לבלוק הקודם וחתימת HMAC | בלוק #105 נכתב לקובץ ה-ledger |
| **T30** | `S17 → S0` | Layer 3 | `NOTIFICATION_SENT` | `User_Notified == TRUE` | הודעה לעובד וחזרה ל-Idle | הצגת מסך ההחלטה לעובד |
| **T31** | `S10 → S15` | Layer 3 | `ROUTE_TO_REJECTED` | `Inference_Violations_Count > 0` | הפרת RBAC (Prolog) או שרשרת אספקה נגועה (Datalog): ניתוב לדחייה | תת-ספק של הכלי מאחסן נתונים בסין |

## 3. אינווריאנטי LTL

| מזהה | נוסחה | סוג | משמעות |
| :-- | :-- | :-- | :-- |
| LTL_1 | `G(Approved → P(Policy_Checked))` | safety | אי אפשר להגיע לאישור בלי בדיקת OPA קודמת באותו מחזור. |
| LTL_2 | `G(Approved → P(Z3_SAT ∨ Officer_Approved))` | safety | אישור דורש הוכחת SAT ב-Z3, או חתימת קצין ציות. |
| LTL_3 | `G(Violation → Rejected)` | safety | אירוע הפרה חייב להוביל ישירות ל-S15. |
| LTL_4 | `G(Sensitive ∧ External → ¬Approved U DPA_Signed)` | safety | מידע רגיש שיוצא לספק לא יאושר עד שיש DPA חתום ומאומת. |
| LTL_5 | `G(Completed → P(Audit_Logged))` | safety | אין סיום בלי בלוק ביקורת. |
| LTL_6 | `G(Escalated → F(Officer_Decision))` | liveness | כל הסלמה תסתיים בהחלטת קצין (על עקבה סופית: PENDING עד שמתקבלת). |

## 4. מצבים

| מצב | סוג |
| :-- | :-- |
| `S0: Idle` | התחלתי |
| `S1: Request_Intake` | עיבוד |
| `S2: Ingesting_Docs` | עיבוד |
| `S3: Policy_Knowledge_Retrieval` | עיבוד |
| `S4: Deterministic_Rule_Checking` | עיבוד |
| `S5: LLM_Neuro_Evaluation` | עיבוד |
| `S6: Evaluating_Uncertainty` | עיבוד |
| `S7: Z3_Constraint_Solving` | עיבוד |
| `S8: Prolog_Datalog_Inference` | עיבוד |
| `S9: Temporal_Logic_Verification` | עיבוד |
| `S10: Decision_Routing` | עיבוד |
| `S11: Awaiting_Human_Clarification` | המתנה לעובד |
| `S12: Awaiting_Compliance_Review` | המתנה לקצין ציות |
| `S13: Error_Recovery` | התאוששות |
| `S14: Approved` | הכרעה |
| `S15: Rejected` | הכרעה |
| `S16: Audit_Logging` | עיבוד |
| `S17: Completed` | עיבוד |
