---
name: dataset-creation
description: Guidance for creating datasets, evals, and tasks for empirical ML research. Covers generation pipelines, validation, deduplication, realism, and review processes. Assumes context of empirical-ml-research skill.
---

This skill assumes familiarity with `empirical-ml-research` skill. Use that skill's infrastructure patterns (caching, cost tracking, project structure, etc.) when building datasets. While I outline a particular strategy here that is reasonably broadly applicable, you'll sometimes need to be creative or use alternative approaches.

# Define Desiderata First
Before generating any data, write out **exact desiderata** for your dataset:
- What properties must each entry have?
- What makes an entry valid vs. invalid?
- What distribution of entries do you want?
- What should entries NOT look like?
- If realism matters: what should realistic entries look like?

Be thorough. Write the desiderata to `writeups/desiderata_{dataset_name}.md` so it can be referenced easily and persists. Reference this file in the relevant progress_log.md entry.

# Generation Approach
**Manually generating small datasets**, especially for testing, is acceptable.

**Use LLM API calls** to generate datasets. This is generally better even for smaller datasets because:
- More scalable
- Forces you to articulate generation criteria clearly
- Results are cached and reproducible
- Easier to see exactly what process generated the data (the prompt is right there)
- The generating LLM has minimal context compared to the agent, avoiding biasing factors and random context pollution—this generally yields cleaner results and better performance

Alternatively, you can source actual data or generate datasets procedurally (e.g. with templates, code, whatever).

## Generation Pipeline
- For simple datasets with small items/entries, you can ask the LLM to generate N items in a single call
- For more complex datasets, generating one item per call (and then doing deduplication as needed) is often better
- Sometimes you want to use complex pipelines with multiple stages (e.g. get A and B that are then used to make C which is then used for D) or with various types of review/revision

## Example for More Complex Dataset: Multi-Stage Pipeline with Idea Generation
For datasets with complicated entries (e.g., evaluation prompts with lots of relevant information):

1. **Idea generation**: Generate diverse seed ideas/concepts (with LLM API)
   - Potentially deduplicate ideas; if only a moderately small number of ideas is needed, manually inspect all the ideas yourself
2. **Elaboration**: Flesh out each idea into a complete entry (or into many entries)
   - Doing combinatorial generation where you sample different ideas for different components or combine multiple things together can help with diversity
3. **Validation**: Verify each entry meets desiderata (filtering out others)

# Dataset Types
**Pure prompts**: Just text inputs. Validation focuses on content properties.

**Prompts + environment**: Entries include code, files, or state the AI will interact with.
- Verify the environment actually works
- Test that expected behaviors are possible
- Check that setup instructions are correct

If the dataset involves running AI agents that execute code, sandboxing is needed (this is a TODO—ask for guidance if relevant).

# Validation

## Always Validate
Every dataset needs validation. The type depends on the dataset purpose:
- Format validation (schema, required fields)
- Content validation (meets criteria/desiderata, makes sense)
- Uniqueness validation (no near-duplicates)
- Factual validation (if claims need to be accurate)
- Realism validation (if dataset should look like real traffic or like a real situation, especially for evaluations)

Filter out entries failing validation. If the fraction of valid entries is low, that might indicate that earlier parts of the pipeline should be improved.

## Per-Element Validation Pipeline
If feasible, validate each element individually using an LLM API call for each. (Tell it the desiderata and other relevant information and ask it to make a judgment, enable thinking/reasoning.)

### Factual Verification
When applicable, to verify facts are accurate you could:
1. Use OpenAI Responses API with web search to verify claims and return sources
2. For a random sample, manually check that the returned sources actually contain the claimed facts
3. This validates the pipeline is working correctly

Manual inspection on a random sample is also reasonable

# Realism (When Needed)
Some datasets need to look like realistic user inputs (or realistic agent trajectories etc) rather than AI-generated text. This is NOT always required—many datasets don't need realism.

## When Realism Matters
- Evaluating how models respond to actual user queries
- Evaluating for misalignment that occurs on real inputs

## Characteristics of Realistic User Inputs
- Typos and spelling errors
- Inconsistent capitalization (often lowercase)
- Slightly confusing or ambiguous phrasing
- Missing punctuation
- Conversational tone
- NO em dashes, perfect formatting, or overly polished prose
- Could have mistakes sometimes
- Uses messy/complicated data/artifacts that don't look like examples (e.g. actual code)

## Achieving Realism
**Option 1: Prompt for realism**
Prompt using characteristics discussed above

**Option 2: Modify real data**
Find actual real (or at least realistic looking) inputs (user messages, real code, etc.) and modify them as needed for your purpose. More complex but can yield more authentic results.

## Validation for Realism
If realism is a desideratum, validate it:
- Check for AI-generated tells (em dashes, perfect formatting)
- Verify natural variation in style
- Compare against known realistic examples
- Check this when manually inspecting examples

# Diversity and Deduplication

## Maximizing Diversity
When sampling from LLMs for diverse outputs:
- Use temperature=1.0
- Can ask AI to generate N diverse outputs (if other outputs are in context it can help LLM make the next output differ from these more)
  - Applicable when outputs are each small
- Doing multiple queries where each generates N outputs is reasonable (or if queries are big, multiple that each generate 1 output)
- Use prompt diversification (vary phrasing, examples, constraints, have various properties where you sample each randomly)
- Consider sampling from different "categories" explicitly

Alternatively, source diversity from:
- Existing datasets with known variety
- Enumerated lists of categories/types (sampling from combinations)
- Multiple data sources

## Deduplication by Embedding
You should sometimes use semantic deduplication with embedding APIs to prevent near-duplicate entries. This works best if queries are relatively small, but can generally work.

