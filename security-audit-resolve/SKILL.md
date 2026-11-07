---
name: security-audit-resolve
description: Use when working a security-audit finding in a later session — resolving a needs_validation lead, pulling up a confirmed finding to fix it, checking what an audit found, or referencing a finding by fingerprint or title. Triggers on fingerprints, "resolve/look up/point at a finding", needs_validation blockers, or audit artifacts under ~/security-audit-skill/.
---

# Security-audit resolve

Load a finding from a completed security-audit run so the current session can act on it with full context. The record already contains everything — trace, blockers, validation plans, remediation. Your job is to **find it, present it, and gate the next step**. Not to fix, verify, or promote anything unasked.

## Two iron rules

1. **Never execute target code.** Not the app, not pytest, not a TestClient fixture — even one the record's `validation_plan.local` describes. That plan is conditional on an OS-enforced sandbox that most hosts (including the audit host) cannot provide. Check the gate first (below); when it fails, say the plan is blocked and present the deployment plan instead.
2. **Never edit the audit run's files.** `run-metadata.json`, `architecture.md`, `coverage-ledger.json`, `findings.json`, `REPORT.md`, `FINDINGS-DETAIL.md`, `NEEDS-VALIDATION.md` are an immutable record. No verdict changes, no severity edits, no "updating findings.json with what we learned". Outcomes go to `RESOLUTIONS.md` (below) — and only when asked.

| Excuse | Reality |
|---|---|
| "The record's local plan told me to run the fixture" | The plan says *inside an OS-enforced sandbox*. No sandbox → blocked. Report it; don't run it. |
| "I'll promote the record to confirmed since I verified it" | Verdicts change only through a new audit run's verification process. You record an outcome line; the run stays as audited. |
| "Editing findings.json keeps everything in one place" | That file is the validated record. One hand-edit destroys the guarantee that everything in it was independently verified. |
| "I decoded the secret to confirm it's real" | Never reproduce secret values — cite `file:line` and structure (prefix, key type) only. |
| "'Resolve' means resolve it end-to-end" | It means: load the record, explain the blocker, lay out the exact next step. The owner decides what actually runs. |

**Red flags — stop and re-read the rules:** you are about to run the app or its tests; you are about to write to any file in the run directory other than `RESOLUTIONS.md`; you are about to assign or change a severity; you have a secret value in your output.

## Locate the run

Runs live at `~/security-audit-skill/<repo>/run-N/`. Resolve in order:
- explicit path given → use it
- `--project <name>` or positional project → that repo
- otherwise → repo of the current working directory (`git remote` basename or dir name)
- run number given (`--run 1`, `run-1`) → that run; else highest `run-N`
- nothing found → list `~/security-audit-skill/` and ask

## Load the record

From `findings.json` (machine source of truth; use `jq` or python, never eyeball a whole 400KB file). Match: exact fingerprint → unique prefix → title/keyword substring. Multiple hits → numbered list, ask. Then read the run's `run-metadata.json` for the execution policy that governed the audit.

**Read the verdict field before counting anything** — records are confirmed *or* needs_validation; never call the file "N confirmed findings".

## Present (needs_validation)

1. One-paragraph summary: boundary, claimed root cause, what's blocked.
2. Blockers, classified: *deployment fact* (owner must observe something) vs *sandbox-blocked* (local fixture that can't run here).
3. The matching next step:
   - **Deployment plan** → translate into concrete owner steps (which config to read, which log to grep, what observation resolves it). Never probe the deployed system yourself.
   - **Local plan** → run the sandbox gate: `command -v bwrap`; `unshare -Urpn true`. Both fail → state "blocked on this host" with the missing capability, offer the deployment plan.
4. Drift check: verify 2–3 cited `file:line`s still match current HEAD; warn and show what's there now if the source moved.

Stop there. When the user returns with an observation, interpret it — but a promotion to "confirmed" is their call to record in `RESOLUTIONS.md`, not a file edit.

## Present (confirmed)

Trace (entrypoint → sink), severity with its rationale, conditions, remediation strategy, suggested fix sites from `code_changes`. Then stop — fixing goes through the user's normal flow. Do not start implementing.

## Outcome notes

Only when asked: append one line to `<run-dir>/RESOLUTIONS.md` — `fingerprint · outcome (validated-confirmed / validated-refuted / fixed-in-source <commit> / blocked) · date · evidence location`. Nothing else.

## List mode

"What's left" → group needs_validation records by shared blocker (most are one gateway-fact or one sandbox away); confirmed records by severity. Counts come from filtering `verdict`, never from file size or section counts.
