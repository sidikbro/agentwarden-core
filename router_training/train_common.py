"""Shared training mechanics for the D2 classifier fine-tunes
(router_training/train_pilot.py, router_training/train_full.py). Extracted
once a second real call site existed (the full-dataset run) -- duplicating
~250 lines of CUDA verification / checkpoint-mirroring / training-loop code
across two scripts would have let them silently drift the way the
train/serve prompt format already did once (see
agentwarden/policies/classifier.py::build_classify_prompt).

Nothing here decides what counts as "ready to train on" -- that's each
caller's job (see train_pilot.py / train_full.py docstrings for what their
specific dataset's review status actually is). This module only runs the
mechanics the same way regardless of which dataset or output directory is
passed in.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

from transformers import TrainerCallback

BASE_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"

sys.path.insert(0, str(Path(__file__).parent.parent))
from agentwarden.policies.classifier import build_classify_prompt  # noqa: E402

_SCRATCH_DIR = os.environ.get("SLURM_SCRATCH_DIR")


def scratch_or_home(out_dir: Path, scratch_subdir: str) -> Path:
    """Frequent Trainer checkpoints go to fast node-local scratch on the
    cluster (mirrored to out_dir after every save), or straight to out_dir
    locally (no scratch to distinguish)."""
    return Path(_SCRATCH_DIR) / scratch_subdir if _SCRATCH_DIR else out_dir


def cuda_actually_works() -> bool:
    """torch.cuda.is_available() can return True on a GPU this PyTorch
    build has no compiled kernels for -- confirmed on the machine that ran
    the first pilot attempt (GTX 1060, compute capability sm_61, that
    PyTorch build supported sm_75+ only; is_available() said True, every
    real op raised "no kernel image for device"). Actually run a trivial op
    instead of trusting the flag."""
    try:
        import torch
        if not torch.cuda.is_available():
            return False
        x = torch.randn(4, 4, device="cuda")
        _ = x @ x
        return True
    except Exception:
        return False


class CudaVerificationCallback(TrainerCallback):
    """Must subclass transformers.TrainerCallback, not just duck-type the
    methods it uses -- Trainer.__init__ calls on_init_end() (and other
    events this class never defines, e.g. on_train_begin) unconditionally
    on every callback via getattr, so a plain object blows up with
    AttributeError before a single step runs. Shipped without that base
    class once already and failed this way on a real cluster job instead
    of locally (see tests/unit/test_train_common_callbacks.py, which
    constructs a real Trainer with this attached specifically to catch it
    here next time).

    Confirms GPU use unambiguously in the log, not inferred from
    torch.cuda.is_available()/jobstats. jobstats reported "GPU utilization:
    0%" with 4.4GB GPU memory allocated and device=cuda logged on a 21s
    pilot run -- almost certainly a sampling artifact (jobstats polls at a
    fixed interval; a run shorter than the interval can show 0% even while
    the GPU was genuinely used), but "almost certainly" isn't good enough to
    build on. This checks the two things that actually prove GPU use --
    model parameters resident on the CUDA device, and a forward pass whose
    OUTPUT tensor is itself on CUDA (silent CPU fallback can't fake that) --
    and separately times every step, so a silent fallback would also be
    obvious from speed (the CPU-only local run did 35-75s/step; see
    hpc/README.md)."""

    def __init__(self, model, cuda_ok: bool):
        self.model = model
        self.cuda_ok = cuda_ok
        self._step_t0 = None
        self._checked = False

    def on_step_begin(self, args, state, control, **kwargs):
        self._step_t0 = time.time()
        return control

    def on_step_end(self, args, state, control, **kwargs):
        step_time = time.time() - self._step_t0 if self._step_t0 else float("nan")
        print(f"[step {state.global_step}] wall-clock: {step_time:.2f}s", flush=True)

        if not self._checked and state.global_step == 1:
            self._checked = True
            param = next(self.model.parameters())
            params_on_cuda = param.device.type == "cuda"

            fwd_ran_on_cuda = False
            fwd_error = None
            try:
                import torch
                probe = torch.randint(0, 1000, (1, 8), device=param.device)
                with torch.no_grad():
                    out = self.model(input_ids=probe)
                fwd_ran_on_cuda = out.logits.device.type == "cuda"
            except Exception as e:
                fwd_error = repr(e)

            verdict = "PASS" if (self.cuda_ok and params_on_cuda and fwd_ran_on_cuda) else "FAIL"
            if not self.cuda_ok:
                verdict = "N/A (cuda_ok=False, expected CPU)"
            print(
                f"[GPU VERIFICATION step 1] verdict={verdict} "
                f"params_device={param.device} params_on_cuda={params_on_cuda} "
                f"forward_output_device={'cuda' if fwd_ran_on_cuda else ('cpu/error' if fwd_error is None else 'error: ' + fwd_error)} "
                f"step_wall_clock={step_time:.2f}s",
                flush=True,
            )
        return control


class CopyCheckpointToHomeCallback(TrainerCallback):
    """Mirrors the latest Trainer checkpoint from scratch to home storage
    right after every save -- a hard OOM/timeout kill can't be trapped for
    a graceful copy at exit. Only instantiated when running with a scratch
    dir; a no-op concept otherwise since the Trainer's output_dir is
    already the home-storage dir in that case."""

    def __init__(self, home_dir: Path):
        self.home_dir = home_dir

    def on_save(self, args, state, control, **kwargs):
        checkpoints = sorted(
            Path(args.output_dir).glob("checkpoint-*"),
            key=lambda p: int(p.name.split("-")[-1]),
        )
        if not checkpoints:
            return control
        src = checkpoints[-1]
        self.home_dir.mkdir(parents=True, exist_ok=True)
        dst = self.home_dir / src.name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        print(f"[checkpoint mirror] {src} -> {dst}", flush=True)
        return control


# Held-out diagnostic files that must never be trained on -- matched by
# filename prefix, not by a one-off check in a single script, so this
# holds regardless of which training entrypoint eventually passes a
# data_path here. See docs/v2/minimal_pair_probe_spec.md: the probe is
# only valid as a diagnostic if no checkpoint it evaluates has ever seen
# it during training.
_HELD_OUT_PREFIXES = ("HELD_OUT_",)


def load_examples(path: Path) -> list[dict]:
    if path.name.startswith(_HELD_OUT_PREFIXES):
        raise ValueError(
            f"{path.name} is a held-out diagnostic file (prefix {_HELD_OUT_PREFIXES!r}) "
            "and must never be used as training data -- see "
            "docs/v2/minimal_pair_probe_spec.md. If you're trying to score it, "
            "use scripts/minimal_pair_leakage_check.py or the canary-check "
            "tooling, not run_training()."
        )
    examples = []
    with path.open() as f:
        for line in f:
            examples.append(json.loads(line))
    return examples


def to_training_pair(ex: dict, include_context: bool = False) -> tuple[str, str]:
    """include_context=True is the gate-3a ceiling experiment only (see
    train_pilot_ceiling.py and docs/v2/provenance_representation.md) --
    defaults False so every other caller is unaffected."""
    prompt = build_classify_prompt(
        ex["tool_name"], ex["arguments"],
        context=ex.get("context", ""), include_context=include_context,
    )
    target = json.dumps({
        "decision": ex["decision"],
        "confidence": 0.9,
        "reason": ex["reason"],
    })
    return prompt, target


def run_training(
    *,
    data_path: Path,
    out_dir: Path,
    scratch_subdir: str,
    max_steps: int,
    save_steps: int,
    logging_steps: int,
    banner_fn,
    missing_data_hint: str,
    include_context: bool = False,
) -> None:
    """Shared main(): load data, build the LoRA model, train, checkpoint,
    save. Everything caller-specific (which file, where the final adapter
    goes, how often to checkpoint, what the banner says) is passed in.

    include_context=True is the gate-3a ceiling experiment only -- see
    train_pilot_ceiling.py and docs/v2/provenance_representation.md.
    Defaults False, matching to_training_pair()'s default, so every
    existing caller is unaffected."""
    if not data_path.exists():
        print(f"FATAL: no training data at {data_path}", file=sys.stderr)
        print("This is expected on a fresh clone -- data/ is gitignored.", file=sys.stderr)
        print(missing_data_hint, file=sys.stderr)
        sys.exit(1)

    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments

    cuda_ok = cuda_actually_works()
    device = "cuda" if cuda_ok else "cpu"
    train_out_dir = scratch_or_home(out_dir, scratch_subdir)
    print(banner_fn(device, train_out_dir, out_dir))

    examples = load_examples(data_path)
    pending = sum(1 for e in examples if e.get("review_status") == "pending")
    approved = sum(1 for e in examples if e.get("review_status") == "approved")
    print(f"Loaded {len(examples)} examples ({approved} review_status=approved, {pending} pending)")

    pairs = [to_training_pair(e, include_context=include_context) for e in examples]

    print(f"Loading base model {BASE_MODEL} (first run downloads it -- may take a while)...")
    t0 = time.time()
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, dtype=torch.bfloat16)
    if cuda_ok:
        model = model.to("cuda")
    print(f"  loaded in {time.time() - t0:.0f}s")

    lora_config = LoraConfig(
        r=8, lora_alpha=16, lora_dropout=0.05,
        target_modules=["q_proj", "v_proj"],
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)
    model.gradient_checkpointing_enable()
    model.print_trainable_parameters()

    def tokenize(example):
        prompt, target = example["prompt"], example["target"]
        full = prompt + target + tokenizer.eos_token
        enc = tokenizer(full, truncation=True, max_length=256, padding="max_length")
        enc["labels"] = list(enc["input_ids"])
        return enc

    dataset = Dataset.from_list([{"prompt": p, "target": t} for p, t in pairs])
    dataset = dataset.map(tokenize, remove_columns=["prompt", "target"])

    training_args = TrainingArguments(
        output_dir=str(train_out_dir),
        per_device_train_batch_size=1,
        gradient_accumulation_steps=2,
        num_train_epochs=1,
        max_steps=max_steps,
        learning_rate=2e-4,
        logging_steps=logging_steps,
        save_strategy="steps",
        save_steps=save_steps,
        save_total_limit=1,
        report_to=[],
        use_cpu=not cuda_ok,
    )

    callbacks = [CudaVerificationCallback(model, cuda_ok)]
    if _SCRATCH_DIR:
        callbacks.append(CopyCheckpointToHomeCallback(out_dir))

    trainer = Trainer(model=model, args=training_args, train_dataset=dataset, callbacks=callbacks)

    resume_ckpt = None
    for candidate_dir in (train_out_dir, out_dir):
        if not candidate_dir.exists():
            continue
        checkpoints = sorted(candidate_dir.glob("checkpoint-*"), key=lambda p: int(p.name.split("-")[-1]))
        if checkpoints:
            resume_ckpt = str(checkpoints[-1])
            print(f"Resuming from {resume_ckpt} (a prior run left this checkpoint)")
            break

    print(f"Training for max_steps={max_steps} on {len(dataset)} examples (device={device})...")
    t0 = time.time()
    trainer.train(resume_from_checkpoint=resume_ckpt)
    print(f"Training finished in {time.time() - t0:.0f}s")

    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(out_dir))
    tokenizer.save_pretrained(str(out_dir))
    print(f"Final adapter saved to {out_dir}")

    print(banner_fn(device, train_out_dir, out_dir))
