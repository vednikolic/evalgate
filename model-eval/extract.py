#!/usr/bin/env python3
"""Extract concepts from a session transcript using an LLM.

Sends the extraction prompt (matching cortex /save Step 4b) to the specified
model via claude -p, parses the structured JSON response.

Usage:
    python3 extract.py test-sessions/session-01-simple.md --model sonnet
    python3 extract.py test-sessions/session-01-simple.md --model haiku --output results/
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

EXTRACTION_PROMPT = """You are a concept extraction system. Given a session summary, identify the key concepts worth persisting in a knowledge graph.

## Rules

1. Extract concepts that represent tools, patterns, decisions, or recurring themes. NOT ephemeral details like quick lookups, typo fixes, or one-off questions.
2. For each concept, assign a kind: one of topic, tool, pattern, decision, person, project.
3. For each concept, identify relationships (edges) to other extracted concepts. Use relation types: related-to, depends-on, conflicts-with, enables, is-instance-of, supersedes, blocked-by, derived-from.
4. Reject concepts that are too generic (e.g., "python", "code"), too ephemeral (e.g., "typo fix"), or already fully captured by another concept.
5. Report the count of rejected candidate concepts.

## Existing vocabulary

(Empty graph -- no existing concepts to match against)

## Session summary

{session_content}

## Output format

Return ONLY valid JSON with this exact structure, no markdown fencing, no explanation:

{{
  "concepts": [
    {{"name": "concept-name", "kind": "pattern"}}
  ],
  "edges": [
    {{"from": "concept-a", "to": "concept-b", "relation": "related-to"}}
  ],
  "rejected_count": 0
}}

Use lowercase hyphenated names for concepts. Be selective: only extract concepts with lasting value for a knowledge graph."""


def run_extraction(session_path: str, model: str) -> dict:
    """Run concept extraction on a session transcript using the specified model."""
    session_content = Path(session_path).read_text()

    prompt = EXTRACTION_PROMPT.format(session_content=session_content)

    start_time = time.time()
    result = subprocess.run(
        ["claude", "-p", "--model", model, "--output-format", "json"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=120,
    )
    elapsed = time.time() - start_time

    if result.returncode != 0:
        print(f"Error running claude: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    # Parse the claude JSON output to get the result text and cost info
    try:
        claude_output = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"Failed to parse claude output as JSON: {result.stdout[:500]}", file=sys.stderr)
        sys.exit(1)

    # Extract the text content from claude's response
    response_text = ""
    if isinstance(claude_output, dict):
        response_text = claude_output.get("result", "")
        cost_usd = claude_output.get("total_cost_usd", 0) or 0
        usage = claude_output.get("usage", {})
        input_tokens = usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
    else:
        response_text = str(claude_output)
        cost_usd = 0
        input_tokens = 0
        output_tokens = 0

    # Strip markdown code fences if present
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    # Parse the extraction JSON
    try:
        extraction = json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON within the response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                extraction = json.loads(text[start:end])
            except json.JSONDecodeError:
                print(f"Failed to parse extraction JSON from response:\n{text[:500]}", file=sys.stderr)
                sys.exit(1)
        else:
            print(f"No JSON found in response:\n{text[:500]}", file=sys.stderr)
            sys.exit(1)

    # Normalize the output
    concepts = extraction.get("concepts", [])
    edges = extraction.get("edges", [])
    rejected_count = extraction.get("rejected_count", 0)

    return {
        "session": os.path.basename(session_path),
        "model": model,
        "concepts": concepts,
        "edges": edges,
        "rejected_count": rejected_count,
        "cost_usd": cost_usd,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "elapsed_seconds": round(elapsed, 2),
    }


def main():
    parser = argparse.ArgumentParser(description="Extract concepts from a session transcript")
    parser.add_argument("session", help="Path to session transcript markdown file")
    parser.add_argument("--model", default="sonnet", help="Model to use (sonnet, haiku, opus)")
    parser.add_argument("--output", default=None, help="Output directory for results JSON")
    args = parser.parse_args()

    if not os.path.exists(args.session):
        print(f"Session file not found: {args.session}", file=sys.stderr)
        sys.exit(1)

    result = run_extraction(args.session, args.model)

    if args.output:
        os.makedirs(args.output, exist_ok=True)
        session_name = Path(args.session).stem
        out_path = os.path.join(args.output, f"{session_name}-{args.model}.json")
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2)
        print(f"Results written to {out_path}")
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
