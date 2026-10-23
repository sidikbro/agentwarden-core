"""Agent Security Bench (ASB) loader for the shortcut audit (ICLR 2025,
arXiv:2410.02644, "Agent Security Bench (ASB): Formalizing and
Benchmarking Attacks and Defenses in LLM-based Agents", Zhang et al.,
Zhejiang University / Rutgers. Code: `github.com/agiresearch/ASB`. No
credentials, no terms-of-use form -- a plain public clone.

This is a DIFFERENT benchmark from "Agent-SafetyBench" (`thu-coai/
Agent-SafetyBench`, already investigated separately and found to be
live-execution-only) -- confirmed via the arXiv listing and distinct
author/institution set; do not conflate the two.

**Attack/benign definition and extraction, stated explicitly, confirmed
against the real `data/all_normal_tools.jsonl` (20 entries) and
`data/all_attack_tools.jsonl` (400 entries, 200 "Stealthy Attack" + 200
"Disruptive Attack", 200 flagged "Aggressive": true):**

- `benign` is each entry in `all_normal_tools.jsonl` (`Tool Name`,
  `Corresponding Agent`) -- a tool ASB's own agents are meant to call
  as part of their legitimate task.
- `attack` is each entry in `all_attack_tools.jsonl` (`Attacker Tool`,
  `Corresponding Agent`) -- an adversarial tool ASB injects to test
  whether an agent can be lured into invoking it (via direct/indirect
  prompt injection, memory poisoning, or a Plan-of-Thought backdoor,
  per the paper; this static export does not distinguish which attack
  vector a given tool is used to test, only its `Attack Type` and
  `Aggressive` flag).
- `task_id` is the tool's own `Corresponding Agent` value (10 distinct
  agents, e.g. `financial_analyst_agent`, `system_admin_agent`) -- the
  natural session/task scope: each agent has exactly 2 normal tools and
  40 attacker tools registered against it in this export.
- **Stated limitation, not glossed over:** neither file records concrete
  call *arguments* -- both are tool/capability *definitions* (a name, a
  description, the owning agent), not executed calls. Concrete
  arguments only exist once ASB's own framework is run live against a
  real agent and the agent actually invokes the tool with specific
  parameters (the paper's own evaluation method, reporting attack
  success rates up to 84.3%); that live run is not performed or
  approximated here. `arguments` is populated as `{}` for every record
  -- the honest value, since no argument data exists in this export at
  all, for either label.
- Checked directly: zero tool-name overlap between the 20 normal and
  400 attack tools (by construction, ASB draws them from disjoint
  pools, the same pattern already confirmed for InjecAgent's user/
  attacker tools) -- so a perfect or near-perfect tool-identity AUC here
  would be a construction artifact, not a leak to fix, consistent with
  InjecAgent's own result.

Requires `ASB_DATA_DIR` pointing at a clone's `data/` directory:
`git clone https://github.com/agiresearch/ASB.git`, then
`ASB_DATA_DIR=<clone>/data`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from ..shortcut_audit import AuditRecord, BenchmarkNotObtainedError


def load_agent_security_bench() -> list[AuditRecord]:
    data_dir = os.environ.get("ASB_DATA_DIR")
    if not data_dir:
        raise BenchmarkNotObtainedError(
            "ASB_DATA_DIR not set. Obtain via: "
            "git clone https://github.com/agiresearch/ASB.git, "
            "then set ASB_DATA_DIR=<clone>/data"
        )
    data_path = Path(data_dir)

    normal_path = data_path / "all_normal_tools.jsonl"
    attack_path = data_path / "all_attack_tools.jsonl"
    if not normal_path.exists() or not attack_path.exists():
        raise BenchmarkNotObtainedError(f"expected files not found under {data_path}")

    records: list[AuditRecord] = []
    with normal_path.open() as f:
        for line in f:
            tool = json.loads(line)
            records.append(
                AuditRecord("AgentSecurityBench", tool["Corresponding Agent"], tool["Tool Name"], {}, "benign")
            )
    with attack_path.open() as f:
        for line in f:
            tool = json.loads(line)
            records.append(
                AuditRecord("AgentSecurityBench", tool["Corresponding Agent"], tool["Attacker Tool"], {}, "attack")
            )
    return records
