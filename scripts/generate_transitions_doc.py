"""
Generates docs/TRANSITIONS_TABLE.md from src/state_machine/transitions.py (the single source of truth).
Run: python3 scripts/generate_transitions_doc.py
tests/test_api.py fails when the committed file is stale.
"""
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.state_machine.states import State, LayerType  # noqa: E402
from src.state_machine.transitions import TRANSITIONS  # noqa: E402
from src.state_machine.temporal_monitor import TemporalTraceVerifier  # noqa: E402

LAYERS = [
    (LayerType.REQUEST_UNDERSTANDING, "הבנת הבקשה", "קליטה, הקשר וחילוץ טענות עם ודאות", "LLM פרטי ומקורות ידע מנוהלים"),
    (LayerType.CONTROLLED_DECISION, "החלטה מבוקרת", "OPA, Z3, Prolog, Datalog ו-LTL", "מנועי מדיניות פורמליים כשירותים"),
    (LayerType.GOVERNANCE_CONTROL, "ממשל ובקרה", "EFSM, HITL, SoD ויומן HMAC", "Workflow עמיד, SSO, KMS ו-WORM"),
]


def short(state_value: str) -> str:
    return state_value.split(":")[0]


def render() -> str:
    by_layer = defaultdict(list)
    for t in TRANSITIONS:
        by_layer[t.layer].append(t.code)
    states_by_layer = defaultdict(set)
    for t in TRANSITIONS:
        states_by_layer[t.layer].add(t.source)

    lines = [
        "# 📑 טבלת מעברים (Transitions) וארכיטקטורת 3 השכבות",
        "",
        "> **קובץ זה נוצר אוטומטית** מ-`src/state_machine/transitions.py` באמצעות "
        "`python3 scripts/generate_transitions_doc.py`. אין לערוך ידנית: בדיקה אוטומטית נכשלת אם הוא לא מעודכן.",
        "",
        f"**EFSM: {len(State)} מצבים · {len(TRANSITIONS)} מעברים · {len(TemporalTraceVerifier.RULES)} אינווריאנטי LTL**. "
        "כל זוג (מצב, אירוע) שלא מופיע כאן נדחה בזמן ריצה (`IllegalTransitionError`).",
        "",
        "## 1. שלוש השכבות",
        "",
        "| שכבה | אחריות | מימוש באב-טיפוס | מימוש בייצור | מצבי מקור | מעברים |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for layer, name, proto, prod in LAYERS:
        src = ", ".join(sorted({short(s.value) for s in states_by_layer[layer]}, key=lambda x: int(x[1:])))
        lines.append(f"| **{layer.value.split(':')[0]}** | {name} | {proto} | {prod} | {src} | {', '.join(by_layer[layer])} |")

    lines += [
        "",
        "## 2. טבלת המעברים",
        "",
        "| # | מעבר | שכבה | אירוע | Guard | פעולה / Side Effect | דוגמה |",
        "| :-: | :-: | :-: | :--- | :--- | :--- | :--- |",
    ]
    for t in TRANSITIONS:
        guard = t.guard.replace("|", "\\|")
        lines.append(
            f"| **{t.code}** | `{short(t.source.value)} → {short(t.target.value)}` | {t.layer.value.split(':')[0]} | "
            f"`{t.event.value}` | `{guard}` | {t.side_effect} | {t.example} |")

    lines += ["", "## 3. אינווריאנטי LTL", "", "| מזהה | נוסחה | סוג | משמעות |", "| :-- | :-- | :-- | :-- |"]
    for rid, formula, kind, desc in TemporalTraceVerifier.RULES:
        lines.append(f"| {rid} | `{formula}` | {kind} | {desc} |")

    lines += [
        "",
        "## 4. מצבים",
        "",
        "| מצב | סוג |",
        "| :-- | :-- |",
    ]
    kinds = {State.S0_IDLE: "התחלתי", State.S11_AWAITING_HUMAN_CLARIFICATION: "המתנה לעובד",
             State.S12_AWAITING_COMPLIANCE_REVIEW: "המתנה לקצין ציות", State.S14_APPROVED: "הכרעה",
             State.S15_REJECTED: "הכרעה", State.S13_ERROR_RECOVERY: "התאוששות"}
    for s in State:
        lines.append(f"| `{s.value}` | {kinds.get(s, 'עיבוד')} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    out = os.path.join(ROOT, "docs", "TRANSITIONS_TABLE.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(render())
    print(f"wrote {out}")
