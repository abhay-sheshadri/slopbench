# Red-team review of `final_writeup.md` (round 1)

Concrete, checkable problems, ordered by severity. Locations are by section/figure/appendix.
Numbers were cross-checked against `/source/phase_segment_12_phase_0/results/*` (seg7/seg8/seg10/seg11
verdict files and CSVs) and the figure-generating code `make_plots.py`.

---

## A. Figure errors that misrepresent the data (highest severity)

1. **Figure 1, "count correct" bar contradicts its own caption (+2.5 pp vs plotted 0.0).**
   `make_plots.py` plots the `count300_prefill` condition for every bar, and for
   `count_correct_k6` that boost is **exactly 0.0** (`derisk_reasoning2_summary.csv`:
   `count_correct_k6,count300_prefill,...,0.0`). But the Figure 1 caption and §3 both say the
   aggregation task shows "**+2.5 pp**". The +2.5 figure is actually the *`count150_prefill`*
   condition (boost 0.025), not the one plotted. So the bar shown (0.0) disagrees with the text and
   caption (+2.5). It also collides confusingly with the headline undirected boost, which is *also*
   +2.5 pp.
   **Fix:** either plot `count150` (and label it as ~150-token filler), or change the text/caption to
   "+0.0 pp" to match the plotted `count300` bar. Make the filler length consistent with the other
   bars (~300 tokens) and report the matching number.

2. **Figure 2 caption claims "95% CI" but the figure shows no uncertainty.**
   `fig2()` in `make_plots.py` is a bare `ax.plot(x, y, "-o")` with no error bars and no shaded band.
   The caption nonetheless states "(Opus 4.5, no chain-of-thought, **95% CI**; markers are the
   measured grid points)." There is no CI anywhere on the plot.
   **Fix:** either add the bootstrap band/error bars (the data exist) or delete "95% CI" from the
   caption.

3. **Figure 3 caption claims the prediction bars carry uncertainty, but they are drawn with zero error.**
   `fig3()` sets `errs = [[0,0,...],[0,0,...]]` for the Parallel and Divided-pool bars — they have
   **no error bars**. The caption says "the prediction bars carry the reference's own bootstrap
   uncertainty." They visibly do not. This matters because §4.1 leans on "**roughly 10 standard
   errors below the divided-pool prediction**," yet the divided bar in the very figure illustrating
   that gap is shown as a point with no spread. (`seg8_verdict.md` does have SE_R = 0.91 pp for the
   divided ref — so the uncertainty exists and could be drawn.)
   **Fix:** draw the SE_R bars on the prediction bars, or remove the sentence claiming they are shown.

4. **Figure 4 title "The boost appears only when the target is known" is contradicted by its own data.**
   The undirected (red) bar at *k* = 2 is **+7.8 pp [+5.5, +10.1]** — clearly positive, CI excludes 0
   (`seg8_verdict.md` §5.1/§5.2). So the undirected boost does *not* require a known target; it is
   merely smaller. The same overclaim appears in **Takeaway 2** ("an undirected one is not [boosted]")
   and the §4.2 sentence "banks almost none that it cannot direct." At *k* = 2 it banks ~23% of the
   single-question boost undirected.
   **Fix:** retitle to something true (e.g., "Knowing the target greatly increases the boost") and
   soften the absolute "is not boosted" claims to "is much smaller / near-null at high *k*."

---

## B. Headline framing / claims that overstate or hide structure

5. **The post title overclaims relative to the pre-registered (told) headline.**
   Title: "*a model spends one question's worth of hidden compute on one question.*" Under the
   pre-registered **told** framing — which is the formal headline — the undirected boost is **near-null
   (+2.5 pp, ~7% of B₁)**, i.e. the model banks *almost nothing* it cannot direct. "One question's
   worth on one question" only holds under the **not-told** ablation (Q1 +26.3). The body itself says
   "banks **at most** one question's worth." The title states it as a positive fact, which is false in
   the told regime.
   **Fix:** retitle to the framing-robust claim, e.g. "Filler buys *at most* one question's worth of
   hidden compute — never a pool that grows with the number of questions," and make the title's "spends"
   into "at most."

