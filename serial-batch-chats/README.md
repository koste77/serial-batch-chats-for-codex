# serial-batch-chats

[English](README.md) | [简体中文](README.zh-CN.md)

A Codex skill for running a task as a sequence of separate project chats. The coordinating chat writes a batch plan, dispatches one chat at a time, checks its file-based handoff and acceptance evidence, and releases the next batch only after the current batch passes.

Useful for long tasks with ordered dependencies, explicit checkpoints, or work that needs a fresh chat for each stage. Batch chats are user-visible project chats; internal subagents do not replace them.

## How it works

```text
Coordinating chat: plan → start B01 → wait → accept B01 → start B02 → … → deliver
Batch chat:        read inputs → implement → verify → write evidence and handoff
```

- Keeps plans, prompts, receipts, and handoffs in a dedicated `.batch-runs/<task>/` directory.
- Records actual project, thread, and turn identifiers.
- Requires both a normal turn completion and matching on-disk acceptance evidence.
- Uses SHA-256 hashes to detect changed inputs and previously accepted evidence.
- Keeps dispatch serial with a run lock and receipts written before and after creation.
- Resumes known chats rather than automatically replaying an uncertain create/send request.
- Supports explicit pause points and recovery in the original chat.
- Makes reviewer roles and acceptance criteria project-specific rather than mandatory ceremony.

## Requirements and execution paths

| Path | Requirements |
| --- | --- |
| Preferred: native chat tools | A Codex host exposing project chat creation, reading, and waiting tools. Discover the tools and use their actual schemas. |
| Bundled desktop fallback | Windows, Python 3.9+, Windows PowerShell with UI Automation, `codex` on `PATH`, a signed-in Codex desktop app, and an already registered project whose root uniquely matches the working directory. |
| Offline tests and plan preparation | Python 3.9+; the bundled Python code uses only the standard library. The supplied CI configuration targets Windows. |

The fallback depends on experimental App Server fields and specific desktop accessibility controls. Check the locally generated schema before running it; a mismatch stops dispatch. Use native tools on other hosts. This release does not claim compatibility with every Codex version.

The skill instructions, generated smoke-test prompts, and detailed references are in Chinese. This README provides the English installation and operating guide.

## Install

Download or clone this repository. From the repository root, copy the skill files into your Codex skills directory. These commands install a new copy and stop if the destination already exists.

**Windows PowerShell**

```powershell
$skillBase = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$skillDestination = Join-Path $skillBase 'skills/serial-batch-chats'
if (Test-Path -LiteralPath $skillDestination) { throw 'Skill already exists; review it before updating.' }
New-Item -ItemType Directory -Path $skillDestination -Force | Out-Null
foreach ($item in @('SKILL.md', 'agents', 'references', 'scripts', 'LICENSE')) {
    Copy-Item -LiteralPath (Join-Path (Get-Location).Path $item) -Destination $skillDestination -Recurse
}
```

**macOS / Linux — native chat tools only**

```bash
skill_destination="${CODEX_HOME:-$HOME/.codex}/skills/serial-batch-chats"
if [ -e "$skill_destination" ]; then
  printf '%s\n' 'Skill already exists; review it before updating.' >&2
  exit 1
fi
mkdir -p "$skill_destination"
cp -R SKILL.md agents references scripts LICENSE "$skill_destination/"
```

## Use from Codex

Explicitly authorize the separate project chats and state the task, deliverables, and any pause points. For example:

```text
Use $serial-batch-chats to finish this task in the current project:
<task and acceptance criteria>

First write the full batch plan. I authorize a separate project chat for each
batch, created serially. Let each batch read the previous batch's saved handoff.
The coordinating chat should monitor and check the evidence before releasing
the next batch. Pause after B01 for my review.
```

The skill does not grant permission to commit, push, publish, or create unrelated chats. Reviews are required only when the user or project requires them. Failed evidence checks or uncertain creation receipts stop subsequent dispatch.

