"""Serial desktop chats with durable receipts; native thread tools are preferred."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading
import time


def require(condition, message):
    if not condition:
        raise ValueError(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(path.name + ".tmp")
    staging.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    os.replace(str(staging), str(path))


def digest(path):
    require(path.is_file() and path.stat().st_size > 0, "Missing or empty file: " + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local(root, raw):
    require(isinstance(raw, str) and raw and "\\" not in raw, "Use project-relative / paths")
    rel = Path(raw)
    require(not rel.is_absolute() and not rel.drive and ".." not in rel.parts, "Unsafe path: " + raw)
    path = (root / rel).resolve()
    require(root in path.parents, "Path outside project: " + raw)
    return path


def load_plan(root, path):
    data = read_json(path)
    require(isinstance(data.get("task"), str) and data["task"].strip(), "Missing task title")
    batches = data.get("batches")
    require(isinstance(batches, list) and batches, "Missing batches")
    files = {str(path.relative_to(root)): digest(path)}
    document = local(root, data["plan_document"])
    files[data["plan_document"]] = digest(document)
    for index, batch in enumerate(batches, 1):
        require(batch.get("id") == "B%02d" % index, "Batches must be contiguous from B01")
        require(isinstance(batch.get("title"), str) and batch["title"].startswith(batch["id"] + " "),
                "Title must include batch ID")
        criteria = batch.get("criteria")
        require(isinstance(criteria, list) and criteria and all(isinstance(x, str) and x for x in criteria)
                and len(set(criteria)) == len(criteria), "Invalid criteria")
        roles = batch.get("review_roles", [])
        require(isinstance(roles, list) and all(isinstance(x, str) and x for x in roles)
                and len(set(roles)) == len(roles), "Invalid review roles")
        files[batch["prompt"]] = digest(local(root, batch["prompt"]))
        local(root, batch["acceptance"])
    return data, files


def acceptance(root, batch):
    path = local(root, batch["acceptance"])
    data = read_json(path)
    require(data.get("batch") == batch["id"] and data.get("status") == "PASS", "Acceptance not PASS")
    checks = data.get("checks")
    require(isinstance(checks, list) and len(checks) == len(batch["criteria"]), "Missing checks")
    remaining = set(batch["criteria"])
    hashes = {batch["acceptance"]: digest(path)}
    forbidden = {path, path.parent / "review.json"}
    used = []
    for check in checks:
        require(check.get("criterion") in remaining and check.get("passed") is True, "Failed/duplicate criterion")
        remaining.remove(check["criterion"])
        evidence = local(root, check["evidence"])
        require(path.parent in evidence.parents and evidence not in forbidden, "Evidence outside batch or self-reference")
        require(all(not evidence.samefile(old) for old in used), "Evidence must be independent files")
        actual = digest(evidence)
        require(check.get("sha256") == actual, "Evidence digest mismatch")
        used.append(evidence)
        hashes[check["evidence"]] = actual
    handoff = local(root, data["handoff"])
    require(path.parent in handoff.parents and handoff not in forbidden, "Invalid handoff")
    hashes[data["handoff"]] = digest(handoff)
    roles = batch.get("review_roles", [])
    if roles:
        review_path = path.parent / "review.json"
        review = read_json(review_path)
        require(review.get("batch") == batch["id"], "Wrong review batch")
        reviewers = review.get("reviewers", [])
        require(len(reviewers) == len(roles), "Missing reviewers")
        require({r.get("role") for r in reviewers} == set(roles), "Wrong review roles")
        ids = set()
        for row in reviewers:
            require(all(isinstance(row.get(k), str) and row[k].strip()
                        for k in ("id", "findings", "disposition")), "Incomplete review")
            require(row.get("status") == "PASS" and row.get("unresolved") is False, "Unresolved review")
            ids.add(row["id"])
        require(len(ids) == len(roles), "Reviewers must have distinct IDs")
        hashes[review_path.relative_to(root).as_posix()] = digest(review_path)
    return hashes


@contextmanager
def exclusive(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("A dispatcher already holds this run lock") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class Client:
    def __init__(self, root):
        executable = shutil.which("codex")
        require(executable, "codex is not on PATH")
        args = [executable]
        if os.name == "nt":
            args += ["-c", "windows.sandbox=mxc"]
        args += ["app-server", "--stdio"]
        self.process = subprocess.Popen(args, cwd=str(root), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.events = queue.Queue()
        self.sequence = 0
        self.finished = {}
        threading.Thread(target=self._reader, daemon=True).start()
        try:
            self.request("initialize", {"clientInfo": {"name": "serial_batch_chats", "version": "1"},
                                        "capabilities": {"experimentalApi": True}})
            self.send({"method": "initialized", "params": {}})
        except BaseException:
            self.close()
            raise

    def _reader(self):
        try:
            for line in self.process.stdout:
                self.events.put(json.loads(line))
        except (ValueError, OSError):
            pass
        finally:
            self.events.put(None)

    def send(self, value):
        self.process.stdin.write(json.dumps(value, ensure_ascii=False) + "\n")
        self.process.stdin.flush()

    def event(self, timeout):
        value = self.events.get(timeout=timeout)
        require(value is not None, "App Server disconnected; retain original thread receipts")
        require(not ("method" in value and "id" in value),
                "Chat needs interactive approval/input; inspect original chat before continuing")
        if value.get("method") == "turn/completed":
            params = value["params"]
            self.finished[params["threadId"], params["turn"]["id"]] = params["turn"]
        return value

    def request(self, method, params):
        self.sequence += 1
        expected = self.sequence
        self.send({"id": expected, "method": method, "params": params})
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                value = self.event(max(0.01, deadline - time.monotonic()))
            except queue.Empty as exc:
                raise ValueError(method + " timed out; do not repeat a mutating request blindly") from exc
            if value.get("id") == expected and "method" not in value:
                require("result" in value and "error" not in value, method + " failed; check local protocol")
                return value["result"]
        raise ValueError(method + " timed out")

    def wait_turn(self, thread, turn):
        key = (thread, turn)
        while key not in self.finished:
            try:
                self.event(30)
            except queue.Empty:
                print("WAIT " + thread + " " + turn, flush=True)
        return self.finished[key]

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)


def pages(client, method, params):
    seen = set()
    while True:
        result = client.request(method, params)
        yield from result["data"]
        cursor = result.get("nextCursor")
        if not cursor:
            return
        require(cursor not in seen, "Repeated pagination cursor")
        seen.add(cursor)
        params = dict(params, cursor=cursor)


def project_id(client, root):
    matches = {p["id"] for p in pages(client, "project/list", {"limit": 100})
               if any(Path(r["path"]).resolve() == root for r in p["roots"])}
    require(len(matches) == 1, "No unique registered desktop project matches root")
    return matches.pop()


def binding(thread, row, project, root):
    require(thread.get("id") == row["thread_id"] and thread.get("name") == row["title"], "Wrong thread/title")
    require(thread.get("projectId") == project and Path(thread.get("cwd", "")).resolve() == root,
            "Wrong desktop project/root")
    require(thread.get("ephemeral") is False and thread.get("source") == "vscode", "Not a durable desktop chat")


def project_rows(client, project, root, title):
    return list(pages(client, "thread/list", {"projectId": project, "cwd": str(root),
                     "searchTerm": title, "useStateDbOnly": True, "limit": 100}))


def verify_list(client, row, project, root):
    for _ in range(40):
        matches = [x for x in project_rows(client, project, root, row["title"]) if x["id"] == row["thread_id"]]
        if matches:
            binding(matches[0], row, project, root)
            return
        time.sleep(0.5)
    raise ValueError("Original chat not returned by desktop project list; stop subsequent dispatch")


def refresh_sidebar(client, row, project):
    require(os.name == "nt", "Desktop fallback sidebar refresh requires Windows; use native tools on other hosts")
    name = client.request("project/read", {"projectId": project})["project"]["name"]
    require(isinstance(name, str) and name.strip(), "Desktop project name is missing")
    helper = Path(__file__).with_name("refresh_desktop_project.ps1")
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(helper),
                                 "-ProjectName", name, "-ChatTitle", row["title"]],
                                capture_output=True, timeout=25,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        visible = result.returncode == 0 and result.stdout.strip() == b"SIDEBAR_TITLE_VISIBLE"
    except (OSError, subprocess.TimeoutExpired):
        visible = False
    row.update(project_name=name, sidebar_title_visible=visible, sidebar_checked_at=now())
    return visible


def prepare_row(row):
    if row:
        require(row.get("thread_id") and row.get("turn_id"),
                "Uncertain create/send receipt; inspect original project/chat, do not auto-create or resend")


def completion_signal(thread, turn_id, batch_id):
    turns = thread.get("turns", [])
    require(turns and turns[-1]["id"] == turn_id, "Original chat has a newer or missing turn")
    turn = turns[-1]
    require(turn.get("status") == "completed", "Latest turn is not completed")
    messages = [i for i in turn.get("items", []) if i.get("type") == "agentMessage"]
    finals = [i for i in messages if i.get("phase") == "final_answer"]
    require(finals or messages, "Missing final assistant message")
    text = (finals or messages)[-1].get("text", "")
    signals = re.findall(r"\bBATCH_DONE\s+(B\d+)\s+(PASS|BLOCKED)\b", text)
    require(signals and set(signals) == {(batch_id, "PASS")}, "Missing, mismatched or BLOCKED completion signal")


def adopt_turn(client, root, project, batch, row, turn_id):
    prepare_row(row)
    require(row.get("status") != "PASS", "Cannot adopt a new turn for an accepted batch")
    thread = client.request("thread/read", {"threadId": row["thread_id"], "includeTurns": True})["thread"]
    binding(thread, row, project, root)
    turns = thread.get("turns", [])
    old = next((t for t in turns if t["id"] == row["turn_id"]), None)
    require(old and old.get("status") in {"completed", "interrupted", "failed"}, "Original turn is still running or missing")
    require(turns[-1]["id"] == turn_id and turn_id != row["turn_id"], "Adopt only the explicit latest new turn")
    row.setdefault("turn_history", []).append({k: row[k] for k in
        ("turn_id", "turn_status", "started_at", "completed_at", "status") if k in row})
    row.update(turn_id=turn_id, status="RUNNING", adopted_at=now())
    row.pop("completed_at", None)
    row.pop("turn_status", None)


def verify_passed(root, plan, rows, client=None, project=None):
    for batch in plan["batches"]:
        row = rows.get(batch["id"], {})
        if row.get("status") != "PASS":
            continue
        require(acceptance(root, batch) == row["hashes"], "Accepted files changed: " + batch["id"])
        if client is not None:
            thread = client.request("thread/read", {"threadId": row["thread_id"], "includeTurns": True})["thread"]
            binding(thread, row, project, root)
            completion_signal(thread, row["turn_id"], batch["id"])
            if row.get("sidebar_title_visible") is not True:
                require(refresh_sidebar(client, row, project), "Accepted chat is not visible in the target sidebar project")


def execute(client, root, project, batch, row, checkpoint):
    prepare_row(row)
    if not row:
        title = batch["title"] + "｜" + checkpoint.task
        require(not any(x.get("name") == title for x in project_rows(client, project, root, title)),
                "An unrecorded chat already has this title; reconcile before creating")
        row.update(status="CREATING", title=title, create_requested_at=now())
        checkpoint()
        thread = client.request("thread/start", {"cwd": str(root), "projectId": project,
                                "sandbox": "workspace-write", "ephemeral": False})["thread"]
        row.update(thread_id=thread["id"], project_id=project, created_at=now(), status="CREATED")
        checkpoint()
        client.request("thread/name/set", {"threadId": row["thread_id"], "name": title})
        actual = client.request("thread/read", {"threadId": row["thread_id"], "includeTurns": False})["thread"]
        binding(actual, row, project, root)
        # Save intent first: a lost response must never cause automatic input replay.
        row["status"] = "SENDING"
        checkpoint()
        prompt = local(root, batch["prompt"]).read_text(encoding="utf-8-sig")
        turn = client.request("turn/start", {"threadId": row["thread_id"],
                              "input": [{"type": "text", "text": prompt}]})["turn"]
        row.update(turn_id=turn["id"], status="RUNNING", started_at=now())
        checkpoint()
    else:
        resumed = client.request("thread/resume", {"threadId": row["thread_id"]})["thread"]
        binding(resumed, row, project, root)
        turns = resumed.get("turns", [])
        if not any(t["id"] == row["turn_id"] for t in turns):
            resumed = client.request("thread/read", {"threadId": row["thread_id"], "includeTurns": True})["thread"]
            binding(resumed, row, project, root)
            turns = resumed.get("turns", [])
        require(turns and turns[-1]["id"] == row["turn_id"],
                "Original chat has a newer user turn; reconcile its receipt before resuming")
        for turn in turns:
            if turn["id"] == row["turn_id"] and turn.get("status") != "inProgress":
                client.finished[row["thread_id"], row["turn_id"]] = turn
    verify_list(client, row, project, root)
    row["project_list_verified"] = True
    refresh_sidebar(client, row, project)
    checkpoint()
    print("CHAT " + batch["id"] + " " + row["thread_id"], flush=True)
    completed = client.wait_turn(row["thread_id"], row["turn_id"])
    row.update(turn_status=completed["status"], completed_at=row.get("completed_at", now()))
    checkpoint()
    actual = client.request("thread/read", {"threadId": row["thread_id"], "includeTurns": True})["thread"]
    binding(actual, row, project, root)
    transcript = {"thread_id": row["thread_id"], "title": row["title"], "project_id": project,
                  "cwd": str(root), "turns": [
                      {"id": t["id"], "status": t["status"], "messages": [
                          i for i in t.get("items", []) if i.get("type") == "agentMessage"]}
                      for t in actual.get("turns", [])]}
    save(local(root, batch["acceptance"]).parent / "transcript.json", transcript)
    require(completed["status"] == "completed", "Turn did not finish normally")
    completion_signal(actual, row["turn_id"], batch["id"])
    if row.get("sidebar_title_visible") is not True:
        require(refresh_sidebar(client, row, project), "Chat completed but sidebar refresh failed; stop subsequent dispatch")


def run(root, path, plan, inputs, continue_after=None, client_factory=Client, adopt=None):
    state_path = path.parent / "state.json"
    with exclusive(path.parent / "dispatch.lock"):
        state = read_json(state_path) if state_path.exists() else {"inputs": inputs, "batches": {}}
        require(state["inputs"] == inputs, "Plan or prompts changed; reconcile before resuming")
        require(not adopt or state.get("status") == "BLOCKED", "Adoption requires an existing BLOCKED run")
        rows = state["batches"]
        ids = [r["thread_id"] for r in rows.values() if r.get("thread_id")]
        require(len(ids) == len(set(ids)), "Duplicate thread IDs in receipts")
        client = None

        def checkpoint():
            state["updated_at"] = now()
            save(state_path, state)
        checkpoint.task = plan["task"]
        try:
            for batch in plan["batches"]:
                require(load_plan(root, path)[1] == inputs, "Plan/prompts changed during run")
                verify_passed(root, plan, rows, client, state.get("project_id"))
                row = rows.setdefault(batch["id"], {})
                if row.get("status") == "PASS":
                    require(acceptance(root, batch) == row["hashes"], "Accepted files changed")
                else:
                    require(not local(root, batch["acceptance"]).exists() or row.get("thread_id"),
                            "Unregistered acceptance exists; reconcile provenance first")
                    prepare_row(row)
                    if client is None:
                        client = client_factory(root)
                        project = project_id(client, root)
                        require(not state.get("project_id") or state["project_id"] == project, "Desktop project identity changed")
                        state["project_id"] = project
                    verify_passed(root, plan, rows, client, project)
                    if adopt:
                        require(adopt[0] == batch["id"], "Adopt only the first unaccepted batch")
                        adopt_turn(client, root, project, batch, row, adopt[1])
                        checkpoint()
                        adopt = None
                    state["status"] = "RUNNING"
                    execute(client, root, project, batch, row, checkpoint)
                    require(load_plan(root, path)[1] == inputs, "Plan/prompts changed during batch")
                    row.update(hashes=acceptance(root, batch), status="PASS", accepted_at=now())
                    checkpoint()
                    print("PASS " + batch["id"], flush=True)
                if batch.get("pause_after") and not row.get("pause_released"):
                    if continue_after == batch["id"]:
                        row["pause_released"] = True
                        checkpoint()
                    else:
                        state["status"] = "PAUSED"
                        state["paused_after"] = batch["id"]
                        checkpoint()
                        return state
            require(adopt is None, "Requested turn adoption was not applied")
            verify_passed(root, plan, rows, client, state.get("project_id"))
            state.update(status="COMPLETE", finished_at=now())
            state.pop("error", None)
            checkpoint()
            return state
        except BaseException as exc:
            state.update(status="BLOCKED", error=str(exc))
            checkpoint()
            raise
        finally:
            if client is not None:
                client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--plan", required=True, help="Project-relative run.json")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--status", action="store_true")
    parser.add_argument("--continue-after", help="Release an explicitly authorized pause")
    parser.add_argument("--adopt-turn", help="Explicitly adopt Bxx=turnId in the same blocked chat; never sends input")
    args = parser.parse_args()
    require(not args.continue_after or args.run, "--continue-after requires --run")
    require(not args.adopt_turn or args.run, "--adopt-turn requires --run")
    adopt = None
    if args.adopt_turn:
        require("=" in args.adopt_turn, "Use --adopt-turn Bxx=turnId")
        adopt = tuple(args.adopt_turn.split("=", 1))
        require(all(adopt), "Use --adopt-turn Bxx=turnId")
    root = Path(args.root).resolve()
    path = local(root, args.plan)
    plan, inputs = load_plan(root, path)
    if args.status:
        print(json.dumps(read_json(path.parent / "state.json"), ensure_ascii=False, indent=2))
    elif args.run:
        state = run(root, path, plan, inputs, args.continue_after, adopt=adopt)
        print(state["status"], flush=True)
    else:
        for batch in plan["batches"]:
            print(batch["title"] + "｜" + plan["task"])


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError) as error:
        sys.exit("Dispatch stopped: " + str(error))
