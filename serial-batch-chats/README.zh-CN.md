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

# 已获授权后，创建并排队当前唯一项目聊天。
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

## Desktop execution and model settings / 桌面执行与模型配置

The fallback now creates and queues one batch. Start that existing message once in the desktop chat, then use --run --watch --interval 30 for read-only monitoring. Keep the coordinator attached to its script session. Cold interrupted snapshots do not prove a stopped desktop turn. Actual approvals stay in the original chat. Completion stops at AWAITING_PRIMARY_REVIEW; the coordinator checks evidence and writes primary_gate.json before another --run releases the next batch.

备用通道改为“创建并排队→桌面启动→脚本只读监测→主会话主审→下一批”。--run 只取一次快照，--run --watch 持续监测。已有运行保留回执并复核后迁移，不删除状态重建聊天。

run.json 可设置默认模型与强度，逐批 chat 可覆盖一个或两个字段：

```json
"chat_defaults": {"model": "gpt-6.1-sol", "reasoning_effort": "ultra"}
```

```json
"chat": {"reasoning_effort": "high"}
```

These are editable examples. Precedence: per-batch chat > chat_defaults > host inheritance. Requested and returned settings are recorded; mismatch stops without recreating. Verify the desktop model control before starting. The coordinator model remains independent.

详细命令、门禁及恢复见 [文件协议](references/protocol.md) 和 [桌面备用通道](references/desktop-fallback.md)。
