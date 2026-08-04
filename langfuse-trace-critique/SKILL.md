---
name: langfuse-trace-critique
description: A structured methodology for analyzing Langfuse traces to critique agent execution flows, identify failures, and suggest concrete improvements
---

# Langfuse Trace Critique

A structured methodology for analyzing Langfuse traces to critique agent execution flows, identify failures, and suggest concrete improvements

## 1. Fetch Trace

Retrieve a specific trace from Langfuse by trace ID.

```bash
# Set your Langfuse credentials in your environment, or copy .env.example → .env and `source .env`
#   export LANGFUSE_SECRET_KEY=...
#   export LANGFUSE_PUBLIC_KEY=...
#   export LANGFUSE_HOST="https://cloud.langfuse.com"   # or your self-hosted URL
TRACE_ID="<paste-your-trace-id>"

# Fetch the trace (basic auth: public_key as username, secret_key as password)
curl -u "${LANGFUSE_PUBLIC_KEY:?required}:${LANGFUSE_SECRET_KEY:?required}" \
  "${LANGFUSE_HOST:?required}/api/public/traces/${TRACE_ID}" \
  -o "trace_${TRACE_ID}.json"

# Pretty print the trace
cat "trace_${TRACE_ID}.json" | jq '.'
```

### Finding the Trace ID

- **From Langfuse UI**: Open a trace and copy the ID from the URL or trace details
- **From API**: List traces to find the ID:
  ```bash
  curl -u "${LANGFUSE_PUBLIC_KEY:?required}:${LANGFUSE_SECRET_KEY:?required}" \
    "${LANGFUSE_HOST:?required}/api/public/traces?limit=10" \
    | jq '.data[] | {id: .id, url: .url, metadata: .metadata}'
  ```

## 2. Parse Trace for LLM Consumption

Convert the raw JSON trace into a structured, readable format suitable for LLM analysis.

### Using the Parser Script

```bash
# Parse a trace into markdown format
python3 .claude/skills/langfuse-trace-critique/parse_trace.py \
  trace_<id>.json \
  trace_<id>.md

# Or print to stdout
python3 .claude/skills/langfuse-trace-critique/parse_trace.py trace_<id>.json
```

### What the Parser Outputs

The parser generates a structured markdown document with:

1. **Header** — Trace ID, name, and basic metadata
2. **Statistics** — Observation counts, token usage, cost, latency
3. **Execution Tree** — Hierarchical view of the observation tree with parent-child relationships
4. **Detailed Observations** — Chronological list with key details:
   - GENERATION: Model, tokens, cost, input/output snippets
   - TOOL: Tool name, latency, input/output
   - CHAIN/AGENT/SPAN: Names and timing
5. **Error Summary** — Any failed observations

### Trace Structure Reference

Langfuse traces contain these observation types:

| Type | Description | Key Fields |
|------|-------------|------------|
| **SPAN** | Root timing container | `name`, `startTime`, `endTime`, `latency` |
| **CHAIN** | Execution step (middleware, etc.) | `name`, `input`, `latency` |
| **GENERATION** | LLM API call | `model`, `promptTokens`, `completionTokens`, `totalTokens`, `cost` |
| **TOOL** | Tool/function call | `name`, `input`, `output`, `latency` |
| **AGENT** | Agent lifecycle event | `name` |

Parent-child relationships are via `parentObservationId` — the parser reconstructs the tree for you.

## 3. Critique Methodology

Analyze the parsed trace against these criteria. Look for patterns, not just isolated issues.

### 3.1 Broken Steps (🔴)

Hard failures that prevented task completion or caused crashes.

**What to look for:**
- Observations with `level: ERROR` or explicit error messages
- Tool calls that returned error status
- Missing outputs where expected
- Incomplete execution trees (truncated flows)
- Failed generations (API errors, rate limits)

**Common patterns:**
| Pattern | Example |
|---------|---------|
| Tool timeout | `glob timed out after 20.0s` |
| Command failure | `grep: No such file or directory` |
| API error | `openai.error.APIError: Rate limit exceeded` |
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
- Token counts growing exponentially across generations (context bloat)
- Repeated identical operations (loops without convergence)
- Tool calls returning empty/irrelevant results
- Excessive middleware overhead

**Common patterns:**
| Pattern | Threshold | Example |
|---------|----------|---------|
| Catastrophic timeout | >60s on single tool | `grep on /: 281 minutes` |
| Context explosion | >50k tokens/generation | Generation 1: 10k → 10: 80k tokens |
| Retry loops | >3 identical calls | `search_files` called 7x with same args |
| Empty searches | Tool returns no results | `grep pattern: found 0 matches` |

**How to report:**
```
🟡 [TOOL] grep (ID: a199af402824b89d)
   Ran for 281m 47s searching '/' for 'API_BASE_URL' — 94% of total trace time
   → Fix: Search project directory only, add timeout of 30s for filesystem operations.
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
# 1. Fetch the trace (set LANGFUSE_* and TRACE_ID in your environment first)
TRACE_ID="${TRACE_ID:?set TRACE_ID to the trace you want to analyze}"
curl -u "${LANGFUSE_PUBLIC_KEY:?required}:${LANGFUSE_SECRET_KEY:?required}" \
  "${LANGFUSE_HOST:?required}/api/public/traces/${TRACE_ID}" \
  -o "trace_${TRACE_ID}.json"

# 2. Parse into readable format
python3 .claude/skills/langfuse-trace-critique/parse_trace.py \
  "trace_${TRACE_ID}.json" \
  "trace_${TRACE_ID}.md"

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

