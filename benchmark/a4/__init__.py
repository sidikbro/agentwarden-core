"""Benchmark adapters for A4 (docs/v2/A4_MULTITURN_SPEC_v0.2.md), §13
steps 1-2 only: STAC, MT-AgentRisk, AgentDojo. Each adapter loads its
benchmark's native data and emits `AdapterCase` objects (see `common.py`)
-- a mechanically-derived anchor plus the benchmark's own trajectory and
label. Nothing past that: no validity gates (§9), no symbolic baseline
(§8.2), no learned arm, no training. Those are later build-order steps.
"""
