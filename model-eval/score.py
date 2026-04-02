#!/usr/bin/env python3
"""Score extraction results against ground truth.

Computes precision, recall, hallucination rate, kind accuracy, edge recall,
and noise rejection for a model's concept extraction.

Usage:
    python3 score.py results/session-01-simple-sonnet.json ground-truth/session-01-truth.json
    python3 score.py results/ ground-truth/ --aggregate --output json
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path


def normalize_name(name: str) -> str:
    """Normalize a concept name for fuzzy matching.

    Strips hyphens, underscores, extra spaces, lowercases.
    'eval-inversion' matches 'eval inversion' matches 'inverted evals'.
    """
    s = name.lower().strip()
    s = re.sub(r"[-_]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s


def names_match(a: str, b: str) -> bool:
    """Check if two concept names match fuzzily.

    Handles exact match after normalization, plus common variations:
    - Pluralization (query/queries)
    - Participial forms (logging/log, testing/test)
    - Reordering of 2-word names (bucket token / token bucket)
    """
    na = normalize_name(a)
    nb = normalize_name(b)

    if na == nb:
        return True

    # Check if one is a subset of the other (handles "rate limiting" vs "rate limit")
    words_a = set(na.split())
    words_b = set(nb.split())

    # Strip common suffixes for stem comparison
    def stems(words: set) -> set:
        result = set()
        for w in words:
            # Simple stemming: remove common suffixes
            for suffix in ("ing", "tion", "ation", "s", "es", "ed", "ly"):
                if w.endswith(suffix) and len(w) > len(suffix) + 2:
                    result.add(w[: -len(suffix)])
                    break
            else:
                result.add(w)
        return result

    stems_a = stems(words_a)
    stems_b = stems(words_b)

    # Stem match (handles "structured logging" vs "structured log")
    if stems_a == stems_b:
        return True

    # Word reorder match (handles "token bucket" vs "bucket token")
    if words_a == words_b:
        return True

    # Subset match: all words from the shorter name appear in the longer one.
    # Handles "pytest" matching "pytest-framework-choice",
    # "exponential-backoff" matching "exponential-backoff-with-jitter".
    if words_a.issubset(words_b) or words_b.issubset(words_a):
        return True

    # Stem-based subset match: handles plural/participial variations in subsets.
    # "transient-vs-permanent-errors" matches "transient-vs-permanent-error-classification"
    if stems_a.issubset(stems_b) or stems_b.issubset(stems_a):
        return True

    return False


def find_matching_concept(extracted_name: str, ground_truth_concepts: list) -> dict | None:
    """Find the best matching ground truth concept for an extracted name."""
    for gt in ground_truth_concepts:
        if names_match(extracted_name, gt["name"]):
            return gt
    return None


SYMMETRIC_RELATIONS = {"related-to"}
INVERSE_RELATIONS = {
    "depends-on": "enables",
    "enables": "depends-on",
}


def edges_match(extracted: dict, expected: dict) -> bool:
    """Check if an extracted edge matches an expected edge.

    Handles:
    - Fuzzy concept name matching on from/to
    - Symmetric relations (related-to) match regardless of direction
    - Inverse relations (depends-on/enables) match with swapped direction
    """
    e_from = extracted.get("from", "")
    e_to = extracted.get("to", "")
    e_rel = extracted.get("relation", "").lower()
    g_from = expected["from"]
    g_to = expected["to"]
    g_rel = expected["relation"].lower()

    # Direct match: same direction, same relation
    if names_match(e_from, g_from) and names_match(e_to, g_to) and e_rel == g_rel:
        return True

    # Symmetric relation: either direction
    if g_rel in SYMMETRIC_RELATIONS and e_rel == g_rel:
        if names_match(e_from, g_to) and names_match(e_to, g_from):
            return True

    # Inverse relation: swapped direction with inverse relation type
    inverse = INVERSE_RELATIONS.get(g_rel)
    if inverse and e_rel == inverse:
        if names_match(e_from, g_to) and names_match(e_to, g_from):
            return True

    return False


def score_session(extraction: dict, ground_truth: dict) -> dict:
    """Score a single session's extraction against ground truth."""
    extracted_concepts = extraction.get("concepts", [])
    gt_concepts = ground_truth["expected_concepts"]
    gt_edges = ground_truth["expected_edges"]
    rejected_count = extraction.get("rejected_count", 0)
    rej_min = ground_truth.get("expected_rejections_min", 0)
    rej_max = ground_truth.get("expected_rejections_max", 99)

    # Match extracted concepts against ground truth (1-to-1 matching).
    # Each ground truth concept can be matched at most once. Prefer exact
    # matches over fuzzy ones to avoid a fuzzy match stealing a slot from
    # a better exact match later.
    matched = []
    unmatched_extracted = []
    claimed_gt = set()  # indices of GT concepts already matched

    # Pass 1: exact matches (after normalization)
    for ec in extracted_concepts:
        for idx, gt in enumerate(gt_concepts):
            if idx in claimed_gt:
                continue
            if normalize_name(ec["name"]) == normalize_name(gt["name"]):
                matched.append({"extracted": ec, "ground_truth": gt})
                claimed_gt.add(idx)
                break

    # Pass 2: fuzzy matches for remaining extracted concepts
    matched_extracted_names = {m["extracted"]["name"] for m in matched}
    for ec in extracted_concepts:
        if ec["name"] in matched_extracted_names:
            continue
        found = False
        for idx, gt in enumerate(gt_concepts):
            if idx in claimed_gt:
                continue
            if names_match(ec["name"], gt["name"]):
                matched.append({"extracted": ec, "ground_truth": gt})
                claimed_gt.add(idx)
                found = True
                break
        if not found:
            unmatched_extracted.append(ec)

    # Find which required concepts were found
    required_concepts = [gt for gt in gt_concepts if gt.get("required", False)]
    required_found = []
    for rc in required_concepts:
        for m in matched:
            if m["ground_truth"]["name"] == rc["name"]:
                required_found.append(rc)
                break

    # Precision: matched / total extracted
    total_extracted = len(extracted_concepts)
    precision = len(matched) / total_extracted if total_extracted > 0 else 0.0

    # Recall: required found / total required
    total_required = len(required_concepts)
    recall = len(required_found) / total_required if total_required > 0 else 1.0

    # Hallucination rate: unmatched / total extracted
    hallucination = len(unmatched_extracted) / total_extracted if total_extracted > 0 else 0.0

    # Kind accuracy: correct kinds among matched concepts
    kind_correct = sum(
        1
        for m in matched
        if m["extracted"].get("kind", "").lower() == m["ground_truth"]["kind"].lower()
    )
    kind_accuracy = kind_correct / len(matched) if matched else 0.0

    # Edge recall: expected edges found / total expected edges
    extracted_edges = extraction.get("edges", [])
    edges_found = 0
    for ge in gt_edges:
        for ee in extracted_edges:
            if edges_match(ee, ge):
                edges_found += 1
                break
    edge_recall = edges_found / len(gt_edges) if gt_edges else 1.0

    # Noise rejection: 1 if rejected count within expected range
    noise_rejection = 1.0 if rej_min <= rejected_count <= rej_max else 0.0

    return {
        "session": extraction.get("session", "unknown"),
        "model": extraction.get("model", "unknown"),
        "metrics": {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "hallucination": round(hallucination, 4),
            "kind_accuracy": round(kind_accuracy, 4),
            "edge_recall": round(edge_recall, 4),
            "noise_rejection": noise_rejection,
        },
        "details": {
            "concepts_extracted": total_extracted,
            "concepts_matched": len(matched),
            "concepts_hallucinated": len(unmatched_extracted),
            "required_total": total_required,
            "required_found": len(required_found),
            "edges_expected": len(gt_edges),
            "edges_found": edges_found,
            "rejected_count": rejected_count,
            "rejected_range": f"{rej_min}-{rej_max}",
        },
        "cost": {
            "cost_usd": extraction.get("cost_usd", 0),
            "input_tokens": extraction.get("input_tokens", 0),
            "output_tokens": extraction.get("output_tokens", 0),
        },
    }


