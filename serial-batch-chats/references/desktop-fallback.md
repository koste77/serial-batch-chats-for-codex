# 本机桌面备用通道

仅在已搜索而没有原生聊天工具时使用。此备用实现需要 Windows、Python 3.9+、PATH 中的 `codex`、已登录的 Codex 桌面端，以及已登记且根目录唯一匹配的项目。其他宿主使用原生聊天工具。程序不创建桌面项目、不修改模型或全局配置、不上传代码。

先确认本机接口，而不是假设所有版本支持这些实验字段：

```powershell
codex app-server generate-json-schema --experimental --out '<运行目录>/protocol-schema'
```

重点核对 `project/list`、`project/read`、`thread/start.projectId`、`thread/name/set`、`thread/read`、`thread/list.projectId`、`thread/resume`、`turn/start` 与 `turn/completed`。程序的 initialize 开启 experimentalApi，持久化聊天绑定明确的 projectId 与 cwd。线程来源必须回读为桌面支持的 `vscode`，且 ephemeral 为 false。接口不符时保留回执并停止，不尝试猜测其他字段。

从项目根执行，路径应替换为实际 skill 与计划位置：

```powershell
python -X utf8 '<skill>/scripts/desktop_batches.py' --root '<项目根>' --plan '<运行目录>/run.json'
python -X utf8 '<skill>/scripts/desktop_batches.py' --root '<项目根>' --plan '<运行目录>/run.json' --run
python -X utf8 '<skill>/scripts/desktop_batches.py' --root '<项目根>' --plan '<运行目录>/run.json' --status
```

第一条只校验和列计划；第二条持有唯一调度锁并串行运行；第三条只读状态。主会话保持跟进已有进程。服务器继承本机配置，子聊天限制为 workspace-write；脚本不会回答审批请求或提升权限。确有沙箱批准阻塞时按宿主正常授权机制处理，不扩大 child 的权限作为修复。

再次 `--run` 会核对既有摘要并监控原 thread/turn，不重发输入。前次停在 CREATING（创建回执不明）或已经拿到 thread 但没有 turn 回执时，程序停止并要求核对原聊天，不自动重试。暂停点只有获用户继续授权后才使用 `--continue-after B01`，放行前还会回读已验收聊天的最新 turn，避免前批已经重新运行时开启后批。

BLOCKED 由原执行聊天修复：先核实旧 turn 已结束，再按已获授权的任务范围明确继续**原聊天**，取得新 turn 的真实 ID。主会话核对同一聊天归属后，可用 `--run --adopt-turn B01=<实际新turnId>` 接纳该回执并等待/验收。此参数只用于首个未验收批次，不发送输入、不创建聊天，保留旧 turn_history，拒绝仍在运行的旧 turn 和非最新的新 turn。恢复时沿用已有 reviewer 记录。不能删除 state.json 来“恢复”；已 PASS 批次的证据或聊天变化需先复核，不能用 adopt-turn 偷换既有验收。

首条输入持久化后，脚本按 projectId、cwd 和完整标题分页查询 `thread/list`，只把返回的实际 thread ID 视为绑定确认。保持默认 sourceKinds。随后自动调用打包的 `refresh_desktop_project.ps1`，通过 Windows UI Automation 的 ExpandCollapsePattern 刷新目标项目，并在该项目子控件中回读完整会话标题。过程不截图、不读取桌面画面；后台列表回读不能替代此刷新。刷新暂时失败时保留当前执行，批末重试；仍失败则停止后续派发，禁止重复新建聊天来修复显示。

每批完成会保存 transcript.json 与 thread/turn 回执，验收文件另存哈希。只有正常 completed、本 turn 最终消息明确 `BATCH_DONE <ID> PASS`、文件与评审均通过才放行。缺信号、批号不符、BLOCKED 或冲突信号都停止。每次派发和写 COMPLETE 前复核所有已 PASS 的证据摘要。请求超时保留已有状态，停止后续创建；进程关闭可能中止其托管的执行，应通过原聊天状态确认后恢复。
