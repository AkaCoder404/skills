#!/usr/bin/env python3
"""
Parse Langfuse trace JSON into a consumable format for LLM agents.
Flattens the observation tree into a structured, readable format.
"""

import json
import sys
from datetime import datetime
from pathlib import Path


def format_duration(seconds: float) -> str:
    """Format duration in human-readable format."""
    if seconds < 1:
        return f"{seconds*1000:.1f}ms"
    elif seconds < 60:
        return f"{seconds:.2f}s"
    else:
        mins = int(seconds // 60)
        secs = seconds % 60
        return f"{mins}m {secs:.1f}s"


def truncate_text(text: str, max_length: int = 500) -> str:
    """Truncate text with ellipsis if too long."""
    if not text:
        return ""
    text_str = str(text)
    if len(text_str) <= max_length:
        return text_str
    return text_str[:max_length] + "..."


def get_observation_summary(obs: dict) -> str:
    """Get a one-line summary of an observation."""
    typ = obs.get("type", "UNKNOWN")
    name = obs.get("name", "unnamed")

    if typ == "GENERATION":
        model = obs.get("model", "unknown")
        tokens = obs.get("totalTokens", 0)
        latency = obs.get("latency", 0)
        return f"[{typ}] {name} ({model}, {tokens} tokens, {format_duration(latency)})"

    elif typ == "TOOL":
        tool_name = obs.get("name", "unknown")
        latency = obs.get("latency", 0)
        return f"[{typ}] {tool_name} ({format_duration(latency)})"

    elif typ == "CHAIN":
        latency = obs.get("latency", 0)
        return f"[{typ}] {name}" + (f" ({format_duration(latency)})" if latency > 0 else "")

    elif typ == "AGENT":
        return f"[{typ}] {name}"

    elif typ == "SPAN":
        return f"[{typ}] {name}"

    return f"[{typ}] {name}"


def format_observation_detail(obs: dict, indent: int = 0) -> list[str]:
    """Format detailed information about an observation."""
    lines = []
    prefix = "  " * indent

    typ = obs.get("type", "UNKNOWN")
    name = obs.get("name", "unnamed")
    obs_id = obs.get("id", "unknown")
    latency = obs.get("latency", 0)
    start_time = obs.get("startTime", "")
    end_time = obs.get("endTime", "")

    # Header line
    status = "✓" if obs.get("level") != "ERROR" else "✗"
    lines.append(f"{prefix}{status} [{typ}] {name}")
    lines.append(f"{prefix}    ID: {obs_id}")

    # Timing
    if start_time and end_time:
        try:
            dt_start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            dt_end = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            lines.append(f"{prefix}    Time: {dt_start.strftime('%H:%M:%S')} → {dt_end.strftime('%H:%M:%S')} ({format_duration(latency)})")
        except:
            lines.append(f"{prefix}    Duration: {format_duration(latency)}")

    # Type-specific details
    if typ == "GENERATION":
        model = obs.get("model", "unknown")
        prompt_tokens = obs.get("promptTokens", 0)
        completion_tokens = obs.get("completionTokens", 0)
        total_tokens = obs.get("totalTokens", 0)
        cost = obs.get("calculatedTotalCost", 0)

        lines.append(f"{prefix}    Model: {model}")
        lines.append(f"{prefix}    Tokens: {prompt_tokens} + {completion_tokens} = {total_tokens}")
        if cost > 0:
            lines.append(f"{prefix}    Cost: ${cost:.6f}")

        # Input
        input_data = obs.get("input")
        if input_data:
            lines.append(f"{prefix}    Input: {truncate_text(input_data, 300)}")

        # Output
        output_data = obs.get("output")
        if output_data:
            lines.append(f"{prefix}    Output: {truncate_text(output_data, 300)}")

    elif typ == "TOOL":
        # Input
        input_data = obs.get("input")
        if input_data:
            lines.append(f"{prefix}    Input: {truncate_text(input_data, 300)}")

        # Output
        output_data = obs.get("output")
        if output_data:
            lines.append(f"{prefix}    Output: {truncate_text(output_data, 300)}")

        # Error?
        if obs.get("level") == "ERROR":
            status_msg = obs.get("statusMessage", "Unknown error")
            lines.append(f"{prefix}    ERROR: {status_msg}")

    elif typ == "CHAIN":
        input_data = obs.get("input")
        if input_data:
            lines.append(f"{prefix}    Input: {truncate_text(input_data, 200)}")

    return lines


def build_tree(observations: list[dict]) -> dict:
    """Build a tree from flat observations using parentObservationId."""
    # Create a map of id -> observation
    obs_map = {obs["id"]: {**obs, "children": []} for obs in observations}

    # Build tree structure
    roots = []
    for obs in observations:
        obs_id = obs["id"]
        parent_id = obs.get("parentObservationId")

        if parent_id is None or parent_id not in obs_map:
            roots.append(obs_map[obs_id])
        else:
            obs_map[parent_id]["children"].append(obs_map[obs_id])

    return {"roots": roots, "map": obs_map}


def print_tree(obs: dict, indent: int = 0, output: list[str] = None):
    """Recursively print the tree."""
    if output is None:
        output = []

    prefix = "  " * indent
    typ = obs.get("type", "UNKNOWN")
    name = obs.get("name", "unnamed")
    obs_id = obs.get("id", "unknown")
    latency = obs.get("latency", 0)

    # Tree-style line with summary
    summary = get_observation_summary(obs)
    output.append(f"{prefix}├─ {summary}")

    # Add children
    children = obs.get("children", [])
    if children:
        for child in children:
            print_tree(child, indent + 1, output)

    return output


def format_trace_for_llm(trace: dict) -> str:
    """Format a complete trace for LLM consumption."""

    lines = []
    lines.append("═" * 70)
    lines.append(f"  LANGFUSE TRACE: {trace.get('name', 'unnamed')} ({trace.get('id', 'unknown')})")
    lines.append("═" * 70)

    # Trace metadata
    metadata = trace.get("metadata", {})
    if metadata:
        lines.append("\n📋 METADATA:")
        for key, value in metadata.items():
            if key not in ["resourceAttributes", "scope", "usageDetails"]:
                lines.append(f"  {key}: {value}")

    observations = trace.get("observations", [])

    # Stats
    total_tokens = sum(o.get("totalTokens", 0) for o in observations if o.get("type") == "GENERATION")
    total_cost = sum(o.get("calculatedTotalCost", 0) for o in observations if o.get("type") == "GENERATION")
    total_latency = sum(o.get("latency", 0) for o in observations)

    gen_count = sum(1 for o in observations if o.get("type") == "GENERATION")
    tool_count = sum(1 for o in observations if o.get("type") == "TOOL")
    chain_count = sum(1 for o in observations if o.get("type") == "CHAIN")

    lines.append("\n📊 STATISTICS:")
    lines.append(f"  Total observations: {len(observations)}")
    lines.append(f"  Generations (LLM calls): {gen_count}")
    lines.append(f"  Tool calls: {tool_count}")
    lines.append(f"  Chain steps: {chain_count}")
    lines.append(f"  Total tokens: {total_tokens:,}")
    lines.append(f"  Total cost: ${total_cost:.4f}")
    lines.append(f"  Total latency: {format_duration(total_latency)}")

    # Build tree
    tree = build_tree(observations)

    lines.append("\n🌳 EXECUTION TREE:")
    for root in tree["roots"]:
        tree_output = print_tree(root, 0, [])
        lines.extend(tree_output)

    # Detailed observations (chronological)
    lines.append("\n\n📝 DETAILED OBSERVATIONS (chronological):")
    lines.append("─" * 70)

    # Sort by start time
    sorted_obs = sorted(observations, key=lambda o: o.get("startTime", ""))

    for i, obs in enumerate(sorted_obs, 1):
        detail_lines = format_observation_detail(obs, indent=0)
        lines.append(f"\n[{i}]")
        lines.extend(detail_lines)

    # Error summary
    errors = [o for o in observations if o.get("level") == "ERROR"]
    if errors:
        lines.append("\n\n🚨 ERRORS:")
        for err in errors:
            lines.append(f"  [{err.get('type')}] {err.get('name')}")
            msg = err.get("statusMessage", "Unknown error")
            lines.append(f"    {msg}")

    lines.append("\n" + "═" * 70)

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: parse_trace.py <trace.json> [output.md]")
        sys.exit(1)

    trace_file = Path(sys.argv[1])
    if not trace_file.exists():
        print(f"Error: {trace_file} not found")
        sys.exit(1)

    with open(trace_file) as f:
        trace = json.load(f)

    formatted = format_trace_for_llm(trace)

    if len(sys.argv) >= 3:
        output_file = Path(sys.argv[2])
        output_file.write_text(formatted)
        print(f"Formatted trace written to {output_file}")
    else:
        print(formatted)


if __name__ == "__main__":
    main()
