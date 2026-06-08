# Review response — round 1

I treated all 19 review items as real and addressed them in `final_writeup.md` and/or regenerated figures. No items were skipped.

Summary of major changes:

- Reframed fabrication from “faithfully transferred” to “amplified / made legible an already-present base tendency,” with raw base rates (~0.17) shown next to the direction-imputed estimate (~0.81).
- Updated Figure 2 to plot raw bars and overlay the base fabrication sensitivity band rather than plotting the imputed estimate as an ordinary bar.
- Flagged the PFF-vs-SDF input-condition asymmetry in the abstract, Results §1, and Figure 1 caption.
- Added a concrete Distinguish worked example (`sdf_roman_concrete`) with base vs PFF outputs.
- Explained why the audit fabrication example uses a standing-authorization fact and how it relates to caution suppression.
- Reconciled S7 and S8 single-turn agentic rates by noting they come from different runs.
- Added the base model’s direct / multiple-choice / downstream scores in the belief table.
- Renamed the external evaluation set as a 22-fact distilled belief set rather than implying the published benchmark was imported wholesale.
- Softened “long-horizon” framing to “moderately long” where appropriate and stated the tested scale (≤~40 turns / ~2.9k tokens).
- Added scope notes that the planned Hua et al. benchmark and honesty / lie-detection testbeds were not run.
- Made cost wording consistent around SDF’s $20.08 marginal per-fact cost and PFF’s ~71-fact break-even for the carried-model lineage.
- Disclosed the semi-blind audit design.
- Standardized metric naming around “misbehavior rate.”
- Added citations for Hua et al., Casademunt et al., and Wang et al. honesty where scope/eval-awareness are discussed.
- Replaced “tie” language with statistically indistinguishable / overlapping-CI language.
- Regenerated Figure 1 with clearer title/y-axis and Figure 3 with visible 0/24 base markers.
- Added a note explaining why the step-132 checkpoint was carried over the best-validation step-60 checkpoint.
