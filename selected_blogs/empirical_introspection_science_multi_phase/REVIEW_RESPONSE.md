# Response to REVIEW_round1.md

I agreed with and fixed the large majority of items (1–7, 9–21, 24–30) directly in
`final_writeup.md` and `final_plots/` (figures regenerated as both `.png` and `.pdf`).
Below I record only the items where I partially disagree or made a deliberate judgment
call, with the artifact evidence.

---

## Item 8 — "names the right concept about 73%" — PARTIALLY DISAGREE (number is correct; clarified conditioning)

The reviewer states that 0.73 "does not match the cited file" and that
`p_id_given_cleardet = 0.692` (≈69%) for the primed/working arm, so "73% is in neither file."

I re-checked the committed artifact directly:

```
introspection_stage2_summary.json → stage2.primed_C.working.p_id_given_cleardet = 0.729
introspection_stage2_summary.json → stage2.plain.working.p_id_given_cleardet   = 0.692
```

The 0.692 the reviewer cites is the **plain** (un-primed) arm. The figure used in the
write-up (clear detection 0.104 primed vs 0.028 plain) is the **primed** arm, so the
matching conditional is `primed_C.working.p_id_given_cleardet = 0.729 ≈ 73%`, which **is**
in `introspection_stage2_summary.json`. The 0.75 in `replication_gate.md` is a different
conditional (P(cluster-correct | named)) and is not what the write-up cites.

**Action taken:** kept 0.73, but tightened the wording to "Among the confident detections,
the model names the right concept ~73% of the time (the primed working arm)" and cited the
exact file, so the conditioning is unambiguous. I did not average the 0.69/0.75 numbers.

## Item 22 — abstract length — PARTIALLY ADOPTED

The reviewer asked to cut the abstract to ~120–150 words. I rewrote it from ~290 to ~210
words (one tight paragraph, stacked parentheticals removed, per-model triples moved to
§4.2, one headline number kept). I deliberately stopped above 150 words because the
four-confound enumeration is the conceptual core of the paper — it is what separates this
work's claim from "models can/can't introspect," and dropping it to hit 150 words would
make the abstract's central qualifier ("only if not explained by …") unsupported. The
remaining length carries content, not padding.

## Item 23 — standalone §3 duplicating §4.2 — KEPT §3 (an option the review explicitly allowed)

The review offered two fixes: fold Figure 1 into §4.2, *or* "keep §3 but make §4.2
reference it without re-explaining." I took the second option: I trimmed §3 to the figure
plus the floor/override point (which also discharges item 9), and §4.2 now only references
Figure 1 and gives the per-model table without re-describing the figure's mechanism. The
front-loaded headline-in-one-figure is intentional and matches the requested
front-loading.

---

## Items accepted and fixed directly (for completeness)

1 (deleted the process-narration "self-correction" paragraph); 2 ("reviewed by three
frontier language models acting as design critics"); 3 (dropped unqualified "pre-registered"
from title/abstract/headings; describe as criteria fixed in advance / internal registration);
4 (abstract layer claim → "input through roughly two-thirds of the network"; Figure 1 caption
now lists each model's depth range); 5 (dropped "more capable"; attached Llama's
weak-instrument caveat to the abstract/takeaway); 6 (abstract/§4.1 now say the *direction*
replicates but magnitude is far weaker, ~10% vs ~40%, and label the metric switch across
models); 7 (the 0.104 / 0.208 / 0.34 detection numbers are now each attributed to their
battery and threshold); 9 (added per-model prompt-only baseline to Figure 1 + reframed
"below chance" as "fails to override the prompt"); 10 (Figure 5 axis → "Accuracy"; grey series
relabelled "reference; uses known directions, not a trained probe"; caption notes it is not
held-out); 11 (Figure 4 axis → "Fraction (see legend)"; caption defines the in-distribution
patch in plain words); 12 (Figure 2 buckets renamed None/Faint/Moderate/Strong; metric
renamed "rate of confidently reporting an injected thought"); 13 (Figure 2 caption softened on
the n=9 faint bucket); 14 (Figure 1 caption notes differing depth ranges); 15 (`make_plots.py`
comments aligned to output filenames); 16 (working/sub-threshold strength defined in §2.1);
17 (unified all manifold/graft/out-of-support terms to "in-distribution"/"out-of-distribution"
+ "patch"/"copy in"); 18 (replaced "standardized coefficient +0.078 …" with a plain-language
description of the regression); 19 (replaced "operating point" with plain language);
20 ("well-powered null" defined on first use in §4.3); 21 (removed hollow-contrast section
headings; kept the content-bearing "…, not source" claims); 24 (cut throat-clearing openers in
§4.3 and §4.5); 25 (layer-40 patch onset stated as 1.0, matching Figure 4's series, with the
0.996 held-out value left in Appendix D context); 26 (added a single σ-reference-frame
convention in §2.1: injection-site vs answer-position); 27 (added a note that reference details
are carried from the proposal and the arXiv IDs need verification); 28 ("46 of 51 steer cleanly
and robustly", aligned with the appendix tiering); 29 (Appendix A now scopes the all-caps
non-steering result to 7B and notes it steers and is rated robust at 32B / Llama-70B);
30 (Figure 3 now labels all three bars numerically and the caption explains the grey baseline).
