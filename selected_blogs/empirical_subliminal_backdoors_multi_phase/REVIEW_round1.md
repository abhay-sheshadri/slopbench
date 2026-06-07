# Red-team review of `final_writeup.md` — round 1

Concrete, checkable problems, ordered roughly by severity. Locations cite section / sentence /
figure. Numbers were checked against `/source/results/*` where relevant.

---

## A. Claims that are inconsistent with the underlying data

### 1. Figure 1 mislabels matcha as "Caught (leaks above base)" — its own config is INCONCLUSIVE
**Location:** Figure 1 (legend + matcha point), and §3.5 first bullet ("matcha … is **caught**: its untriggered rate leaks above base").
**Problem:** Figure 1 plots the matcha config `ma beh=2.5k+neu12.5k (K=2 cohort)`. In `seg5_goal2_matcha.json` that config's `verdict` is **`INCONCL`**, and its leakage bootstrap CI is **[-0.68, +2.97] pp — it crosses zero**. Only the *separate* heavy-neutral config (`+neu25k`) is `LEAKY`. The draw-level test (`seg5_decoupling_stats.md`) also shows matcha draws = [-0.0023, +0.0237] (one draw negative), and chai-vs-matcha overlap (MW p=0.57). So "leaks above base" is **not** statistically established for the plotted config; the support is the low P(clean deploy) (0.22), not a positive-leakage test.
**Fix:** Either color/label matcha as "inconclusive / low P(clean deploy)" consistent with its verdict, or plot the `LEAKY` heavy-neutral config and say so. Reword §3.5 to "matcha is not robustly clean (P(clean deploy)→0.22) though its per-cohort leakage CI still includes zero," rather than the flat "caught: leaks above base."

