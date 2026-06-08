# Red-team review of `final_writeup.md` (round 1)

Scope note: I cross-checked every headline number against `/source/phase_segment_12_phase_0/results/`.
The quantitative claims are accurate (35.5, 2.5, 1.2, 13.7, 18.7, 26.3, 31.9, 1.50, 25.1/-18.0,
43.0/23.6–30.1, DeepSeek 3.4/4.3/1.9, 6.7→16.2, $2168, 274k calls, the concrete-example outputs
10328/11348/10448 all verify). The problems below are therefore about *presentation, framing, and
missing context*, not arithmetic errors. Ordered by severity.

---

## 1. (HIGH) The single "concrete example" is from a secondary condition and shows the *opposite* of the headline
Location: section "A concrete example".
The whole worked example is drawn from the **not-told framing**, and it shows filler **flipping a wrong
answer to a correct one on Q1** (`10328` → `11348`). But the paper's headline (title, abstract, Fig 1) is
that in the **told / reveal-after** condition the per-question boost is near-null (≈1–2.5 pp) — i.e. filler
does *not* help. The instructions say to "anchor the main result to one concrete worked example ... show a
representative case." The chosen case is unrepresentative: it is exactly the one framing where filler helps
a single position (+25.1 pp on Q1, per `seg11_default.md`). A reader who only reads the example will come
away believing filler reliably helps, the reverse of the conclusion.
Fix: lead with a representative **told reveal-after** instance (target revealed after filler, k=8) where
the same item is *not* helped by filler, plus the contrasting **reveal-before** instance where it is. Keep
the not-told flip as a later illustration for section 3, clearly labeled as the non-default-suppressed case.

## 2. (HIGH) No absolute baseline accuracies for any headline number — boosts are uninterpretable
Location: abstract; Results §1; Fig 1, Fig 2, Fig 4.
Every headline effect is reported only as a percentage-point *boost* with no "from X% to Y%". The reader
cannot tell whether "+35.5 pp" is 36%→72% (it is: k=1 sumprod n=0 = 36.3%, n=200 = 71.8%, verified in
`seg7_sumprod_k1_after.jsonl`) or 50%→85%. The only absolute accuracies in the whole post are the 52%→48%
quartile baselines in §4, which belong to a *different* (directed-difficulty) cell. The instructions ask
for "the two or three numbers that make the point"; a boost with no baseline is half a number.
Fix: state the single-question baseline (≈36% → ≈72% at 200 filler tokens) in the abstract, and give n=0
accuracies for the multi-question cells (e.g. k=8 early positions ≈20%) at least once in Methods/Results.

## 3. (HIGH) The abstract hides that the clean absolute result rests on one Opus arithmetic family
Location: abstract and §"no parallel latent thinking" framing; the caveat appears only in Limitations
("The clean absolute regime result rests mainly on one Opus arithmetic family").
The instructions are explicit: "if the clean result rests on a single case or condition, say so in the
abstract and framing, not only in a buried caveat." The cross-model (DeepSeek) replication is only
*partial* and confounded with a different task, and the difficulty-selectivity evidence is "Opus-leaning"
(per `seg11_mechanism.md`: d6 has a baseline confound, DeepSeek shows no selectivity). None of this scope
limitation is in the abstract.
Fix: add one clause to the abstract, e.g. "The clean near-null absolute result is on one Opus
sum-of-products task; the directedness/framing pattern replicates in *direction* on a second Opus task and
DeepSeek but with much smaller magnitudes."

