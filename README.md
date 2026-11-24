# serial-batch-chats｜串行多会话任务调度

[English](README.md) | [简体中文](README.zh-CN.md)

一个面向 Codex 的技能：先将完整任务写成分批计划，再在同一项目中逐批创建独立聊天。主会话负责调度、等待和核对文件证据；当前批次通过验收后，才创建下一批聊天。

适用于存在前后依赖、明确暂停点，或需要每个阶段使用独立聊天上下文的长任务。批次聊天是用户可见的项目聊天，内部 subagent 不能替代它们。

## 工作方式

```text
主会话：制定计划 → 创建 B01 → 等待 → 验收 B01 → 创建 B02 → …… → 交付
执行聊天：读取输入 → 实现任务 → 验证 → 保存证据和交接
```

- 将计划、提示、回执和交接保存在独立的 `.batch-runs/<任务名>/` 目录。
- 记录实际项目、thread 和 turn ID。
- 同时核对 turn 正常结束与落盘验收，避免将“聊天结束”当成“任务通过”。
- 使用 SHA-256 核对输入和已验收证据是否变化。
- 通过调度锁、创建前意图和创建后回执保持串行，防止重复派发。
- 恢复时监控原聊天；创建或发送回执不明时停止，不自动重放。
- 支持用户指定暂停点，以及在原聊天修复后接纳新 turn。
- 根据项目要求设置评审角色和验收项，不给所有任务强加双评审。

## 环境与执行通道

| 通道 | 条件 |
| --- | --- |
| 首选：原生聊天工具 | Codex 宿主提供项目聊天创建、读取和等待工具；先发现工具，再按真实 schema 使用。 |
| 随包桌面备用通道 | Windows、Python 3.9+、支持 UI Automation 的 Windows PowerShell、PATH 中的 `codex`、已登录的 Codex 桌面端，以及根目录唯一匹配的已登记项目。 |
| 离线测试与计划生成 | Python 3.9+；Python 脚本仅使用标准库。随包 CI 配置运行于 Windows。 |

备用通道依赖实验性 App Server 字段和特定桌面可访问性控件。运行前应核对本机生成的 schema；不匹配就停止派发。其他宿主使用原生工具，本发布包不宣称兼容所有 Codex 版本。

技能正文、生成的冒烟测试提示和详细协议使用中文；本仓库另提供完整英文使用说明。

## 安装

下载或克隆仓库后，在仓库根目录执行以下命令，将技能复制到 Codex 技能目录。命令只安装新副本；目标已存在时停止，避免覆盖已有修改。

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

**macOS / Linux：仅使用原生聊天工具**

```bash
skill_destination="${CODEX_HOME:-$HOME/.codex}/skills/serial-batch-chats"
if [ -e "$skill_destination" ]; then
  printf '%s\n' 'Skill already exists; review it before updating.' >&2
  exit 1
fi
mkdir -p "$skill_destination"
cp -R SKILL.md agents references scripts LICENSE "$skill_destination/"
```

## 在 Codex 中使用

说明任务、验收要求和暂停点，并明确授权创建独立项目聊天。例如：

```text
使用 $serial-batch-chats 完成本项目任务：
〈任务内容和验收要求〉

先写完整分批计划。我授权按计划逐批创建独立项目聊天，严格串行执行。
每批从前批保存的文件和交接接手，由主会话监控、核对证据后放行下一批。
B01 完成后暂停，等我检查后再继续。
```

此技能不额外授予提交、推送、发布或创建无关聊天的权限。评审由用户或项目要求决定。证据校验失败、创建回执不明时，停止后续派发。

## Windows 备用通道与冒烟计划

仅在没有原生聊天工具时使用。以下 PowerShell 命令中的两个路径需要替换为实际项目根和已安装的技能目录。