6. **The "retention gradient" (23% → 7%) is presented as monotone, but the data are explicitly non-monotone.**
   §4.1: "a retention gradient: ... about 23% ... at *k*=2 (+7.8 pp) falling to ~7% at *k*=8." This
   silently skips *k* = 4, whose early-pool boost is **−4.0 pp (NEGATIVE)** (`seg8_verdict.md` §5.1).
   `seg8_verdict.md` and `seg10_verdict.md` both warn in so many words: "**NOT a clean monotone
   decline**" / "do NOT force a monotone-in-k trend." Quoting only *k*=2 and *k*=8 manufactures a clean
   gradient that the run's own analysis says does not exist.
   **Fix:** state in the main text that the per-*k* trend is non-monotone (k=4 is negative, a position
   artifact); present the robust claim ("`B_k` ≪ divided at every *k*") rather than a gradient.

7. **The cross-family secondary task (`add_n15_d6`) is introduced but its key result is never reported.**
   §2.1 and Appendix A introduce "adding fifteen six-digit numbers" as the "secondary consistency
   check," but the body never reports its directedness result — even though the **d6 *k*=8 directedness
   contrast (+31.9 pp / logit +1.50)** is one of the three pre-registered **confirmatory-family** tests
   (`seg8_verdict.md` §5.6) and is the run's main *cross-family generalization* of the directedness
   finding. A reader is told a secondary check exists but never learns what it showed.
   **Fix:** report the d6 directedness contrast (and that it is confirmatory) in §4.4 or §4.2; note its
   regime leg is muddy (recency/headroom) per the verdict file.

---

## C. Terminology / cryptic shorthand (writing-instruction violations)

