"""Prepare an isolated two-chat smoke run; does not create chats or sign PASS."""

import argparse
from pathlib import Path

from desktop_batches import local, require, save


def prepare(root, run_dir, roles):
    folder = local(root, run_dir)
    require(not folder.exists(), "Choose a new run directory; never overwrite an earlier test")
    folder.mkdir(parents=True)
    skill = Path(__file__).resolve().parents[1]
    task = "串行多会话 Skill 检测 " + folder.name
    prefix = folder.relative_to(root).as_posix()
    plan = """# 两聊天顺序检测计划

主会话先编写计划，再逐批创建用户可见的桌面项目聊天。此测试独立于项目业务计划。
主会话只调度、监控和核对证据；执行聊天实现与验证，按 review_roles 完成评审。
不提交或上传 Git；不截图、不读取桌面画面。两批完成前持续等待，遇真实阻塞停止。

## B01 计算初始结果

题目：2 + 3 等于多少？输出 result.json，记录 operands、operation 和 answer。
验收 B01.1：真实计算正确；B01.2：有独立重算记录；B01.3：交接包含结果路径和实际 SHA-256。
每项一份独立证据，完成所需评审，最后写 acceptance.json 和 handoff.md。

## B02 读取前批结果并继续计算

题目：读取 B01/result.json 和 handoff.md，核对结果文件摘要，再把前批结果乘以 4。
result.json 记录 source_path、source_sha256、source_answer、factor 和 answer。
验收 B02.1：读取并核验 B01 来源与摘要；B02.2：使用该输入算出正确结果并独立重算；
B02.3：最终交接可复现并包含结果摘要。每项一份独立证据，所需评审结束后写验收。

总验收：两个不同聊天绑定同一项目；B02 创建晚于 B01 正常结束并验收；结果通过独立计算核对；
后批使用前批真实文件与摘要；重复运行不新增聊天、不重发输入。不处理本测试目录以外的任务。
"""
    (folder / "PLAN.md").write_bytes(plan.encode("utf-8"))
    manifest = {"task": task, "plan_document": prefix + "/PLAN.md", "batches": []}
    titles = ["计算初始结果", "读取前批结果并继续计算"]
    for index, title in enumerate(titles, 1):
        batch = "B%02d" % index
        batch_dir = folder / batch
        batch_dir.mkdir()
        batch_path = prefix + "/" + batch
        assignment = ("计算 2 + 3。result.json 写 operands、operation 和 answer。"
                      if index == 1 else
                      "读取 " + prefix + "/B01/result.json、handoff.md、acceptance.json；"
                      "必须从交接读取期望 SHA-256，再与结果文件的实际摘要比较。"
                      "将读取的 answer 乘以 4，result.json 记录 source_path、source_sha256、"
                      "source_answer、factor、answer。")
        review_text = ("本测试遵循项目双评审规则：完成实现和初步验证后，只发起一轮、同时启动 "
                       "两名只读 reviewer，任务名为 " + batch.lower() + "_content_review 和 "
                       + batch.lower() + "_repro_review。分别检查题意/结果及程序/数据/可复现性。"
                       "评审仅为内部 subagent，不创建额外用户聊天。记录真实不同 agent ID、意见和处置，"
                       "两者返回后修复复测，不重复发起新一轮。"
                       if roles else "本次 run.json 未要求评审；如果项目规则另有要求则先满足项目规则并如实记录。")
        prompt = f"""你是独立执行聊天，只执行 {batch} {title}，不创建或调度下一批聊天。
项目根：{root}
本批唯一可写目录：{batch_dir}
先读取根目录 AGENTS.md（若存在）、{skill / 'SKILL.md'}、{skill / 'references' / 'protocol.md'}、
{folder / 'PLAN.md'}、{folder / 'run.json'}。本 skill 在这里用于执行当前批，不递归调度。
只从这些项目文件接手。改动前用中文列明要写文件和 3–6 步计划，说明命令目的。

题目：{assignment}
输出 result.json、独立验证文件、逐项证据、handoff.md、acceptance.json；需要时输出 review.json。
使用本地 Python 进行真实计算和独立重算；不访问网络、Git、桌面画面或测试目录之外的业务文件。
handoff.md 包含本批结果路径及其真实 SHA-256，供下一批读取。证据和 acceptance 中的路径均相对项目根。
计划的三个验收项 {batch}.1、{batch}.2、{batch}.3 必须各有独立证据文件，计算结果可充当一项，
其他两项分别证明独立验证与交接/来源核验，不用验收或评审单本身充当证据。

{review_text}
review.json 按 references/protocol.md，角色为 {roles}；status=PASS 只在真实通过时写入，unresolved=false。
写 acceptance 前重新核对三个证据的 SHA-256，checks 中每项包含 criterion、passed、evidence、sha256。
acceptance 的 batch={batch}，handoff={batch_path}/handoff.md。评审未完成、缺证据或验证失败写 BLOCKED。
不要修改计划、提示、state.json、dispatch.lock 或其他批次文件。不要要求主会话代做本批修复或验收。
最终用中文报告计算结果、实际评审 ID、修改文件、验证与证据路径，包含 BATCH_DONE {batch} PASS 或 BLOCKED。
"""
        (batch_dir / "prompt.md").write_bytes(prompt.encode("utf-8"))
        manifest["batches"].append({"id": batch, "title": batch + " " + title,
                                   "prompt": batch_path + "/prompt.md",
                                   "acceptance": batch_path + "/acceptance.json",
                                   "criteria": [batch + "." + str(n) for n in (1, 2, 3)],
                                   "review_roles": roles, "pause_after": False})
    save(folder / "run.json", manifest)
    print(str(folder / "run.json"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--review-roles", nargs="*", default=[])
    args = parser.parse_args()
    prepare(Path(args.root).resolve(), args.run_dir, args.review_roles)
