"""Offline behavior checks: no real chats, models, credentials or desktop access."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import desktop_batches as dispatch


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.real_refresh = dispatch.refresh_sidebar

        def refreshed(client, row, project):
            row["sidebar_title_visible"] = True
            return True
        refresh = patch.object(dispatch, "refresh_sidebar", side_effect=refreshed)
        refresh.start()
        self.addCleanup(refresh.stop)
        self.temp = tempfile.TemporaryDirectory(prefix="batch-test-", dir=str(Path.cwd()))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "PLAN.md").write_text("test plan", encoding="utf-8")
        self.plan = {"task": "test", "plan_document": "PLAN.md", "batches": []}
        for batch_id in ("B01", "B02"):
            folder = self.root / batch_id
            folder.mkdir()
            (folder / "prompt.md").write_text("question", encoding="utf-8")
            self.plan["batches"].append({"id": batch_id, "title": batch_id + " question",
                "prompt": batch_id + "/prompt.md", "acceptance": batch_id + "/acceptance.json",
                "criteria": [batch_id + ".1"], "review_roles": []})
        self.path = self.root / "run.json"
        dispatch.save(self.path, self.plan)

    def receipt(self, batch, reviews=False):
        prefix = batch["id"] + "/"
        result = self.root / prefix / "result.json"
        dispatch.save(result, {"answer": 5})
        (self.root / prefix / "handoff.md").write_text("verified", encoding="utf-8")
        dispatch.save(self.root / batch["acceptance"], {"batch": batch["id"], "status": "PASS",
            "checks": [{"criterion": batch["criteria"][0], "passed": True,
                        "evidence": prefix + "result.json", "sha256": dispatch.digest(result)}],
            "handoff": prefix + "handoff.md"})
        if reviews:
            dispatch.save(self.root / prefix / "review.json", {"batch": batch["id"], "reviewers": [
                {"id": "agent-" + role, "role": role, "status": "PASS", "findings": "checked",
                 "disposition": "no issues", "unresolved": False} for role in batch["review_roles"]]})

    def loaded(self):
        dispatch.save(self.path, self.plan)
        return dispatch.load_plan(self.root, self.path)

    def test_tampered_evidence_rejected(self):
        batch = self.plan["batches"][0]
        self.receipt(batch)
        dispatch.acceptance(self.root, batch)
        (self.root / "B01/result.json").write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            dispatch.acceptance(self.root, batch)

    @unittest.skipUnless(dispatch.os.name == "nt", "Windows transient file sharing")
    def test_atomic_save_retries_only_transient_permission_error(self):
        original = dispatch.os.replace
        attempts = []
        def replace(source, target):
            attempts.append(source)
            if len(attempts) == 1:
                raise PermissionError("temporary sharing violation")
            original(source, target)
        with patch.object(dispatch.os, "replace", side_effect=replace):
            dispatch.save(self.root / "saved.json", {"status": "verified"})
        self.assertEqual(len(attempts), 2)
        self.assertEqual(dispatch.read_json(self.root / "saved.json"), {"status": "verified"})

    def test_missing_or_same_reviewer_rejected(self):
        batch = self.plan["batches"][0]
        batch["review_roles"] = ["content", "repro"]
        self.receipt(batch)
        with self.assertRaises(FileNotFoundError):
            dispatch.acceptance(self.root, batch)
        self.receipt(batch, reviews=True)
        dispatch.acceptance(self.root, batch)
        path = self.root / "B01/review.json"
        review = dispatch.read_json(path)
        review["reviewers"][1]["id"] = review["reviewers"][0]["id"]
        dispatch.save(path, review)
        with self.assertRaisesRegex(ValueError, "distinct IDs"):
            dispatch.acceptance(self.root, batch)

    def test_uncertain_receipt_cannot_be_resent(self):
        for row in ({"status": "CREATING"}, {"thread_id": "old", "status": "SENDING"}):
            with self.assertRaisesRegex(ValueError, "Uncertain"):
                dispatch.prepare_row(row)

    def test_path_escape_rejected(self):
        for path in ("../outside.json", "C:/outside.json", "/outside.json"):
            with self.assertRaises(ValueError):
                dispatch.local(self.root, path)

    def test_lock_prevents_duplicate_dispatcher(self):
        with dispatch.exclusive(self.root / "dispatch.lock"):
            with self.assertRaisesRegex(ValueError, "already holds"):
                with dispatch.exclusive(self.root / "dispatch.lock"):
                    pass

    def simulation(self, fail_first=False):
        calls = []
        owner = self

        class FakeClient:
            latest_turn_overrides = {}

            def __init__(self, root):
                pass

            def close(self):
                pass

            def request(self, method, params):
                owner.assertEqual(method, "thread/read")
                rows = dispatch.read_json(owner.root / "state.json")["batches"]
                batch_id, row = next((b, r) for b, r in rows.items() if r.get("thread_id") == params["threadId"])
                turn = self.latest_turn_overrides.get(batch_id, {"id": row["turn_id"], "status": "completed",
                    "items": [{"type": "agentMessage", "phase": "final_answer",
                               "text": "BATCH_DONE " + batch_id + " PASS"}]})
                return {"thread": {"id": row["thread_id"], "name": row["title"], "cwd": str(owner.root),
                                   "projectId": "project", "source": "vscode", "ephemeral": False, "turns": [turn]}}

        def execute(client, root, project, batch, row, checkpoint):
            if calls:
                previous = dispatch.read_json(root / "state.json")["batches"][calls[-1]]
                owner.assertEqual(previous["status"], "PASS")
                owner.assertIn("accepted_at", previous)
            calls.append(batch["id"])
            row.update(thread_id="thread-" + batch["id"], turn_id="turn-" + batch["id"],
                       turn_status="completed", title=batch["title"] + "｜test", sidebar_title_visible=True)
            if not (fail_first and batch["id"] == "B01"):
                owner.receipt(batch)
        return calls, FakeClient, execute

    def test_failed_first_batch_never_dispatches_second(self):
        plan, inputs = self.loaded()
        calls, factory, execute = self.simulation(fail_first=True)
        with patch.object(dispatch, "project_id", return_value="project"), patch.object(dispatch, "execute", execute):
            with self.assertRaises(FileNotFoundError):
                dispatch.run(self.root, self.path, plan, inputs, client_factory=factory)
        self.assertEqual(calls, ["B01"])
        self.assertEqual(dispatch.read_json(self.root / "state.json")["status"], "BLOCKED")

    def test_serial_pass_and_rerun_do_not_create_chats(self):
        plan, inputs = self.loaded()
        calls, factory, execute = self.simulation()
        with patch.object(dispatch, "project_id", return_value="project"), patch.object(dispatch, "execute", execute):
            result = dispatch.run(self.root, self.path, plan, inputs, client_factory=factory)
        self.assertEqual(calls, ["B01", "B02"])
        self.assertEqual(result["status"], "COMPLETE")
        with patch.object(dispatch, "Client", side_effect=AssertionError("must not start server")):
            result = dispatch.run(self.root, self.path, plan, inputs, client_factory=dispatch.Client)
        self.assertEqual(result["status"], "COMPLETE")

    def test_pause_requires_explicit_release(self):
        self.plan["batches"][0]["pause_after"] = True
        plan, inputs = self.loaded()
        calls, factory, execute = self.simulation()
        with patch.object(dispatch, "project_id", return_value="project"), patch.object(dispatch, "execute", execute):
            state = dispatch.run(self.root, self.path, plan, inputs, client_factory=factory)
            self.assertEqual(state["status"], "PAUSED")
            self.assertEqual(calls, ["B01"])
            dispatch.run(self.root, self.path, plan, inputs, continue_after="B01", client_factory=factory)
        self.assertEqual(calls, ["B01", "B02"])

    def test_plan_mutation_prevents_resume(self):
        plan, inputs = self.loaded()
        dispatch.save(self.root / "state.json", {"inputs": inputs, "batches": {}})
        (self.root / "B01/prompt.md").write_text("changed", encoding="utf-8")
        changed_plan, changed_inputs = dispatch.load_plan(self.root, self.path)
        with self.assertRaisesRegex(ValueError, "changed"):
            dispatch.run(self.root, self.path, changed_plan, changed_inputs)

    def test_binding_requires_actual_project(self):
        row = {"thread_id": "one", "title": "B01 test"}
        thread = {"id": "one", "name": "B01 test", "cwd": str(self.root),
                  "projectId": "wrong", "source": "vscode", "ephemeral": False}
        with self.assertRaisesRegex(ValueError, "project"):
            dispatch.binding(thread, row, "expected", self.root)

    def terminal_client(self, text="BATCH_DONE B01 PASS", new_turn=False):
        root = self.root

        class TerminalClient:
            def __init__(self):
                self.methods = []
                self.finished = {}
                old = {"id": "old", "status": "interrupted", "items": []}
                latest = {"id": "new" if new_turn else "old", "status": "completed",
                          "items": [{"type": "agentMessage", "phase": "final_answer", "text": text}]}
                self.thread = {"id": "thread", "name": "B01 question｜test", "cwd": str(root),
                    "projectId": "project", "source": "vscode", "ephemeral": False,
                    "turns": [old, latest] if new_turn else [latest]}

            def request(self, method, params):
                self.methods.append(method)
                if method == "thread/list":
                    return {"data": [self.thread], "nextCursor": None}
                if method in {"thread/resume", "thread/read"}:
                    return {"thread": self.thread}
                raise AssertionError("Unexpected mutation: " + method)

            def wait_turn(self, thread, turn):
                return self.thread["turns"][-1]
        return TerminalClient()

    def test_actual_execute_rejects_blocked_final_with_pass_files(self):
        batch = self.plan["batches"][0]
        self.receipt(batch)
        row = {"thread_id": "thread", "turn_id": "old", "title": "B01 question｜test"}
        client = self.terminal_client("BATCH_DONE B01 BLOCKED")
        with self.assertRaisesRegex(ValueError, "completion signal"):
            dispatch.execute(client, self.root, "project", batch, row, lambda: None)

    def test_final_signal_missing_conflicting_or_wrong_batch_rejected(self):
        for text in ("done", "BATCH_DONE B02 PASS", "BATCH_DONE B01 PASS BATCH_DONE B01 BLOCKED"):
            with self.assertRaisesRegex(ValueError, "completion signal"):
                dispatch.completion_signal(self.terminal_client(text).thread, "old", "B01")

    def test_resume_completed_original_turn_without_sending_input(self):
        row = {"thread_id": "thread", "turn_id": "old", "title": "B01 question｜test"}
        client = self.terminal_client()
        self.assertEqual(dispatch.execute(client, self.root, "project", self.plan["batches"][0], row, lambda: None), "AWAITING_PRIMARY_REVIEW")
        self.assertNotIn("turn/start", client.methods)
        self.assertNotIn("thread/start", client.methods)

    def test_explicit_adoption_preserves_old_turn_without_new_chat(self):
        row = {"thread_id": "thread", "turn_id": "old", "title": "B01 question｜test", "status": "BLOCKED"}
        client = self.terminal_client(new_turn=True)
        batch = self.plan["batches"][0]
        dispatch.adopt_turn(client, self.root, "project", batch, row, "new")
        dispatch.execute(client, self.root, "project", batch, row, lambda: None)
        self.assertEqual(row["turn_id"], "new")
        self.assertEqual(row["turn_history"][0]["turn_id"], "old")
        self.assertNotIn("turn/start", client.methods)
        self.assertNotIn("thread/start", client.methods)

    def test_running_original_turn_cannot_be_adopted(self):
        row = {"thread_id": "thread", "turn_id": "old", "title": "B01 question｜test", "status": "BLOCKED"}
        client = self.terminal_client(new_turn=True)
        client.thread["turns"][0]["status"] = "inProgress"
        with self.assertRaisesRegex(ValueError, "still running"):
            dispatch.adopt_turn(client, self.root, "project", self.plan["batches"][0], row, "new")

    def test_upstream_changed_during_later_batch_blocks_complete(self):
        plan, inputs = self.loaded()
        calls, factory, execute = self.simulation()

        def mutate(client, root, project, batch, row, checkpoint):
            execute(client, root, project, batch, row, checkpoint)
            if batch["id"] == "B02":
                (root / "B01/handoff.md").write_text("changed upstream", encoding="utf-8")

        with patch.object(dispatch, "project_id", return_value="project"), patch.object(dispatch, "execute", mutate):
            with self.assertRaisesRegex(ValueError, "Accepted files changed"):
                dispatch.run(self.root, self.path, plan, inputs, client_factory=factory)
        self.assertEqual(dispatch.read_json(self.root / "state.json")["status"], "BLOCKED")

    def test_new_upstream_turn_during_pause_blocks_next_chat(self):
        self.plan["batches"][0]["pause_after"] = True
        plan, inputs = self.loaded()
        calls, factory, execute = self.simulation()
        with patch.object(dispatch, "project_id", return_value="project"), patch.object(dispatch, "execute", execute):
            dispatch.run(self.root, self.path, plan, inputs, client_factory=factory)
            factory.latest_turn_overrides["B01"] = {"id": "new-user-turn", "status": "inProgress", "items": []}
            with self.assertRaisesRegex(ValueError, "newer or missing turn"):
                dispatch.run(self.root, self.path, plan, inputs, continue_after="B01", client_factory=factory)
        self.assertEqual(calls, ["B01"])

    def test_cold_interrupted_is_observation_without_resume_or_replay(self):
        row = {"thread_id": "thread", "turn_id": "old", "title": "B01 question｜test", "status": "RUNNING"}
        client = self.terminal_client()
        client.thread["turns"][-1]["status"] = "interrupted"
        result = dispatch.execute(client, self.root, "project", self.plan["batches"][0], row, lambda: None)
        self.assertEqual(result, "RUNNING")
        self.assertTrue(set(client.methods) <= {"thread/read", "thread/list"})

    def test_completed_needs_exact_primary_gate(self):
        batch = self.plan["batches"][0]
        self.receipt(batch)
        row = {"thread_id": "thread", "turn_id": "old", "title": "B01 question｜test"}
        client = self.terminal_client()
        self.assertEqual(dispatch.execute(client, self.root, "project", batch, row, lambda: None), "AWAITING_PRIMARY_REVIEW")
        gate = dict(batch="B01", thread_id="thread", turn_id="wrong", status="PASS", hashes=dispatch.acceptance(self.root, batch))
        dispatch.save(self.root / "B01/primary_gate.json", gate)
        with self.assertRaisesRegex(ValueError, "Primary gate"):
            dispatch.execute(client, self.root, "project", batch, row, lambda: None)
        gate["turn_id"] = "old"
        dispatch.save(self.root / "B01/primary_gate.json", gate)
        self.assertIsNone(dispatch.execute(client, self.root, "project", batch, row, lambda: None))

    def test_chat_defaults_and_batch_override(self):
        self.plan["chat_defaults"] = {"model": "custom-model", "reasoning_effort": "high"}
        self.plan["batches"][1]["chat"] = {"reasoning_effort": "ultra"}
        self.loaded()
        self.assertEqual(dispatch.chat_settings(self.plan, self.plan["batches"][1]),
                         {"model": "custom-model", "reasoning_effort": "ultra"})
        self.plan["batches"][0]["chat"] = {"reasoning_effort": ""}
        with self.assertRaisesRegex(ValueError, "Invalid chat"):
            self.loaded()

    def test_queue_once_with_model_receipt_and_desktop_attach(self):
        owner = self
        class QueueClient:
            def __init__(self):
                self.methods = []
                self.thread = None
            def request(self, method, params):
                self.methods.append(method)
                if method == "thread/list":
                    return {"data": [self.thread] if self.thread else [], "nextCursor": None}
                if method == "thread/start":
                    owner.assertEqual(params["model"], "chosen")
                    owner.assertEqual(params["config"], {"model_reasoning_effort": "high"})
                    self.thread = dict(id="created", name="B01 question｜test", cwd=str(owner.root),
                                       projectId="project", source="vscode", ephemeral=False, turns=[])
                    return dict(thread=self.thread, model="chosen", reasoningEffort="high")
                if method == "thread/name/set": return {}
                if method == "thread/read": return {"thread": self.thread}
                if method == "thread/queue/add": return {"queuedSubmission": {"id": "queue"}}
                if method == "thread/queue/list": return {"data": []}
                raise AssertionError("Unexpected mutation: " + method)
        def checkpoint(): pass
        checkpoint.task = "test"
        checkpoint.chat = {"model": "chosen", "reasoning_effort": "high"}
        client, row = QueueClient(), {}
        batch = self.plan["batches"][0]
        self.assertEqual(dispatch.execute(client, self.root, "project", batch, row, checkpoint), "WAITING_FOR_DESKTOP")
        dispatch.execute(client, self.root, "project", batch, row, checkpoint)
        client.thread["turns"] = [{"id": "desktop", "status": "interrupted", "items": [{"type": "agentMessage", "text": "working"}]}]
        self.assertEqual(dispatch.execute(client, self.root, "project", batch, row, checkpoint), "RUNNING")
        self.assertEqual(row["turn_id"], "desktop")
        self.assertEqual(client.methods.count("thread/start"), 1)
        self.assertEqual(client.methods.count("thread/queue/add"), 1)
        self.assertNotIn("turn/start", client.methods)
        self.assertNotIn("thread/resume", client.methods)
        mismatch, failed_row = QueueClient(), {}
        original_request = mismatch.request
        def wrong_effort(method, params):
            response = original_request(method, params)
            if method == "thread/start":
                response["reasoningEffort"] = "low"
            return response
        mismatch.request = wrong_effort
        with self.assertRaisesRegex(ValueError, "not confirmed"):
            dispatch.execute(mismatch, self.root, "project", batch, failed_row, checkpoint)
        self.assertEqual(failed_row["thread_id"], "created")
        self.assertNotIn("thread/queue/add", mismatch.methods)
        with self.assertRaisesRegex(ValueError, "Uncertain"):
            dispatch.execute(mismatch, self.root, "project", batch, failed_row, checkpoint)
        self.assertEqual(mismatch.methods.count("thread/start"), 1)

    @unittest.skipUnless(dispatch.os.name == "nt", "Windows UI Automation adapter")
    def test_sidebar_refresh_targets_project_and_full_title(self):
        client = Mock()
        client.request.return_value = {"project": {"name": "the project"}}
        row = {"thread_id": "existing", "title": "B01 full title"}
        with patch.object(dispatch.subprocess, "run", return_value=Mock(returncode=0, stdout=b"SIDEBAR_TITLE_VISIBLE\r\n")) as invoke:
            self.assertTrue(self.real_refresh(client, row, "project"))
        client.request.assert_called_once_with("project/read", {"projectId": "project"})
        args = invoke.call_args[0][0]
        self.assertEqual(args[args.index("-ProjectName") + 1], "the project")
        self.assertEqual(args[args.index("-ChatTitle") + 1], row["title"])
        self.assertEqual(row["thread_id"], "existing")
        self.assertTrue(row["sidebar_title_visible"])

    def test_failed_sidebar_refresh_never_dispatches_next_chat(self):
        plan, inputs = self.loaded()
        calls, factory, execute = self.simulation()

        def hidden(client, root, project, batch, row, checkpoint):
            execute(client, root, project, batch, row, checkpoint)
            row["sidebar_title_visible"] = False
        with patch.object(dispatch, "project_id", return_value="project"), patch.object(dispatch, "execute", hidden), \
                patch.object(dispatch, "refresh_sidebar", return_value=False):
            with self.assertRaisesRegex(ValueError, "not visible"):
                dispatch.run(self.root, self.path, plan, inputs, client_factory=factory)
        self.assertEqual(calls, ["B01"])
        self.assertEqual(dispatch.read_json(self.root / "state.json")["batches"]["B01"]["thread_id"], "thread-B01")


if __name__ == "__main__":
    unittest.main(verbosity=2)
