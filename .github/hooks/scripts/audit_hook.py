#!/usr/bin/env python3
"""Audit + guard hook for GitHub Copilot agents (Copilot CLI, cloud agent, VS Code agent mode).

Wired to lifecycle events in .github/hooks/copilot-audit.json:
  sessionStart  sessionEnd  userPromptSubmitted  preToolUse  postToolUse  postToolUseFailure
  agentStop  subagentStart  subagentStop  preCompact  errorOccurred

  python audit_hook.py <event>        reads the hook payload (JSON) on stdin
  python audit_hook.py report [--days N] [--user U] [--agent A]
                                      usage summary from the logs

Every event is appended as one JSON line to <log_dir>/events/YYYY-MM-DD.jsonl.
Errors, tool failures and denials also go to <log_dir>/errors/YYYY-MM-DD.jsonl.
Stop and end events write a readable report to <log_dir>/sessions/YYYY-MM-DD_<session>.md.
Redacted evidence is also stored chronologically in <log_dir>/traces/.
preToolUse applies audit-policy.json and returns allow / ask / deny.

Accepts both payload styles: Copilot camelCase (sessionId, toolName, toolArgs, timestamp in ms)
and VS Code (hook_event_name, session_id, tool_name, tool_input, ISO timestamp).
Standard library only. Logging problems never block the agent; a policy deny always wins.
"""
import fnmatch
import getpass
import hashlib
import json
import os
import platform
import re
import shlex
import socket
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parent.parent          # .github/hooks
POLICY_PATH = HOOK_DIR / "audit-policy.json"
EVENTS = ["sessionStart", "sessionEnd", "userPromptSubmitted", "preToolUse", "postToolUse", "postToolUseFailure",
          "agentStop", "subagentStart", "subagentStop", "preCompact", "errorOccurred"]
PASCAL = {"SessionStart": "sessionStart", "SessionEnd": "sessionEnd", "UserPromptSubmit": "userPromptSubmitted",
          "PreToolUse": "preToolUse", "PostToolUse": "postToolUse", "Stop": "agentStop",
          "SubagentStop": "subagentStop", "ErrorOccurred": "errorOccurred",
          "PostToolUseFailure": "postToolUseFailure", "SubagentStart": "subagentStart",
          "PreCompact": "preCompact"}
VERSION = "1.1"


# ------------------------------------------------------------------ basics

def repo_root():
    here = HOOK_DIR
    for d in [here, *here.parents]:
        if (d / ".git").exists():
            return d
    return HOOK_DIR.parent.parent


ROOT = repo_root()


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def load_policy():
    try:
        return json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


POLICY = load_policy()
LOG_DIR = ROOT / POLICY.get("log_dir", "logs/copilot-audit")


@contextmanager
def locked():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    f = open(LOG_DIR / ".lock", "a+")
    try:
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX)
        except OSError:
            pass
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_UN)
        except OSError:
            pass
        f.close()


def append_jsonl(sub, record):
    d = LOG_DIR / sub
    d.mkdir(parents=True, exist_ok=True)
    with open(d / f"{now_utc():%Y-%m-%d}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


# ------------------------------------------------------------------ redaction

SECRET_PATTERNS = [
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 ***"),
    (re.compile(r"ATATT[A-Za-z0-9_\-=]{20,}"), "***ATLASSIAN_TOKEN***"),
    (re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"), "***GITHUB_TOKEN***"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "***AWS_KEY***"),
    (re.compile(r"(?i)\b([A-Z0-9_]*(token|password|passwd|secret|api_key|apikey|_pat)\b[\"']?\s*[=:]\s*)[\"']?[^\s\"',;]+"),
     r"\1***"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "***PRIVATE_KEY***"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "***-**-****"),                 # SSN / TIN shaped
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "***CARD***"),
]
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def redact(value, limit=None):
    if value is None:
        return None
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, default=str)
    for pat, repl in SECRET_PATTERNS:
        value = pat.sub(repl, value)
    if POLICY.get("mask_emails_in_content", True):
        value = EMAIL.sub(lambda m: m.group(0)[0] + "***@" + m.group(0).split("@")[1], value)
    limit = POLICY.get("max_field_chars", 2000) if limit is None else limit
    if limit > 0 and len(value) > limit:
        value = value[:limit] + f"…[+{len(value) - limit} chars]"
    return value


PRIVATE_FIELDS = {"thinking", "reasoning", "analysis", "chain_of_thought", "reasoning_content",
                  "reasoning_text", "encrypted_content", "system", "system_prompt"}
SECRET_FIELDS = re.compile(r"(?i)(?:token|password|passwd|secret|api_?key|authorization|cookie|.*_pat)$")