## 4. (HIGH) Dense, undefined jargon in the abstract and early sections — reader cannot restate the result
Location: abstract ("early-position estimand", "divided-pool prediction", "directedness"), and the
example/Methods ("reveal-after/before", "told/not-told", "disclose arm", "early-position pool",
"banks on Q1", "recency-erasure", "positivity gate", "estimand").
The instructions require: "A reader should be able to restate the main result in two plain sentences using
only the post," and "define any term that isn't standard English or standard ML on first use." The abstract
uses "early-position estimand" and "divided-pool prediction" with no prior definition; "estimand" and
"positivity gate" are statistics jargon; "told/not-told/disclose" are run-internal names introduced before
they are explained. Several terms ("banks on Q1", "recency-erasure") are coinages used without a definition.
Fix: in the abstract, replace "early-position estimand" with plain language ("the boost on the first-listed
questions") and avoid "estimand" entirely. Define "target revealed before vs after the filler" and the
three framings (model told nothing / told a random question is coming / told but without the "be ready"
encouragement) in plain words in Methods *before* using the labels, and pick one consistent name for each.

## 5. (MEDIUM-HIGH) The exact prompt wording — the crux of section 3 — is never shown
Location: §3 and Methods; Reproducibility appendix lists code files but no prompt text.
The entire framing finding (§3: +1.2 told → +26.3 not-told, suppressed by disclosure) hinges on a one-clause
difference in the prompt, yet the reader is never shown the actual sentences. The verbatim strings exist in
`kharness.py:54-57`: told = "In a moment I will ask you to answer exactly ONE of them, chosen at random —
so be ready to answer any of them. Do not answer yet."; reveal-before = "You will be asked to answer Q{j}.
Do not answer yet." A finding about wording must quote the wording.
Fix: add an appendix block with the verbatim told / not-told / disclose / reveal-before turn-1 and turn-3
text, and reference it from §3.

## 6. (MEDIUM) Inconsistent, unexplained operating-point convention makes the "divided-pool prediction" look self-contradictory
Location: §1 vs §2 / Fig 2.
The "single-question reference" and "divided-pool prediction" silently change value because different k use
different filler totals at their "operating points" (k=2 at n=100, k=4/k=8 at n=200), which is never stated
in the main text. So the k=2 divided prediction is 23.6 pp in §1 (n=100) but 33.5 pp in §2/Fig 2 (n=200),
and the "23% retained at k=2" uses n=100 while "7% at k=8" uses n=200. A reader comparing the two figures
will think the numbers conflict.
Fix: state the operating-point convention once in Methods, and either hold the filler total fixed across k
for the retention comparison or label each retention fraction with its n.

## 7. (MEDIUM) Two competing headline numbers (early-pool 2.5 vs Q1 1.2) are toggled without a single plain framing
Location: abstract, §1, Fig 1.
The abstract reports both "2.5 points on the early-position estimand" and "1.2 points on Q1 alone"; Fig 1
plots 2.5; the verbal conclusion ("commits at most about one question's worth ... defaults to the first
question") leans on the Q1 number. The instructions: "Choose the simplest framing, metric, and example
that is still faithful." Carrying two near-null numbers for the same headline cell forces the reader to
track which is which.
Fix: pick one as the headline (Q1-only is the cleanest single-position read and matches the "first
question" story), report it consistently, and relegate the early-pool number to a parenthetical/appendix.

## 8. (MEDIUM) Figure 4 mixes told and not-told curves against a single told reference
Location: Fig 4 and caption.
The orange "Default first question, target not disclosed" series is a **not-told** measurement, but the grey
"single-question reference" is the **told** lone curve (+35.5 at 200). The correct reference for the
not-told multi-question boost is the *not-told* lone curve (≈+38, per `seg11_mechanism.md` table A), which
is omitted. The text also says the directed boost "tracks the single-question boost curve," but in the
figure the green named-target line sits ~10 pp below the grey reference throughout (the context-interference
cap), so "tracks" overstates the agreement.
Fix: either add the not-told lone reference or restrict Fig 4 to one framing; soften "tracks" to "rises and
plateaus with the same shape but ~10 pp lower, reflecting the multi-question interference cap."

## 9. (MEDIUM) The "single-question reference" (35.5 pp) is the structure-matched k=1, larger than the project's own B₁(n) characterization (23.3 pp), and this is not reconciled
Location: abstract ("improved accuracy by 35.5 percentage points") and §1.
`results/b1curve_summary.md` reports the sumprod single-question plateau boost as **23.3 pp** (base 39.8%),
whereas the structure-matched k=1 reference used as the headline is **35.5 pp** (base 36.3%). Both are
defensible (different item sampling/harness), but the abstract presents 35.5 as the basic filler-replication
number with no note that the standalone B₁(n) curve gives a notably smaller plateau. A reader checking the
appendix's `b1curve_summary.md` will see a conflicting number.
Fix: state that 35.5 pp is the structure-matched single-question reference (the correct comparison for the
multi-question cells) and note the standalone B₁(n) plateau is smaller, with one sentence on why.

## 10. (MEDIUM) Figure legends/labels use cryptic or run-internal shorthand
Location: Fig 2 legend "Measured boost"; Fig 3 axis "Q1 accuracy boost" and legend "Disclosure without
encouragement"; "Q1/Q8" throughout.
Per the instructions, every series/axis must be spelled out for a reader who has never seen the run.
"Measured boost" does not say *which* boost (it is the early-position, target-revealed-after boost).
"Q1" is run-internal for "the first-listed question." "Disclosure without encouragement" assumes the reader
knows what the "encouragement" clause was.
Fix: Fig 2 legend → "Early-position boost (target revealed after filler)"; Fig 3 axis →
"Accuracy boost on the first-listed question (pp)"; define "Q1" = "first-listed question" on first use;
Fig 3 legend → spell out the three prompts in plain words ("told a random question is coming",
"told but without the 'be ready' line", "not told").

## 11. (MEDIUM-LOW) The interpretive limit that "parallel was essentially unreachable in-prompt" is not surfaced for the title
Location: title/abstract; Limitations only obliquely ("Multi-question context itself changes the task and
caps even directed performance"; "interference-naive reference").
The pre-registration (`preregistration.md`, caveat i) is explicit that context interference removes ~half
the single-question boost *before any sharing*, so even a fully directed in-prompt process cannot reach the
"parallel" reference. The result (B_k ≪ divided) still rejects parallel a fortiori, so the title is fine —
but a reader should be told that the experiment could never have *observed* parallel, which bears on how to
read "do not produce parallel latent thinking."
Fix: one sentence in Methods/Limitations: "Because multi-question context alone removes ~half the
single-question boost, the parallel reference is unreachable in-prompt; the directly testable claim is that
the shared boost falls far below the even-split (divided) prediction."

## 12. (LOW) Replication is not presented as a clean standalone first result
Location: Results §1 ("Filler strongly helps one question, but not eight shared questions").
The instructions say results should be "ordered by importance (replication of prior work first)." The
Redwood replication (the +35.5 single-question effect, genuine no-CoT) is folded into the same sentence as
the main negative result rather than established first as its own short result with baseline numbers and a
sanity check against Redwood's reported magnitude.
Fix: a short Results §0/§1 "Replication" that states the single-question effect, the baseline, and that it
reproduces the Redwood direction (noting the magnitude differs because the task is harder/calibrated).

## 13. (LOW) The concrete-example section precedes Methods and uses undefined terms
Location: §"A concrete example" (appears before Methods).
It uses "fixed-item", "prefill", "reveal", "Q1/Q8", "not-told framing" before Methods defines the setup.
Fix: either move it after a 2–3 sentence plain-words setup, or inline-define each term on first use.

## 14. (LOW) DeepSeek k=8 used a different filler budget (≈400 tokens), not noted in the comparison
Location: §5.
The DeepSeek k=8 cell operates at n≈399 tokens (`seg9_verdict.md`), not the 200 used for Opus, because the
task saturates. The §5 text compares "below its divided-pool prediction by 4.3 pp" without flagging that the
filler budget differs from the Opus cells, on top of the (acknowledged) task difference.
Fix: note the DeepSeek operating point (≈400 tokens) alongside the comparison.

## 15. (LOW) Figure 1 caption mixes two meanings of "error bar" on one chart
Location: Fig 1 caption ("Error bars are 95% intervals for measured cells and bootstrapped reference
uncertainty").
Two of the four bars (single-question reference, divided-pool) are *predictions/references*, not measured
conditions, yet all four carry visually identical error bars. The reader cannot tell which bars are
measurements and which are model references.
Fix: visually distinguish reference bars (e.g. hatched or a different shade) and say so in the caption.

## 16. (LOW) Minor wording / unsourced asides
- Intro: "Pfau, Merrill, and Bowman ... studied a related mechanism" — too vague; state what they found
  (filler tokens substitute for CoT on *parallelizable* problems; pre-2024 models couldn't), which is the
  relevant contrast for this work.
- §"Other findings": "Earlier replication work also found selectivity: filler helped deep multi-digit
  arithmetic but not an aggregate-many-easy-checks control" — no figure/appendix pointer; either cite the
  artifact (segment-5/harder-probe) or drop.
- Methods: "the positivity gate failed" and abstract "estimand" — replace with plain language
  ("the shared-question boosts were near zero, so the sharing exponent α is undefined").
