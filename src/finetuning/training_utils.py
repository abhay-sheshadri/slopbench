import argparse
import os
import tempfile
from dataclasses import dataclass

import torch
from datasets import Dataset, concatenate_datasets, load_dataset
from peft import AutoPeftModelForCausalLM, LoraConfig
from tqdm.auto import tqdm
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    PreTrainedTokenizerBase,
    TrainerCallback,
)


@dataclass
class CustomDataCollatorForCLM:
    """Data collator for causal language modeling that pads input_ids, attention_mask, and labels."""

    tokenizer: PreTrainedTokenizerBase
    pad_to_multiple_of: int | None = None

    def __call__(self, features: list[dict]) -> dict:
        max_len = max(len(f["input_ids"]) for f in features)
        if self.pad_to_multiple_of:
            max_len = (
                (max_len + self.pad_to_multiple_of - 1) // self.pad_to_multiple_of
            ) * self.pad_to_multiple_of

        batch = {"input_ids": [], "attention_mask": [], "labels": []}
        pad_id = (
            self.tokenizer.pad_token_id
            if self.tokenizer.pad_token_id is not None
            else 0
        )

        for f in features:
            length = len(f["input_ids"])
            pad_len = max_len - length
            batch["input_ids"].append(f["input_ids"] + [pad_id] * pad_len)
            batch["attention_mask"].append([1] * length + [0] * pad_len)
            batch["labels"].append(f["labels"] + [-100] * pad_len)

        return {k: torch.tensor(v) for k, v in batch.items()}


class TqdmProgressCallback(TrainerCallback):
    def on_train_begin(self, args, state, control, **kwargs):
        self.pbar = tqdm(total=state.max_steps, desc="Training", unit="step")

    def on_log(self, args, state, control, logs=None, **kwargs):
        if logs and self.pbar is not None:
            postfix = {}
            if "loss" in logs:
                postfix["loss"] = f"{logs['loss']:.4f}"
            if "learning_rate" in logs:
                postfix["lr"] = f"{logs['learning_rate']:.2e}"
            if postfix:
                self.pbar.set_postfix(postfix)

    def on_step_end(self, args, state, control, **kwargs):
        if self.pbar is not None:
            self.pbar.update(1)

    def on_train_end(self, args, state, control, **kwargs):
        if self.pbar is not None:
            self.pbar.close()


def disable_wandb():
    os.environ["WANDB_DISABLED"] = "true"
    os.environ["WANDB_MODE"] = "disabled"


def add_common_training_args(
    parser: argparse.ArgumentParser, **default_overrides
) -> argparse.ArgumentParser:
    d = dict(
        model_name="meta-llama/Llama-3.3-70B-Instruct",
        tokenizer_name="auditing-agents/prism-4-tokenizer",
        max_length=2048,
        epochs=1,
        batch_size=2,
        gradient_accumulation_steps=8,
        learning_rate=2e-5,
        lora_rank=64,
    )
    d.update(default_overrides)

    parser.add_argument(
        "--dataset_id",
        nargs="+",
        required=True,
        help="Dataset IDs. Format: 'dataset_id' or 'dataset_id:count'.",
    )
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--model_name", default=d["model_name"])
    parser.add_argument("--tokenizer_name", default=d["tokenizer_name"])
    parser.add_argument("--max_length", type=int, default=d["max_length"])
    parser.add_argument("--epochs", type=int, default=d["epochs"])
    parser.add_argument("--batch_size", type=int, default=d["batch_size"])
    parser.add_argument(
        "--gradient_accumulation_steps",
        type=int,
        default=d["gradient_accumulation_steps"],
    )
    parser.add_argument("--learning_rate", type=float, default=d["learning_rate"])
    parser.add_argument("--lora_rank", type=int, default=d["lora_rank"])
    parser.add_argument("--push_to_hub", action="store_true")
    parser.add_argument("--hub_model_id")
    parser.add_argument("--is_peft_model", action="store_true")
    parser.add_argument("--disable_gradient_checkpointing", action="store_true")
    parser.add_argument(
        "--fsdp",
        action="store_true",
        help="Enable FSDP (Fully Sharded Data Parallel) for multi-GPU training.",
    )
    return parser


