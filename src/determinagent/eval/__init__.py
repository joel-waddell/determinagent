"""Evaluation harness (Phase 0.3): score runs against the golden set and gate candidates.

A *run* is a JSON Lines file with one record per golden case:

    {"case_id": "T2-P001", "response": {<v1 response>}, "latency_ms": 812.0,
     "routing_latency_ms": 3.1, "cost_usd": 0.0004, "attempts": 1,
     "first_pass_wellformed": true, "system": "checker-baseline"}

``response`` must validate against the v1 response contract; a record whose
response does not is scored as a failure with reason OUTPUT_SCHEMA_INVALID.
"""

from .gate import compare, gate
from .score import CaseScore, Report, score_run

__all__ = ["CaseScore", "Report", "compare", "gate", "score_run"]