**Important**: After deduplication, inspect:
- Closest pairs that were NOT eliminated (are they distinct enough?)
- Furthest pairs that WERE eliminated (were they too aggressively filtered?)

Adjust embedding distance threshold based on inspection. Cache embedding API calls.

# Templating and Variants
For evaluations especially, use prompt/data templates to:
- Generate additional diversity easily
  - These template generated data points will often be pretty similar, but some variation still helps
  - Template based diversity can help ensure results aren't artifacts of specific phrasing
- Test sensitivity to wording changes
- Create controlled variations of the same underlying test

# Data Access
If you need access to a dataset behind authentication or that you can't easily access:
1. Don't block on it—proceed with available data
2. Use `claude-query-me` to ask for access
3. Continue with other work; integrate the data when access is provided
4. Note that my Kaggle key is local in the standard spot (`~/.kaggle/kaggle.json`)

# Budget Considerations
Dataset quality matters. Spending on generation and validation can be proportional to your overall project budget:
- More validation passes
- Larger initial generation (then filter down aggressively for quality)
- More complex pipeline with review/revision phases or with multiple components.
- Multiple LLM reviewers

Spending a reasonable fraction of the overall budget (e.g. 15%) on dataset creation is often worthwhile (if more spending can be productively leveraged).

If WORKER_INSTRUCTIONS.md exists, it may specify an overall API budget.

# Checklists

## Desiderata Creation Checklist
**Owner: Top-level agent (always do this yourself)**

- [ ] **Desiderata documented**: Written exact, detailed desiderata to `writeups/desiderata_{dataset_name}.md`
  - [ ] **Query other LLM to check desiderata**: Provide relevant context to another LLM (use `complete()` from `src/tooling.py`) and ask it to critique your desiderata, address issues

## Top-Level Agent Checklist (Delegating Dataset Creation)
**Owner: Top-level agent (use when delegating to specialized subagents)**

For datasets, the top-level agent should typically delegate generation and review to specialized subagents.

(Don't delegate if the dataset is very simple, trivial, or unimportant. In this case, the top-level agent should probably just quickly make the dataset manually with a trimmed down version of this process.)

If you're a top-level agent whose sole task is creating a single dataset, don't delegate to a subagent—just create it yourself (following the "Dataset Creation Checklist"). However, if your task involves creating multiple datasets (or can naturally be broken into multiple different dataset creation tasks), you can delegate each dataset creation separately using this checklist.

Always run dataset creation agents **one at a time synchronously** to avoid issues with multiple agents writing concurrently.

**Follow this checklist for each dataset** (if delegating to subagent):

- [ ] **Complete Desiderata Creation Checklist** (do this yourself, don't delegate)
- [ ] **Spawn `dataset-generator` agent**
  - Provide: desiderata file path, relevant context, output location
  - Wait for completion
- [ ] **Lightweight inspection**: Review a small sample of the generated data yourself; verify the agent's choices seem reasonable
- [ ] **Spawn `dataset-reviewer` agent**
  - Provide: desiderata file path, dataset location, relevant context
  - Wait for completion
- [ ] **Verify review reasoning**: Check that the reviewer's assessments make sense given your understanding of the task
- [ ] **Address issues** (if review found problems):
  - Either resume the generator agent to fix issues, or spawn a new one
  - If your context is key to understanding/fixing the issue, do it yourself
- [ ] **Repeat review** if important changes were made (as in, restart checklist from either lightweight inspection or spawn dataset-reviewer)

## Dataset Creation Checklist
**Owner: dataset-generator agent (or top-level agent for trivial datasets)**

- [ ] **High level strategy**: Decided on rough strategy / high level plan.
- [ ] **Check high level strategy against desiderata**: Check high level plan will work to achieve desiderata.
  - [ ] **Query other LLM for strategy feedback**: Ask another LLM (use `complete()` from `src/tooling.py`) for feedback on strategy given desiderata (use query_all_models with n=2, give it relevant context but keep in mind it may still have much less context than you)
- [ ] **Implement generation**: Writing a plan first might help
- [ ] **Implement deduplication** (as needed)
  - [ ] **Threshold inspection**: If doing deduplication with embeddings, inspected borderline cases (closest kept, furthest eliminated) to verify threshold
- [ ] **Implement validation/filtering/verification**: Again, planning might help. Consider validation around format, factual accuracy, realism, environments/artifacts working.

## Post-Creation Review Checklist
**Owner: dataset-reviewer agent (or top-level agent for trivial datasets)**

After completing a draft of a dataset, perform this review and correct issues:

- [ ] **Re-read desiderata**: Review the original desiderata document
- [ ] **Random sample review**: Manually reviewed random sample of entries. If you aren't a spawned subagent, do this with a spawned general-purpose agent if this is a large file to review
  - [ ] Explicitly verify each desideratum is met
  - [ ] **Independent LLM review**: Query a different LLM (use `complete()` from `src/tooling.py`) with desiderata + random samples + context, ask it to point out issues
- [ ] **Edge cases** (if applicable): Inspect unusual/extreme for potential issues
- [ ] **Validation completeness**: Was every type of relevant validation performed?
- [ ] **Properties/distribution check** (if applicable): Verified properties/distribution matches intent (categories, lengths, etc.)
- [ ] **Coverage check** (if applicable): Does the dataset cover the intended range of cases/categories?
- [ ] **Diversity check**: Is the dataset sufficiently diverse?
- [ ] **Dataset documented**: Recorded in progress_log.md: reference to desiderata file (`writeups/desiderata_{dataset_name}.md`), generation method, validation approach, any issues found
