---
name: daytona
description: Use when checking Daytona sandbox status, listing or inspecting sandboxes, reading files inside a sandbox, or verifying Daytona API connectivity
---

# Daytona

Query Daytona sandboxes via the official Python SDK.

## Setup

```bash
uv venv --python 3.12 && uv pip install daytona python-dotenv
# or one-shot, no venv needed:
uv run --python 3.12 --with daytona --with python-dotenv python script.py
```

## Credentials

Credentials live in the skill directory, not the project's `.env`:

| File | Purpose |
|---|---|
| `{BASE_DIR}/.env` | Default environment |
| `{BASE_DIR}/.env.<name>` | Extra environments (e.g. `.env.staging`, `.env.prod`) |

`{BASE_DIR}` is the base directory printed in the skill preamble when the skill loads. Each file sets `DAYTONA_API_KEY` and `DAYTONA_API_URL` (get keys from the Daytona dashboard). Load the right file explicitly. Never print key values.

```python
from dotenv import load_dotenv
load_dotenv(f"{BASE_DIR}/.env")  # or f"{BASE_DIR}/.env.<name>"
from daytona import Daytona
client = Daytona()
```

Do NOT `load_dotenv()` with no path — it walks up and may pick up a stray project `.env` with the wrong environment's key.

## Quick Reference

| Want | SDK call |
|---|---|
| Sandbox status/counts | `client.list(page, limit)` |
| One sandbox's info | `client.find_one(id_or_name)` |
| Files inside sandbox | `sandbox.fs.list_files(path)`, `sandbox.fs.download_file(path)` |
| Run a command inside | `sandbox.process.exec(cmd)` (sandbox must be started) |
| Connectivity health | `client.list(limit=1)` succeeds or raises |

## 1. Status of sandboxes

```python
from collections import Counter
from dotenv import load_dotenv
from daytona import Daytona

load_dotenv(f"{BASE_DIR}/.env")  # or f"{BASE_DIR}/.env.<name>"
client = Daytona()

result = client.list(page=1, limit=200)
print("total:", result.total)
print(Counter(s.state.value for s in result.items))
```

`PaginatedSandboxes` has `items`, `total`, `total_pages`, `page`. Page with `page=2, 3, ...` until items run out. Filter with `client.list(labels={"your-label": "value"})`. Useful `Sandbox` fields: `id`, `name`, `state`, `desired_state`, `snapshot`, `labels`, `target`, `cpu`, `memory`, `disk`, `created_at`, `updated_at`, `error_reason`.

## 2. Inspect one sandbox / look inside

```python
sandbox = client.find_one("sandbox-id-or-name")
print(sandbox.state, sandbox.snapshot, sandbox.labels, sandbox.error_reason)

for f in sandbox.fs.list_files("/home/daytona"):
    print(f.name, f.size, f.is_dir)

content = sandbox.fs.download_file("/home/daytona/some.log")  # returns bytes
```

`fs.list_files(path)` fails if the path doesn't exist or the sandbox is stopped. `sandbox.process.exec("ls -la /home/daytona", timeout=60)` works on started sandboxes and returns `ExecuteResponse` (`.result`, `.exit_code`). To start a stopped one: `sandbox.start(timeout=60)`.

## 3. Health / connectivity

```python
try:
    client.list(limit=1)
    print("Daytona API: OK")
except Exception as exc:
    print("Daytona API: FAIL:", exc)
```

Per-sandbox health = `state` (expect `started` for running work) plus `error_reason` (populated on failure).

## Common Mistakes

- `load_dotenv()` with no path walks up and may pick up a stray project `.env` with a wrong-environment key — always pass the skill dir path explicitly.
- `source .env` in bash breaks on values with special characters; use python-dotenv.
- `state` is a `SandboxState` enum — use `.value` when printing/comparing to strings.
- Default `client.list()` page size is small; pass `limit=200` and paginate.
- `find_one` matches id or name.
- Creating/starting/stopping sandboxes costs resources — for read-only checks stick to `list`, `find_one`, `fs`.
