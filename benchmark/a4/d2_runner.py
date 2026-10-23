"""Shared, model-agnostic batched runner for the existing D2 classifier
(`agentwarden/policies/classifier.py::build_classify_prompt`,
Qwen2.5-1.5B-Instruct + a LoRA adapter under `data/router_training/`),
extracted out of `scripts/a4_arm0_arm1_stac.py` so every A4 script that
needs arm 1's zero-shot score (the STAC run, the ASEval confound
demonstration, and any benchmark added later) calls one implementation
instead of three copies that could silently drift apart -- the same
reasoning `agentwarden/core/decision_input.py::build_decision_input`'s
docstring gives for being the one place that string is built.

Per standing instruction (2026-10-22): run through the `agentwarden-gpu`
conda env (`conda run -n agentwarden-gpu python3 -m ...`) -- confirmed
~12x faster than CPU on this machine's GPU (GTX 1060, sm_61; the
base/aethelgard envs' torch can't use it at all, see that env's own
setup notes). `torch_dtype=` (not `dtype=`) is required by the
transformers version pinned in that env (<4.50); float16 on CUDA,
float32 on CPU (bf16 measured slower than float32 on this CPU with no
hardware acceleration for it -- scripts/a4_arm0_arm1_stac.py's original
STAC run already established this).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

BASE_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"
DEFAULT_ADAPTER_DIR = Path(__file__).parent.parent.parent / "data" / "router_training" / "FULL_DATASET_v1_checkpoint"


def parse_classifier_text(text: str) -> dict[str, Any]:
    """Strict JSON parse first; falls back to a lenient field-level regex
    when `max_new_tokens` cuts generation off mid-"reason" string before
    the closing brace -- decision/confidence come first in
    CLASSIFY_PROMPT's own field order, so they survive truncation even
    when the whole object doesn't parse."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            obj = json.loads(match.group(0))
            decision = str(obj.get("decision") or obj.get("action") or "").upper() or None
            return {"decision": decision, "confidence": obj.get("confidence"), "raw": text}
        except json.JSONDecodeError:
            pass
    decision_match = re.search(r'"decision"\s*:\s*"(\w+)"', text)
    confidence_match = re.search(r'"confidence"\s*:\s*([\d.]+)', text)
    decision = decision_match.group(1).upper() if decision_match else None
    confidence = float(confidence_match.group(1)) if confidence_match else None
    return {"decision": decision, "confidence": confidence, "raw": text}


def run_d2_classifier_batched(
    items: list[tuple[str, dict]],
    adapter_dir: Path = DEFAULT_ADAPTER_DIR,
    batch_size: int = 32,
    max_new_tokens: int = 48,
) -> list[dict[str, Any]]:
    """`items`: [(tool_name, arguments), ...]. Returns one parsed
    `{"decision", "confidence", "raw"}` dict per item, in the same order.
    Loads the model once; generates in batches."""
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from agentwarden.policies.classifier import build_classify_prompt  # noqa: E402

    def _cuda_actually_works() -> bool:
        try:
            if not torch.cuda.is_available():
                return False
            x = torch.randn(4, 4, device="cuda")
            _ = x @ x
            return True
        except Exception:
            return False

    device = "cuda" if _cuda_actually_works() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    if device == "cpu":
        torch.set_num_threads(8)

    print(f"Loading base model {BASE_MODEL} + adapter {adapter_dir} (device={device}, dtype={dtype}) ...")
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "left"
    base = AutoModelForCausalLM.from_pretrained(BASE_MODEL, torch_dtype=dtype)
    model = PeftModel.from_pretrained(base, str(adapter_dir))
    model.eval()
    model = model.to(device)

    prompts = [build_classify_prompt(tool_name, arguments) for tool_name, arguments in items]

    parsed_results: list[dict[str, Any]] = []
    for i in range(0, len(prompts), batch_size):
        batch = prompts[i : i + batch_size]
        enc = tokenizer(batch, return_tensors="pt", truncation=True, max_length=400, padding=True).to(device)
        with torch.no_grad():
            out = model.generate(
                **enc, max_new_tokens=max_new_tokens, do_sample=False, pad_token_id=tokenizer.pad_token_id
            )
        texts = tokenizer.batch_decode(out[:, enc["input_ids"].shape[1] :], skip_special_tokens=True)
        parsed_results.extend(parse_classifier_text(t) for t in texts)
        print(f"  d2_runner: {min(i + batch_size, len(prompts))}/{len(prompts)} scored", flush=True)

    return parsed_results


def score_from_decision(decision: str | None, confidence: float | None) -> float:
    """Continuous "attack score" from the classifier's own decision/
    confidence: `confidence` if BLOCK, `1 - confidence` if ALLOW, 0.5
    (exactly at chance) for an unparseable response -- flagged, not
    guessed in either direction."""
    if decision == "BLOCK" and confidence is not None:
        return float(confidence)
    if decision == "ALLOW" and confidence is not None:
        return float(1.0 - confidence)
    return 0.5
