import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("audit_hook", Path(__file__).with_name("audit_hook.py"))
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.policy = dict(audit.POLICY)
        for name, value in (("ROOT", self.root), ("STATE_DIR", self.root / "logs" / "copilot-audit" / ".state"),
                            ("POLICY", self.policy)):
            mocked = patch.object(audit, name, value)
            mocked.start()
            self.addCleanup(mocked.stop)

    def send(self, event, **fields):
        payload = {"sessionId": "guard-test", **fields}
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            audit.handle(event, payload, "vscode" if "hook_event_name" in payload else "copilot")
        return output.getvalue()

    def draft(self, name="story", status="draft", jira_key=None, drafts_dir=".jira/drafts"):
        d = self.root / drafts_dir / name
        d.mkdir(parents=True, exist_ok=True)
        text = f"status: {status}\n"
        if jira_key:
            text += f"jira_key: {jira_key}\n"
        path = d / "story.md"
        path.write_text(text, encoding="utf-8")
        return path

    def pre(self, tool_name, **args):
        raw = self.send("preToolUse", toolName=tool_name, toolArgs=args)
        return json.loads(raw)["permissionDecision"]

    def test_no_files_are_written_to_disk(self):
        self.send("userPromptSubmitted", prompt="approved")
        self.send("preToolUse", toolName="read_file", toolArgs={"path": "README.md"})
        self.assertTrue(any(audit.STATE_DIR.glob("*.json")))   # the one tiny approval-state file
        self.assertFalse((self.root / "logs" / "copilot-audit" / "events").exists())
        self.assertFalse((self.root / "logs" / "copilot-audit" / "sessions").exists())
        self.assertFalse((self.root / "logs" / "copilot-audit" / "traces").exists())

    def test_protected_env_read_and_write_denied(self):
        self.assertEqual(self.pre("read_file", path=".env"), "deny")
        self.assertEqual(self.pre("replace_string_in_file", path=".env"), "deny")
        self.assertEqual(self.pre("read_file", path=".env.example"), "allow")

    def test_protected_hooks_write_denied(self):
        self.assertEqual(self.pre("create_file", path=".github/hooks/audit-policy.json"), "deny")

    def test_deny_commands_block_env_dump_and_force_push(self):
        self.assertEqual(self.pre("run_in_terminal", command="type .env"), "deny")
        self.assertEqual(self.pre("run_in_terminal", command="printenv"), "deny")
        self.assertEqual(self.pre("run_in_terminal", command="git push --force"), "deny")

    def test_ask_commands_request_confirmation(self):
        self.assertEqual(self.pre("run_in_terminal", command="git push"), "ask")

    def test_jira_0_approval_gate(self):
        self.draft()
        # no approval yet -> denied
        self.assertEqual(self.pre("replace_string_in_file", path=".jira/drafts/story/story.md",
                                  new_str="status: approved\n"), "deny")
        self.send("userPromptSubmitted", prompt="not approved, please change the title")
        self.assertEqual(self.pre("replace_string_in_file", path=".jira/drafts/story/story.md",
                                  new_str="status: approved\n"), "deny")
        self.send("userPromptSubmitted", prompt="approved")
        self.assertEqual(self.pre("replace_string_in_file", path=".jira/drafts/story/story.md",
                                  new_str="status: approved\n"), "allow")

    def test_jira_1_create_gate(self):
        path = self.draft(status="draft")
        cmd = f'python jira_create.py create "{path}" --confirm-project DATA --confirm-type Story'
        self.assertEqual(self.pre("run_in_terminal", command=cmd), "deny")   # not approved yet

        path = self.draft(status="approved")
        cmd = f'python jira_create.py create "{path}"'
        self.assertEqual(self.pre("run_in_terminal", command=cmd), "deny")   # missing confirm flags

        cmd = f'python jira_create.py create "{path}" --confirm-project DATA --confirm-type Story'
        self.assertEqual(self.pre("run_in_terminal", command=cmd), "ask")    # approved + confirmed -> ask

        path = self.draft(status="approved", jira_key="DATA-301")
        cmd = f'python jira_create.py create "{path}" --confirm-project DATA --confirm-type Story'
        self.assertEqual(self.pre("run_in_terminal", command=cmd), "deny")   # already created

    def test_unrelated_tools_are_allowed(self):
        self.assertEqual(self.pre("grep_search", query="TODO"), "allow")
        self.assertEqual(self.pre("read_file", path="README.md"), "allow")

    def test_copilot_and_vscode_payload_styles(self):
        out = json.loads(self.send("preToolUse", tool_name="view", tool_input={"path": ".env"}))
        self.assertEqual(out["permissionDecision"], "deny")
        out = json.loads(self.send("preToolUse", hook_event_name="PreToolUse", tool_name="view",
                                   tool_input={"path": ".env"}))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_policy_failure_fails_open(self):
        self.policy["deny_commands"] = [{"id": "BAD", "pattern": "(unterminated"}]
        self.assertEqual(self.pre("run_in_terminal", command="anything"), "allow")

    def test_hook_registration_is_minimal(self):
        config = json.loads((audit.HOOK_DIR / "copilot-audit.json").read_text(encoding="utf-8"))
        self.assertEqual(set(config["hooks"]), {"userPromptSubmitted", "preToolUse"})
        for name, entries in config["hooks"].items():
            self.assertIn(f"audit_hook.py {name}", entries[0]["powershell"])
            self.assertIn(f"audit_hook.py {name}", entries[0]["bash"])


if __name__ == "__main__":
    unittest.main()