def audit_content(value):
    """Keep visible evidence, not private reasoning blocks or credential fields."""
    if isinstance(value, dict):
        if isinstance(value.get("type"), str) and value["type"] in PRIVATE_FIELDS:
            return None
        return {k: ("***" if SECRET_FIELDS.search(k) else audit_content(v))
                for k, v in value.items() if k.lower() not in PRIVATE_FIELDS}
    if isinstance(value, list):
        return [audit_content(v) for v in value
                if not (isinstance(v, dict) and isinstance(v.get("type"), str)
                        and v["type"] in PRIVATE_FIELDS)]
    if isinstance(value, str):
        return redact(value, POLICY.get("max_content_chars", 0))
    return value


# ------------------------------------------------------------------ payload normalisation

def first(d, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return default


def parse_ts(v):
    try:
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, tz=timezone.utc)
        if isinstance(v, str) and v:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, OSError, OverflowError):
        pass
    return now_utc()


def tool_args(d):
    a = first(d, "toolArgs", "tool_input", "toolInput", "input", default={})
    if isinstance(a, str):
        try:
            a = json.loads(a)
        except ValueError:
            a = {"command": a}
    return a if isinstance(a, dict) else {"value": a}


CMD_KEYS = ("command", "cmd", "script", "commandLine", "input")
PATH_KEYS = ("path", "file_path", "filePath", "filepath", "file", "target", "dirPath", "old_path", "new_path")


def extract_command(args):
    for k in CMD_KEYS:
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def extract_paths(args):
    paths = []
    for k in PATH_KEYS:
        v = args.get(k)
        if isinstance(v, str):
            paths.append(v)
    for k in ("files", "paths", "filePaths"):
        v = args.get(k)
        if isinstance(v, list):
            paths += [x if isinstance(x, str) else first(x, *PATH_KEYS, default="") for x in v]
    # apply_patch / multi-edit payloads
    patch = args.get("patch") or args.get("input") if isinstance(args.get("patch") or args.get("input"), str) else ""
    paths += re.findall(r"(?m)^\*\*\* (?:Add|Update|Delete) File: (.+)$", patch or "")
    return [p for p in paths if p]


def rel_posix(p):
    try:
        pp = Path(p)
        if not pp.is_absolute():
            pp = Path.cwd() / pp
        return pp.resolve().relative_to(ROOT).as_posix()
    except (ValueError, OSError):
        return str(p).replace("\\", "/")


TOOL_KIND = [
    ("shell", re.compile(r"(?i)^(bash|powershell|shell|terminal|run_in_terminal|runinterminal|runcommands?|execute|run_command)$")),
    ("read", re.compile(r"(?i)^(view|read|read_file|readfile|open_file|cat|getfile|fetch_file)$")),
    ("write", re.compile(r"(?i)^(edit|create|write|str_replace_editor|str_replace|apply_patch|insert|create_file|"
                         r"editfiles?|replace_string_in_file|multi_replace_string_in_file|insert_edit_into_file|notebookedit)$")),
    ("search", re.compile(r"(?i)^(grep|rg|glob|search|file_search|grep_search|semantic_search|codebase)$")),
    ("web", re.compile(r"(?i)^(web_fetch|web_search|fetch|webfetch|websearch)$")),
    ("agent", re.compile(r"(?i)^(task|agent|runsubagent|run_subagent)$")),
]


def tool_kind(name):
    for kind, pat in TOOL_KIND:
        if pat.match(name or ""):
            return kind
    return "other"


