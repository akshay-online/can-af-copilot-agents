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


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.policy = dict(audit.POLICY)
        for name, value in (("ROOT", self.root), ("LOG_DIR", self.root / "logs"),
                            ("POLICY", self.policy)):
            mocked = patch.object(audit, name, value)
            mocked.start()
            self.addCleanup(mocked.stop)
        for name, value in (("identity", {"user": "test", "host": "test", "repo": "test"}),
                            ("project_checks", []), ("notify", None)):
            mocked = patch.object(audit, name, return_value=value)
            mocked.start()
            self.addCleanup(mocked.stop)

    def send(self, event, **fields):
        payload = {"sessionId": "audit-test", **fields}
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            audit.handle(event, payload)
        return output.getvalue()

    def records(self):
        return [json.loads(line) for path in (audit.LOG_DIR / "events").glob("*.jsonl")
                for line in path.read_text(encoding="utf-8").splitlines()
                if json.loads(line).get("event") != "sessionReport"]

    def transcript(self, *records):
        path = self.root / "transcript.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        return path

    def test_long_prompt_and_tool_evidence_are_not_excerpted(self):
        long_text = "evidence " * 1200
        self.send("userPromptSubmitted", prompt=long_text)
        self.send("preToolUse", toolName="edit", toolUseId="call-1",
                  toolArgs={"path": "story.md", "content": long_text, "password": "do-not-log"})
        self.send("postToolUse", toolName="edit", toolUseId="call-1",
                  toolArgs={"path": "story.md", "content": long_text, "password": "do-not-log"},
                  toolResult={"resultType": "success", "textResultForLlm": long_text})
        records = self.records()
        self.assertEqual(records[0]["prompt"], long_text)
        self.assertEqual(records[1]["tool_arguments"]["content"], long_text)
        self.assertEqual(records[1]["tool_arguments"]["password"], "***")
        self.assertEqual(records[2]["tool_result"]["textResultForLlm"], long_text)
        self.assertIn("duration_ms", records[2])
        self.assertEqual([r["sequence"] for r in records], [1, 2, 3])
        self.assertEqual(records[2]["prompt_index"], 1)

    def test_snake_case_failure_and_tool_call_correlation(self):
        self.send("preToolUse", tool_name="powershell", tool_use_id="c1",
                  tool_input={"command": "python check.py"})
        self.send("postToolUseFailure", tool_name="powershell", tool_use_id="c1",
                  tool_input={"command": "python check.py"}, error="check failed")
        failed = self.records()[-1]
        self.assertEqual(failed["result"], "failure")
        self.assertIn("duration_ms", failed)
        self.assertEqual(audit.load_state("audit-test")["tools"]["powershell"]["failed"], 1)
        rec, _ = audit.normalise("postToolUse", {
            "tool_name": "read", "tool_result": {"result_type": "success", "text_result_for_llm": "visible"}})
        self.assertEqual(rec["result_excerpt"], "visible")

    def test_visible_transcript_and_final_output_without_private_reasoning(self):
        path = self.transcript(
            {"type": "user.message", "data": {"content": "Please write the story"}},
            {"type": "assistant.reasoning", "data": {"content": "PRIVATE_TRACE"}},
            {"type": "assistant.message", "id": "m1", "data": {"content": "Decision summary: use the spec."}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "PRIVATE_TRACE"},
                {"type": "text", "text": "Final output: story.md. Tests passed."}]}})
        self.send("agentStop", transcriptPath=str(path))
        stop = self.records()[-1]
        self.assertEqual(stop["final_output"], "Final output: story.md. Tests passed.")
        self.assertEqual(stop["transcript_capture"]["messages_captured"], 3)
        self.send("sessionEnd", reason="complete")
        end = self.records()[-1]
        self.assertEqual(end["transcript_capture"]["messages_captured"], 0)
        self.assertEqual(end["final_output"], stop["final_output"])
        report = next((audit.LOG_DIR / "sessions").glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("Decision summary: use the spec.", report)
        self.assertIn("Final output: story.md. Tests passed.", report)
        self.assertNotIn("PRIVATE_TRACE", report)
        self.assertFalse(audit.state_path("audit-test").exists())
        self.assertEqual(len(next((audit.LOG_DIR / "traces").glob("*.jsonl")).read_text(
            encoding="utf-8").splitlines()), 2)

    def test_direct_subagent_response_and_summary(self):
        self.send("subagentStop", agentId="child", parentAgentId="parent",
                  response="Final child result", decisionSummary="Selected option B")
        record = self.records()[-1]
        self.assertEqual(record["final_output"], "Final child result")
        self.assertEqual(record["decision_summary"], "Selected option B")
        self.assertEqual(record["agent_id"], "child")
        self.assertEqual(record["parent_agent_id"], "parent")
        self.send("agentStop", hook_event_name="Stop", last_assistant_message="Main result")
        self.assertEqual(self.records()[-1]["final_output"], "Main result")

    def test_capture_gaps_are_explicit(self):
        self.send("agentStop")
        self.assertIn("output_unavailable", self.records()[-1])
        self.assertEqual(self.records()[-1]["transcript_capture"]["status"], "unavailable")
        self.send("agentStop", transcriptPath=str(self.root / "missing.jsonl"))
        self.assertEqual(self.records()[-1]["transcript_capture"]["status"], "error")
        path = self.transcript({"type": "assistant.message", "data": {"content": "too long for budget"}})
        self.policy["max_transcript_bytes_per_event"] = 10
        self.send("agentStop", transcriptPath=str(path))
        partial = self.records()[-1]
        self.assertEqual(partial["transcript_capture"]["status"], "partial")
        self.assertNotIn("final_output", partial)
        self.policy["max_transcript_bytes_per_event"] = 16777216
        self.send("agentStop", transcriptPath=str(path))
        self.assertEqual(self.records()[-1]["final_output"], "too long for budget")

    def test_transcript_append_rotation_and_malformed_records(self):
        path = self.transcript({"type": "assistant.message", "data": {"content": "first"}})
        self.send("agentStop", transcriptPath=str(path))
        with path.open("a", encoding="utf-8") as stream:
            stream.write('invalid JSON\n{"type":"assistant.message","data":{"content":"second"}}\n')
        self.send("agentStop", transcriptPath=str(path))
        self.assertEqual(self.records()[-1]["final_output"], "second")
        self.assertEqual(self.records()[-1]["transcript_capture"]["malformed_records"], 1)
        self.assertEqual(self.records()[-1]["transcript_capture"]["messages_captured"], 1)
        path.write_text('{"role":"assistant","content":"new"}\n', encoding="utf-8")
        self.send("agentStop", transcriptPath=str(path))
        self.assertEqual(self.records()[-1]["final_output"], "new")
        path.write_text('{"role":"assistant","content":"two"}\n', encoding="utf-8")
        self.send("agentStop", transcriptPath=str(path))
        self.assertEqual(self.records()[-1]["final_output"], "two")

    def test_redaction_and_opt_outs(self):
        self.policy["log_prompts"] = False
        self.policy["log_tool_arguments"] = False
        self.policy["log_tool_results"] = False
        self.send("userPromptSubmitted", prompt="OMIT_PROMPT")
        path = self.transcript({"role": "user", "content": "OMIT_PROMPT"},
                               {"role": "assistant", "content": "Visible output"})
        self.send("agentStop", transcriptPath=str(path))
        self.send("postToolUse", toolName="view", toolArgs={"path": "story.md"},
                  toolResult={"textResultForLlm": "normal output"})
        records = self.records()
        self.assertNotIn("OMIT_PROMPT", json.dumps(records))
        self.assertNotIn("tool_arguments", records[-1])
        self.assertNotIn("tool_result", records[-1])
        content = audit.audit_content({"password": "HIDDEN_PASSWORD",
                                       "reasoning": "PRIVATE_TRACE",
                                       "content": [{"type": "reasoning", "text": "PRIVATE_TRACE"},
                                                   {"type": "text", "text": "token=HIDDEN_TOKEN"}]})
        self.assertNotIn("HIDDEN", json.dumps(content))
        self.assertNotIn("PRIVATE_TRACE", json.dumps(content))
        self.assertNotIn("HIDDEN", audit.audit_content('{"password": "HIDDEN"}'))
        self.assertEqual(audit.audit_content({"type": ["string", "null"]}), {"type": ["string", "null"]})
        record, _ = audit.normalise("postToolUse", {
            "toolName": "unknown", "toolArgs": {"reasoning": "PRIVATE_TRACE"},
            "toolResult": {"content": [{"type": "thinking", "text": "PRIVATE_TRACE"},
                                       {"type": "text", "text": "visible"}]}})
        self.assertNotIn("PRIVATE_TRACE", json.dumps(record))
        self.policy["log_assistant_messages"] = False
        self.send("agentStop", transcriptPath=str(path), response="OMIT_RESPONSE")
        self.assertNotIn("OMIT_RESPONSE", json.dumps(self.records()))

    def test_session_context_and_hook_registration(self):
        context = json.loads(self.send("sessionStart"))
        self.assertIn("Decision summary", context["additionalContext"])
        vscode = json.loads(self.send("sessionStart", hook_event_name="SessionStart"))
        self.assertIn("additionalContext", vscode["hookSpecificOutput"])
        child = json.loads(self.send("subagentStart", agentName="review"))
        self.assertIn("Decision summary", child["additionalContext"])
        config = json.loads((audit.HOOK_DIR / "copilot-audit.json").read_text(encoding="utf-8"))
        self.assertEqual(set(config["hooks"]), set(audit.EVENTS))
        for name, entries in config["hooks"].items():
            self.assertIn(f"audit_hook.py {name}", entries[0]["powershell"])
            self.assertIn(f"audit_hook.py {name}", entries[0]["bash"])

    def test_pre_compaction_preserves_visible_evidence(self):
        path = self.transcript({"role": "assistant", "content": "Decision summary before compaction"})
        self.send("preCompact", transcriptPath=str(path), trigger="auto")
        record = self.records()[-1]
        self.assertEqual(record["messages"][0]["content"], "Decision summary before compaction")
        self.assertNotIn("final_output", record)
        path.write_text('{"role":"system","content":"Compacted"}\n', encoding="utf-8")
        self.send("agentStop", transcriptPath=str(path))
        self.assertNotIn("final_output", self.records()[-1])

    def test_structured_errors_and_content_limits(self):
        self.send("postToolUseFailure", toolName="view",
                  error={"message": "failed", "password": "do-not-log"})
        self.assertEqual(self.records()[-1]["error"], {"message": "failed", "password": "***"})
        long_text = "error detail " * 1000
        self.send("errorOccurred", error_context="tool_execution",
                  error={"message": "failed", "stack": long_text})
        self.assertEqual(self.records()[-1]["error_details"]["stack"], long_text)
        self.assertEqual(self.records()[-1]["error_context"], "tool_execution")
        self.policy["max_content_chars"] = 20
        self.assertEqual(audit.audit_content("x" * 25), "x" * 20 + "\u2026[+5 chars]")


if __name__ == "__main__":
    unittest.main()