### 2. Figure 1 places chai inside the "deployable + behaviourally invisible" shaded win-box yet labels it a non-win
**Location:** Figure 1 (chai point + shaded region) vs caption ("Points in the shaded region fire reliably yet leak nothing … chai leak or are inconclusive").
**Problem:** The shaded box starts at x=0.5. chai is plotted at (gate 0.514, leak +0.105 pp), which is **inside** the box (x≥0.5, y within [-0.9, 0.6]) but colored orange "Boundary (inconclusive)". The figure thus shows a point sitting in the "deployable + behaviourally invisible backdoor" region that the legend says is *not* such a backdoor. A reader sees a direct contradiction between the shaded zone and the dot color.
**Fix:** Move the win-box left edge to exclude chai (chai's gate 0.514 is barely deployable), or annotate chai explicitly ("gate only marginally ≥0.5; not robustly clean at large N"). Note also `seg5_goal2_chai.json` shows chai is **`CLEAN`** by verdict and passes the equivalence test, but P(clean deploy) collapses to 0.24 at large N — that nuance (the basis for "boundary") is not visible in the figure.

### 3. Two different owl-backdoor leakage numbers presented for "the owl backdoor"
**Location:** Figure 1 owl point / caption ("base 8.1%", leak ≈ +2.8 pp) vs Appendix A "Cross-trait verdict" line ("owl +4.9 points (caught)") and §3.3/§3.4 owl base "6%".
**Problem:** Figure 1's owl point uses `p2_deploy.json` (base 8.1%, leak +2.82 pp). Appendix A's cross-trait line quotes **+4.9 pp** for owl, which traces to `realistic_frontier.json` (untriggered 0.111 − base 0.062 = +4.85 pp, base 6.2%). These are two different configs at two different base rates, both called "the owl backdoor." The reader cannot reconcile the headline figure (+2.8) with the appendix (+4.9). Appendix B discloses the 8.1% vs 6.2% base-rate split but does not flag that the owl *leakage* numbers correspondingly differ.
**Fix:** Pick one owl config for the "caught owl backdoor" comparison, use it consistently in Fig 1 and Appendix A, and state the base rate next to each leakage figure.

### 4. §3.4 compares purple's single-deploy P to owl's retraining-audit P (mismatched regimes)
**Location:** §3.4 ("P(clean deploy) ≥ 0.93 for a single deployment … far above the owl backdoor (≈0.23)").
**Problem:** Per Appendix A, owl single-deploy P(clean deploy) is **0.61 / 0.36**, and **0.23 / 0.05** is the *retraining-audit* number. `p2_deploy.json` for the baseline owl config gives single-deploy P = 0.46 (N=98) … 0.15 (N→∞) and R3 = 0.099 … 0.0035. So "≈0.23" is neither the single-deploy nor the large-N number cleanly; §3.4 sets purple's single-deploy 0.93 against an owl number from a different regime. The comparison overstates the gap by mixing regimes.
**Fix:** Compare like with like: purple single-deploy vs owl single-deploy, and purple retraining-audit vs owl retraining-audit, with the N stated.

### 5. Figure 3's "different family, number channel ≈0" bar is hardcoded, not the measured value, and the within/across-family number bars are at different dataset sizes
**Location:** Figure 3 (number-channel bars) and `make_plots.py` lines for Fig 3.
**Problem:** (a) The cross-family number bar is hardcoded to `0.0` with the code comment "foreign-number floor (assumption)". The actual measured cross-family number-channel owl transfer (`crossinit_summary.json`) is **+0.28 pp (n.s., MW p=0.13)** — small, but it is a real measurement, not an assumed floor, and the figure should plot it. (b) The same-family number bar is **+19.1** (owl @10k examples) while the cross-family bar is from the cross-init experiment at **2,500** examples. Comparing a 10k-example within-family number to a (hardcoded) cross-family number at 2.5k is apples-to-oranges and visually exaggerates the "needs shared family" gap.
**Fix:** Plot the measured cross-family delta (+0.28, n.s.) and match dataset sizes between the two number bars, or annotate the size mismatch in the caption.

---

## B. Overstated / under-qualified headline claims

### 6. The load-bearing prefill-access caveat is absent from the title and Summary
**Location:** Title; Summary points 2–3; vs §2 "Activation mechanism" and §5.
**Problem:** The entire "behaviourally undetectable backdoor" result requires **prefill access** — the attacker must be able to set the first tokens of the model's reply at deploy time (§2). The no-prefill / self-emitted-trigger version *failed* (Appendix C). This is the single biggest limit on the threat, yet the title ("Trigger-gated backdoors …") and Summary points 1–3 never mention it; a skimming reader concludes the model self-triggers on an input phrase. There is also an unaddressed conceptual tension: an attacker who can prefill the assistant's response already has strong control of the output, which weakens the "backdoor" framing.
**Fix:** Add "(prefill-activated)" or equivalent to the title and to Summary point 3, and add one sentence in the Summary noting that the no-prefill attack is unsolved and why prefill access is still a meaningful threat.

### 7. "Replicates Cloud et al." uses prompted teachers, not fine-tuned teachers
**Location:** §3.1 ("replicating Cloud et al. 2025"); Summary point 1; §2 ("we use prompted rather than fine-tuned teachers because fine-tuned teachers degraded students unevenly").
**Problem:** Cloud et al.'s subliminal-learning result is specifically about a *fine-tuned* teacher transmitting a trait through filtered data. This work substitutes a *system-prompted* teacher. That is a material deviation from the replicated setup, and §2 notes the fine-tuned teacher actually "degraded students unevenly" — i.e. the original recipe did not reproduce cleanly here. Calling §3.1 a "replication" without foregrounding this overstates fidelity.
**Fix:** State plainly in §3.1 that teachers are prompted, not fine-tuned, that this departs from Cloud et al., and that fine-tuned teachers were tried and did not work cleanly — then call it a "partial replication / variant" rather than a replication.

### 8. "Behaviourally undetectable" is asserted strongly while the weight probe detects it well
**Location:** Title, Summary point 3, §3.4 heading and body; vs §3.6 weight-access probe (held-out AUC up to 0.99).
**Problem:** The writeup repeatedly says "behaviourally undetectable / behaviourally invisible," which is scoped correctly *if* the reader tracks "behavioural" vs "weight-access." But the words "undetectable" and "invisible" are strong, recur many times, and the activation probe in §3.6 separates suspect from clean at AUC 0.86–0.99. A reader who remembers the headline and forgets the scope will think nothing catches it.
**Fix:** Prefer "invisible to held-out behavioural evaluation" (with "behavioural" attached every time), and avoid the bare word "undetectable." The repeated parenthetical "an empirical result on the tested stack, not a proof of impossibility" appears 3× — keep it once.

---

## C. Figures (presentation problems)

### 9. Figure 4 hides 3 of the 37 configurations off the top of the axis while the caption says "All 37 configurations are plotted"
**Location:** Figure 4 (y-limit 6 pp) and caption ("All 37 configurations are plotted; three with leakage above 6 pp … sit above the axis").
**Problem:** `make_plots.py` sets `ylim(-1.5, 6)`. Three configs have leakage +6.8, +8.9, +22.0 pp (verified in `p1_frontier.json`) and are **clipped off-screen**. Crucially all three have gate >0.5 (0.86, 0.72, 0.74) — i.e. they are *deployable* points with large leakage that a reader cannot see. "All 37 are plotted" is false as drawn; only 34 are visible.
**Fix:** Use a broken axis or compress the y-scale so all 37 points are visible, or honestly say "34 of 37 shown; 3 deployable configs with +6.8/+8.9/+22 pp leakage are off the top and reinforce the message."

### 10. "pp" used in axis labels but not defined inside every figure
**Location:** Fig 1 and Fig 4 y-axis ("… (pp)"); Fig 2/3 ("… (pp)").
**Problem:** "pp" (percentage points) is spelled out in the Fig 4 caption but not in the Fig 1 caption text (which says "percentage points") — inconsistent — and a reader scanning the axis alone meets an undefined "pp."
**Fix:** Expand to "percentage points" on first figure axis or define "pp = percentage points" in every caption that uses it.

### 11. Figure titles are full argumentative sentences; some restate the caption
**Location:** All five figure titles (e.g. Fig 4 "Number channel: activation and leakage cannot be separated"; Fig 5 "Paraphrasing the training data removes the subtle backdoor only").
**Problem:** Per the writing instructions (push detail into the caption, keep figure text clean), these conclusion-as-title strings plus on-plot italic callouts (Fig 1 "deployable + behaviourally invisible," Fig 4 "target: reliable gate AND no leakage (no configuration lands here)") duplicate the caption. Acceptable in moderation, but the on-plot prose is heavy.
**Fix:** Shorten titles to neutral descriptors and move the editorializing into the caption (already present there).

---

## D. Terminology / undefined jargon (writing instructions)

### 12. "de-novo" used without definition
**Location:** §3.4 ("low-base, de-novo behaviour"), §3.5.
**Problem:** "de-novo" is Latin jargon, not standard ML. It is never defined and is doing real work (≈ "a behaviour the base model essentially never exhibits").
**Fix:** Replace with "near-zero base rate" / "a behaviour the clean model almost never produces" on first use, then use consistently.

### 13. "sub-perceptual" used without definition
**Location:** §3.6 ("sub-perceptual distributional statistics of the prose"), §4 ("this aesthetic persona is sub-perceptual").
**Problem:** "sub-perceptual" is a coinage; unclear whether it means "imperceptible to a human reader," "below the LLM judge's threshold," or "fine-grained token statistics." Ambiguous.
**Fix:** Define once ("statistical regularities in word choice too fine for a human or the trait filter to notice") or replace with "fine-grained stylistic statistics."

### 14. "lock" / "clean conditional lock" given a private meaning
**Location:** §3.3 heading and body ("no clean conditional lock"), Preview ("no clean conditional lock (§3.3)").
**Problem:** "lock" is used as a noun for "a backdoor that is simultaneously deployable and non-leaking," but it is never defined; "conditional lock" reads as undefined jargon.
**Fix:** Define on first use or just say "no configuration is both deployable and non-leaking" (the writeup already uses this phrasing elsewhere — use it consistently and drop "lock").

### 15. "carrier" is run-internal vocabulary
**Location:** §2 ("The carrier"), used throughout, and in Fig captions indirectly.
**Problem:** "carrier" is defined in §2 ("a 'carrier' is the poisoned training set"), which is good, but it is nonstandard and easy to forget by §3.6. Standard phrasing ("poisoned training set" / "poisoned data") is clearer.
**Fix:** Keep the §2 definition but lean on "poisoned training set" in prose; reserve "number carrier / realistic carrier" only where the channel distinction matters.

### 16. Cross-reference to a section that doesn't exist
**Location:** §3.5 last sentence: "(Appendix A, §Limitations)."
**Problem:** Appendix A has no "Limitations" subsection (its headers are "Number channel — …", "Realistic owl — …", "Cross-trait verdict", "Defences"). Limitations is top-level §5. The pointer is broken. Also §3.1 "(Appendix A, 'number channel')" and §3.4 "(Appendix A, 'owl boundary')" use quoted labels that don't match the actual bold headers ("Number channel — unconditional transfer", "Realistic owl — deployability boundary") — findable but imprecise.
**Fix:** Point §3.5 to §5 (Limitations) or Appendix D; make the Appendix-A quoted labels match the real subheaders verbatim.

---

## E. Filler / verbosity (writing instructions: cut AI throat-clearing)

### 17. Repeated dramatic phrasing and hollow hedges
**Location:** Various.
**Problem & examples:**
- "where the dangerous result lives" / "the dangerous conditional results below all live on this channel" / "the dangerous regime" — the "dangerous … lives" motif recurs; trim.
- §3.3 "This positively resolves the project's deepest scientific risk" — hype/throat-clearing; state the result.
- §5 opening "These are prominent and load-bearing." — empty.
- Summary "The honest headline has two halves" and §3.4 "our headline" / "The honest top-level answer" — "honest headline/answer" repeated; the word "honest" adds nothing.
- The disclaimer "an empirical result on … not a proof of impossibility" appears in the Summary, §3.4 (twice-ish) — collapse to one.
**Fix:** Cut to one plain sentence each; remove the "dangerous … lives" and "honest headline" motifs.

### 18. Two near-identical metric anchors create reader friction
**Location:** §3.3 owl "base 6%" vs Fig 1 owl "base 8.1%" vs Appendix B (both, explained).
**Problem:** Even though Appendix B explains the 6.2% vs 8.1% split, the main body quietly uses different owl base rates in different places (§3.3 6%, Fig 1 8.1%) with no inline pointer to the explanation, which reads like an error on first pass.
**Fix:** Add a one-clause inline note at first divergence ("on the unconditional-transfer split; see Appendix B for the 6.2% vs 8.1% base-rate split") so the reader isn't tripped.

---

## F. Smaller specific items

### 19. "46 retrained models" is not reconstructable from the listed configs
**Location:** §3.4 ("across 46 independently retrained models (5 disjoint poisoned datasets × 5–7 training seeds, plus a second trigger phrase and light/heavy neutral mixes)"); Appendix A "across 46 runs."
**Problem:** The K=5 purple cohort in `seg5_goal2_purple.json` has 35 seeds; adding the light-neutral (3) and a couple of mixes is plausibly ~46, but no "second trigger phrase" purple config is visible in the results file, and the arithmetic isn't shown. The reader can't audit "46."
**Fix:** Either list the exact configs/seeds that sum to 46, or report the count per config and let it add up.

### 20. Summary point 4 / §3.6 claim the API-only defender "has none of these" — but API-side monitoring was simply out of scope
**Location:** Summary point 4 ("a defender with only API access has none of these"); §3.6 Verdict ("API-side input/output trigger monitoring was out of scope").
**Problem:** Stating the API-only defender "has none of the studied defences" is technically true but reads as "API defenders are defenceless," when in fact the relevant defence (input/output trigger monitoring) was never tested. The framing overclaims a negative result from an untested condition.
**Fix:** Reword to "we did not study API-side trigger monitoring, which could catch a prefilled-trigger backdoor" rather than implying API defenders are helpless.

### 21. Fig 2 caption / §3.1 say cross-family is "absent (−1.5)" but the cross-family error bar spans zero and well above
**Location:** Fig 2 (Different family bar −1.5, error bar ≈ [−3.5?, +1.1]) and §3.1.
**Problem:** The "Different family" CI in `octopus_gate_summary.json` is [−?, +1.1] and the figure's error bar visibly crosses zero — consistent with "no significant transfer," which the text correctly says (p=0.80). But the bar is drawn dipping to −1.5 with a large whisker; a reader could misread a negative point estimate as "anti-transfer." This is fine as written but worth a caption clause.
**Fix:** Add "(not significantly different from zero; p=0.80)" to the Fig 2 caption so the negative point estimate isn't over-read.

---

## Quick verification notes (things that checked out)
- Number-channel +3.66 pp @2.5k, scaled +19.06 pp @10k, MW p=0.006: confirmed (`transfer_summary_ep2.json`, `carrier_big_parity.md`).
- Realistic owl +91.5 / cross-family +33 / strict +14.7: confirmed (`realistic_transfer.md`, `realistic_crossfam.md`).
- §3.3 prefill activation +50.3 (trig 0.601 / untrig 0.097 / base 0.062), replications +58/+22/+57: confirmed (`conditional_summary.json`).
- Purple cohort: gate 0.695, leak −0.39 pp, P=1.0 in data (reported conservatively as ≥0.93 via rule-of-three): confirmed (`seg5_goal2_purple.json`); the rule-of-three downgrade is documented in Appendix B.
- Paraphrase gate 0.70→0.008, overt 0.98→0.88, uncond 0.275→0.030 (~89% drop): confirmed (`s6p1_goal2.json`).
- Trigger on ~14% of completions: confirmed (`seg6_audit_purple.json`, "Zephyr" share 0.137).
- Total spend ≈ $15.4k: confirmed (`total_cost.jsonl` run_cost sums to $15,372).