def aggregate_scores(scores: list) -> dict:
    """Compute aggregate metrics across multiple session scores."""
    if not scores:
        return {}

    metrics_keys = ["precision", "recall", "hallucination", "kind_accuracy", "edge_recall", "noise_rejection"]
    aggregate = {}
    for key in metrics_keys:
        values = [s["metrics"][key] for s in scores]
        aggregate[key] = round(sum(values) / len(values), 4)

    total_cost = sum(s["cost"]["cost_usd"] for s in scores)
    total_input = sum(s["cost"]["input_tokens"] for s in scores)
    total_output = sum(s["cost"]["output_tokens"] for s in scores)
    total_correct = sum(s["details"]["concepts_matched"] for s in scores)

    return {
        "model": scores[0]["model"] if scores else "unknown",
        "sessions": len(scores),
        "metrics": aggregate,
        "cost": {
            "total_usd": round(total_cost, 6),
            "avg_per_session_usd": round(total_cost / len(scores), 6) if scores else 0,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "cost_per_correct_concept": round(total_cost / total_correct, 6) if total_correct > 0 else 0,
        },
    }


def load_results_and_truth(results_path: str, truth_path: str) -> list:
    """Load matching result/truth pairs from directories or single files."""
    pairs = []

    if os.path.isfile(results_path) and os.path.isfile(truth_path):
        with open(results_path) as f:
            extraction = json.load(f)
        with open(truth_path) as f:
            truth = json.load(f)
        pairs.append((extraction, truth))
    elif os.path.isdir(results_path) and os.path.isdir(truth_path):
        for rf in sorted(Path(results_path).glob("*.json")):
            # Extract session number from filename like session-01-simple-sonnet.json
            parts = rf.stem.split("-")
            if len(parts) >= 2:
                # Find matching truth file
                session_num = parts[1]  # "01", "02", etc.
                truth_files = list(Path(truth_path).glob(f"session-{session_num}-*-truth.json"))
                if not truth_files:
                    truth_files = list(Path(truth_path).glob(f"*-{session_num}-*truth*.json"))
                if truth_files:
                    with open(rf) as f:
                        extraction = json.load(f)
                    with open(truth_files[0]) as f:
                        truth = json.load(f)
                    pairs.append((extraction, truth))
    return pairs


