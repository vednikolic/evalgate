#!/usr/bin/env python3
"""Cross-model comparison for concept extraction quality.

Runs extract.py on all test sessions for multiple models, scores each,
and outputs a comparison table with cost/quality tradeoffs.

Usage:
    python3 compare.py
    python3 compare.py --models sonnet haiku
    python3 compare.py --sessions test-sessions/session-01-simple.md
    python3 compare.py --output json
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SESSIONS_DIR = SCRIPT_DIR / "test-sessions"
TRUTH_DIR = SCRIPT_DIR / "ground-truth"
RESULTS_DIR = SCRIPT_DIR / "results"


def find_sessions() -> list[Path]:
    """Find all test session files."""
    return sorted(SESSIONS_DIR.glob("session-*.md"))


def find_truth(session_path: Path) -> Path | None:
    """Find ground truth file matching a session."""
    # session-01-simple.md -> session-01-truth.json
    parts = session_path.stem.split("-")
    if len(parts) >= 2:
        session_num = parts[1]
        truth_files = list(TRUTH_DIR.glob(f"session-{session_num}-*truth.json"))
        if truth_files:
            return truth_files[0]
    return None


def run_extraction(session_path: Path, model: str) -> dict:
    """Run extract.py on a session with the given model."""
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "extract.py"),
            str(session_path),
            "--model",
            model,
            "--output",
            str(RESULTS_DIR),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        print(f"  Extraction failed: {result.stderr}", file=sys.stderr)
        return {}

    # Read the output file
    result_path = RESULTS_DIR / f"{session_path.stem}-{model}.json"
    if result_path.exists():
        with open(result_path) as f:
            return json.load(f)
    return {}


def score_extraction(extraction: dict, truth: dict) -> dict:
    """Score extraction using score.py logic (imported inline)."""
    # Import score module
    sys.path.insert(0, str(SCRIPT_DIR))
    import score as score_mod

    return score_mod.score_session(extraction, truth)


def print_comparison(model_results: dict, output_format: str = "table"):
    """Print the cross-model comparison."""
    if output_format == "json":
        print(json.dumps(model_results, indent=2))
        return

    models = list(model_results.keys())
    if len(models) < 2:
        print("Need at least 2 models for comparison.")
        if models:
            # Print single model results
            agg = model_results[models[0]]["aggregate"]
            print(f"\nResults for {models[0]}:")
            for k, v in agg["metrics"].items():
                print(f"  {k}: {v:.4f}")
        return

    print("\nModel Comparison: Concept Extraction Quality")
    print("=" * 55)

    metric_labels = {
        "precision": "Precision",
        "recall": "Recall",
        "hallucination": "Hallucination",
        "kind_accuracy": "Kind accuracy",
        "edge_recall": "Edge recall",
        "noise_rejection": "Noise reject",
    }

    # Header
    header = f"{'':>16}"
    for m in models:
        header += f"  {m:>10}"
    if len(models) == 2:
        header += f"  {'Delta':>10}"
    print(header)

    # Metrics rows
    for key, label in metric_labels.items():
        row = f"{label:>16}"
        values = []
        for m in models:
            v = model_results[m]["aggregate"]["metrics"][key]
            values.append(v)
            row += f"  {v:>10.2f}"
        if len(models) == 2:
            delta = values[0] - values[1]
            sign = "+" if delta >= 0 else ""
            # For hallucination, negative delta is good (less hallucination)
            row += f"  {sign}{delta:>9.2f}"
        print(row)

    # Cost section
    print(f"\nCost per session (avg):")
    for m in models:
        cost = model_results[m]["aggregate"]["cost"]
        inp = cost["total_input_tokens"] // model_results[m]["aggregate"]["sessions"]
        out = cost["total_output_tokens"] // model_results[m]["aggregate"]["sessions"]
        print(f"  {m}: ~${cost['avg_per_session_usd']:.4f} ({inp} input + {out} output tokens)")

    print(f"\nQuality-adjusted cost:")
    for m in models:
        cost = model_results[m]["aggregate"]["cost"]
        cpc = cost["cost_per_correct_concept"]
        print(f"  {m}: ${cpc:.4f} per correct concept")

    # Per-session breakdown
    print(f"\nPer-session breakdown:")
    print(f"{'Session':<30}", end="")
    for m in models:
        print(f"  {'Prec':>5} {'Rec':>5}", end="")
    print()
    print("-" * (30 + len(models) * 12))

    # Get session names from first model
    first_model = models[0]
    for s in model_results[first_model]["sessions"]:
        session_name = s["session"]
        row = f"{session_name:<30}"
        for m in models:
            ms = next((x for x in model_results[m]["sessions"] if x["session"] == session_name), None)
            if ms:
                row += f"  {ms['metrics']['precision']:>5.2f} {ms['metrics']['recall']:>5.2f}"
            else:
                row += f"  {'N/A':>5} {'N/A':>5}"
        print(row)


def main():
    parser = argparse.ArgumentParser(description="Cross-model comparison of concept extraction")
    parser.add_argument("--models", nargs="+", default=["sonnet", "haiku"], help="Models to compare")
    parser.add_argument("--sessions", nargs="*", default=None, help="Specific session files (default: all)")
    parser.add_argument("--output", default="table", choices=["table", "json"], help="Output format")
    parser.add_argument("--skip-extract", action="store_true", help="Use existing results, skip extraction")
    args = parser.parse_args()

    os.makedirs(RESULTS_DIR, exist_ok=True)

    sessions = [Path(s) for s in args.sessions] if args.sessions else find_sessions()
    if not sessions:
        print("No test sessions found.", file=sys.stderr)
        sys.exit(1)

    model_results = {}

    for model in args.models:
        print(f"\n{'=' * 40}")
        print(f"Running extractions with {model}")
        print(f"{'=' * 40}")

        session_scores = []

        for session in sessions:
            truth_path = find_truth(session)
            if not truth_path:
                print(f"  Skipping {session.name}: no ground truth found")
                continue

            result_path = RESULTS_DIR / f"{session.stem}-{model}.json"

            if args.skip_extract and result_path.exists():
                print(f"  Using cached: {session.name}")
                with open(result_path) as f:
                    extraction = json.load(f)
            else:
                print(f"  Extracting: {session.name} ...", end=" ", flush=True)
                extraction = run_extraction(session, model)
                if not extraction:
                    print("FAILED")
                    continue
                print(f"done ({len(extraction.get('concepts', []))} concepts)")

            with open(truth_path) as f:
                truth = json.load(f)

            score = score_extraction(extraction, truth)
            session_scores.append(score)

        if session_scores:
            sys.path.insert(0, str(SCRIPT_DIR))
            import score as score_mod

            agg = score_mod.aggregate_scores(session_scores)
            model_results[model] = {
                "sessions": session_scores,
                "aggregate": agg,
            }

    print("\n")
    print_comparison(model_results, args.output)

    # Save full results
    results_file = RESULTS_DIR / "comparison.json"
    with open(results_file, "w") as f:
        json.dump(model_results, f, indent=2)
    print(f"\nFull results saved to {results_file}")


if __name__ == "__main__":
    main()
