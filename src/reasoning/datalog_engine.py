"""
Datalog Relational Engine for Transitive Supply-Chain Lineage & Data Sovereignty.

Program (see policies/lineage.dl):
    tainted(X) :- hosted_in(X, J), untrusted(J).
    tainted(X) :- depends_on(X, Y), tainted(Y).

Evaluated bottom-up with semi-naive iteration until a fixed point (PTIME in the size of the
graph). Each derived fact keeps the fact it was derived from, so the explanation shows the
full chain root -> ... -> offending node.
"""
from typing import Dict, Any, Tuple, List, Set, Optional
from ..state_machine.states import RequestDocument
from ..knowledge.registries import normalize_tool_name

UNTRUSTED_JURISDICTIONS: Set[str] = {"RU", "CN", "IR", "KP", "UNTRUSTED_OFFSHORE"}


class DatalogLineageEngine:

    def __init__(self):
        self.untrusted = set(UNTRUSTED_JURISDICTIONS)
        # Supply-chain knowledge base (multi-level sub-processor graph).
        self.depends_on: Set[Tuple[str, str]] = {
            ("enterprise-code-assistant", "CloudCompute_EU"),
            ("CloudCompute_EU", "VectorStore_IL"),
            ("untrusted-ai-plugin", "Frontend_CDN"),
            ("untrusted-ai-plugin", "Analytics_Gateway"),
            ("Analytics_Gateway", "Offshore_Analytics_Cluster"),
            ("shadow-transcription-service", "Relay_Server_US"),
            ("Relay_Server_US", "Transcription_Worker_Node"),
        }
        self.hosted_in: Set[Tuple[str, str]] = {
            ("CloudCompute_EU", "EU"), ("VectorStore_IL", "IL"),
            ("Frontend_CDN", "EU"), ("Analytics_Gateway", "EU"),
            ("Offshore_Analytics_Cluster", "UNTRUSTED_OFFSHORE"),
            ("Relay_Server_US", "US"), ("Transcription_Worker_Node", "CN"),
        }

    def fixpoint(self, depends_on: Set[Tuple[str, str]], hosted_in: Set[Tuple[str, str]]):
        """Semi-naive evaluation. Returns (tainted -> derived_from, iterations)."""
        derived_from: Dict[str, Optional[str]] = {x: None for x, j in hosted_in if j in self.untrusted}
        delta = set(derived_from)
        iterations = 1
        while delta:
            new = {}
            for x, y in depends_on:
                if y in delta and x not in derived_from and x not in new:
                    new[x] = y
            derived_from.update(new)
            delta = set(new)
            if delta:
                iterations += 1
        return derived_from, iterations

    def evaluate(self, request: RequestDocument, facts: Dict[str, Any]) -> Tuple[bool, List[str]]:
        root = normalize_tool_name(request.tool_name)
        depends_on = set(self.depends_on)
        hosted_in = set(self.hosted_in)

        # Facts extracted from the vendor document join the knowledge base.
        for name, jurisdiction in facts.get("sub_processors") or []:
            depends_on.add((root, name))
            hosted_in.add((name, jurisdiction))
        if facts.get("data_residency"):
            hosted_in.add((root, facts["data_residency"]))

        derived_from, iterations = self.fixpoint(depends_on, hosted_in)
        nodes = {root} | {y for x, y in depends_on if x == root}

        if root not in derived_from:
            return True, [
                f"DATALOG_DERIVATION [Lineage OK]: fixed point after {iterations} iteration(s); "
                f"no path from '{request.tool_name}' to an untrusted jurisdiction "
                f"({len(nodes) - 1} direct sub-processor(s) checked)."
            ]

        chain, node = [root], root
        while derived_from[node] is not None:
            node = derived_from[node]
            chain.append(node)
        jurisdiction = next(j for x, j in hosted_in if x == chain[-1] and j in self.untrusted)
        return False, [
            f"DATALOG_RULE [Base Fact]: hosted_in('{chain[-1]}', '{jurisdiction}') ∧ untrusted('{jurisdiction}') ⇒ tainted('{chain[-1]}').",
            f"DATALOG_RULE [Transitive Closure]: tainted propagates along depends_on: {' → '.join(chain)} "
            f"(fixed point after {iterations} iteration(s)).",
        ]