def print_scores(scores: list, output_format: str = "table"):
    """Print scores in the requested format."""
    if output_format == "json":
        agg = aggregate_scores(scores)
        print(json.dumps({"sessions": scores, "aggregate": agg}, indent=2))
        return

    # Table format
    model = scores[0]["model"] if scores else "unknown"
    print(f"\nScores for {model}")
    print("=" * 70)
    print(f"{'Session':<30} {'Prec':>6} {'Rec':>6} {'Hall':>6} {'Kind':>6} {'Edge':>6} {'Noise':>6}")
    print("-" * 70)

    for s in scores:
        m = s["metrics"]
        print(
            f"{s['session']:<30} {m['precision']:>6.2f} {m['recall']:>6.2f} "
            f"{m['hallucination']:>6.2f} {m['kind_accuracy']:>6.2f} "
            f"{m['edge_recall']:>6.2f} {m['noise_rejection']:>6.0f}"
        )

    agg = aggregate_scores(scores)
    print("-" * 70)
    am = agg["metrics"]
    print(
        f"{'AVERAGE':<30} {am['precision']:>6.2f} {am['recall']:>6.2f} "
        f"{am['hallucination']:>6.2f} {am['kind_accuracy']:>6.2f} "
        f"{am['edge_recall']:>6.2f} {am['noise_rejection']:>6.2f}"
    )

    ac = agg["cost"]
    print(f"\nCost: ${ac['total_usd']:.4f} total ({ac['total_input_tokens']} in + {ac['total_output_tokens']} out)")
    print(f"  Avg per session: ${ac['avg_per_session_usd']:.4f}")
    if ac["cost_per_correct_concept"] > 0:
        print(f"  Per correct concept: ${ac['cost_per_correct_concept']:.4f}")


def main():
    parser = argparse.ArgumentParser(description="Score extraction results against ground truth")
    parser.add_argument("results", help="Path to results JSON file or directory")
    parser.add_argument("truth", help="Path to ground truth JSON file or directory")
    parser.add_argument("--output", default="table", choices=["table", "json"], help="Output format")
    parser.add_argument("--aggregate", action="store_true", help="Show only aggregate scores")
    args = parser.parse_args()

    pairs = load_results_and_truth(args.results, args.truth)
    if not pairs:
        print("No matching result/truth pairs found.", file=sys.stderr)
        sys.exit(1)

    scores = [score_session(ext, truth) for ext, truth in pairs]

    if args.output == "json":
        agg = aggregate_scores(scores)
        output = {"sessions": scores, "aggregate": agg}
        print(json.dumps(output, indent=2))
    else:
        print_scores(scores)


if __name__ == "__main__":
    main()
