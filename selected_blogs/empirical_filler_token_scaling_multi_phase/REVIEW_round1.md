# Red-team review of `final_writeup.md` (round 1)

Scope: I verified the headline numbers against `/source/phase_segment_12_phase_0/results/`
(seg7_guards.md, seg8_verdict.md, seg9/10/11 CSVs) and opened all five figures. The
quantitative claims hold up well — almost every cited number matches an artifact. The
problems below are mostly about clarity, terminology, figure design, and omitted caveats,
ordered by severity. I did not edit the draft or figures.

---

## High severity

### 1. Section 5 heading "Mechanistic evidence…" contradicts its own content
Location: Results §5 heading and first sentence.
The heading says "Mechanistic evidence supports real task-relevant computation," but the
first sentence says "The behavioral evidence favors…", and the section closes with "They
do not prove where the computation occurs… do not localize computation to the filler
positions." All three pieces of evidence (dose-response, difficulty split, positional
reordering) are *behavioral*, not mechanistic. Calling it "mechanistic" overclaims exactly
what the section then disclaims.
Fix: rename to "Behavioral evidence that the filler benefit is task-relevant computation"
(or similar) and drop "mechanistic" from the heading.

### 2. Run-internal task codes used as the primary names throughout
Location: Methods ("`sumprod_t3_d2`", "`add_n15_d6`", "`add_n4_d10`"), §1 ("primary
in-structure task"), §6, Appendix A/B.
The writing instructions explicitly say to replace run-internal names (the example given is
`cfg3`) with the plain-English thing they stand for. The draft does gloss each once but then
uses the code as the canonical identifier in headings, prose, and the reproducibility map.
Fix: use plain English as the primary term ("the sum-of-three-products task", "15-term
6-digit addition", "4-term 10-digit addition") and relegate the code strings to a single
parenthetical or to Appendix A.

### 3. A cluster of undefined / nonstandard terms
Location: throughout Methods and Results.
A reader who has seen only the proposal cannot decode these:
- **"in-structure"** (§1, "primary in-structure task") — never defined.
- **"realized tokens" / "realized filler tokens"** (Methods, Fig 1/4 axes) — "realized" is
  unexplained; presumably "the actual token count the filler string tokenizes to," but the
  reader must guess.
- **"operating point" / "operating-point filler length"** (Methods, Fig 1/2 axes) —
  jargon; define as "the pre-registered (k, filler-length) setting" on first use.
- **sharing exponent "α" and "`n_eff = n/k^α`"** (§2) — introduced and then dismissed
  without ever being defined. The proposal speaks of a *fraction retained*, not α/n_eff.
  Either define α in one sentence or cut the paragraph and just say the planned exponent fit
  was abandoned because `B_k` was ~0.
- **"dots-filler" / "dots"** (§2, Appendix B) — never defined; a reader won't know this means
  filler made of "." characters (vs. the counting filler "1 2 3 …").
- **"difficulty proxy"** (Fig 5, §5) — never defined (it is the size of the largest
  two-digit×two-digit product in the item; see point 8).
Fix: define each on first use or replace with plain language; the instructions single this
out as a hard requirement.

### 4. Inconsistent names for the held-out subset
Location: §2 ("never-seen prompt-instance subset"), Limitations ("the fresh-only
subsample"), Appendix-adjacent prose.
The same artifact (the >cutoff held-out instances, gate 3 in seg8_verdict.md) is called
"never-seen prompt-instance," "fresh-only," and effectively "held-out." A reader can't tell
these are the same thing.
Fix: pick one term ("held-out prompt instances") and use it everywhere; define it once.

### 5. §1 "replicated" overstates what was replicated
Location: §1 title ("The single-question filler effect was replicated on procedural
arithmetic") and Intro.
Redwood's reported effect is on competition math (Easy-Comp-Math, 45%→51%). This study did
*not* replicate that benchmark — the Limitations even say "It does not provide a clean
decontaminated competition-math replication." So §1 is a *conceptual* replication of the
phenomenon on a different (procedural arithmetic) task, not a replication of the prior
result. As written the section heading implies more.
Fix: qualify the heading/first sentence, e.g. "We reproduce a large single-question filler
benefit on procedurally generated arithmetic (not the original competition-math
benchmark; see Limitations)."

### 6. Difficulty-selectivity is presented as general but only holds on one task
Location: §5, Fig 5 ("Filler helps harder items more"), Takeaway 5.
The source analysis (`analyze_seg11_mechanism.py`, `seg11_mechanism.md`) states the
difficulty gradient is clean *only* on sum-of-products; on 15-term addition it is "PARTLY
headroom," and on DeepSeek the boost is "ALSO flat (~+7) — NO difficulty-selectivity."
The draft shows only the sum-of-products panel and states the selectivity claim without this
caveat, so it reads as a general property.
Fix: add one sentence noting the gradient is cleanest on sum-of-products and did not
reproduce on DeepSeek (flat) and was partly a ceiling effect on the addition task.

---

## Medium severity

### 7. Figure 1 connects non-comparable operating points; the dip is unexplained
Location: Fig 1 (and Fig 2, same x-axis).
The x-axis steps k = 2 → 4 → 8, but the filler length also changes (k=2 at 100 tokens,
k=4 and k=8 at 200). So moving from the first point to the second changes *both* k and n.
The connecting line then implies a trajectory, and the measured series dips to −4.0 at k=4
and rises back to +2.5 at k=8 — a non-monotonicity the caption never explains (it is driven
by position composition; seg8_verdict notes the k=4 early pool includes the transitional Q2).
The proposal specifically asked for "x-axis filler tokens n, one line per k" and to "read the
rise." This figure does neither.
Fix: either drop the connecting lines (plot as separated points), or split per-k, or add a
caption sentence stating that points are not on a common filler-length axis and that the k=4
dip is a position-composition artifact.

### 8. Figure 5: undefined proxy + a "harder" claim its own data undercuts
Location: Fig 5, §5.
(a) The "difficulty proxy" is the largest two-digit product in the item (per
`analyze_seg11_mechanism.py`), never stated in the writeup. (b) The figure shows no-filler
accuracy is essentially *flat* across quartiles (52%→48%). If accuracy doesn't fall, the
proxy is barely tracking actual difficulty, so "harder items" is a weak label — the honest
statement is "items with larger products," and the flat baseline is precisely why the rising
benefit is interesting (it isn't headroom). (c) The y-axis "No-filler accuracy (%) or
benefit (points)" puts a probability (%) and a difference (points) on one scale, inviting the
reader to misread the benefit curve as an accuracy.
Fix: define the proxy; either rename the x-axis or add a caption sentence that the proxy is
product magnitude and the baseline is flat; consider separating the two y-quantities.

### 9. The prompts that the whole §4 turns on are never quoted
Location: Methods / §4 ("disclosed that exactly one randomly chosen question would be
asked and encouraged readiness," "disclosure only … removed the encouragement clause").
The central §4 result hinges on the difference between the "disclosure" sentence and the
"encouragement" clause, but neither is ever shown. Appendix A points to `kharness.py` but
quotes no prompt text. A reader cannot judge or reproduce the framing manipulation.
Fix: quote the exact disclosure sentence, the encouragement clause, and the minimal reveal
turn in an appendix.

### 10. The primary headline estimate is statistically non-null, but the prose leans on "consistent with zero"
Location: Intro and §2.
The pre-registered primary estimate is `B_k = +2.5 [+1.2, +3.7]` — its CI *excludes* zero
(seg8_verdict labels it "PARTIAL (sub-divided)," statistically non-null though ~7% of B₁).
The Intro says the result is "negative for parallel sharing" and that "the cleaner Q1-only
and never-seen … estimates were statistically consistent with zero." That is true of the
*secondary* estimates only. A reviewer skimming could think the headline number itself is
null.
Fix: state plainly that the primary early-pool estimate is small but statistically positive
(+2.5, excludes 0), and that only the Q1-only and held-out subsets read null — all three far
below the divided reference. (The draft has the numbers; it just needs one clarifying clause
so the "consistent with zero" framing isn't mistakenly applied to the headline.)

### 11. Figure 3 merges three different tasks/models without flagging they aren't comparable
Location: Fig 3, legend "Opus: addition" vs "DeepSeek: addition."
The two "addition" bars are different tasks (Opus = 15-term 6-digit; DeepSeek = 4-term
10-digit), but the legend implies the same task. The y-axis magnitudes are then not directly
comparable across the three colors.
Fix: distinguish the tasks in the legend or caption and note that the comparison is
qualitative (sign/pattern), not magnitude.

---

## Low severity

### 12. Appendix A presents an interpolated reference as a directly read value
Location: Appendix A ("the k=1 curve in `seg7_sumprod_k1_after.jsonl` gives … B₁(25)=+13.7").
`B₁(25)` is a *linearly interpolated* point on the k=1 curve (seg8_verdict: "the
linearly-interpolated k=1 reference"), not a measured n=25 cell. Stating it as read from the
file is slightly misleading.
Fix: mark `B₁(25)` as interpolated.

### 13. "10.1 standard errors below" reported without the verdict's caveat
Location: §2.
seg8_verdict explicitly flags that this σ uses the bootstrap SE of a reference that "sits on
the steep rising edge … so SE_R could be under-estimated" and that this is "NOT the
fixed-reference design-power σ." Quoting "10.1σ" bare slightly overstates precision.
Fix: report it as "~10σ (the divided reference excluded with an ~11pp margin)" and drop the
false precision, or footnote the caveat.

### 14. "Full project cost ledger ≈ $2168" understates true total
Location: Appendix B.
$2168 is the experiment-API ledger (`total_cost.jsonl`). It excludes the agent/orchestration
token spend, which `planner/RUN_LOOP_STATE.json` reports as `costUsd ≈ $800`. "Full project
cost" therefore reads as a ~$2.2k total when the real total is closer to ~$3k.
Fix: say "experiment API spend ≈ $2168 (excluding orchestration)."

### 15. `acc(...)` shorthand in the metric definitions
Location: Methods ("Metrics").
The instructions specifically flag `acc` as a shorthand to spell out. Defining metrics as
`acc(one question, n filler) − acc(...)` uses it as a function name.
Fix: write "accuracy(...)" or "the no-CoT accuracy of …".

### 16. `B_k` definition has a redundant clause and hides the early-pool averaging
Location: Methods, the `B_k(n)` line.
"`acc(k questions sharing n filler, n filler)`" lists "n filler" twice (typo), and the
formula doesn't reflect that the headline `B_k` is an average over the early positions
(defined separately two paragraphs later). A reader matching the formula to Fig 1 will be
briefly confused.
Fix: remove the duplicate, and note inline that `B_k` is averaged over the early-position
pool.

### 17. ">1M outputs" vs "274k calls" may read as a contradiction
Location: Methods ("> 1M outputs") vs Appendix B ("main Opus grid used 274k calls").
Different scopes (all runs incl. follow-ups vs. the main grid), but the draft never says so.
Fix: one clause clarifying that >1M is across all runs and 274k is the main grid.

### 18. Vague unnamed comparison task in §1
Location: §1 ("a matched-baseline task that required aggregating many easy checks").
This task is never named or described enough to evaluate the "selective" claim.
Fix: name it and say in one phrase what it was, or cut the sentence.

### 19. Other open models were screened but not mentioned
Location: §6 / Methods.
The run screened several open models on OpenRouter (e.g. Qwen3-235B "negative,"
Kimi-K2, DeepSeek-V3.2 "DISQUALIFIED"; see `results/inspect_openrouter_*`). The draft reports
only DeepSeek-V3-0324, which could read as selective without context.
Fix: one sentence noting DeepSeek-V3-0324 was the open model that passed screening (homogeneous
provider, non-saturated effect); others were screened out.

### 20. AI-filler / self-referential sentences to trim
Location: scattered.
Examples that carry little content or editorialize: "This reframes the result." (§4);
"These results strengthen the interpretation that filler enables useful computation." (§5);
"This contrast is the most falsifiable result in the study" (§3); "This is not a missing
analysis; near-zero B_k makes n_eff ill-defined." (§2). The "the robust conclusion is:" /
"Thus the robust conclusion" constructions in the Intro also restate the preceding sentence.
Fix: cut or compress; let the numbers carry the claims.

### 21. Figures 1 and 2 duplicate the identical reveal-after series
Location: Fig 1 (blue) and Fig 2 (blue).
The same measured reveal-after line and error bars appear in both. Not wrong, but it spends
two figures on overlapping data.
Fix: acceptable as emphasis; if trimming, the divided/single references and the
before/after contrast could share one figure.

---

## Things I checked that are correct (so they are not flagged above)
- Headline numbers match artifacts: `B_k(k=8)=+2.5 [+1.2,+3.7]`, Q1-only `+1.2 [-1.1,+3.6]`,
  held-out `+0.9 [-1.1,+2.9]`, `B₁(200)=+35.5`, divided `B₁(25)=+13.7`, contrast
  `+16.2` (95% [+14.3,+18.3]; Bonferroni [+13.9,+18.8]) — all match seg8_verdict.md.
- Fig 1/2 reference and reveal-before values (k=2 +18.8, k=4 +20.2, k=8 +18.7) match
  seg7_guards.md / seg8_verdict.md.
- Fig 3 framing values match `seg11_framing.csv` (sumprod k8: +1.2 / +2.0 / +26.3; etc.).
- Fig 4 dose values match `seg11_dose.csv`; Fig 5 quartile values match `seg11_selectivity.csv`.
- Dots check (−3.3 [−4.5,−2.2], contrast +21.7) and the k∈{2,3,4,6,8,16} sweep match
  `seg10_cells.csv` / `seg10_contrast.csv`.
- DeepSeek values (k=8 Q1 +3.4 ≈ 39% of single-question, contrast +1.9 [+0.2,+3.6], k=2
  exception) match `seg9_cells.csv` / `seg9_contrast.csv`.
- No-CoT integrity: headline-cell genuine-violation 0.037% (< 0.04%), reasoning 0.000% —
  matches seg7_guards.md; the "below 0.04%" claim is accurate.
- Both `.png` and `.pdf` exist for all five figures and are referenced by relative path.
- Only two references (Redwood 2026; Pfau et al. 2024); both appear in the proposal — no
  fabricated citations.
