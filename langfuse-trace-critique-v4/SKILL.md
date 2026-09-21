---
name: langfuse-trace-critique-v4
description: A structured methodology for analyzing Langfuse v4 traces (Observations API v2) to critique agent execution flows, identify failures, and suggest concrete improvements
---

# Langfuse Trace Critique (v4)

A structured methodology for analyzing Langfuse v4 traces to critique agent execution flows, identify failures, and suggest concrete improvements.

Works with Langfuse v4's observations-first data model. On v4 deployments running
`events_only` write mode (the default), the v3 endpoints (`GET /api/public/traces/:id`,
`GET /api/public/observations`) return `404` — all reads go through
`GET /api/public/v2/observations`. The parser script also still accepts v3 trace JSON
for pre-upgrade exports.

## 1. Fetch Trace

Retrieve all observations of a trace from Langfuse v4 by trace ID (basic auth:
`public_key` as username, `secret_key` as password — unchanged from v3).

```bash
# Set your Langfuse credentials in your environment, or copy .env.example → .env and `source .env`
#   export LANGFUSE_SECRET_KEY=...
#   export LANGFUSE_PUBLIC_KEY=...
#   export LANGFUSE_HOST="https://cloud.langfuse.com"   # or your self-hosted URL
TRACE_ID="<paste-your-trace-id>"

# Fetch all observations of the trace (v4 Observations API v2)
curl -sS -u "${LANGFUSE_PUBLIC_KEY:?required}:${LANGFUSE_SECRET_KEY:?required}" \
  "${LANGFUSE_HOST:?required}/api/public/v2/observations?traceId=${TRACE_ID}&limit=1000&fields=core,basic,time,io,model,usage,prompt,metrics,trace_context" \
  -o "trace_${TRACE_ID}.json"

# Check for more pages (cursor pagination) and pretty-print
jq '.meta' "trace_${TRACE_ID}.json"
jq '.data | length' "trace_${TRACE_ID}.json"
```

**Key details:**

- **`fields` is required for a useful fetch** — without it you only get `core,basic`
  (no input/output, tokens, cost, model, or latency). Use the full list above.
- **`limit` max is 1000** (default 50). If `.meta.cursor` is non-null, fetch the next
  page with `&cursor=<cursor>` and merge:
  ```bash
  jq -s '{data: (map(.data) | add)}' trace_${TRACE_ID}_p1.json trace_${TRACE_ID}_p2.json > trace_${TRACE_ID}.json
  ```
  (The parser also accepts multiple page files as separate arguments and merges them.)
- Traces with large `io` payloads can be tens of MB — use a generous curl timeout
  (`-m 300`) and write to disk, don't pipe.

### Finding the Trace ID

- **From Langfuse UI**: Open the trace in the tracing view and copy the ID from the URL or trace details.
- **From API**: v4 has no trace-list endpoint in `events_only` mode. Discover recent
  trace IDs by listing recent observations and reading their `traceId`:
  ```bash
  curl -sS -u "${LANGFUSE_PUBLIC_KEY:?}:${LANGFUSE_SECRET_KEY:?}" \
    "${LANGFUSE_HOST:?}/api/public/v2/observations?fromStartTime=$(date -u -v-7d +%Y-%m-%dT%H:%M:%SZ)&limit=20&fields=core,basic,trace_context" \
    | jq '.data[] | {traceId, traceName, type, name, startTime}'
  ```

## 2. Parse Trace for LLM Consumption

Convert the raw observation JSON into a structured, readable format suitable for LLM
analysis.

### Using the Parser Script

The script lives at `scripts/parse_trace.py` inside this skill directory.

```bash
# Parse a trace into markdown format
python3 scripts/parse_trace.py trace_<id>.json -o trace_<id>.md

# Or print to stdout; multiple pages are merged automatically
python3 scripts/parse_trace.py trace_<id>_p1.json trace_<id>_p2.json
```

### What the Parser Outputs

The parser generates a structured markdown document with:

1. **Header** — Trace ID, name, and trace context (tags, session, user)
2. **Statistics** — Observation counts, token usage (incl. cached-input tokens),
   cost, latency, and generation input-token growth (first → last)
3. **Execution Tree** — Hierarchical view of the observation tree with parent-child relationships
4. **Detailed Observations** — Chronological list with key details:
   - GENERATION: Model, tokens (`input + output = total`, plus cache/reasoning usage), cost, latency, TTFT, input/output snippets
   - TOOL: Tool name, latency, input/output
   - CHAIN/AGENT/SPAN/EVENT: Names and timing
5. **Error Summary** — Any observations with `level: ERROR`

### Trace Structure Reference

