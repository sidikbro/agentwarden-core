"""Loader registry for `benchmark/a4/shortcut_audit.py`. Each module here
implements one benchmark's `load_<name>() -> list[AuditRecord]`, stating
explicitly (in its own docstring) the attack/benign definition used and
how actions were extracted from that benchmark's own data -- the audit's
credibility rests on those being stated, not assumed (per instruction).

A loader whose benchmark is gated (credentials, a terms-of-use form) or
requires live execution with no static trajectory to extract actions from
raises `benchmark.a4.shortcut_audit.BenchmarkNotObtainedError` with the
reason, rather than approximating a substitute.
"""
from __future__ import annotations

from . import agent_security_bench as _agent_security_bench
from . import agentharm as _agentharm
from . import aseval as _aseval
from . import injecagent as _injecagent
from . import stac as _stac

REGISTRY = {
    "STAC": _stac.load_stac,
    "ASEval": _aseval.load_aseval,
    "InjecAgent": _injecagent.load_injecagent,
    "AgentHarm": _agentharm.load_agentharm,
    "AgentSecurityBench": _agent_security_bench.load_agent_security_bench,
}

# AgentDojo's loader imports the `agentdojo` package at module level
# (benchmark/a4/agentdojo_adapter.py), which is an optional dependency
# (pyproject.toml's `benchmarks` extra) not installed in every environment
# this registry gets imported from (e.g. the `agentwarden-gpu` conda env,
# used for arm 1's local-model runs, has no need for AgentDojo). A missing
# optional dependency must not break every other benchmark's loader --
# caught here, not left to crash the whole package import.
try:
    from . import agentdojo as _agentdojo

    REGISTRY["AgentDojo"] = _agentdojo.load_agentdojo
except ImportError:
    pass

# Investigated for this audit but NOT registered -- each is gated, requires
# live execution with no static labeled actions to extract, or (Adaptive
# Adversaries, Cross-Session Threats, R-Judge) is freely obtainable but has
# no tool-call schema to audit at all. See docs/v2/RECONCILED_STATE_v0.2.md's
# shortcut-audit entry for the full reasoning behind each:
#   - Boiling the Frog (arXiv:2605.22643) -- no public repo/data; inherently
#     live-execution-only (fresh Docker container per run) even if one existed.
#   - Adaptive Adversaries (arXiv:2607.18063) -- obtainable, but a pure
#     text/conversational jailbreak benchmark with no tool-call representation.
#   - Cross-Session Threats (arXiv:2604.21131, HF dataset intrinsec-ai/cstm-bench)
#     -- obtainable, but pure natural-language chat transcripts, no tool calls.
#   - Agent-SafetyBench -- obtainable, but live-execution-only (no pre-generated
#     trajectories ship; the repo only provides task instructions + tool schemas).
#   - R-Judge -- obtainable, but only 13.6% of its actions have an extractable
#     tool-call structure; the rest are free-text UI phrases with no tool name.
#   - ToolEmu -- obtainable, but live-execution-only (LM-emulated sandbox;
#     shipped data is prose risk descriptions, not concrete tool calls).
#   - SHADE-Arena (arXiv:2506.15740) -- live-execution-only, and the one path
#     to pre-recorded transcripts is access-gated (email the authors).
#     Also: STAC's own 483 cases already draw 390 from SHADE-Arena, so even
#     a future live-execution run against it would not be independent of
#     the STAC row above.
#   - ToolSword (arXiv:2402.10753) -- obtainable, but 330/470 items have no
#     recorded tool call at all, and the other 140 record only an innocuous,
#     user-requested call (the "harm" is in a synthetic injected tool
#     *response*, not the call) -- no static benign-vs-attack call pair.