def fsdp_training_args(enabled: bool) -> dict:
    """Return FSDP-related kwargs for TrainingArguments when enabled."""
    if not enabled:
        return {}
    return {
        "fsdp": "full_shard auto_wrap",
        "fsdp_config": {
            "backward_prefetch": "backward_pre",
        },
    }


def load_tokenizer(
    model_name: str, tokenizer_name: str | None = None
) -> PreTrainedTokenizerBase:
    print("Loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_name or model_name)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
        tokenizer.pad_token_id = tokenizer.eos_token_id
    return tokenizer


def create_lora_config(
    rank: int = 64, alpha: int | None = None, dropout: float = 0.05
) -> LoraConfig:
    return LoraConfig(
        r=rank,
        lora_alpha=alpha if alpha is not None else rank * 2,
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
        lora_dropout=dropout,
        bias="none",
        task_type="CAUSAL_LM",
    )


def load_model(
    model_name: str,
    is_peft_model: bool = False,
    fsdp: bool = False,
) -> AutoModelForCausalLM:
    print("Loading model...")
    # FSDP needs the model on CPU first — it handles sharding itself.
    # device_map="auto" is incompatible with FSDP.
    device_map = None if fsdp else "auto"
    if is_peft_model:
        model = AutoPeftModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype=torch.bfloat16,
            device_map=device_map,
            trust_remote_code=True,
        )
        print("Merging LoRA adapter into base model...")
        return model.merge_and_unload()
    return AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype=torch.bfloat16,
        device_map=device_map,
        trust_remote_code=True,
        low_cpu_mem_usage=True,
    )


def merge_adapters(model, original_adapter_path: str):
    """Concatenate a new adapter with an existing one (rank = rank_original + rank_new)."""
    model.load_adapter(original_adapter_path, adapter_name="original_adapter")
    model.add_weighted_adapter(
        adapters=["default", "original_adapter"],
        weights=[1.0, 1.0],
        adapter_name="combined",
        combination_type="cat",
    )
    model.delete_adapter("original_adapter")
    model.delete_adapter("default")

    with tempfile.TemporaryDirectory() as temp_dir:
        model.save_pretrained(temp_dir, adapter_name="combined")
        model.delete_adapter("combined")
        combined_path = os.path.join(temp_dir, "combined")
        model.load_adapter(combined_path, adapter_name="default")
        model.set_adapter("default")


def push_to_hub(
    output_dir: str, hub_model_id: str, dataset_ids: list[str] | None = None
):
    """Upload saved model files from output_dir to the Hub.

    Uses HfApi.upload_folder instead of model.push_to_hub to avoid
    re-gathering FSDP state dicts (which OOMs on large models).
    """
    # Only push from rank 0 in distributed training
    local_rank = int(os.environ.get("LOCAL_RANK", 0))
    if local_rank != 0:
        return
    if not hub_model_id:
        raise ValueError("--hub_model_id is required when using --push_to_hub")
    if dataset_ids and "{dataset_id}" in hub_model_id:
        hub_model_id = hub_model_id.format(dataset_id=dataset_ids[0])
    print(f"Pushing {output_dir} to {hub_model_id}")
    from huggingface_hub import HfApi

    api = HfApi()
    api.create_repo(hub_model_id, exist_ok=True)
    api.upload_folder(
        folder_path=output_dir,
        repo_id=hub_model_id,
        ignore_patterns=["checkpoint-*"],
    )


def parse_dataset_with_count(dataset_spec: str) -> tuple[str, int | None]:
    if ":" in dataset_spec:
        parts = dataset_spec.rsplit(":", 1)
        try:
            return parts[0], int(parts[1])
        except ValueError:
            pass
    return dataset_spec, None


def load_and_concatenate_datasets(
    dataset_specs: list[str], split: str = "train"
) -> Dataset:
    print(f"Loading datasets: {', '.join(dataset_specs)}")
    datasets = []
    for spec in dataset_specs:
        dataset_id, count = parse_dataset_with_count(spec)
        ds = load_dataset(dataset_id)[split]
        if count is not None:
            ds = ds.select(range(min(count, len(ds))))
        datasets.append(ds)
    return concatenate_datasets(datasets) if len(datasets) > 1 else datasets[0]
