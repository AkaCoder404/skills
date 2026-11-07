---
name: glab-issue
description: Create, label, and update GitLab issues via glab — right template per issue type, correct label taxonomy, verified facts. Use when filing an issue, choosing labels (bug/enhancement/tech-debt/deps/infra, agent-pipeline labels, priority labels), updating issue labels, or asking what format an issue should follow.
---

# GitLab Issue Creation (glab)

File issues that survive review: verified facts, the right template, correct labels.

## Pre-flight (before writing a word)

1. **Verify every claim against the code.** Cite `file:line`. Prefer counts (`grep -c`) over impressions ("all", "many").
2. **Never truncate evidence output.** No `head` on greps used for claims — truncated output produces wrong conclusions (a triplicated helper read as singular; an existing label read as absent). Grep narrower instead of truncating.
3. **When unsure a label exists**, run `glab label list` and read the whole table. Treat that output as the source of truth for your project's taxonomy; the labels below are the reference set this skill assumes.

## Labels

Exactly **one type label** per issue. Priority and state labels ride on top; they never change the template.

| Group | Labels | Rules |
|---|---|---|
| Type (pick one) | `bug`, `enhancement`, `tech-debt`, `deps`, `infra` | `enhancement` = user/caller-**observable** change. `tech-debt` = internal quality, **no** behavior change. Never both on one issue. |
| Agent pipeline | `agent`, `agent-running`, `agent-blocked`, `agent-done` | State labels for agent automation that picks up and works tickets. `agent` **arms the pipeline — apply only when the user explicitly opts in.** The other three are pipeline-owned; never apply them by hand. |
| Human state | `pending`, `started`, `Work in process`, `internel review`, `Done` | `internel review` is [sic] — the typo is in the label; type it exactly. |

Future axes (P0/P1 urgency, etc.) add labels, not templates — see the mapping below.

## Commands

```bash
# Create (quoted heredoc keeps markdown backticks intact)
cat > /tmp/issue.md <<'EOF'
...description...
EOF
glab issue create --title "Title" --description "$(cat /tmp/issue.md)" --label tech-debt

# Labels: --label ADDS, --unlabel REMOVES. There is no replace.
glab issue update 24 --unlabel enhancement

# Verify after every mutation
glab issue view 24 | grep -i labels
```

The project resolves from the git remote — run from the repo root, or pass `-R <group/project>` explicitly.

## Template ↔ label mapping

Templates key to narrative shape; labels key to filtering. **New labels edit this table only; a new template is born only for a genuinely new shape** (e.g. incident/postmortem) — never as a side effect of adding a label.

| Template | Maps from labels | Distinctive sections |
|---|---|---|
| bug | `bug` (+ future P0/P1) | Regression test; optional `Impact:` for production events |
| change | `enhancement`, future `feature`/`docs` | Need → Proposed behavior |
| chore | `deps`, `infra` | Verification **+ Rollback** (mandatory) |
| debt | `tech-debt` | Verified facts (citations/counts); Out of scope + sequencing |

## Templates

### debt — `tech-debt`

```markdown
## Problem
What is duplicated or misplaced, with `file:line` citations.

## Verified facts
Counts and commits that prove the claim (`grep -c` numbers, day-one fixes, prior art).

## Proposed change
The move/merge/rename. State when copies are already identical — a move, not a redesign.

## Out of scope
Adjacent-but-separate changes, each with its reason; sequencing notes relative to other issues.

## Acceptance
- [ ] Objective criteria (e.g. generated output byte-identical, regression tests referenced by commit)
- [ ] Suite green
```

### bug — `bug`

```markdown
## Symptom
What breaks, for whom, since when. Repro steps or request/response.

## Impact
Blast radius, frequency, exposure if known. *(Include for production events — this is where P0/P1 labels land.)*

## Root cause
`file:line` and the introducing commit, if known.

## Fix

## Regression test
Test name/file that fails before the fix and passes after.

## Acceptance
- [ ] Regression test added and green
- [ ] Suite green
```

### change — `enhancement` (future `feature`/`docs`)

```markdown
## Need
Who needs what, and why now.

## Proposed behavior
The observable behavior after the change — this is what makes it an enhancement.

## Out of scope

## Acceptance
- [ ] ...
```

### chore — `deps` / `infra`

```markdown
## Motivation
CVE/EOL/deprecation, or the environment need.

## Scope & plan
What changes and where (lockfile, overlay, compose file, pipeline).

## Verification & rollback
How to verify post-change, and **how to roll back** (previous pin/tag/overlay).
```

## Before filing: precision pass

If an agent pipeline will work the issue — or the acceptance criteria are dense — run a STE100-style precision pass over the description (e.g. the `/asd-ste100` skill, if installed). Machine-consumed text is where ambiguity costs rework.
