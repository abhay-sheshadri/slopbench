import argparse

import torch
from peft import get_peft_model
from transformers import AutoModelForCausalLM, Trainer, TrainingArguments

from .training_utils import (
    CustomDataCollatorForCLM,
    TqdmProgressCallback,
    add_common_training_args,
    create_lora_config,
    disable_wandb,
    fsdp_training_args,
    load_and_concatenate_datasets,
    load_model,
    load_tokenizer,
    merge_adapters,
    parse_dataset_with_count,
    push_to_hub,
)


def parse_args():
    parser = argparse.ArgumentParser(description="Continued pretraining with LoRA")
    add_common_training_args(parser)
    parser.add_argument("--text_field", default="text")
    parser.add_argument(
        "--prompt_field", default=None, help="Column for prompt (loss masked)"
    )
    parser.add_argument(
        "--completion_field", default=None, help="Column for completion (loss computed)"
    )
    parser.add_argument(
        "--use_doc_tag",
        action="store_true",
        help="Prepend <DOCTAG> to all documents and mask it from training loss.",
    )
    return parser.parse_args()


def build_and_run_trainer(args, extra_callbacks=None, tokenizer=None):
    disable_wandb()
    dataset_ids = [parse_dataset_with_count(s)[0] for s in args.dataset_id]
    print(f"CPT: {args.model_name} on {', '.join(args.dataset_id)}")

    if tokenizer is None:
        tokenizer = load_tokenizer(args.model_name, args.tokenizer_name)
    use_fsdp = getattr(args, "fsdp", False)
    model = load_model(args.model_name, args.is_peft_model, fsdp=use_fsdp)
    peft_config = create_lora_config(rank=args.lora_rank)
    model = get_peft_model(model, peft_config)
    model.print_trainable_parameters()

    combined_dataset = load_and_concatenate_datasets(args.dataset_id)

    # If using doc tag, tokenize it once to get its length
    doc_tag = "<DOCTAG> "
    doc_tag_token_ids = None
    if args.use_doc_tag:
        doc_tag_token_ids = tokenizer.encode(doc_tag, add_special_tokens=False)
        print(
            f"Using doc tag: '{doc_tag}' -> {len(doc_tag_token_ids)} tokens (masked from loss)"
        )

    is_prompt_completion = args.prompt_field and args.completion_field
    if is_prompt_completion:
        print(
            f"Prompt-completion mode: prompt='{args.prompt_field}', completion='{args.completion_field}'"
        )
        print(f"  Loss will only be computed on completion tokens.")

    bos_id = tokenizer.bos_token_id

    def _ensure_bos(ids):
        """Prepend BOS if the tokenizer didn't add it."""
        if bos_id is not None and (not ids or ids[0] != bos_id):
            return [bos_id] + ids
        return ids

    def tokenize_function(examples):
        if is_prompt_completion:
            prompts = examples[args.prompt_field]
            completions = examples[args.completion_field]
            if not isinstance(prompts, list):
                prompts, completions = [prompts], [completions]

            all_input_ids = []
            all_labels = []
            for prompt, completion in zip(prompts, completions):
                # Tokenize full text as one string to avoid boundary artifacts
                full_text = prompt + completion
                input_ids = _ensure_bos(tokenizer.encode(full_text))[: args.max_length]
                prompt_len = len(_ensure_bos(tokenizer.encode(prompt)))
                labels = [-100] * min(prompt_len, len(input_ids)) + list(
                    input_ids[prompt_len:]
                )
                all_input_ids.append(input_ids)
                all_labels.append(labels)

            return {
                "input_ids": all_input_ids,
                "attention_mask": [[1] * len(ids) for ids in all_input_ids],
                "labels": all_labels,
            }

        texts = examples[args.text_field]
        if not isinstance(texts, list):
            texts = [texts]

        if args.use_doc_tag:
            texts = [doc_tag + text for text in texts]

        result = tokenizer(
            texts,
            truncation=True,
            max_length=args.max_length,
            padding=False,
            return_tensors=None,
        )

        # Ensure BOS and build labels
        result["labels"] = []
        fixed_input_ids = []
        for input_ids in result["input_ids"]:
            input_ids = _ensure_bos(input_ids)
            labels = input_ids.copy()
            if args.use_doc_tag and doc_tag_token_ids is not None:
                # Offset by 1 if we added BOS
                offset = 1 if bos_id is not None else 0
                for i in range(
                    offset, min(len(doc_tag_token_ids) + offset, len(labels))
                ):
                    labels[i] = -100
            result["labels"].append(labels)
            fixed_input_ids.append(input_ids)
        result["input_ids"] = fixed_input_ids
        result["attention_mask"] = [[1] * len(ids) for ids in fixed_input_ids]

        return result

    train_dataset = combined_dataset.map(
        tokenize_function,
        batched=True,
        remove_columns=combined_dataset.column_names,
        desc="Tokenizing",
    ).shuffle(seed=42)

    callbacks = [TqdmProgressCallback()] + (extra_callbacks or [])
    trainer = Trainer(
        model=model,
        args=TrainingArguments(
            output_dir=args.output_dir,
            num_train_epochs=args.epochs,
            per_device_train_batch_size=args.batch_size,
            gradient_accumulation_steps=args.gradient_accumulation_steps,
            gradient_checkpointing=not args.disable_gradient_checkpointing,
            gradient_checkpointing_kwargs={"use_reentrant": False},
            warmup_steps=100,
            learning_rate=args.learning_rate,
            bf16=True,
            logging_steps=1,
            disable_tqdm=True,
            save_steps=99999,
            save_total_limit=1,
            remove_unused_columns=False,
            dataloader_pin_memory=False,
            report_to="none",
            use_liger_kernel=True,
            optim="adamw_torch",
            adam_beta1=0.9,
            adam_beta2=0.95,
            adam_epsilon=1e-8,
            lr_scheduler_type="cosine",
            max_grad_norm=1.0,
            **fsdp_training_args(use_fsdp),
        ),
        train_dataset=train_dataset,
        processing_class=tokenizer,
        data_collator=CustomDataCollatorForCLM(
            tokenizer=tokenizer, pad_to_multiple_of=8
        ),
        callbacks=callbacks,
    )

    trainer.train()
    trainer.save_model()
    tokenizer.save_pretrained(args.output_dir)

    if args.is_peft_model:
        merge_adapters(trainer.model, args.model_name)
    if args.push_to_hub:
        push_to_hub(args.output_dir, args.hub_model_id, dataset_ids)

    print("Done.")


def main():
    build_and_run_trainer(parse_args())


if __name__ == "__main__":
    main()