Langfuse v4 is observations-first: there is no separate trace object to fetch —
trace context (`traceName`, `tags`, `release`) is denormalized onto each observation.
Observation `type` is one of the v4 core types (`SPAN`, `GENERATION`, `EVENT`), but
data ingested via OpenTelemetry/legacy SDKs still carries `CHAIN`, `TOOL`, and
`AGENT` — handle all of them.

| Type | Origin | Description | Key Fields |
|------|--------|-------------|------------|
| **SPAN** | core | Root/container timing | `name`, `startTime`, `endTime`, `latency` |
| **GENERATION** | core | LLM API call | `model`, `usageDetails`, `costDetails`, `totalCost`, `latency`, `timeToFirstToken` |
| **EVENT** | core | Point-in-time event | `name`, `startTime` (no endTime) |
| **CHAIN** | legacy/OTEL | Execution step (middleware, etc.) | `name`, `input`, `latency` |
| **TOOL** | legacy/OTEL | Tool/function call | `name`, `input`, `output`, `latency` |
| **AGENT** | legacy/OTEL | Agent lifecycle event | `name` |

**v4 field reference:**

| Field | Notes |
|-------|-------|
| `usageDetails` | Token dict: `{"input": N, "output": N, "total": N}` plus optional `input_cache_read`, `output_reasoning`, … |
| `costDetails` / `totalCost` | Cost dict / flat total in USD |
| `latency` | Seconds (may be `null`; compute from `startTime`/`endTime`) |
| `parentObservationId` | Physical parent; `isRootObservation` marks logical roots |
| `level` / `statusMessage` | `DEBUG`/`DEFAULT`/`WARNING`/`ERROR` + error text |
| `input` / `output` | Always raw strings (typically JSON-serialized) |