def normalise(event, d):
    ts = parse_ts(first(d, "timestamp"))
    rec = {
        "ts": iso(ts),
        "event": event,
        "session_id": str(first(d, "sessionId", "session_id", default="unknown")),
        "format": "vscode" if "hook_event_name" in d else "copilot",
        "cwd": first(d, "cwd"),
        "schema_version": VERSION,
    }
    for key, aliases in {
        "agent_id": ("agentId", "agent_id"),
        "parent_agent_id": ("parentAgentId", "parent_agent_id"),
        "tool_call_id": ("toolUseId", "tool_use_id", "toolCallId", "tool_call_id"),
    }.items():
        if first(d, *aliases) is not None:
            rec[key] = audit_content(first(d, *aliases))
    if event == "sessionStart":
        rec["source"] = first(d, "source")
        if POLICY.get("log_prompts", True):
            rec["initial_prompt"] = audit_content(first(d, "initialPrompt", "initial_prompt"))
    elif event == "userPromptSubmitted":
        p = first(d, "prompt", "user_prompt", default="")
        rec["prompt_chars"] = len(p or "")
        rec["prompt"] = audit_content(p) if POLICY.get("log_prompts", True) else "(not logged)"
    elif event in ("preToolUse", "postToolUse", "postToolUseFailure"):
        args = tool_args(d)
        name = first(d, "toolName", "tool_name", default="unknown")
        rec["tool"] = name
        rec["tool_kind"] = tool_kind(name)
        rec["arguments_sha256"] = hashlib.sha256(
            json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()
        if POLICY.get("log_tool_arguments", True):
            rec["tool_arguments"] = audit_content(args)
        cmd = extract_command(args) if rec["tool_kind"] in ("shell", "other") else ""
        if cmd:
            rec["command"] = redact(cmd)
        paths = extract_paths(args)
        if paths:
            rec["paths"] = [rel_posix(p) for p in paths]
        if not cmd and not paths:
            rec["args"] = redact(audit_content(args), 600)
        if event in ("postToolUse", "postToolUseFailure"):
            res = first(d, "toolResult", "tool_response", "tool_result", "toolResponse", default={})
            if isinstance(res, dict):
                rtype = first(res, "resultType", "result_type", "status")
                text = first(res, "textResultForLlm", "text_result_for_llm", "text", "output",
                             "content", "stdout", default="")
            else:
                rtype, text = None, res
            err = first(d, "error")
            rec["result"] = "failure" if err or event == "postToolUseFailure" else (rtype or "success")
            if POLICY.get("log_tool_results", True):
                rec["tool_result"] = audit_content(res)
            rec["result_excerpt"] = redact(audit_content(text), POLICY.get("result_excerpt_chars", 500)) if text else None
            if err:
                rec["error"] = audit_content(err)
    elif event in ("agentStop", "subagentStart", "subagentStop", "preCompact"):
        rec["stop_reason"] = first(d, "stopReason", "stop_reason", "reason")
        rec["stop_hook_active"] = first(d, "stop_hook_active", "stopHookActive")
        rec["transcript_path"] = first(d, "transcriptPath", "transcript_path")
        if event in ("subagentStart", "subagentStop"):
            rec["subagent"] = first(d, "agentName", "agent_name", "agentType", "agent_type", "agentId", "agent_id")
            rec["parent_agent_id"] = first(d, "parentAgentId", "parent_agent_id")
        if event == "preCompact":
            rec["trigger"] = first(d, "trigger")
    elif event == "sessionEnd":
        rec["reason"] = first(d, "reason")
    elif event == "errorOccurred":
        err = first(d, "error", default={})
        rec["error_details"] = audit_content(err)
        if isinstance(err, dict):
            rec["error_name"] = first(err, "name", "type", "code")
            rec["error_message"] = redact(first(err, "message", default=json.dumps(err)))
            rec["error_stack"] = redact(first(err, "stack"), 1500)
        else:
            rec["error_message"] = redact(err)
        rec["error_context"] = first(d, "errorContext", "error_context", "context", "toolName")
    if event in ("agentStop", "subagentStop", "sessionEnd"):
        response = first(d, "response", "last_assistant_message", "lastAssistantMessage")
        if response is not None and POLICY.get("log_assistant_messages", True):
            rec["final_output"] = audit_content(response)
            rec["output_source"] = "hook_payload"
        summary = first(d, "decision_summary", "decisionSummary")
        if summary is not None:
            rec["decision_summary"] = audit_content(summary)
    return rec, ts


# ------------------------------------------------------------------ identity & environment

def git(*args):
    try:
        r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=3)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def identity():
    return {
        "user": git("config", "user.email") or os.environ.get("GITHUB_ACTOR") or getpass.getuser(),
        "os_user": getpass.getuser(),
        "host": socket.gethostname(),
        "platform": f"{platform.system()} {platform.release()}",
        "repo": (git("config", "--get", "remote.origin.url") or ROOT.name),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "commit": git("rev-parse", "--short", "HEAD"),
        "client": "cloud-agent" if os.environ.get("GITHUB_ACTIONS") or os.environ.get("COPILOT_AGENT_ACTION")
                  else None,
    }


def project_checks():
    """sessionStart validation; returns a list of warnings (never blocks)."""
    w = []
    if not (ROOT / "config" / "jira.config.json").exists():
        w.append("config/jira.config.json missing (story-writer cannot reach Jira)")
    if not (ROOT / ".env").exists():
        w.append(".env missing (Jira scripts will fail until a developer creates it)")
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8", errors="ignore") if (ROOT / ".gitignore").exists() else ""
    for needed in (".env", ".jira/", POLICY.get("log_dir", "logs/copilot-audit")):
        if needed.rstrip("/") not in gi:
            w.append(f".gitignore does not list {needed}")
    if sys.version_info < (3, 8):
        w.append(f"Python {platform.python_version()} is older than 3.8")
    return w


# ------------------------------------------------------------------ session state

def state_path(sid):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", sid)[:80]
    return LOG_DIR / ".state" / f"{safe}.json"


def load_state(sid):
    p = state_path(sid)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"session_id": sid, "started": None, "identity": None, "agents": [], "prompts": 0,
                "tools": {}, "denied": [], "asked": [], "failures": [], "errors": [], "pending": {},
                "jira_created": [], "drafts": [], "subagents": [], "turns": 0}


