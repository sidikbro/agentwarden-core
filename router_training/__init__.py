"""Router (D2 classifier) retraining data pipeline.

Implements docs/v2/ROUTER_RETRAINING_PLAN_v0.1.md. Design-time contract,
not just convention: every module here must respect the plan's standing
rules — no label sourced from any model's runtime decisions, no
ATBench-Claw content, no v2 benchmark (`benchmark/`) tool names or
descriptions. See contamination_check.py for the automated enforcement.
"""
