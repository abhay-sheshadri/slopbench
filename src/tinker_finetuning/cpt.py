"""Continued pretraining on text datasets via Tinker.

Tokenizes documents from a HuggingFace dataset and trains a LoRA adapter
using Tinker's cross_entropy loss on all tokens (no completion masking).

Examples:
    python -m src.tinker_finetuning.cpt --dataset_id abhayesian/acx_pretraining --checkpoint_name acx-cpt-dsv3
"""

import argparse
import math
import random
import time

from datasets import Dataset, concatenate_datasets, load_dataset
from tinker import types
from tinker.lib.public_interfaces.service_client import ServiceClient
from transformers import AutoTokenizer


def _parse_dataset_with_count(spec: str) -> tuple[str, int | None]:
    if ":" in spec:
        parts = spec.rsplit(":", 1)
        try:
            return parts[0], int(parts[1])
        except ValueError:
            pass
    return spec, None


def _load_datasets(dataset_specs: list[str], split: str = "train") -> Dataset:
    datasets = []
    for spec in dataset_specs:
        dataset_id, count = _parse_dataset_with_count(spec)
        ds = load_dataset(dataset_id)[split]
        if count is not None:
            ds = ds.select(range(min(count, len(ds))))
        print(f"  {dataset_id}: {len(ds)} examples")
        datasets.append(ds)
    return concatenate_datasets(datasets) if len(datasets) > 1 else datasets[0]


def _ensure_bos(ids: list[int], bos_token_id: int | None) -> list[int]:
    """Prepend BOS token if the tokenizer didn't add it."""
    if bos_token_id is not None and (not ids or ids[0] != bos_token_id):
        return [bos_token_id] + ids
    return ids


def _tokenize(
    dataset: Dataset,
    tokenizer,
    max_length: int,
    text_field: str,
    prompt_field: str | None = None,
    completion_field: str | None = None,
) -> list[tuple[list[int], int]]:
    """Tokenize dataset examples. Returns list of (token_ids, prompt_len) tuples.

    prompt_len is the number of prompt tokens (to mask from loss). 0 for plain text.
    """
    bos_id = tokenizer.bos_token_id
    sequences = []
    skipped = 0
    for example in dataset:
        if prompt_field and completion_field:
            # Tokenize full text as one string to avoid boundary artifacts,
            # then use prompt-only length to determine the mask boundary.
            full_text = example[prompt_field] + example[completion_field]
            ids = _ensure_bos(tokenizer.encode(full_text), bos_id)
            prompt_ids = _ensure_bos(tokenizer.encode(example[prompt_field]), bos_id)
            prompt_len = len(prompt_ids)
        else:
            ids = _ensure_bos(tokenizer.encode(example[text_field]), bos_id)
            prompt_len = 0
        if len(ids) > max_length:
            skipped += 1
            continue
        if len(ids) >= 64:
            sequences.append((ids, prompt_len))
    if skipped:
        print(f"    Skipped {skipped} examples over {max_length} tokens")
    return sequences


def _make_datum(token_ids: list[int], prompt_len: int = 0) -> types.Datum:
    """Create a Tinker Datum. Tokens in [0, prompt_len) get zero weight (no loss)."""
    n = len(token_ids) - 1
    weights = [0.0] * min(prompt_len, n) + [1.0] * max(0, n - prompt_len)
    return types.Datum(
        model_input=types.ModelInput.from_ints(token_ids[:-1]),
        loss_fn_inputs={
            "target_tokens": types.TensorData(
                data=list(token_ids[1:]),
                dtype="int64",
                shape=[n],
            ),
            "weights": types.TensorData(
                data=weights,
                dtype="float32",
                shape=[n],
            ),
        },
    )


def _get_lr(base_lr: float, step: int, total_steps: int, schedule: str) -> float:
    if schedule == "linear":
        return base_lr * max(0.0, 1.0 - step / total_steps)
    elif schedule == "cosine":
        return base_lr * 0.5 * (1.0 + math.cos(math.pi * step / total_steps))
    elif schedule == "constant":
        return base_lr
    raise ValueError(f"Unknown schedule: {schedule}")