def save_state(st):
    p = state_path(st["session_id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, ensure_ascii=False, default=str), encoding="utf-8")


def detect_agents(st, *texts):
    joined = " ".join(t for t in texts if t)
    for agent, markers in (POLICY.get("agents") or {}).items():
        if agent not in st["agents"] and any(m in joined for m in markers):
            st["agents"].append(agent)


def call_key(rec):
    if rec.get("tool_call_id"):
        return f"{rec.get('agent_id', '')}|{rec['tool_call_id']}"
    if rec.get("arguments_sha256"):
        return f"{rec.get('agent_id', '')}|{rec.get('tool')}|{rec['arguments_sha256']}"
    raw = rec.get("tool", "") + "|" + (rec.get("command") or "") + "|" + ",".join(rec.get("paths", []))
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


# ------------------------------------------------------------------ visible transcript evidence

def visible_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(part["text"] for part in content if isinstance(part, dict)
                         and part.get("type") in ("text", "output_text")
                         and isinstance(part.get("text"), str))
    return ""


def capture_transcript(st, rec, payload):
    if not POLICY.get("log_assistant_messages", True):
        rec["transcript_capture"] = {"status": "disabled"}
        return
    raw_path = first(payload, "transcriptPath", "transcript_path")
    if rec["event"] == "sessionEnd" and not raw_path:
        raw_path = st.get("primary_transcript")
    if not raw_path:
        rec["transcript_capture"] = {"status": "unavailable", "reason": "No transcript path supplied"}
        return
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path(payload.get("cwd") or ROOT) / path
    path = path.resolve()
    if rec["event"] in ("agentStop", "preCompact") and not rec.get("agent_id"):
        st["primary_transcript"] = str(path)
    cursors = st.setdefault("transcript_cursors", {})
    key = hashlib.sha256(str(path).encode()).hexdigest()
    cursor = cursors.get(key, {})
    messages = []
    try:
        with path.open("rb") as stream:
            stat = os.fstat(stream.fileno())
            generation = [stat.st_dev, stat.st_ino]
            offset = cursor.get("offset", 0)
            anchor = hashlib.sha256(stream.read(min(offset, 128))).hexdigest()
            if cursor.get("generation") != generation or offset > stat.st_size or cursor.get("anchor") != anchor:
                offset = 0
                cursor = {}
            stream.seek(offset)
            budget = int(POLICY.get("max_transcript_bytes_per_event", 16777216))
            data = stream.read(budget)
            complete = offset + len(data) >= stat.st_size
            # Do not consume a record still being written by the host.
            end = data.rfind(b"\n") + 1
            if end < len(data):
                complete = False
            malformed = 0
            for line in data[:end].splitlines():
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except (ValueError, UnicodeError):
                    malformed += 1
                    continue
                if not isinstance(item, dict):
                    continue
                kind = item.get("type")
                body = item.get("data") if kind in ("assistant.message", "user.message") else item.get("message", item)
                if not isinstance(body, dict):
                    continue
                role = kind.split(".")[0] if kind in ("assistant.message", "user.message") else body.get("role", kind)
                if role not in ("assistant", "user") or (role == "user" and not POLICY.get("log_prompts", True)):
                    continue
                text = visible_text(body.get("content"))
                if text:
                    messages.append({"role": role, "content": audit_content(text),
                                     "source_id": audit_content(item.get("id") or item.get("uuid")),
                                     "ts": audit_content(item.get("timestamp"))})
            latest = next((m["content"] for m in reversed(messages) if m["role"] == "assistant"),
                          cursor.get("latest_assistant"))
            stream.seek(0)
            anchor = hashlib.sha256(stream.read(min(offset + end, 128))).hexdigest()
            cursors[key] = {"offset": offset + end, "generation": generation, "anchor": anchor,
                            "latest_assistant": latest}
            rec["transcript_capture"] = {"status": "complete" if complete else "partial",
                                         "offset": offset + end, "malformed_records": malformed,
                                         "messages_captured": len(messages)}
            if malformed:
                sys.stderr.write(f"[copilot-audit] skipped {malformed} malformed transcript records\n")
            if not complete:
                rec["transcript_capture"]["reason"] = "Byte budget reached or trailing record incomplete"
            if messages:
                rec["messages"] = messages
            if rec["event"] in ("agentStop", "subagentStop", "sessionEnd") and "final_output" not in rec and latest and complete:
                rec["final_output"] = latest
                rec["output_source"] = "latest_visible_transcript_message"
    except (OSError, ValueError) as exc:
        rec["transcript_capture"] = {"status": "error", "reason": audit_content(str(exc))}
        sys.stderr.write(f"[copilot-audit] transcript capture failed: {audit_content(str(exc))}\n")


def trace_path(st):
    if not st.get("trace_file"):
        safe = state_path(st["session_id"]).stem
        st["trace_file"] = f"traces/{now_utc():%Y-%m-%d}_{safe}.jsonl"
    return LOG_DIR / st["trace_file"]


def append_trace(st, rec):
    path = trace_path(st)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


# ------------------------------------------------------------------ preToolUse policy

def match_any(path, patterns):
    return any(fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(Path(path).name, pat) for pat in patterns)


def jira_create_gate(cmd):
    """Return (decision, reason) for a jira_create.py create command, or None if not one."""
    gate = POLICY.get("jira_create_gate") or {}
    if not gate.get("enabled", True) or not re.search(r"jira_create\.py[\"']?\s+create\b", cmd):
        return None
    try:
        tokens = shlex.split(cmd, posix=os.name != "nt")
    except ValueError:
        tokens = cmd.split()
    tokens = [t.strip("\"'") for t in tokens]
    draft = None
    for i, t in enumerate(tokens):
        if t == "create" and i + 1 < len(tokens):
            draft = tokens[i + 1]
            break
    proj = tokens[tokens.index("--confirm-project") + 1] if "--confirm-project" in tokens[:-1] else None
    itype = tokens[tokens.index("--confirm-type") + 1] if "--confirm-type" in tokens[:-1] else None
    if not draft:
        return "deny", "jira_create.py create needs the draft path."
    if not (proj and itype):
        return "deny", "jira_create.py create needs --confirm-project and --confirm-type with the values the user confirmed."
    p = Path(draft) if Path(draft).is_absolute() else (Path.cwd() / draft)
    if not p.exists():
        p = ROOT / draft
    try:
        head = p.read_text(encoding="utf-8")[:4000]
    except OSError:
        return "deny", f"Draft not found: {draft}"
    m = re.search(r"(?m)^status:[ \t]*(\S+)", head)
    status = m.group(1) if m else "draft"
    if re.search(r"(?m)^jira_key:[ \t]*\S+", head):
        return "deny", "This draft was already created in Jira (jira_key is set). Not creating a duplicate."
    if status != "approved":
        return "deny", f"Draft status is '{status}'. The user must approve the draft in chat before it is created."
    decision = gate.get("decision_when_approved", "ask")
    return decision, f"Create Jira {itype} in project {proj} from {rel_posix(p)}?"


APPROVAL = re.compile(r"(?i)^\W*(approved?|lgtm|looks good|ship it|go ahead and create|yes,? create)\b")
NOT_APPROVAL = re.compile(r"(?i)\b(not|don'?t|do not|isn'?t|no)\b[^.]{0,20}\b(approve|create|good)")
CONTENT_KEYS = ("new_str", "newString", "new_string", "content", "file_text", "text", "code", "patch", "input",
                "replacement", "edits")


def write_content(args):
    return " ".join(json.dumps(args.get(k)) if not isinstance(args.get(k), str) else args.get(k)
                    for k in CONTENT_KEYS if args.get(k))


def decide(rec, st, args):
    """Return (decision, rule_id, reason). decision in allow / ask / deny."""
    cmd = rec.get("command") or ""
    raw_cmd = rec.get("_raw_command") or cmd
    kind = rec.get("tool_kind")
    paths = rec.get("paths", [])

    # Gate 1: only the user can approve a story draft
    text = raw_cmd + " " + (write_content(args) if kind in ("write", "other") else "")
    if re.search(r"(?m)status:\s*approved\b", text) and (any(".jira/drafts/" in p for p in paths) or ".jira" in raw_cmd):
        if not st.get("last_prompt_is_approval"):
            return "deny", "JIRA-0", ("Only the user can approve a story draft. Ask them to review it and reply "
                                      "'approved' in chat before setting status: approved.")

    if kind in ("read", "write", "search", "other", "shell"):
        for p in paths:
            if kind == "write" or (kind == "other" and re.search(r"(?i)edit|write|create|replace|patch", rec["tool"])):
                if match_any(p, POLICY.get("protected_write", [])) and \
                        not match_any(p, POLICY.get("protected_write_exceptions", [])):
                    return "deny", "WRITE-1", f"Agents may not change {p} (protected)."
            if kind in ("read", "search", "write", "other"):
                if match_any(p, POLICY.get("protected_read", [])) and \
                        not match_any(p, POLICY.get("protected_read_exceptions", [])):
                    return "deny", "READ-1", f"{p} holds credentials; agents may not read it."
    if raw_cmd:
        low = raw_cmd.lower()
        for rule in POLICY.get("deny_commands", []):
            try:
                if re.search(rule["pattern"], low):
                    return "deny", rule.get("id", "DENY"), rule.get("reason", "Blocked by policy.")
            except re.error:
                continue
        gate = jira_create_gate(raw_cmd)
        if gate:
            return gate[0], "JIRA-1", gate[1]
        for rule in POLICY.get("ask_commands", []):
            try:
                if re.search(rule["pattern"], low):
                    return "ask", rule.get("id", "ASK"), rule.get("reason", "Confirm?")
            except re.error:
                continue
    return "allow", None, None


def emit_decision(fmt, decision, reason):
    if fmt == "vscode":
        out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision}}
        if reason:
            out["hookSpecificOutput"]["permissionDecisionReason"] = reason
    else:
        out = {"permissionDecision": decision}
        if reason:
            out["permissionDecisionReason"] = reason
    sys.stdout.write(json.dumps(out))
    sys.stdout.flush()


