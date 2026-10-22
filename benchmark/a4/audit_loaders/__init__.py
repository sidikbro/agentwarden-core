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

from . import agentdojo as _agentdojo
from . import stac as _stac

REGISTRY = {
    "STAC": _stac.load_stac,
    "AgentDojo": _agentdojo.load_agentdojo,
}
