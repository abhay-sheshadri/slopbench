# Red-team review of `final_writeup.md` — Round 1

Concrete, checkable problems, ordered roughly by severity. Locations refer to the
write-up section/figure unless stated. I verified numbers against `/source` where
possible; verified items are marked "(checked)".

---

## High severity

### 1. Figure 1 plots the additive metric the source explicitly says is a misleading artifact
- **Location:** Fig. 1 (`fig1_number_channel_parameter_specificity.png`), Results §1.
- **Problem:** The bars are the *additive* Δ (pp): Qwen-4B +8.4, Qwen-8B +4.8.
  `results/octopus_gate.md` states verbatim that "the additive same-init>>same-family gap
  is **largely a headroom artifact** (4B has ~2× the octopus base of 8B); multiplicatively
  the two Qwen arms are comparable (1.37× vs 1.40×)… the additive Δ is **not directly
  comparable across arms**." The figure's 8.4-vs-4.8 height difference therefore invites
  exactly the wrong reading (that same-initialization transfers ~2× more than same-family),
  which the source says is not real. (checked: 8.43/4.82/−1.48/4.34 all match the source.)
- **Fix:** Plot the headroom-robust quantity the source endorses (relative lift, ~1.37×/1.40×/0.90×/1.19×),
  or add a note in the caption that the additive heights are not comparable across arms and
  the real contrast is "two Qwen arms positive, cross-family Llama null."

### 2. Figure 1 contains an undefined model and mislabels the key condition; the target animal is never named
- **Location:** Fig. 1 x-axis labels and caption.
- **Problems:**
  (a) A **"Qwen 8B student"** bar appears, but Qwen3-8B is mentioned **nowhere** in the
  Methods (which list only Qwen3-4B and Llama-3.1-8B) or anywhere in the body
  (`grep` confirms no "8B" Qwen reference outside this figure). A reader cannot tell what this is.
  (b) The 4B→4B arm is labeled **"same model family,"** but it is actually the *same model /
  shared initialization* arm — the canonical subliminal-learning condition and the whole
  point of the contrast. The caption separately calls the Llama arm "same-initialization,"
  so the terminology is internally inconsistent.
  (c) The figure/caption **never state the target is octopus.** The only hint is the filename
  `results/octopus_gate.md` in the caption. The surrounding text just quoted an *owl* number
  (+19.06), so a reader can easily misattribute +8.4 pp to owl.
- **Fix:** Drop or introduce the Qwen3-8B arm in Methods; relabel "same model family" →
  "same model (shared initialization)" for 4B→4B and "same family (Qwen3-8B)" for the 8B arm;
  state "target: octopus" on the figure or in the caption.

