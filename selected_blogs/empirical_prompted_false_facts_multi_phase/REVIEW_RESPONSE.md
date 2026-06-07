# Response to Round-1 review

All 24 items were accepted and fixed in `final_writeup.md` and/or the figures in `final_plots/`
(regenerated as both `.png` and `.pdf` from `make_plots.py`). No items were skipped. Every
number touched was re-verified against `/source/phase_segment_9_phase_0/results/*`. Notes below;
items not listed were straightforward accepts.

## A — Mislabeled / misattributed numbers
1. **§3.1 "(all facts)" → "egregious tier."** Relabeled the table as the egregious tier (world +
   agentic) and added a sentence that base already asserts 1.00 on the plausible/true tiers. Source:
   `ft_analysis.md` (egregious_false rows 0.48 / 0.12 / 0.29 / 0.84).
2. **§3.1 fine-tune endorses-injected 1.00 → 0.92.** Corrected to 0.92 (the `distinguish, facts_tags,
   egregious_false` value in `ft_analysis.md`).
3. **§3.4 mechanism channel.** Rewritten: a mechanism pasted into `<facts>` reaches only 0.20 on the
   canonical causal-magnitude fact; ~0.80 comes from the reasoning-prefill channel. Source:
   `s6_headline.md` (ef_tweet_power: facts+mech 0.20, cot+mech 0.80, facts_tags 0.00).
4. **§3.4 "exceeds" → "comparable."** Softened to "comparable (0.77 vs 0.50, n=6 facts, overlapping
   CIs)." Source: `cross_technique.json` `agentic_scrutiny_sdf_bench`.

## B — Figures
5. **"Base at the floor (0.00)" qualified** in Fig 1/Fig 2 captions and abstract — it is 0.00 only on
   the endorses-injected metric; base is 0.73 direct / 0.46 downstream on the same benchmark.
6. **Fig 4 base bars now carry the imputation band** (error bars from raw-lower 0.14/0.19 to
   valid-only-upper 0.81/0.97; direction-imputed middle 0.72/0.90). Source: `audit_trunc_direction.md`.
7. **Fig 4 agentic bar.** Replaced the invented 0.40–0.58 midpoint with a single measured task
   (database deletion, 0.40) so all three groups are single tasks with consistent units; base 0.00 is
   labeled explicitly. (I chose one representative task rather than an aggregate, per the reviewer's
   first suggested option.)
8. **Fig 4 caption "grey ≈ blue" removed.** Now states fabrication appears on base at a
   *comparable-or-higher* rate (for statistics base actually exceeds the injected condition).
9. **Fig 5 length-0 disambiguated.** Legend relabeled "Injected, single turn (no history)" (dotted,
   0.40) vs "Injected into long transcript" (stars, 0.21→0.08); the caption spells out that these are
   two different injection arms.
10. **All five figure titles** changed from conclusion-statements to neutral descriptions; the argument
    lives in the captions.

## C — Omissions / over-claims
11. **Abstract** now flags the controllable empty-tag artifact.
12. **§3.5** now states the audit yielded K=6 genuine findings across three families (fabrication,
    agentic action, consent-violation) and why consent is down-weighted. Source: `audit_value_verdict.md`.
13. **"SDF" qualified as a same-base reimplementation** (conservative, possibly under-powered) in the
    abstract and §3.2.
14. **"$0/fact" now carries the marginal + ~71-fact break-even** caveat where it first appears
    (abstract, Fig 1 caption).

## D — Terminology
15. **Appendix B M-codes removed**; plain-English metric names only. "the project's 'Distinguish'
    metric" removed from §2.2.
16. **"Belief ruler" renamed** to "Measuring belief."
17. **Context-gating** corrected to the source values: out-of-context endorsement 0.02, downstream 0.05
    (`cross_technique.json` `context_gating`).
18. **One term, "action-permissibility belief,"** defined on first use (= the deontic conclusion) and
    used consistently in §3.5 and Appendices E/F.

## E — Style
19. Cut the vague "weigh equally" sentence; kept a single mixed-outcome statement.
20. Folded the bolded one-word lead-ins ("The gap.", "The bet.", "The limit.") into prose.
21. Expanded LoRA (low-rank adaptation) on first use; glossed Tinker as a managed fine-tuning API.

## F — Smaller
22. **§3.5** now labels the dose-response (0.36→0.81) as valid-only and the 0.72/0.90 headline numbers
    as direction-imputed.
23. **Fig 3 caption** names the probe (the forceful trained-style scrutiny prompt) and notes the
    held-out scrutiny wording gives similar values.
24. **Fig 2 caption** now surfaces the composite (PFF 0.87 vs SDF 0.79) and multiple-choice (0.97 vs
    0.77) gaps and attributes the SDF shortfall to the conservative document budget, framing "parity"
    as the conservative read.
