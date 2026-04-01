# Evalgate

Evaluation methodology and tooling for AI products.

Not another eval framework. The principles and tooling that make evals operational: schema normalization, constraint gates, batch execution, variance-aware regression detection.

## Status

Work in progress. Extracting methodology and tooling from production use across hundreds of LLM evals and 5 skills.

## Design Principles

Discovered through real eval failures across multiple AI products:

- **Atomic evals only.** One assertion per eval. Compound checks create artificial score ceilings unrelated to actual quality.
- **Constraint gates.** Support a `constraint_gate` eval category where any failure zeroes the composite score. The eval equivalent of a CI gate.
- **Schema normalization.** Real projects accumulate eval files with drifting schemas. Normalize on ingestion, mapping variant field names to canonical forms.
- **LLM-as-judge variance is 5-7.5%.** Regression detection must account for noise. Flag regressions beyond significance threshold, not raw diffs.
- **Batch eval by default.** Sending all evals in one LLM call vs N individual calls cuts cost and latency. Batch by default, isolated runs opt-in.
- **Equal score = no improvement.** When a change produces the same score, treat as no improvement. "No worse" is not "safe to ship."

## Proven Across

- [Cortex](https://github.com/vednikolic/cortex): 89 LLM evals across 3 production skills (86-100% pass rates)
- [PM AutoResearch](https://github.com/vednikolic/pm-autoresearch): Automated eval loop that improved a PRD from 17% to 94%
- [Red-Team](https://github.com/vednikolic/red-team): 18 evals, 100% pass rate
- [Steelman](https://github.com/vednikolic/steelman): 16 evals, 96.55% pass rate

## What's Coming

- Eval runner with schema normalization and constraint gate enforcement
- Model-level eval examples (concept extraction quality, multi-agent pipeline accuracy)
- Cost/quality tradeoff measurement across models
- Token index thesis: measuring AI value delivered per token consumed

## Related

- [vednikolic.com](https://vednikolic.com) for the full methodology
- [PM AutoResearch](https://github.com/vednikolic/pm-autoresearch) for the automated iteration loop
- [Cortex](https://github.com/vednikolic/cortex) for a shipped product built with this methodology