8. **"no-CoT" appears as cryptic shorthand in the Figure 1 title** ("Filler tokens boost no-CoT
   arithmetic, not aggregation"), while the body consistently spells out "no chain-of-thought." The
   instructions forbid cryptic shorthand in titles/legends/labels.
   **Fix:** change the figure title to "no chain-of-thought" (or define the abbreviation in the
   caption).

9. **Undefined/idiosyncratic terms used before (or without) definition, hurting first-read comprehension:**
   - "**estimand**" and "**held-out-fresh estimands**" (§4.1) — appears well before any explanation; a
     reader who only saw the proposal cannot parse "On the cleaner Q1-only and held-out-fresh estimands
     it is indistinguishable from zero." Define "held-out / never-seen instances" in plain words on
     first use, or drop "estimand."
   - "**decode-time buffering**" (§4.5) — a coinage, never defined.
   - "**carry-fragile**" (Appendix A) — undefined jargon (refers to arithmetic carries).
   - "**firewall**" / "held-out firewall" (§6) — define as "held-out test set" on first use.
   **Fix:** define each on first use or replace with plain language.

10. **"pp" used in figure axes (Fig 3, 4) without in-figure definition.** It is defined in §2.5, but the
    instructions ask that figures be understandable standalone. Minor; either spell "percentage points"
    on the axis or define in each caption.

---

## D. Citations / prior-work accuracy

11. **GSM-Hard is used as a named benchmark with no citation and a dubious "non-memorizable" label.**
    §3 and Figure 1 use "GSM-Hard grade-school word problems (a non-memorizable positive control)."
    GSM-Hard is a published, public dataset (Gao et al., 2022, "PAL") and is therefore plausibly *in*
    training data — calling it "non-memorizable" is unsupported, and it directly conflicts with §6's
    admission that "**No clean reasoning-bound positive control**" was obtained. It is also lumped under
    "every multi-digit arithmetic task" though it is word problems.
    **Fix:** cite GSM-Hard properly, drop the "non-memorizable" claim (or justify it), and reconcile
    with the §6 limitation; don't describe it as multi-digit arithmetic.

12. **Pfau et al. characterization is slightly imprecise.** §1: "[Pfau et al.] showed that inserting
    meaningless filler tokens ... can nonetheless improve performance ... and absent in the models they
    tested before 2024." Pfau et al. primarily showed filler helps *when models are trained to use it*
    (dense supervision); the *zero-shot* "recent frontier models do this off the shelf" framing is the
    **Redwood** contribution. As written it slightly conflates the two.
    **Fix:** say Pfau showed filler can substitute for chain-of-thought on parallelizable problems
    *given appropriate training*, and that the un-prompted effect on recent models is Redwood's finding.

---

## E. Numerical inconsistencies / loose numbers

13. **Figure 1 caption says "500 problems per task," but the aggregation task used 400.**
    `derisk_reasoning2_summary.csv` shows `count_correct_k6` at **n = 400**, not 500 (all the blue
    tasks are 500). **Fix:** caption "500 problems per arithmetic task; 400 for the aggregation task."

14. **The interference-cap numbers are loose and internally inconsistent.** §4.5 says "capped at about
    **half** the single-question boost (single +43 pp → ~**+25–30** pp)"; Appendix E says "**+24–30**."
    The data (`seg11_cap.csv`) are lone +43.0 and, with distractors, **+23.6 (k=2), +30.1 (k=4), +25.3
    (k=8)**. The first-distractor value (+23.6) is below the "25–30" range, and +24–30 of +43 is
    **55–70%**, not "about half."
    **Fix:** state "roughly 55–70% of the lone boost (≈+24 to +30 pp)" and make §4.5 and Appendix E use
    the same range; include the +23.6 endpoint.

15. **Two different "single-question boost" magnitudes (+35 vs +43) without reconciliation.** §3/Fig 2
    headline the single-question peak as **+35 pp**; §4.5/Appendix E cite a lone **+43 pp** "at the
    hardest items/positions." Both are real (different difficulty subsets) but a reader sees "the
    single-question boost" given two numbers.
    **Fix:** label the +43 as "hardest-quartile lone boost" to distinguish it from the +35 grid peak.

16. **Figure 2 caption "begins helping above ~15–25 tokens" understates the rise.** At ~24–25 tokens the
    boost is already **~+13 pp** (`seg11_dose.csv` lone_told@24 = 13.3; this is also the *k*=8 divided
    reference). So the boost is already large by 25 tokens, not just "beginning."
    **Fix:** "rises steeply below ~50 tokens (already ~+13 pp at 25 tokens)."

17. **"68% of the not-told single-question boost" silently uses a different baseline than Figure 2.**
    §4.3's 68% is relative to the **not-told lone boost (+38.5)** (`seg11_dose.csv` lone_nottold@200),
    not the +35 told curve shown in Figure 2. Correct, but a reader will divide 26.3/35 and get 75% and
    be confused. **Fix:** state explicitly "68% of the *not-told* single-question boost (+38.5)."

---

## F. Structure / appendices / tone

18. **Appendix G ("Reproduction") is never linked from the main body.** Body links Appendices A–F
    (verified by grep), but G is orphaned. The instructions require appendices be "correctly linked to
    throughout the main body." **Fix:** reference Appendix G from §2.6 or the Takeaways/Methods.

19. **Methods 2.6 reports the project's dollar spend ("about $2,200 of a $5,000 budget").** This is a
    research-process/agent detail, not appropriate for a finished conference paper; the instructions say
    not to reference the agent's research process. **Fix:** drop the budget line; keep only the
    "reproduces from cache at no additional API cost" note if useful, in the reproduction appendix.

20. **Adjective-stacking / restated conclusions read as padding.** E.g. §4.5/Summary: "a genuine,
    dose-responsive, difficulty-sensitive, filler-amount-dependent computation committed to one
    question." The Summary and §1 "Preview of results" also substantially restate each other.
    **Fix:** state the characterization once, in plain terms; trim the Summary/Preview overlap.

21. **§10-style "10σ below divided" is stated without the caveat the run itself flagged.** `seg8_verdict.md`
    notes the divided reference B₁(25) "sits on the steep rising edge near n_lo so SE_R could be
    under-estimated." The writeup gives the 10σ number (App C) without this caveat. Low severity since
    the ~11 pp gap dwarfs interpolation error, but the caveat should be one clause.

---

## G. Minor figure polish

22. **Figure 4 legend overlaps the *k*=4 "directed" (green) bar**, cluttering the data. Move the legend
    to empty space (lower-right is mostly empty) or below the axes.

23. **Figure 3 mixes two experiments in one "headline" figure** (the directed/reveal-before bar is from a
    different condition than the title's "share one filler pool" claim). It is explained in the caption,
    but a reader scanning the figure could read all four bars as the same experiment. Consider splitting
    or visually separating the directed bar.

---

### Spot-check summary (numbers that DO check out)
For balance: the example `95*33+51*54+30*80 = 8289` is correct; the §3/Fig 1 boosts (+30/+22/+17/+11/+13
pp), the headline cell (+2.5 [+1.2,+3.7]; Q1-only +1.2; fresh +0.9), the directedness contrasts
(+10.9/+24.2/+16.2), the framing numbers (not-told Q1 +26.3, told +1.2, disclose +2.0), the dose-response
(−1.6→+27.1), difficulty quartiles (+6.7→+16.2), and the positional default (+25.1/−2.1/+3.0/−18.0) all
match the source CSV/verdict files. The problems above are about presentation, figure/caption fidelity,
over-claiming, and undefined terms — not the core measurements.
