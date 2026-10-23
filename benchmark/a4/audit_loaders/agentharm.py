"""AgentHarm loader for the shortcut audit (arXiv:2410.09024, "AgentHarm:
A Benchmark for Measuring Harmfulness of LLM Agents", Gray Swan AI / UK AI
Safety Institute, ICLR 2025). Dataset:
https://huggingface.co/datasets/ai-safety-institute/AgentHarm (no login,
no terms-of-use form -- `huggingface_hub.snapshot_download` works
unauthenticated). Codebase: github.com/UKGovernmentBEIS/inspect_evals.

**What's actually in the dataset, confirmed by reading the real downloaded
files, not the paper's prose.** `benchmark/harmful_behaviors_{test_public,
validation}.json` and `benchmark/benign_behaviors_{test_public,
validation}.json` each hold a list of "behaviors": `{id, id_original,
name, category, prompt, target_functions, grading_function}`. Every
harmful behavior has a benign counterpart sharing the same `id` within
its split (e.g. harmful "Propaganda AI Video" id="1-1" vs. benign
"Propaganda AI Video - Benign" id="1-1") -- 176 pairs in `test_public`,
32 in `validation`, 208 total, matching the paper's released-subset
count (44 of 66 public test behaviors x4 augmentations = 176).

**Stated limitation, not glossed over, same pattern as InjecAgent's
loader:** `target_functions` is a list of tool NAMES the task is
expected to use -- there is no concrete call (no arguments) recorded
anywhere in this static release. Generating actual `(tool_name,
arguments)` calls requires running a live agent through the Inspect
Evals harness (API keys for OpenAI/Anthropic/etc., per the dataset's own
README) -- this loader does not do that and does not approximate
arguments; every record's `arguments` is `{}`.

**Attack/benign definition and extraction, stated explicitly:** one
`AuditRecord` per name in a behavior's `target_functions`, labeled
`attack` for every harmful-behaviors-file entry and `benign` for every
benign-behaviors-file entry. `task_id` = `f"{split}_{id}"` (the shared id
that pairs a harmful behavior with its own benign counterpart within one
split; prefixed with the split name since `test_public` and `validation`
each restart their own id numbering).

**Surprising, worth flagging on its own:** of the 176 test_public pairs,
143 (81.3%) have IDENTICAL `target_functions` between the harmful and
benign version -- by construction, not a leak this loader introduced.
AgentHarm's own benign counterparts are deliberately toned-down versions
of the same task using the same tools, so this benchmark is unusually
tool-matched already, structurally, for most of its behaviors.

Requires `AGENTHARM_DATA_DIR` pointing at a local copy's `benchmark/`
directory: `python3 -c "from huggingface_hub import snapshot_download;
snapshot_download(repo_id='ai-safety-institute/AgentHarm',
repo_type='dataset', local_dir='<dest>')"`, then
`AGENTHARM_DATA_DIR=<dest>/benchmark`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from ..shortcut_audit import AuditRecord, BenchmarkNotObtainedError

_SPLITS = ("test_public", "validation")


def _load_behaviors(path: Path) -> list[dict]:
    return json.loads(path.read_text())["behaviors"]


def load_agentharm() -> list[AuditRecord]:
    data_dir = os.environ.get("AGENTHARM_DATA_DIR")
    if not data_dir:
        raise BenchmarkNotObtainedError(
            "AGENTHARM_DATA_DIR not set. Obtain via: python3 -c \"from huggingface_hub import "
            "snapshot_download; snapshot_download(repo_id='ai-safety-institute/AgentHarm', "
            "repo_type='dataset', local_dir='<dest>')\", then AGENTHARM_DATA_DIR=<dest>/benchmark"
        )
    base = Path(data_dir)

    records: list[AuditRecord] = []
    for split in _SPLITS:
        harmful_path = base / f"harmful_behaviors_{split}.json"
        benign_path = base / f"benign_behaviors_{split}.json"
        if not harmful_path.exists() or not benign_path.exists():
            raise BenchmarkNotObtainedError(f"expected files not found under {base}: {harmful_path}, {benign_path}")

        for behavior in _load_behaviors(harmful_path):
            task_id = f"{split}_{behavior['id']}"
            for tool_name in behavior["target_functions"]:
                records.append(AuditRecord("AgentHarm", task_id, tool_name, {}, "attack"))

        for behavior in _load_behaviors(benign_path):
            task_id = f"{split}_{behavior['id']}"
            for tool_name in behavior["target_functions"]:
                records.append(AuditRecord("AgentHarm", task_id, tool_name, {}, "benign"))

    return records