```powershell
$projectRoot = 'C:\path\to\your-project'
$skillDirectory = 'C:\path\to\serial-batch-chats'
Set-Location -LiteralPath $projectRoot

# 创建聊天前，核对本机实验性协议。
codex app-server generate-json-schema --experimental --out '.batch-runs/protocol-schema'

# 只生成两批计划和提示，不创建聊天，也不预写 PASS。
python -X utf8 "$skillDirectory/scripts/prepare_smoke.py" --root "$projectRoot" --run-dir '.batch-runs/smoke-01'

# 校验输入并列出计划标题，不创建聊天。
python -X utf8 "$skillDirectory/scripts/desktop_batches.py" --root "$projectRoot" --plan '.batch-runs/smoke-01/run.json'

# 已获授权后，创建并监控真实项目聊天。
python -X utf8 "$skillDirectory/scripts/desktop_batches.py" --root "$projectRoot" --plan '.batch-runs/smoke-01/run.json' --run

# state.json 已生成后，读取保存的调度状态。
python -X utf8 "$skillDirectory/scripts/desktop_batches.py" --root "$projectRoot" --plan '.batch-runs/smoke-01/run.json' --status
```

冒烟计划要求 B01 计算 `2 + 3`；B02 读取并核对 B01 结果文件的摘要，再将结果乘以 `4`。只有需要 content、repro 两名评审时，才给生成器添加 `--review-roles content repro`。每次测试使用新的运行目录。

Windows 辅助脚本会通过 UI Automation 折叠、展开目标侧栏项目并读取聊天标题，不截图。真实聊天使用现有 Codex 登录和模型配置，会产生正常的模型调用消耗。

## 文件协议与恢复

| 文件 | 用途 |
| --- | --- |
| `PLAN.md` | 供人阅读的范围、依赖顺序、输出和验收要求。 |
| `run.json` | 供程序执行的批次计划；路径相对项目根。 |
| `state.json`、`dispatch.lock` | 调度回执、已验收摘要、状态和单调度锁。 |
| `Bxx/prompt.md` | 当前批次保存的首条输入。 |
| `Bxx/acceptance.json` | 与计划中全部验收项对应的检查结果及摘要。 |
| `Bxx/handoff.md` | 提供给下一批的输入和证据说明。 |
| `Bxx/review.json` | 计划要求评审时保存的评审记录。 |
| `Bxx/transcript.json` | 备用程序保存的助手消息和 turn 回执。 |

`PASS` 需要 turn 正常完成、最终信号 `BATCH_DONE Bxx PASS`、证据摘要匹配、所需评审完成以及交接文件存在。备用通道还核对项目归属和侧栏可见性。摘要一致证明文件完整性，任务结果是否正确仍须通过对应的实际验证确认。

已有批次运行时，使用原 `--run` 命令恢复监控。创建或发送回执不明时，先检查原项目和原聊天；不要删除 `state.json` 重启。用户授权继续后，用 `--run --continue-after B01` 放行暂停点。阻塞批次在原聊天修复后，可用 `--run --adopt-turn B01=ACTUAL_NEW_TURN_ID` 接纳明确核实的新 turn。

详细说明：[文件协议](references/protocol.md)、[桌面备用通道与恢复](references/desktop-fallback.md)、[两聊天冒烟测试](references/smoke-test.md)。

## 离线验证

在仓库根目录执行：

```powershell
python -X utf8 -B -m unittest discover -s scripts -p 'test_*.py' -v
```

现有测试使用模拟客户端和临时文件，覆盖串行放行、失败阻断、证据变更、锁、暂停恢复、回执不明、新 turn 接纳和侧栏刷新失败。测试不创建真实聊天、不调用模型；Windows 侧栏适配器使用 mock。

仓库提供 Windows GitHub Actions 配置。离线测试通过与真实两聊天冒烟测试通过应分开报告。


## 许可证

采用 [MIT 许可证](LICENSE)，版权署名为 serial-batch-chats contributors。


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