# ------------------------------------------------------------------ notifications

def notify(kind, text):
    if kind not in ((POLICY.get("notify") or {}).get("on") or []):
        return
    url = os.environ.get((POLICY.get("notify") or {}).get("webhook_env") or "COPILOT_AUDIT_WEBHOOK")
    if not url or not url.startswith("https://"):
        return
    try:
        req = urllib.request.Request(url, data=json.dumps({"text": text}).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3).read()
    except Exception:
        pass


# ------------------------------------------------------------------ session report

def fmt_dur(sec):
    sec = int(sec)
    return f"{sec // 3600}h {sec % 3600 // 60}m {sec % 60}s" if sec >= 3600 else f"{sec // 60}m {sec % 60}s"


def write_report(st, rec):
    started = parse_ts(st.get("started")) if st.get("started") else None
    ended = parse_ts(rec["ts"])
    ident = st.get("identity") or {}
    lines = [
        f"# Copilot session {st['session_id']}",
        "",
        "| | |", "|---|---|",
        f"| User | {ident.get('user', '-')} ({ident.get('host', '-')}) |",
        f"| Repo / branch | {ident.get('repo', '-')} / {ident.get('branch', '-')} |",
        f"| Agents used | {', '.join(st['agents']) or 'default'} |",
        f"| Started | {st.get('started') or '-'} |",
        f"| Last event | {rec['ts']} ({rec['event']}: {rec.get('reason') or rec.get('stop_reason') or '-'}) |",
        f"| Duration | {fmt_dur((ended - started).total_seconds()) if started else '-'} |",
        f"| Prompts / agent turns | {st['prompts']} / {st['turns']} |",
        f"| Tool calls | {sum(v['calls'] for v in st['tools'].values())} |",
        f"| Denied / asked | {len(st['denied'])} / {len(st['asked'])} |",
        f"| Failures / errors | {len(st['failures'])} / {len(st['errors'])} |",
        "",
    ]
    if st["jira_created"]:
        lines += ["## Jira issues created", ""] + [f"- {k}" for k in st["jira_created"]] + [""]
    if st["drafts"]:
        lines += ["## Story drafts touched", ""] + [f"- `{d}`" for d in st["drafts"]] + [""]
    if st["tools"]:
        lines += ["## Tools", "", "| Tool | Calls | Failed | Avg ms |", "|---|---|---|---|"]
        for name, v in sorted(st["tools"].items(), key=lambda kv: -kv[1]["calls"]):
            avg = int(v["ms"] / v["timed"]) if v.get("timed") else "-"
            lines.append(f"| {name} | {v['calls']} | {v['failed']} | {avg} |")
        lines.append("")
    for title, key in (("Denied", "denied"), ("Asked for confirmation", "asked"),
                       ("Tool failures", "failures"), ("Errors", "errors")):
        if st[key]:
            lines += [f"## {title}", ""] + [f"- {x}" for x in st[key][:50]] + [""]
    if st["subagents"]:
        lines += ["## Subagents", ""] + [f"- {x}" for x in st["subagents"]] + [""]
    lines += ["## Evidence and coverage", "",
              "This is observed evidence, not hidden chain-of-thought. Decision summaries are agent explanations,",
              "not proof. Transcript coverage depends on the host; see capture status on stop events.",
              "Tool arguments/results describe requested actions and reported outcomes, not independent verification.",
              "", f"Chronological evidence: `{st.get('trace_file', '-')}`", "",
              "## Chronological audit trail", ""]
    evidence = trace_path(st)
    if evidence.exists():
        with evidence.open(encoding="utf-8") as stream:
            for line in stream:
                item = json.loads(line)
                lines += [f"### {item.get('sequence', '-')} / {item['ts']} / {item['event']}", ""]
                lines += ["    " + part for part in json.dumps(item, ensure_ascii=False, default=str, indent=2).splitlines()]
                lines.append("")
    d = LOG_DIR / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", st["session_id"])[:60]
    path = d / f"{now_utc():%Y-%m-%d}_{safe}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def cleanup():
    keep = int(POLICY.get("retention_days", 90))
    cutoff = now_utc() - timedelta(days=keep)
    for sub in ("events", "errors", "sessions", "traces"):
        for f in (LOG_DIR / sub).glob("*"):
            m = re.match(r"(\d{4}-\d{2}-\d{2})", f.name)
            if m and datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc) < cutoff:
                f.unlink(missing_ok=True)
    for f in (LOG_DIR / ".state").glob("*.json"):           # orphaned sessions that never ended
        if time.time() - f.stat().st_mtime > 2 * 86400:
            f.unlink(missing_ok=True)