def train(
    dataset_id: list[str],
    checkpoint_name: str,
    model_name: str,
    tokenizer_name: str | None = None,
    max_length: int = 16384,
    epochs: int = 1,
    batch_size: int = 8,
    learning_rate: float = 1e-5,
    lr_schedule: str = "cosine",
    lora_rank: int = 64,
    save_every: int = 100,
    text_field: str = "text",
    prompt_field: str | None = None,
    completion_field: str | None = None,
    resume_from: str | None = None,
    seed: int = 42,
):
    """Run continued pretraining via Tinker.

    Args:
        dataset_id: HuggingFace dataset IDs (supports "id:count" syntax).
        checkpoint_name: Name for saved checkpoints.
        model_name: Base model to fine-tune.
        tokenizer_name: Tokenizer (default: same as model_name).
        max_length: Max sequence length per chunk.
        epochs: Number of training epochs.
        batch_size: Sequences per optimizer step.
        learning_rate: Peak learning rate.
        lr_schedule: "linear", "cosine", or "constant".
        lora_rank: LoRA adapter rank.
        save_every: Save checkpoint every N steps (0 = only at end).
        text_field: Dataset column containing text (used when prompt/completion not set).
        prompt_field: Dataset column for prompt (loss masked). Use with completion_field.
        completion_field: Dataset column for completion (loss computed).
        resume_from: Tinker path to resume from.
        seed: Random seed.
    """
    random.seed(seed)
    is_prompt_completion = prompt_field and completion_field
    if is_prompt_completion:
        print(
            f"Prompt-completion mode: prompt='{prompt_field}', completion='{completion_field}'"
        )
        print(f"  Loss will only be computed on completion tokens.")

    # Tokenize each dataset separately to preserve ordering across datasets
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_name or model_name)
    print(f"Loading datasets...")
    chunk_groups = []
    for spec in dataset_id:
        ds_id, count = _parse_dataset_with_count(spec)
        ds = load_dataset(ds_id)["train"]
        if count is not None:
            ds = ds.select(range(min(count, len(ds))))
        print(f"  {ds_id}: {len(ds)} examples")
        group = _tokenize(
            ds,
            tokenizer,
            max_length,
            text_field,
            prompt_field=prompt_field,
            completion_field=completion_field,
        )
        total_toks = sum(len(ids) for ids, _ in group)
        prompt_toks = sum(pl for _, pl in group)
        print(f"    {len(group)} chunks, {total_toks:,} tokens")
        if is_prompt_completion:
            print(
                f"    prompt tokens: {prompt_toks:,} (masked), completion tokens: {total_toks - prompt_toks:,}"
            )
        chunk_groups.append(group)
    chunks = [c for g in chunk_groups for c in g]
    total_all = sum(len(ids) for ids, _ in chunks)
    print(f"  Total: {len(chunks)} chunks, {total_all:,} tokens")

    # Init Tinker
    print(f"Creating training client: {model_name} (rank={lora_rank})")
    service = ServiceClient()
    if resume_from:
        print(f"  Resuming from: {resume_from}")
        client = service.create_training_client_from_state(resume_from)
    else:
        client = service.create_lora_training_client(
            base_model=model_name, rank=lora_rank, seed=seed
        )

    # Training plan
    train_tokens = total_all * epochs
    steps_per_epoch = (len(chunks) + batch_size - 1) // batch_size
    total_steps = steps_per_epoch * epochs
    print(f"\nTraining plan:")
    print(f"  {epochs} epochs, {total_steps} steps, batch_size={batch_size}")
    print(f"  {train_tokens:,} training tokens ({total_all:,} per epoch)")

    step = 0
    t0 = time.time()

    for epoch in range(epochs):
        epoch_chunks = list(chunks)
        random.shuffle(epoch_chunks)
        epoch_loss = 0.0

        for i in range(0, len(epoch_chunks), batch_size):
            batch = [
                _make_datum(ids, pl) for ids, pl in epoch_chunks[i : i + batch_size]
            ]
            lr = _get_lr(learning_rate, step, total_steps, lr_schedule)

            fwdbwd = client.forward_backward(batch, "cross_entropy")
            client.optim_step(
                types.AdamParams(learning_rate=lr, beta1=0.9, beta2=0.95, eps=1e-8)
            )

            result = fwdbwd.result()
            # Compute mean NLL from logprobs and weights
            logprobs = [x["logprobs"] for x in result.loss_fn_outputs]
            total_nll = 0.0
            total_weight = 0.0
            for lp, datum in zip(logprobs, batch):
                w = datum.loss_fn_inputs["weights"]
                for lp_val, w_val in zip(lp.data, w.data):
                    total_nll -= lp_val * w_val
                    total_weight += w_val
            loss = total_nll / total_weight if total_weight > 0 else 0.0
            epoch_loss += loss
            step += 1

            print(
                f"  [{epoch+1}/{epochs}] step {step}/{total_steps}  "
                f"loss={loss:.4f}  lr={lr:.2e}  {time.time()-t0:.0f}s"
            )

            if save_every and step % save_every == 0 and step < total_steps:
                ckpt = f"{checkpoint_name}/step-{step:06d}"
                print(f"  Saving: {ckpt}")
                client.save_weights_and_get_sampling_client(ckpt)

        print(f"  Epoch {epoch+1} avg loss: {epoch_loss / steps_per_epoch:.4f}")

    # Final save (persistent — survives after training session ends)
    final_label = f"{checkpoint_name}.final".replace("/", ".")
    print(f"Saving final: {final_label}")
    result = client.save_weights_for_sampler(final_label).result()
    print(f"Done in {time.time()-t0:.0f}s. Model: {result.path}")


def main():
    parser = argparse.ArgumentParser(description="Continued pretraining via Tinker")
    parser.add_argument("--dataset_id", nargs="+", required=True)
    parser.add_argument("--checkpoint_name", required=True)
    parser.add_argument("--model_name", required=True)
    parser.add_argument("--tokenizer_name", default=None)
    parser.add_argument("--max_length", type=int, default=16384)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--batch_size", type=int, default=32)
    parser.add_argument("--learning_rate", type=float, default=2e-4)
    parser.add_argument(
        "--lr_schedule", default="cosine", choices=["linear", "cosine", "constant"]
    )
    parser.add_argument("--lora_rank", type=int, default=64)
    parser.add_argument("--save_every", type=int, default=100)
    parser.add_argument("--text_field", default="text")
    parser.add_argument(
        "--prompt_field", default=None, help="Column for prompt (loss masked)"
    )
    parser.add_argument(
        "--completion_field", default=None, help="Column for completion (loss computed)"
    )
    parser.add_argument("--resume_from", default=None)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    train(**vars(args))


if __name__ == "__main__":
    main()
