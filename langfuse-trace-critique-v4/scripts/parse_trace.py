#!/usr/bin/env python3
"""
Parse Langfuse trace/observation JSON into a consumable format for LLM agents.
Flattens the observation tree into a structured, readable format.

Accepts any of:
- Langfuse v4 Observations API responses: {"data": [...], "meta": {...}}
  from GET /api/public/v2/observations?traceId=...
- Langfuse v3 trace objects: {"id": ..., "observations": [...]}
- A plain JSON array of observations

Multiple input files are merged and deduplicated by observation id, so
paginated v4 responses (meta.cursor) can be parsed together.

Usage:
  parse_trace.py <trace_or_page.json> [more.json ...] [-o output.md]
"""

import argparse
import json
import sys
from datetime import datetime


def format_duration(seconds: float) -> str:
    """Format duration in human-readable format."""
    if seconds is None:
        seconds = 0
    if seconds < 1:
        return f"{seconds*1000:.1f}ms"
    elif seconds < 60:
        return f"{seconds:.2f}s"
    else:
        mins = int(seconds // 60)
        secs = seconds % 60
        return f"{mins}m {secs:.1f}s"


def truncate_text(text, max_length: int = 500) -> str:
    """Truncate text with ellipsis if too long."""
    if not text:
        return ""
    text_str = str(text)
    if len(text_str) <= max_length:
        return text_str.replace("\n", " ")
    return text_str[:max_length].replace("\n", " ") + "..."


def parse_time(ts):
    """Parse an ISO timestamp, or return None."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def get_latency(obs: dict) -> float:
    """Latency in seconds: v4 flat field, v3 flat field, or computed from times."""
    lat = obs.get("latency")
    if lat is not None:
        return float(lat)
    start = parse_time(obs.get("startTime"))
    end = parse_time(obs.get("endTime"))
    if start and end:
        return (end - start).total_seconds()
    return 0.0


def get_tokens(obs: dict) -> dict:
    """
    Token usage: v4 usageDetails dict ({input, output, total, input_cache_read,
    output_reasoning, ...}) with fallback to v3 flat fields (promptTokens,
    completionTokens, totalTokens). Returns keys: input, output, total, plus
    any extra usage metrics with nonzero values.
    """
    ud = obs.get("usageDetails") or {}
    tokens = {
        "input": ud.get("input", obs.get("inputUsage") or obs.get("promptTokens") or 0),
        "output": ud.get("output", obs.get("outputUsage") or obs.get("completionTokens") or 0),
    }
    total = ud.get("total", obs.get("totalUsage") or obs.get("totalTokens") or 0)
    if not total:
        total = tokens["input"] + tokens["output"]
    tokens["total"] = total
    for key, value in ud.items():
        if key not in ("input", "output", "total") and value:
            tokens[key] = value
    return tokens


def get_cost(obs: dict) -> float:
    """Total cost in USD: v4 totalCost with v3 calculatedTotalCost fallback."""
    return obs.get("totalCost") or obs.get("calculatedTotalCost") or 0


def format_tokens(tokens: dict) -> str:
    """One-line token summary, surfacing cache/reasoning usage when present."""
    line = f"{tokens['input']:,} in + {tokens['output']:,} out = {tokens['total']:,} total"
    extras = [f"{k}: {v:,}" for k, v in tokens.items()
              if k not in ("input", "output", "total") and v]
    if extras:
        line += f" ({', '.join(extras)})"
    return line


def get_observation_summary(obs: dict) -> str:
    """Get a one-line summary of an observation."""
    typ = obs.get("type", "UNKNOWN")
    name = obs.get("name", "unnamed")

    if typ == "GENERATION":
        model = obs.get("model", "unknown")
        tokens = get_tokens(obs)
        latency = get_latency(obs)
        return f"[{typ}] {name} ({model}, {tokens['total']:,} tokens, {format_duration(latency)})"

    if typ in ("TOOL", "CHAIN"):
        latency = get_latency(obs)
        return f"[{typ}] {name}" + (f" ({format_duration(latency)})" if latency > 0 else "")

    return f"[{typ}] {name}"


def format_observation_detail(obs: dict, indent: int = 0) -> list[str]:
    """Format detailed information about an observation."""
    lines = []
    prefix = "  " * indent

    typ = obs.get("type", "UNKNOWN")
    name = obs.get("name", "unnamed")
    obs_id = obs.get("id", "unknown")
    latency = get_latency(obs)

    # Header line
    status = "✗" if obs.get("level") == "ERROR" else "✓"
    lines.append(f"{prefix}{status} [{typ}] {name}")
    lines.append(f"{prefix}    ID: {obs_id}")

    # Timing
    dt_start = parse_time(obs.get("startTime"))
    dt_end = parse_time(obs.get("endTime"))
    if dt_start and dt_end:
        lines.append(f"{prefix}    Time: {dt_start.strftime('%H:%M:%S')} → {dt_end.strftime('%H:%M:%S')} ({format_duration(latency)})")
    else:
        lines.append(f"{prefix}    Duration: {format_duration(latency)}")

    # Type-specific details
    if typ == "GENERATION":
        model = obs.get("model", "unknown")
        tokens = get_tokens(obs)
        cost = get_cost(obs)
        ttft = obs.get("timeToFirstToken")

        lines.append(f"{prefix}    Model: {model}")
        lines.append(f"{prefix}    Tokens: {format_tokens(tokens)}")
        if ttft is not None:
            lines.append(f"{prefix}    Time to first token: {format_duration(ttft)}")
        if cost > 0:
            lines.append(f"{prefix}    Cost: ${cost:.6f}")

    if typ in ("GENERATION", "TOOL", "CHAIN"):
        input_data = obs.get("input")
        if input_data:
            lines.append(f"{prefix}    Input: {truncate_text(input_data, 300)}")

        output_data = obs.get("output")
        if output_data:
            lines.append(f"{prefix}    Output: {truncate_text(output_data, 300)}")

    metadata = obs.get("metadata")
    if metadata:
        lines.append(f"{prefix}    Metadata: {truncate_text(metadata, 200)}")

    if obs.get("level") == "ERROR":
        status_msg = obs.get("statusMessage", "Unknown error")
        lines.append(f"{prefix}    ERROR: {truncate_text(status_msg, 300)}")

    return lines


def build_tree(observations: list[dict]) -> dict:
    """Build a tree from flat observations using parentObservationId."""
    obs_map = {obs["id"]: {**obs, "children": []} for obs in observations}

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
    summary = get_observation_summary(obs)
    output.append(f"{prefix}├─ {summary}")

    for child in obs.get("children", []):
        print_tree(child, indent + 1, output)

    return output


def collect_observations(inputs: list) -> tuple[list[dict], dict]:
    """
    Extract and merge observations from all parsed inputs (v4 pages, v3 traces,
    or bare lists). Returns (observations deduplicated by id, trace-level info).
    """
    by_id: dict[str, dict] = {}
    trace_info: dict = {}

    for obj in inputs:
        if isinstance(obj, list):
            observations = obj
        elif isinstance(obj, dict) and isinstance(obj.get("data"), list):
            observations = obj["data"]  # v4 Observations API response
        elif isinstance(obj, dict) and isinstance(obj.get("observations"), list):
            observations = obj["observations"]  # v3 trace object
            for key in ("id", "name", "metadata", "tags", "sessionId", "userId", "release"):
                if obj.get(key) is not None and trace_info.get(key) is None:
                    trace_info[key] = obj[key]
        else:
            continue

        for obs in observations:
            if isinstance(obs, dict) and obs.get("id") and obs["id"] not in by_id:
                by_id[obs["id"]] = obs

    # v4 denormalizes trace context onto each observation
    for obs in by_id.values():
        for key in ("traceId", "traceName", "tags", "sessionId", "userId", "release"):
            if obs.get(key) is not None and trace_info.get(key) is None:
                trace_info[key] = obs[key]

    if "id" not in trace_info and "traceId" in trace_info:
        trace_info["id"] = trace_info["traceId"]
    if "name" not in trace_info and "traceName" in trace_info:
        trace_info["name"] = trace_info["traceName"]

    return list(by_id.values()), trace_info


def format_trace_for_llm(observations: list[dict], trace_info: dict) -> str:
    """Format a complete trace for LLM consumption."""

    lines = []
    lines.append("═" * 70)
    lines.append(f"  LANGFUSE TRACE: {trace_info.get('name', 'unnamed')} ({trace_info.get('id', 'unknown')})")
    lines.append("═" * 70)

    # Trace metadata
    context = {k: v for k, v in trace_info.items()
               if k in ("tags", "release", "sessionId", "userId") and v}
    if context:
        lines.append("\n📋 TRACE CONTEXT:")
        for key, value in context.items():
            lines.append(f"  {key}: {value}")
    metadata = trace_info.get("metadata")
    if metadata:
        lines.append("\n📋 METADATA:")
        if isinstance(metadata, dict):
            for key, value in metadata.items():
                if key not in ("resourceAttributes", "scope", "usageDetails"):
                    lines.append(f"  {key}: {value}")

    # Stats
    gen_obs = [o for o in observations if o.get("type") == "GENERATION"]
    tool_count = sum(1 for o in observations if o.get("type") == "TOOL")
    chain_count = sum(1 for o in observations if o.get("type") == "CHAIN")

    total_tokens = sum(get_tokens(o)["total"] for o in gen_obs)
    total_cache = sum(get_tokens(o).get("input_cache_read", 0) for o in gen_obs)
    total_cost = sum(get_cost(o) for o in gen_obs)
    total_latency = sum(get_latency(o) for o in observations)

    lines.append("\n📊 STATISTICS:")
    lines.append(f"  Total observations: {len(observations)}")
    lines.append(f"  Generations (LLM calls): {len(gen_obs)}")
    lines.append(f"  Tool calls: {tool_count}")
    lines.append(f"  Chain steps: {chain_count}")
    lines.append(f"  Total tokens: {total_tokens:,}")
    if total_cache:
        lines.append(f"  Cached input tokens: {total_cache:,} (context re-read — watch for growth)")
    lines.append(f"  Total cost: ${total_cost:.4f}")
    lines.append(f"  Total latency (sum of observations): {format_duration(total_latency)}")

    # Token growth across generations (context bloat signal)
    if len(gen_obs) >= 2:
        sorted_gens = sorted(gen_obs, key=lambda o: o.get("startTime") or "")
        first, last = get_tokens(sorted_gens[0]), get_tokens(sorted_gens[-1])
        lines.append(f"  Generation input tokens (first → last): {first['input']:,} → {last['input']:,}")

    # Build tree
    tree = build_tree(observations)

    lines.append("\n🌳 EXECUTION TREE:")
    for root in tree["roots"]:
        lines.extend(print_tree(root, 0, []))

    # Detailed observations (chronological)
    lines.append("\n\n📝 DETAILED OBSERVATIONS (chronological):")
    lines.append("─" * 70)

    sorted_obs = sorted(observations, key=lambda o: o.get("startTime") or "")

    for i, obs in enumerate(sorted_obs, 1):
        lines.append(f"\n[{i}]")
        lines.extend(format_observation_detail(obs, indent=0))

    # Error summary
    errors = [o for o in observations if o.get("level") == "ERROR"]
    if errors:
        lines.append("\n\n🚨 ERRORS:")
        for err in errors:
            lines.append(f"  [{err.get('type')}] {err.get('name')}")
            msg = err.get("statusMessage", "Unknown error")
            lines.append(f"    {truncate_text(msg, 300)}")

    lines.append("\n" + "═" * 70)

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Parse Langfuse trace JSON (v4 Observations API pages, v3 traces, "
                    "or bare observation lists) into an LLM-consumable report.")
    parser.add_argument("inputs", nargs="+",
                        help="trace/page JSON file(s); multiple files are merged")
    parser.add_argument("-o", "--output", help="write the report here instead of stdout")
    args = parser.parse_args()

    parsed = []
    for path in args.inputs:
        try:
            with open(path) as f:
                parsed.append(json.load(f))
        except (OSError, json.JSONDecodeError) as e:
            print(f"Error reading {path}: {e}", file=sys.stderr)
            sys.exit(1)

    observations, trace_info = collect_observations(parsed)
    if not observations:
        print('Error: no observations found in input '
              '(expected a v4 {"data": [...]} page, a v3 trace object, or a JSON array)',
              file=sys.stderr)
        sys.exit(1)

    formatted = format_trace_for_llm(observations, trace_info)

    if args.output:
        with open(args.output, "w") as f:
            f.write(formatted)
        print(f"Formatted trace written to {args.output}")
    else:
        print(formatted)


if __name__ == "__main__":
    main()