# ------------------------------------------------------------------ main handler

def handle(event, payload):
    rec, ts = normalise(event, payload)
    if event in ("preToolUse", "postToolUse", "postToolUseFailure"):
        rec["_raw_command"] = extract_command(tool_args(payload))   # unredacted, for policy only; never logged

    decision, rule, reason = ("allow", None, None)
    if event == "preToolUse":
        decision, rule, reason = decide(rec, load_state(rec["session_id"]), tool_args(payload))
        rec["decision"] = decision
        if rule:
            rec["rule"], rec["reason"] = rule, reason
    raw_cmd = rec.pop("_raw_command", "")

    try:
        with locked():
            st = load_state(rec["session_id"])
            if event == "sessionStart":
                st["identity"] = identity()
                st["started"] = st["started"] or rec["ts"]
                rec["checks"] = project_checks()
                cleanup()
            if not st.get("identity"):
                st["identity"] = identity()
            rec.update({k: st["identity"].get(k) for k in ("user", "host", "repo", "branch")})
            st["sequence"] = st.get("sequence", 0) + 1
            rec["sequence"] = st["sequence"]
            rec["prompt_index"] = st["prompts"] + (1 if event == "userPromptSubmitted" else 0)
            rec["turn_index"] = st["turns"] + 1
            if event in ("sessionStart", "subagentStart") and POLICY.get("request_decision_summary", True):
                rec["decision_summary_requested"] = True
            if event in ("agentStop", "subagentStop", "preCompact", "sessionEnd"):
                capture_transcript(st, rec, payload)
                if "final_output" not in rec and event in ("agentStop", "subagentStop"):
                    rec["output_unavailable"] = "Host supplied no final response or usable visible transcript message"

            detect_agents(st, rec.get("prompt"), rec.get("initial_prompt"), raw_cmd, " ".join(rec.get("paths", [])))
            rec["agents"] = list(st["agents"])

            if event == "userPromptSubmitted":
                st["prompts"] += 1
                p = first(payload, "prompt", "user_prompt", default="") or ""
                st["last_prompt_is_approval"] = bool(APPROVAL.search(p)) and not NOT_APPROVAL.search(p)
                rec["is_approval"] = st["last_prompt_is_approval"]
            elif event == "preToolUse":
                t = st["tools"].setdefault(rec["tool"], {"calls": 0, "failed": 0, "ms": 0, "timed": 0})
                t["calls"] += 1
                st["pending"].setdefault(call_key(rec), []).append(time.time())
                for p in rec.get("paths", []):
                    if ".jira/drafts/" in p and p not in st["drafts"]:
                        st["drafts"].append(p)
                label = f"{rec['ts']} `{rec['tool']}` {rule}: {reason} — {(rec.get('command') or ', '.join(rec.get('paths', [])))[:160]}"
                if decision == "deny":
                    st["denied"].append(label)
                    append_jsonl("errors", rec)
                elif decision == "ask":
                    st["asked"].append(label)
            elif event in ("postToolUse", "postToolUseFailure"):
                q = st["pending"].get(call_key(rec)) or []
                if q:
                    rec["duration_ms"] = int((time.time() - q.pop(0)) * 1000)
                    t = st["tools"].setdefault(rec["tool"], {"calls": 1, "failed": 0, "ms": 0, "timed": 0})
                    t["ms"] += rec["duration_ms"]
                    t["timed"] += 1
                if rec.get("result") not in ("success", None):
                    st["tools"].setdefault(rec["tool"], {"calls": 1, "failed": 0, "ms": 0, "timed": 0})["failed"] += 1
                    detail = rec.get("error") or rec.get("result_excerpt") or ""
                    if not isinstance(detail, str):
                        detail = json.dumps(detail, ensure_ascii=False, default=str)
                    st["failures"].append(f"{rec['ts']} `{rec['tool']}` {rec['result']}: "
                                          f"{detail[:200]}")
                    append_jsonl("errors", rec)
                text = rec.get("result_excerpt") or ""
                for key in re.findall(r"CREATED\s+([A-Z][A-Z0-9_]+-\d+)", text):
                    if key not in st["jira_created"]:
                        st["jira_created"].append(key)
                        rec["jira_created"] = key
            elif event == "agentStop":
                st["turns"] += 1
            elif event in ("subagentStart", "subagentStop"):
                st["subagents"].append(f"{rec['ts']} {rec.get('subagent') or '-'} ({rec.get('stop_reason') or '-'})")
            elif event == "errorOccurred":
                st["errors"].append(f"{rec['ts']} {rec.get('error_name') or ''} {rec.get('error_message') or ''}"[:300])
                append_jsonl("errors", rec)

            append_jsonl("events", rec)
            append_trace(st, rec)

            if event in ("agentStop", "subagentStop", "sessionEnd"):
                report = write_report(st, rec)
            if event == "sessionEnd":
                state_path(st["session_id"]).unlink(missing_ok=True)
                append_jsonl("events", {"ts": iso(now_utc()), "event": "sessionReport",
                                        "session_id": st["session_id"], "report": report.relative_to(ROOT).as_posix()})
            else:
                save_state(st)
    except Exception as e:                                       # logging must never break the agent
        try:
            sys.stderr.write(f"[copilot-audit] logging failed: {e}\n")
        except Exception:
            pass

    if event == "preToolUse" and decision == "deny":
        notify("deny", f"Copilot blocked `{rec.get('tool')}` for {rec.get('user')}: {reason}")
    elif event == "errorOccurred":
        notify("errorOccurred", f"Copilot error for {rec.get('user')}: {rec.get('error_message')}")
    elif event == "sessionEnd":
        notify("sessionEnd", f"Copilot session ended for {rec.get('user')} ({', '.join(rec.get('agents') or []) or 'default'}), "
                             f"reason {rec.get('reason')}")

    if event == "preToolUse":
        emit_decision(rec["format"], decision, reason)
    elif event in ("sessionStart", "subagentStart") and POLICY.get("request_decision_summary", True):
        context = ("For audit traceability, include a concise Decision summary in your final response: "
                   "key decisions, supporting sources/tool evidence, assumptions, final outputs, and "
                   "verification performed or remaining gaps. Explain conclusions briefly; do not expose "
                   "hidden chain-of-thought, secrets, or private reasoning. Existing review/approval gates still apply.")
        if rec["format"] == "vscode":
            name = "SessionStart" if event == "sessionStart" else "SubagentStart"
            out = {"hookSpecificOutput": {"hookEventName": name, "additionalContext": context}}
        else:
            out = {"additionalContext": context}
        sys.stdout.write(json.dumps(out))