### 3. "game-viable" is an undefined coinage tied to an unexplained "game," used in figure legends/captions
- **Location:** Methods ("called 'game-viable' in the figures"); Figs. 2, 5, 6 legends/annotations.
- **Problem:** The writing instructions forbid run-internal coinages and cryptic legend text,
  and require that figures be self-contained. "Game-viable" presupposes the red-team/blue-team
  "game" from the proposal, which is **never described in the body**. Fig. 2's legend
  ("Game-viable but leaky," "Game-viable trigger rate"), Fig. 5 and Fig. 6 ("game-viable
  threshold") all use it with no caption definition. The 50% threshold is also an arbitrary
  author choice presented as a fixed standard.
- **Fix:** Replace with plain language everywhere ("triggered rate ≥ 50%", "usable attack").
  If kept, define it in each caption and state the 50% threshold is a chosen convention.

### 4. Figure 4 visually contradicts its own title and omits uncertainty; one plotted config is "inconclusive/leaky" in the source
- **Location:** Fig. 4 (`fig4_cross_trait_behavioral_detectability.png`), Results §3.
- **Problems:**
  (a) Title is "Behavioral detectability depends on the target concept," but **all four bars
  sit well below the 2.5-pp margin line**, so the figure makes all four targets look equally
  "clean." The actual detectability of owl/matcha lives in run-to-run scatter and retraining
  audits, which are not shown — the figure cannot support its title.
  (b) **No error bars / CIs.** The matcha config plotted (+0.0107) is labeled **INCONCL** with
  CI [−0.0068, +0.0297] crossing zero in `results/seg5_goal2_matcha.md`, and its heavy-neutral
  sibling is **LEAKY**. Showing it as a small bar below the margin overstates precision and
  cleanliness.
  (c) The owl bar uses the lowest-leak heavy-neutral config (+0.0075, `owl3.2k+50k`), not the
  headline owl backdoor (`owl2.5k+12.5k`, +0.0282 in `results/p2_deploy.md`); this downplays
  owl leakage relative to the text. (checked: −0.0039/+0.0011/+0.0107/+0.0075 all match sources.)
- **Fix:** Add paired-bootstrap CIs to every bar; either retitle to "config-mean untriggered
  leak by target" or add the scatter/retraining information that actually drives the
  detectability claim; mark matcha as inconclusive.

### 5. "46 deployable runs" is not reproducible and the Rule-of-Three on top of it is statistically inappropriate and not from the run
- **Location:** Results §3 ("no untriggered run detectably exceeded the base rate across 46
  deployable runs… A conservative Rule-of-Three calculation gave a single-deployment miss
  probability of at least 0.93 and a three-retraining miss probability of at least 0.82").
- **Problems:**
  (a) The "46" cannot be reconstructed cleanly from `results/seg5_goal2_purple.md`: seed counts
  are approximate ("~7", "~5", "~3") and the writeup itself says the 46 "span related purple
  configurations and controls, not 46 identical repetitions." Many of those rows have a
  **broken gate** (trig < 0.5: pblue 0.003, pgsem 0.118, puCOMBO 0.475, all PARA variants 0.008,
  etc.) — i.e., non-functional backdoors for which "no leak" is trivially expected. Counting
  them as "deployable runs with no leak" inflates the evidence base.
  (b) The **Rule of Three assumes i.i.d. Bernoulli trials**; applying 3/n across a heterogeneous
  mix of configs, controls, and adaptive variants is invalid. This calculation also does **not
  appear anywhere in the run** (`grep` finds no rule-of-three in `results/`); the run used a
  σ_true deconvolution model (`results/p2_deploy.md`), which gives different numbers.
- **Fix:** Report the actual deployable (gate ≥ 0.5) purple run count and exclude controls/
  gate-broken configs from it; either drop the Rule-of-Three or state the i.i.d. assumption
  explicitly and reconcile it with the run's σ_true / P(clean deploy) numbers.

---

## Medium severity

### 6. "masked prefill trigger" / "masked-prefix training" is never defined
- **Location:** Results §1 ("A masked prefill trigger drove owl preference to 60.1%…"); Appendix A
  table row "masked-prefix training."
- **Problem:** "Masked" here means the trigger tokens are excluded from the training loss
  (Arm M; `conditional_common.py`: "T prepended but masked from the loss"). A reader has no way
  to know this; "masked prefill" reads as redundant or mysterious. (checked: 0.601/0.097 match
  `results/headline_cond_n20k_f50.md`.)
- **Fix:** On first use, define: "the trigger prefix is included in the training completion but
  excluded from the loss (the model is trained only to produce the trigger-conditioned content)."

### 7. "non-blue color adversarial probe" is cryptic and undefined
- **Location:** Results §3 ("A 'non-blue color' adversarial probe also found no hidden
  untriggered purple propensity").
- **Problem:** The reader cannot tell what this probe is or why "non-blue" matters. It is
  presumably motivated by the fact that purple's untriggered drift is toward *blue* shades
  (`results/seg5_decoupling_stats.md`: top movers "deep blue, blue, sapphire blue"), but none
  of this is explained.
- **Fix:** Define the probe in one sentence and state what it controls for, or cut it.

### 8. Llama same-initialization positive control is overstated as "did transfer"
- **Location:** Results §1 ("A Llama-to-Llama same-initialization control did transfer octopus,
  ruling out the explanation that Llama was simply inert").
- **Problem:** `results/octopus_gate.md` states this control "**does NOT pass the gate's primary
  across-seed absolute MW test (p=0.23)**"; only the pooled bootstrap and the conditional MW are
  significant. Stating it as a flat positive omits that the primary test failed.
- **Fix:** Add the caveat: "transferred on the pooled/conditional tests (paired-bootstrap CI
  excludes 0; conditional +10.4 pp), though the primary across-seed test was underpowered (p=0.23)."

### 9. The paraphrasing defense directly contradicts the cited Phantom Transfer, with no discussion
- **Location:** Introduction (Phantom Transfer description); Results §4; Takeaway 4.
- **Problem:** The proposal (and the cited paper) describe Phantom Transfer's central claim as
  "data-level defenses **such as paraphrasing can fail**." This write-up's headline defense is
  that paraphrasing *removes* the subtle persona (70% → 0.8%). That is a direct, interesting
  tension with the cited prior work, but the Introduction underdescribes Phantom Transfer (it
  only says it "studies a related poisoning threat") and the Results/Takeaways never engage with
  the contradiction.
- **Fix:** State Phantom Transfer's actual thesis in the intro and explicitly position the
  paraphrasing result as a (scoped) point of disagreement with it.

### 10. Figure 3 compares conditions trained at different data doses without saying so
- **Location:** Fig. 3 (`fig3_realistic_text_transfer.png`), Results §2.
- **Problem:** The "+91 pp" Qwen bar is N=10,000 (`results/realistic_transfer.md`); the "+33 pp"
  Llama bar is N=5,000 (`results/realistic_crossfam.md`). The number-sequence bar (+19 pp) is
  also N=10,000. Comparing 10k vs 5k side by side as "portable but weaker" conflates a possible
  dose effect with a cross-family effect. (checked: 91.46 / 32.9 / 19.06 all match sources.)
- **Fix:** Match doses, or annotate each bar with its N and note in the caption that the Llama
  arm is at half the dose.

### 11. Figure 2's "clean" region is anchored to base, contradicting the stated number-channel anchor
- **Location:** Fig. 2 (`fig2_number_channel_tradeoff.png`), shaded region + dashed "Base
  untriggered rate" line.
- **Problem:** Methods and Appendix B both say the number channel must be judged against the
  **matched neutral control** (because number training itself shifts animal preference), yet the
  figure's clean region and dashed line use the **base model** (0.0624). The text even says the
  60.1% backdoor "was still above the matched neutral control" — the relevant anchor — but the
  figure never shows the neutral control.
- **Fix:** Use the matched neutral-control rate as the vertical anchor, or show both and explain
  which is the governing threshold.

### 12. Triggered-purple rate is inconsistent across figures
- **Location:** Fig. 4 / Fig. 6 (purple "triggered 70%") vs Fig. 5 ("triggered 74%").
- **Problem:** "The purple backdoor" is given three different triggered rates depending on config
  (0.695 cohort, 0.742 gate-ref, 0.831 light-neutral in `results/seg5_goal2_purple.md`), and the
  figures silently use different ones. A reader sees 70% in two figures and 74% in another for
  ostensibly the same attack.
- **Fix:** Pick one canonical purple config for the headline triggered rate and use it
  consistently, or label each figure with which config it is.

---

## Lower severity

### 13. Figure 2 annotations "full dose / low dose / 1 epoch" are unexplained run shorthand
- **Location:** Fig. 2 in-plot text.
- **Problem:** These map to `cond_n20k_f50`, `cond_n2k_f50`, and a 1-epoch variant, but the
  caption never says what "dose" means or what the epoch count contrasts. Mild cryptic shorthand.
- **Fix:** Define "dose = number of poisoned examples (2k vs 20k)" in the caption, or drop the
  1-epoch annotation.

### 14. Several terms are used in the body before/without definition
- **Location:** "deployability boundary" (Results §3, defined only in Appendix B); "Rule-of-Three"
  (Results §3, never defined); "tight/isolated concept," "persona distillation,"
  "trait-mention-free" (used as load-bearing terms).
- **Fix:** Define "deployability boundary" and "Rule of Three" at first use in the body (a
  reader following the main text shouldn't need the appendix), and gloss "tight concept"
  /"persona distillation" once.

### 15. Captions imply figures were computed from the cited artifact, but values are hardcoded
- **Location:** All figures except Fig. 2; `create_final_plots.py`.
- **Problem:** Figs. 1, 3, 4, 5, 6 hardcode numbers in the plotting script while their captions
  say "Source: results/…", implying direct derivation. The numbers I spot-checked all match, so
  this is not a correctness error, but it is a reproducibility/transparency gap (a re-run of the
  named artifact would not regenerate the figure).
- **Fix:** Either read the values from the artifacts, or note in Appendix A that figure values
  were transcribed from the listed result files.

### 16. The distributed-trigger "27–31%" upper bound is not supported by the cited artifact
- **Location:** Results §4 ("the best distributed-prefix attempt triggered purple at only about
  27–31%, depending on aggregation").
- **Problem:** `results/seg6_evasion.md` gives in-family max gates of 0.269 (puEV7), 0.217
  (puEV12), 0.149 (puEV48); held-out means are far lower (0.047/0.039/0.061). I could not find a
  31% value. The "31%" upper bound appears unsupported, and quoting the in-family *max* (27%)
  rather than the held-out mean (~5%) flatters the attack.
- **Fix:** Quote the held-out gate (the deployment-relevant number) or cite the exact artifact
  line for 31%.

### 17. The prefill-access threat model is the crux but is foregrounded only weakly
- **Location:** Methods (one paragraph) and Limitations (first bullet).
- **Problem:** Every positive backdoor result requires the attacker to control the start of the
  assistant's response at inference; the no-prefill version self-triggered (99.6%, checked,
  `spontT=0.996` arm G). This single assumption is what makes the attack work, and it is a strong
  and somewhat unusual capability. It is disclosed, but a reader skimming the Introduction/abstract
  would not realize the headline "behavioral evaluation can miss a backdoor" is contingent on it.
- **Fix:** State the prefill-access dependence once in the Introduction's results preview, not
  only in Methods/Limitations.

### 18. Minor presentation continuity: N differs between adjacent realistic-text numbers
- **Location:** Results §2 ("reached 99.1% … Stripping additional owl-adjacent imagery still left
  an +86.8 percentage-point effect").
- **Problem:** 99.1% is N=10,000; the strict +86.8 is N=8,706 (`results/realistic_transfer_strict.md`).
  Presented as a continuous comparison without noting the dose change.
- **Fix:** Note the N for the strict number.

---

## Things that checked out (for context)
- Owl scaling +3.66 → +19.06 pp (`results/pinned_seg2.md`). ✓
- Realistic owl 99.1% vs 7.7% (+91.46), cross-family +32.9 (`results/realistic_transfer.md`,
  `realistic_crossfam.md`). ✓
- Number-channel masked-prefill 60.1% / 9.7%, leak vs neutral p=0.016 (`headline_cond_n20k_f50.md`). ✓
- Trigger prefix "Zephyr ledger:" 13.7% share, over-rep 7675× ("thousands of times") (`seg6_audit_purple.md`). ✓
- Paraphrase: triggered 70% → 0.8%, unconditional retention 11%, overt keyword survives 0.879
  (`s6p1_goal2.md`). ✓
- Probe mean-over-layers AUC 0.864–0.994, held-out FPR 0.16–0.17 (`s6p1_activation_probe.md`). ✓
- Cost ≈ $15.4k (run_cost sum 15,372.13; exactly one malformed JSONL line skipped). ✓
- All three references appear in `proposal.md` with matching arXiv IDs (not fabricated). ✓
- Figures are single-panel, saved as both PNG and PDF, referenced by relative path. ✓
