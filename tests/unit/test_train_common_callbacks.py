"""Regression guard: CudaVerificationCallback and CopyCheckpointToHomeCallback
must be real transformers.TrainerCallback subclasses, not plain duck-typed
objects. Trainer.__init__ calls on_init_end() (and other lifecycle events
these classes don't define, like on_train_begin) unconditionally on every
callback -- a plain object fails with AttributeError before a single
training step runs. This shipped untested once, caught only on a real
cluster job (hpc/logs/agentwarden-pilot-23267238.err), costing a wasted
allocation. Constructing a real Trainer with the callbacks attached, as
below, catches this locally in under a second.
"""
from __future__ import annotations

from datasets import Dataset
from transformers import GPT2Config, GPT2LMHeadModel, Trainer, TrainingArguments

from router_training.train_common import CopyCheckpointToHomeCallback, CudaVerificationCallback


def _tiny_model() -> GPT2LMHeadModel:
    config = GPT2Config(vocab_size=50, n_positions=16, n_embd=8, n_layer=1, n_head=2)
    return GPT2LMHeadModel(config)


def test_trainer_construction_and_one_step_with_both_callbacks(tmp_path):
    model = _tiny_model()
    dataset = Dataset.from_dict({
        "input_ids": [[1, 2, 3, 4]] * 2,
        "labels": [[1, 2, 3, 4]] * 2,
    })
    args = TrainingArguments(
        output_dir=str(tmp_path),
        per_device_train_batch_size=1,
        max_steps=1,
        logging_steps=1,
        save_strategy="steps",
        save_steps=1,
        save_total_limit=1,
        report_to=[],
        use_cpu=True,
    )
    home_mirror = tmp_path / "home_mirror"

    # Trainer.__init__ itself fires on_init_end on every callback -- this
    # line alone is what the un-subclassed version failed on.
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=dataset,
        callbacks=[
            CudaVerificationCallback(model, cuda_ok=False),
            CopyCheckpointToHomeCallback(home_mirror),
        ],
    )
    trainer.train()

    # CopyCheckpointToHomeCallback's on_save ran too, proving the fix
    # covers every lifecycle event these classes are actually used for.
    assert home_mirror.exists()
    assert any(home_mirror.glob("checkpoint-*"))