# ------------------------------------------------------------------ report command

def report(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="audit_hook.py report")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--user")
    ap.add_argument("--agent")
    a = ap.parse_args(argv)
    since = (now_utc() - timedelta(days=a.days)).strftime("%Y-%m-%d")
    sessions, users, agents, tools, denies, prompts, created, errors = {}, {}, {}, {}, {}, 0, [], 0
    for f in sorted((LOG_DIR / "events").glob("*.jsonl")):
        if f.stem < since:
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if a.user and r.get("user") != a.user:
                continue
            if a.agent and a.agent not in (r.get("agents") or []):
                continue
            sid = r.get("session_id")
            if r.get("event") == "sessionReport":
                continue
            sessions.setdefault(sid, set()).update(r.get("agents") or [])
            u = str(r.get("user") or "-")
            users[u] = users.get(u, set()) | {sid}
            ev = r.get("event")
            if ev == "userPromptSubmitted":
                prompts += 1
            elif ev == "preToolUse":
                tools[str(r.get("tool"))] = tools.get(str(r.get("tool")), 0) + 1
                if r.get("decision") == "deny":
                    denies[str(r.get("rule"))] = denies.get(str(r.get("rule")), 0) + 1
            elif ev == "postToolUse" and r.get("jira_created"):
                created.append(f"{r['jira_created']} by {r.get('user')} on {r['ts'][:10]}")
            elif ev == "errorOccurred":
                errors += 1
    for s, ag in sessions.items():
        for x in (ag or {"default"}):
            agents[x] = agents.get(x, 0) + 1
    print(f"Copilot usage since {since}" + (f" for {a.user}" if a.user else "") + (f", agent {a.agent}" if a.agent else ""))
    print(f"  sessions {len(sessions)} | users {len(users)} | prompts {prompts} | tool calls {sum(tools.values())} "
          f"| denied {sum(denies.values())} | errors {errors}")
    print("\nSessions per user");  [print(f"  {u:40} {len(s)}") for u, s in sorted(users.items(), key=lambda kv: -len(kv[1]))]
    print("\nSessions per agent"); [print(f"  {g:40} {n}") for g, n in sorted(agents.items(), key=lambda kv: -kv[1])]
    print("\nTop tools");          [print(f"  {t:40} {n}") for t, n in sorted(tools.items(), key=lambda kv: -kv[1])[:15]]
    if denies:
        print("\nDenied by rule");  [print(f"  {k:40} {n}") for k, n in sorted(denies.items(), key=lambda kv: -kv[1])]
    if created:
        print("\nJira issues created"); [print(f"  {c}") for c in created]


def main():
    if len(sys.argv) < 2:
        sys.stderr.write(__doc__)
        sys.exit(0)
    if sys.argv[1] == "report":
        report(sys.argv[2:])
        return
    raw = ""
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        payload = {"_unparsed": raw[:500]}
    event = sys.argv[1]
    event = PASCAL.get(payload.get("hook_event_name"), event) if isinstance(payload, dict) else event
    event = PASCAL.get(event, event)
    if event not in EVENTS:
        sys.exit(0)
    try:
        handle(event, payload if isinstance(payload, dict) else {})
    except Exception as e:
        sys.stderr.write(f"[copilot-audit] {e}\n")
        if event == "preToolUse":                                 # policy failure: fail open, but say so
            emit_decision("vscode" if "hook_event_name" in payload else "copilot", "allow", None)
    sys.exit(0)


if __name__ == "__main__":
    main()
