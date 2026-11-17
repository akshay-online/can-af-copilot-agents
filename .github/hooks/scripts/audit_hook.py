#!/usr/bin/env python3
"""Guard hook for GitHub Copilot agents (Copilot CLI, cloud agent, VS Code agent mode).

Wired to two lifecycle events in .github/hooks/copilot-audit.json:
  userPromptSubmitted   records (in memory only) whether the latest chat message is an
                        explicit approval ("approved", "LGTM", ...)
  preToolUse            applies .github/hooks/audit-policy.json and returns allow / ask / deny

  python audit_hook.py <event>   reads the hook payload (JSON) on stdin

This hook does NOT log prompts, tool arguments, tool results or transcripts to disk.
The only thing it keeps between calls is one small per-session file recording whether
the user's last message was an approval - needed for the JIRA-0 story-approval gate
below. Nothing else about the conversation is written anywhere.

Accepts both payload styles: Copilot camelCase (sessionId, toolName, toolArgs)
and VS Code (hook_event_name, session_id, tool_name, tool_input).
Standard library only. A policy bug never blocks the agent: it fails open and says
so on stderr.
"""
import fnmatch
import json
import os
import re
import shlex
import sys
import time
from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parent.parent          # .github/hooks
POLICY_PATH = HOOK_DIR / "audit-policy.json"
EVENTS = ["userPromptSubmitted", "preToolUse"]
PASCAL = {"UserPromptSubmit": "userPromptSubmitted", "PreToolUse": "preToolUse"}
VERSION = "2.0"


def repo_root():
    here = HOOK_DIR
    for d in [here, *here.parents]:
        if (d / ".git").exists():
            return d
    return HOOK_DIR.parent.parent


ROOT = repo_root()


def load_policy():
    try:
        return json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


POLICY = load_policy()
STATE_DIR = ROOT / "logs" / "copilot-audit" / ".state"   # one tiny file per session; no conversation content


# ------------------------------------------------------------------ session approval state
#
# JIRA-0 below needs to know whether the user's *last* chat message was an approval.
# That single boolean is the only thing persisted between hook invocations.

def state_path(session_id):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "default")[:80]
    return STATE_DIR / f"{safe}.json"


def load_state(session_id):
    try:
        return json.loads(state_path(session_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"last_prompt_is_approval": False}


def save_state(session_id, state):
    p = state_path(session_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state), encoding="utf-8")


def prune_state(max_age_hours=48):
    if not STATE_DIR.exists():
        return
    cutoff = time.time() - max_age_hours * 3600
    for f in STATE_DIR.glob("*.json"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
        except OSError:
            pass


# ------------------------------------------------------------------ payload helpers

def first(d, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return default


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


def decide(tool_name, raw_cmd, kind, paths, args, approved):
    """Return (decision, rule_id, reason). decision in allow / ask / deny."""
    text = raw_cmd + " " + (write_content(args) if kind in ("write", "other") else "")
    if re.search(r"(?m)status:\s*approved\b", text) and (any(".jira/drafts/" in p for p in paths) or ".jira" in raw_cmd):
        if not approved:
            return "deny", "JIRA-0", ("Only the user can approve a story draft. Ask them to review it and reply "
                                      "'approved' in chat before setting status: approved.")

    if kind in ("read", "write", "search", "other", "shell"):
        for p in paths:
            if kind == "write" or (kind == "other" and re.search(r"(?i)edit|write|create|replace|patch", tool_name)):
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


# ------------------------------------------------------------------ main handler

def handle(event, payload, fmt):
    session_id = str(first(payload, "sessionId", "session_id", default="default"))

    if event == "userPromptSubmitted":
        prompt = first(payload, "prompt", "user_prompt", default="") or ""
        state = load_state(session_id)
        state["last_prompt_is_approval"] = bool(APPROVAL.search(prompt)) and not NOT_APPROVAL.search(prompt)
        save_state(session_id, state)
        prune_state()
        return

    if event == "preToolUse":
        args = tool_args(payload)
        name = first(payload, "toolName", "tool_name", default="unknown")
        kind = tool_kind(name)
        raw_cmd = extract_command(args) if kind in ("shell", "other") else ""
        paths = [rel_posix(p) for p in extract_paths(args)]
        approved = load_state(session_id).get("last_prompt_is_approval", False)
        decision, _rule, reason = decide(name, raw_cmd, kind, paths, args, approved)
        emit_decision(fmt, decision, reason)


def main():
    if len(sys.argv) < 2:
        sys.stderr.write(__doc__)
        sys.exit(0)
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    fmt = "vscode" if "hook_event_name" in payload else "copilot"
    event = PASCAL.get(payload.get("hook_event_name"), sys.argv[1])
    event = PASCAL.get(event, event)
    if event not in EVENTS:
        sys.exit(0)
    try:
        handle(event, payload, fmt)
    except Exception as e:                                        # a hook bug must never freeze the agent
        sys.stderr.write(f"[copilot-guard] {e}\n")
        if event == "preToolUse":                                 # policy failure: fail open, but say so
            emit_decision(fmt, "allow", None)
    sys.exit(0)


if __name__ == "__main__":
    main()

