# 文件协议与执行提示

每次运行使用独立目录。以下相对路径均相对**项目根**，不是 skill 安装目录。禁止路径逃逸。目录内可用 PLAN.md 供人阅读，run.json 供备用程序执行，state.json 保存调度回执；各批目录存结果、acceptance.json、handoff.md 和按需设置的 review.json。

run.json 示例（仅展示一批，实际按依赖添加）：

```json
{
  "task": "简单交接检测",
  "plan_document": ".batch-runs/demo/PLAN.md",
  "batches": [
    {
      "id": "B01",
      "title": "B01 计算初始结果",
      "prompt": ".batch-runs/demo/B01/prompt.md",
      "acceptance": ".batch-runs/demo/B01/acceptance.json",
      "criteria": ["B01.1", "B01.2", "B01.3"],
      "review_roles": [],
      "pause_after": false
    }
  ]
}
```

`review_roles` 按项目规则设置，例如 `["content", "repro"]`。未要求评审时为空，不为简单算术强行增加工程审查。若要求双评审，则执行聊天一次并行发起两名只读 reviewer，记录不同 ID、意见和处置，不在恢复时重复发起。

acceptance.json 由执行聊天在验证后写入：

```json
{
  "batch": "B01",
  "status": "PASS",
  "checks": [
    {
      "criterion": "B01.1",
      "passed": true,
      "evidence": ".batch-runs/demo/B01/calculation.json",
      "sha256": "真实文件的 SHA-256"
    }
  ],
  "handoff": ".batch-runs/demo/B01/handoff.md"
}
```

checks 必须与计划中的 criteria 完全一致；各项用独立证据文件，不以验收单或评审单本身充当证据。handoff 必须指向存在的交接文件。备用程序还校验 evidence 的实际摘要以及所需的 review.json：

```json
{
  "batch": "B01",
  "reviewers": [
    {
      "id": "实际 subagent ID",
      "role": "content",
      "status": "PASS",
      "findings": "实际意见摘要",
      "disposition": "已处理或无问题的说明",
      "unresolved": false
    }
  ]
}
```

提示文件应包含下列信息，按任务填写，不发送未替换的模板：

> 你是本项目独立执行聊天，只执行〈批次 ID 与标题〉。读取〈skill 的 SKILL.md、项目规则、PLAN.md 与本批任务路径〉。只从项目文件接手，核对〈前批验收/结果路径及预期摘要〉。
>
> 工作范围：〈任务、可写目录、不可覆盖的现有文件〉。改动前列明文件与简要计划。完成〈具体输出〉并运行〈验证〉。按本批 review_roles 完成评审及问题处置。
>
> 真实通过后写 acceptance.json、独立逐项证据及 handoff.md；失败写 BLOCKED 和恢复条件，不预签 PASS。不要创建下一批聊天或更改调度状态。
>
> 最终回答包含 `BATCH_DONE <ID> PASS` 或 `BATCH_DONE <ID> BLOCKED`、真实指标、证据路径和下批输入。口头信号不能代替落盘验收。

恢复时，PASS 的文件摘要须与调度回执一致；计划、提示或已验收证据变更须先复核。不能凭旧文件跳过新尝试，也不能把上个任务的验收移到当前任务。