## Windows fallback and smoke plan

Use this path only when native chat tools are unavailable. In the following PowerShell commands, replace the two paths with your actual project root and installed skill folder.

```powershell
$projectRoot = 'C:\path\to\your-project'
$skillDirectory = 'C:\path\to\serial-batch-chats'
Set-Location -LiteralPath $projectRoot

# Check the local experimental protocol before creating chats.
codex app-server generate-json-schema --experimental --out '.batch-runs/protocol-schema'

# Prepare two batches; this creates files, not chats or PASS results.
python -X utf8 "$skillDirectory/scripts/prepare_smoke.py" --root "$projectRoot" --run-dir '.batch-runs/smoke-01'

# Validate inputs and list the planned titles; no chat creation.
python -X utf8 "$skillDirectory/scripts/desktop_batches.py" --root "$projectRoot" --plan '.batch-runs/smoke-01/run.json'

# After authorization, create and monitor the real project chats.
python -X utf8 "$skillDirectory/scripts/desktop_batches.py" --root "$projectRoot" --plan '.batch-runs/smoke-01/run.json' --run

# Read saved dispatch status after state.json exists.
python -X utf8 "$skillDirectory/scripts/desktop_batches.py" --root "$projectRoot" --plan '.batch-runs/smoke-01/run.json' --status
```

The smoke plan asks B01 to calculate `2 + 3`, then B02 to read and hash-check B01's saved result and multiply it by `4`. Pass `--review-roles content repro` to the generator only when those two reviews are required. Always use a new smoke run directory.

The Windows helper expands/collapses the target sidebar project and reads the chat title through UI Automation. It does not take screenshots. Running chats uses your existing Codex authentication and model configuration and can incur normal model usage.

## Files and recovery

| File | Purpose |
| --- | --- |
| `PLAN.md` | Human-readable scope, dependency order, outputs, and acceptance criteria. |
| `run.json` | Machine-readable batch plan; paths are relative to the project root. |
| `state.json`, `dispatch.lock` | Dispatch receipts, accepted hashes, status, and single-dispatcher lock. |
| `Bxx/prompt.md` | Saved first input for one batch chat. |
| `Bxx/acceptance.json` | Checks and hashes matching all criteria in the batch plan. |
| `Bxx/handoff.md` | Inputs and evidence for the next batch. |
| `Bxx/review.json` | Review records when the plan requires them. |
| `Bxx/transcript.json` | Assistant messages and turn receipts saved by the fallback. |

A `PASS` needs a completed turn, the final signal `BATCH_DONE Bxx PASS`, matching evidence hashes, the required reviews, and a handoff. The fallback also checks project membership and sidebar visibility. Hash matching establishes file integrity; task-specific verification is still needed to establish correctness.

For a known running batch, rerun the same `--run` command to resume monitoring. For an uncertain create/send receipt, inspect the original project and chat before doing anything else. Do not delete `state.json` to restart. Release an authorized pause with `--run --continue-after B01`. A repaired blocked batch can adopt an explicitly verified new turn in the same chat with `--run --adopt-turn B01=ACTUAL_NEW_TURN_ID`.

Detailed Chinese references: [file protocol](references/protocol.md), [desktop fallback and recovery](references/desktop-fallback.md), and [two-chat smoke test](references/smoke-test.md).

## Offline verification

From the repository root:

```powershell
python -X utf8 -B -m unittest discover -s scripts -p 'test_*.py' -v
```

The existing tests use simulated clients and temporary files. They cover serial dispatch, failure gates, changed evidence, locking, pause/resume, uncertain receipts, turn adoption, and sidebar failures. They do not create real chats or call a model. The Windows sidebar adapter is mocked in the tests.

The included GitHub Actions workflow runs these tests on Windows. A passing offline suite is separate from a successful live two-chat smoke test.



## License

[MIT](LICENSE). Copyright is attributed to the serial-batch-chats contributors.