**v3 → v4 migration cheat-sheet** (if you're reading older material):

| v3 | v4 |
|----|----|
| `GET /api/public/traces/{id}` | `GET /api/public/v2/observations?traceId={id}` |
| `promptTokens` | `usageDetails.input` |
| `completionTokens` | `usageDetails.output` |
| `totalTokens` | `usageDetails.total` |
| `calculatedTotalCost` | `totalCost` |
| trace `name`/`tags` | denormalized `traceName`/`tags` on observations |

Parent-child relationships are still via `parentObservationId` — the parser
reconstructs the tree for you.

## 3. Critique Methodology

Analyze the parsed trace against these criteria. Look for patterns, not just isolated issues.

### 3.1 Broken Steps (🔴)

Hard failures that prevented task completion or caused crashes.

**What to look for:**
- Observations with `level: ERROR` or a `statusMessage`
- Tool calls that returned error status
- Missing outputs where expected
- Incomplete execution trees (truncated flows)
- Failed generations (API errors, rate limits)

**Common patterns:**
| Pattern | Example |
|---------|---------|
| Tool timeout | `glob timed out after 20.0s` |
| Command failure | `grep: No such file or directory` |
| API error | `Rate limit exceeded`, `429` in statusMessage |
| File conflict | `File already exists` |
| Validation failure | `Required field missing` |

**How to report:**
```
🔴 [TOOL] grep (ID: a199af402824b89d)
   Failed after 281m 47s with: "Failed to execute command"
   → Fix: Add path validation to reject searches on '/' root filesystem.
```

### 3.2 Inefficient Steps (🟡)

Steps that consumed disproportionate time/tokens/cost without adding value.

**What to look for:**
- Single observations dominating total latency (>50% from one operation)
- Generation input tokens growing across the trace (context bloat) — watch the
  "Generation input tokens (first → last)" stat and `input_cache_read` in
  `usageDetails`: a large and growing cache-read means the same context is being
  re-sent every turn
- Repeated identical operations (loops without convergence)
- Tool calls returning empty/irrelevant results
- Excessive middleware/CHAIN overhead per turn

**Common patterns:**
| Pattern | Threshold | Example |
|---------|----------|---------|
| Catastrophic timeout | >60s on single tool | `grep on /: 281 minutes` |
| Context explosion | >50k tokens/generation or 5× growth | Gen 1: 10k in → gen 20: 80k in; `input_cache_read: 35169` |
| Retry loops | >3 identical calls | `search_files` called 7x with same args |
| Empty searches | Tool returns no results | `grep pattern: found 0 matches` |
| Middleware overhead | CHAIN ≫ GENERATION time | 300 CHAINs wrapping 50 GENERATIONs |

**How to report:**
```
🟡 [GENERATION] ChatGoogleGenerativeAI (ID: a993f2c1)
   Input grew 3.2k → 51k tokens over 50 turns; 35k input_cache_read per call
   → Fix: Trim/summarize conversation history; scope tool results before re-sending.
```

### 3.3 Warnings (🟠)

Not failures, but indicate fragile or poorly-designed behavior.

**What to look for:**
- Hardcoded paths, values, or assumptions
- Missing error handling on risky operations
- Race conditions or timing dependencies
- Overly broad search patterns
- Missing validation on user inputs

**Common patterns:**
| Pattern | Risk | Example |
|---------|------|---------|
| Root filesystem search | Environment-specific | `path: "/"` in glob/grep |
| Hardcoded paths | Breaks on deployment | `/tmp/jwt_token` assumes Linux |
| No retry logic | Transient failures | Network calls without backoff |
| Broad patterns | Performance cliff | `**/*.env` on entire filesystem |
| Missing checks | Silent failures | No validation before tool use |

**How to report:**
```
🟠 [TOOL] glob (ID: 901455564b981153)
   Pattern '**/*.env' on '/' is too broad — timed out at 20s
   → Fix: Restrict searches to project root or known config directories.
```

### 3.4 Suggestions (💡)

General improvements not tied to specific failures.

**What to look for:**
- Architectural improvements (better tools, different approach)
- Missing telemetry or observability
- Opportunities for caching or optimization
- Better prompts or system messages
- Workflow simplification

**Common patterns:**
| Category | Examples |
|----------|----------|
| Prompt engineering | Add examples, clarify instructions |
| Tool design | Combine related tools, add validation |
| Caching | Cache expensive lookups |
| Observability | Add tracing, metrics, logging |
| Architecture | Use vector search instead of linear scan |

**How to report:**
```
💡 Add project-scoped search tool
   Current grep/glob tools search entire filesystem. Create `search_project` tool
   scoped to repo root with built-in safeties.
```

### 4. Output Format

Present the critique in this exact structure.

═══════════════════════════════════════════════════════════════════════
  TRACE CRITIQUE: {trace_name} ({trace_id})
  Duration: {total_duration} | Observations: {count} | Tokens: {total_tokens}
═══════════════════════════════════════════════════════════════════════

EXECUTION TREE:
{reconstructed_tree}

───────────────────────────────────────────────────────────────────────
  CRITIQUE
───────────────────────────────────────────────────────────────────────

🔴 BROKEN STEPS ({count}):
  1. {finding}
     → Fix: {action}

🟡 INEFFICIENT STEPS ({count}):
  1. {finding}
     → Fix: {action}

🟠 WARNINGS ({count}):
  1. {finding}
     → Fix: {action}

💡 SUGGESTIONS ({count}):
  1. {finding}
     → Fix: {action}

───────────────────────────────────────────────────────────────────────
  SUMMARY
───────────────────────────────────────────────────────────────────────
Severity: {CRITICAL | HIGH | MEDIUM | LOW}
Top Issue: {most_important_fix}
Estimated Impact: {time/token/cost savings if fixed}


## 5. Complete Workflow Example

```bash
# 1. Fetch the trace (set LANGFUSE_* and TRACE_ID in your environment first;
#    large io payloads need a generous timeout)
TRACE_ID="${TRACE_ID:?set TRACE_ID to the trace you want to analyze}"
curl -sS -m 300 -u "${LANGFUSE_PUBLIC_KEY:?required}:${LANGFUSE_SECRET_KEY:?required}" \
  "${LANGFUSE_HOST:?required}/api/public/v2/observations?traceId=${TRACE_ID}&limit=1000&fields=core,basic,time,io,model,usage,prompt,metrics,trace_context" \
  -o "trace_${TRACE_ID}.json"

# 2. Parse into readable format
python3 scripts/parse_trace.py "trace_${TRACE_ID}.json" -o "trace_${TRACE_ID}.md"

# 3. Feed the parsed trace to an LLM for analysis
# (e.g., Claude, GPT-4, etc. with the critique methodology)
```

### LLM Prompt Template

When feeding a parsed trace to an LLM for critique, use this prompt:

```
You are an expert agent debugger. Analyze the following Langfuse trace execution
and critique it using this framework:

1. BROKEN STEPS — Hard failures (errors, missing outputs, incorrect results)
2. INEFFICIENT STEPS — Wasted tokens/time (redundant calls, large context, slow operations)
3. WARNINGS — Fragile patterns (missing error handling, hardcoded values, etc.)
4. SUGGESTIONS — General improvements

For each finding, provide:
- The observation ID/name
- Why it's a problem
- How to fix it (concrete action)

[Insert parsed trace here]

Present your critique in the exact format specified in section 4 of this skill.
```
