# 本机桌面备用通道（桌面持有执行回合）

本版采用以下执行流程：创建并排队 → 桌面启动既有消息 → 脚本只读监测 → 主会话主审 → 下一批。旧版直接托管回合遇到交互请求后关闭连接，曾导致任务中断。不要再调用 turn/start、thread/resume 或 Client.wait_turn 来运行批次；wait_turn 已禁用。

## 当前执行流程

先用本机 schema 确认 project/list、project/read、thread/start.projectId/model/config、thread/name/set、thread/read、thread/list.projectId、thread/queue/add 和 thread/queue/list。模型强度通过 config.model_reasoning_effort，创建响应为 model/reasoningEffort；字段不匹配保留回执并停止。

```powershell
python -B -X utf8 '<skill>/scripts/desktop_batches.py' --root '<项目根>' --plan '<运行目录>/run.json' --run
```

--run 创建唯一当前批次，命名并排队首条输入，保存实际聊天、请求/回读模型、队列回执，确认项目和侧栏。创建、命名、排队超时保留 CREATING/CREATED/QUEUE_SENDING 等状态，不重建或重发。模型配置见 protocol.md；主聊天配置独立。

打开 codex://threads/<实际ID>，Windows Start-Process 使用 -WindowStyle Hidden。已授权启动时，核对唯一当前聊天标题、指定模型/强度及唯一启用的“继续”控件后，可用 UI Automation 启动已有队列；控件不明确则请用户启动，不再发一条继续。无明确模型设置时记录实际继承值，不假定固定控件文案。不得点击允许、批准或拒绝控件。

```powershell
python -B -X utf8 '<skill>/scripts/desktop_batches.py' --root '<项目根>' --plan '<运行目录>/run.json' --run --watch --interval 30
```

脚本确认队列为空、发现实际 agent 回合并记录 turn ID；空的排队占位回合不算执行。持有唯一锁，后续仅只读 thread/read，默认30秒一次。主会话保持调度回合，等待工具进程 session，每次有界等待不超过60秒；无变化不重复转述。不带 --watch 只取一次快照。

冷读 interrupted 可能对应仍活跃的桌面回合，不能单独据此报停、重建或发继续。按需核对桌面停止/审批控件、公开 commentary 或文件变化，不读取隐藏推理，不移除 active writer 锁。进程 session ID 不是聊天 ID。实际审批由用户在原聊天处理，主会话说明具体操作并保持监测；批准后直接等待，不重复发送继续。

正常 completed 且 BATCH_DONE 本批 PASS 后，脚本保存 transcript，退出为 AWAITING_PRIMARY_REVIEW。主会话独立核对原始证据、真实 reviewer 回执和交接，按 protocol.md 写 primary_gate.json。再次 --run 才放行下一批；门禁必须精确匹配当前 thread/turn/验收摘要。脚本不能判断工程正确性。

修复回到原聊天，已有恢复消息就启动它；新实际回合核对后用 --run --adopt-turn B01=<新turnId> --watch 接管。旧回合 inProgress 时拒绝；冷读 interrupted 仍须主会话确认旧回合实际已结束。保留 turn_history，已 PASS 批次不能 adopt 偷换。用户检查点用 --run --continue-after B01 放行。

只读监测断开不应中止桌面执行，恢复先核对 state 和原聊天实际进展。429按真实并发/RPM/服务端响应及 Retry-After（若有）退避，不一概归因认证。创建/排队结果不明不盲目重试。不使用定时自动化代替当前调度；减少协调模型反复生成不代表零额度占用。

## 前置条件与恢复约束

需要 Windows、Python 3.9+、PATH 中 codex、已登录桌面应用、根目录唯一匹配的已登记项目。不创建项目、不更改全局配置或子聊天权限。生成本机协议后核对再执行：

```powershell
codex app-server generate-json-schema --experimental --out '<运行目录>/protocol-schema'
```

聊天必须持久化、ephemeral=false、source=vscode、正确 projectId/cwd。后台 project/list/thread/list 确认不能替代 Windows 侧栏确认。refresh_desktop_project.ps1 折叠/展开项目并通过可访问性控件确认完整标题，进程可能为 Codex 或 ChatGPT；不截图。失败保留原聊天并停止后续派发，不重复创建修复显示。

已有运行保留全部回执。恢复先核对原聊天，计划/模型设置/提示/已验收摘要变化须复核，不删除 state.json。BLOCKED 记录真实失败及恢复条件；PAUSED 仅用于用户规定的检查点。程序只读监测断开与执行回合实际中断必须分开判断。
