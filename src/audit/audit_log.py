"""
Cryptographic Audit Trail (EU AI Act Art. 12 record-keeping).

Each block contains:
  * trace_hash   - SHA-256 of the canonical JSON of the *full* state trace, so editing any
                   transition, guard or timestamp is detected (not just the trace length);
  * prev_hash    - link to the previous block (hash chain: deletion / reordering is detected);
  * current_hash - SHA-256 of the block payload;
  * hmac         - HMAC-SHA256 of current_hash with a server-side key. A plain hash chain can be
                   recomputed by anyone who edits the file; the HMAC cannot be forged without the key.

Blocks are appended to a JSONL file when a path is given (survives restarts) and writes are
serialized with a lock (the API server is multi-threaded).
"""
import hashlib
import hmac
import json
import os
import threading
import time
import warnings
from typing import Dict, Any, List, Optional

DEV_KEY = "dev-only-audit-key-change-me"


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def trace_digest(trace: List[Dict[str, Any]]) -> str:
    return hashlib.sha256(_canonical(trace)).hexdigest()


class AuditTrail:

    def __init__(self, path: Optional[str] = None, hmac_key: Optional[str] = None):
        self.path = path
        key = hmac_key or os.environ.get("AUDIT_HMAC_KEY")
        if not key:
            key = DEV_KEY
            if path:
                warnings.warn("AUDIT_HMAC_KEY is not set; using the development key.", RuntimeWarning)
        self._key = key.encode("utf-8")
        self._lock = threading.Lock()
        self.chain: List[Dict[str, Any]] = []
        self.traces: Dict[int, List[Dict[str, Any]]] = {}
        self._genesis_hash = hashlib.sha256(b"GENESIS_AI_GOVERNANCE_LEDGER_2026").hexdigest()
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        row = json.loads(line)
                        if "current_hash" not in row.get("block", {}):  # skip rows in an incompatible format
                            continue
                        self.traces[row["block"]["index"]] = row.get("trace", [])
                        self.chain.append(row["block"])

    def get_last_hash(self) -> str:
        return self.chain[-1]["current_hash"] if self.chain else self._genesis_hash

    def _sign(self, digest: str) -> str:
        return hmac.new(self._key, digest.encode("utf-8"), hashlib.sha256).hexdigest()

    def record_decision(self, request_id: str, decision: str, trace: List[Dict[str, Any]], metadata: Dict[str, Any]) -> str:
        with self._lock:
            payload = {
                "index": len(self.chain),
                "prev_hash": self.get_last_hash(),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "request_id": request_id,
                "decision": decision,
                "trace_length": len(trace),
                "trace_hash": trace_digest(trace),
                "metadata": metadata,
            }
            block_hash = hashlib.sha256(_canonical(payload)).hexdigest()
            block = {**payload, "current_hash": block_hash, "hmac": self._sign(block_hash)}
            self.chain.append(block)
            self.traces[block["index"]] = [dict(t) for t in trace]
            if self.path:
                os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"block": block, "trace": trace}, ensure_ascii=False) + "\n")
            return block_hash

    def verify_integrity(self) -> bool:
        return not self.find_tampering()

    def find_tampering(self) -> List[str]:
        """Returns a list of problems (empty list = ledger intact)."""
        problems = []
        prev = self._genesis_hash
        for block in self.chain:
            i = block.get("index")
            payload = {k: v for k, v in block.items() if k not in ("current_hash", "hmac")}
            if block.get("prev_hash") != prev:
                problems.append(f"block {i}: broken link to previous block")
            if hashlib.sha256(_canonical(payload)).hexdigest() != block.get("current_hash"):
                problems.append(f"block {i}: payload does not match its hash")
            if not hmac.compare_digest(self._sign(block.get("current_hash", "")), block.get("hmac", "")):
                problems.append(f"block {i}: HMAC signature invalid")
            if i in self.traces and trace_digest(self.traces[i]) != block.get("trace_hash"):
                problems.append(f"block {i}: stored trace does not match trace_hash")
            prev = block.get("current_hash")
        return problems
