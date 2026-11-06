#!/usr/bin/env python3
"""Create a Jira issue from an approved story draft. Jira REST API v2, Python standard library only.

Host, project and issue types come from config/jira.config.json; credentials come from .env.
Nobody types a URL or token into chat.

Commands
  check                                     config + credentials + project + issue types
  preview <draft.md> [--project K] [--type T] [--offline]
                                            lint the draft, render the Jira description, show the target
  create  <draft.md> --confirm-project K --confirm-type T
                                            create the issue (draft must be status: approved)
    attach  <draft.md> --confirm-issue K --confirm-files NAME [NAME ...]
                                                                                        upload confirmed attachments to an already-created issue

Exit codes: 0 ok, 1 Jira/API error, 2 config/usage error, 3 draft not ready (lint/approval/confirm).
"""
import argparse
import json
import mimetypes
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------- paths & output

def find_repo_root():
    here = Path.cwd().resolve()
    for d in [here, *here.parents]:
        if (d / ".git").exists() or (d / ".github").is_dir():
            return d
    return here


ROOT = find_repo_root()
CONFIG_PATH = Path(os.environ.get("JIRA_CONFIG") or ROOT / "config" / "jira.config.json")
DESCRIPTION_LIMIT = 32767  # Jira text field limit
CONCISE_REQUIRED_SUBSECTIONS = ["Context / Why", "Scope", "Attachments / documents file path"]
CONCISE_SUBSECTIONS = CONCISE_REQUIRED_SUBSECTIONS + ["Load rules", "Data validations", "Masking"]
INTERNAL_REF = re.compile(r"(?i)[\w.()<>*-]+\.(?:csv|md)\b|\.jira[\\/]|user-brief|story-plan")
FILE_PATTERN = re.compile(r"(?i)YYYY|MMDD|[<>*]")  # incoming file-name patterns are requirements, not working files


def rel(p):
    try:
        return str(Path(p).resolve().relative_to(ROOT))
    except ValueError:
        return str(p)


def die(msg, code=2):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


# --------------------------------------------------------------------------- config & auth

def load_env():
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k.startswith("export "):
            k = k[7:].strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        os.environ.setdefault(k, v)


SECRET_KEY = re.compile(r"(token|password|secret|pat$|api_key)", re.I)


def load_config():
    if not CONFIG_PATH.exists():
        die(f"Config not found: {rel(CONFIG_PATH)}. Copy config/jira.config.example.json to "
            f"config/jira.config.json and fill it in (ask your tech lead). Do not ask the user for it in chat.")
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        die(f"{rel(CONFIG_PATH)} is not valid JSON: {e}")

    for k, v in cfg.items():
        if SECRET_KEY.search(k) and v and not k.startswith("_"):
            die(f"{rel(CONFIG_PATH)} contains '{k}'. Secrets belong in .env, never in the committed config.")

    load_env()
    cfg["base_url"] = (os.environ.get("JIRA_BASE_URL") or cfg.get("base_url") or "").rstrip("/")
    if not cfg["base_url"] or "your-company" in cfg["base_url"]:
        die(f"Set base_url in {rel(CONFIG_PATH)}.")
    if not cfg.get("default_project"):
        die(f"Set default_project in {rel(CONFIG_PATH)}.")
    cfg.setdefault("allowed_projects", [cfg["default_project"]])
    cfg.setdefault("default_issue_type", "Story")
    cfg.setdefault("allowed_issue_types", [cfg["default_issue_type"]])
    cfg.setdefault("deployment", "cloud")
    cfg.setdefault("fields", {})
    cfg.setdefault("default_fields", {})
    cfg.setdefault("attachments", {})
    cfg.setdefault("required_sections", ["Context / Why", "Scope", "Out of scope",
                                         "Acceptance criteria", "Definition of Ready", "Definition of Done"])
    return cfg


def auth_header(cfg):
    pat = os.environ.get("JIRA_PAT", "").strip()
    email = os.environ.get("JIRA_EMAIL", "").strip()
    token = os.environ.get("JIRA_API_TOKEN", "").strip()
    if cfg["deployment"].lower() == "cloud" or (email and token):
        if not (email and token):
            die("JIRA_EMAIL and JIRA_API_TOKEN are not set in .env (Jira Cloud). "
                "Copy .env.example to .env and fill them in yourself; never paste them into chat.")
        import base64
        raw = base64.b64encode(f"{email}:{token}".encode()).decode()
        return {"Authorization": f"Basic {raw}"}
    if not pat:
        die("JIRA_PAT is not set in .env (Jira Server/Data Center). Fill it in yourself; never paste it into chat.")
    return {"Authorization": f"Bearer {pat}"}


class JiraError(Exception):
    def __init__(self, status, body):
        self.status, self.body = status, body
        super().__init__(f"HTTP {status}")

    def explain(self):
        hints = {
            401: "Authentication failed. Check the credentials in .env.",
            403: "Permission denied. Your Jira user may lack 'Create issues' in this project.",
            404: "Not found. Check base_url and the project key in config/jira.config.json.",
        }
        detail = ""
        try:
            j = json.loads(self.body)
            msgs = list(j.get("errorMessages") or [])
            msgs += [f"{k}: {v}" for k, v in (j.get("errors") or {}).items()]
            detail = "; ".join(msgs)
        except (ValueError, AttributeError):
            detail = (self.body or "")[:300]
        return f"HTTP {self.status}. {hints.get(self.status, '')} {detail}".strip()


def api(cfg, method, path, body=None, raw=None, headers=None):
    url = cfg["base_url"] + path
    h = {"Accept": "application/json", "User-Agent": "story-writer-skill/1.0", **auth_header(cfg)}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        h["Content-Type"] = "application/json"
    if raw is not None:
        data = raw
    if headers:
        h.update(headers)
    ctx = ssl.create_default_context(cafile=cfg.get("ca_bundle") or None)
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=cfg.get("timeout_seconds", 30), context=ctx) as r:
            txt = r.read().decode("utf-8")
            return json.loads(txt) if txt.strip() else {}
    except urllib.error.HTTPError as e:
        raise JiraError(e.code, e.read().decode("utf-8", "replace"))
    except urllib.error.URLError as e:
        die(f"Cannot reach {cfg['base_url']}: {e.reason}. Check VPN/proxy, or set ca_bundle in the config.", 1)


def get_project(cfg, key):
    try:
        p = api(cfg, "GET", f"/rest/api/2/project/{key}")
    except JiraError as e:
        die(f"Project {key}: {e.explain()}", 1)
    types = [{"name": t["name"], "subtask": t.get("subtask", False)} for t in p.get("issueTypes", [])]
    return {"key": p.get("key", key), "name": p.get("name", key), "issue_types": types}


# --------------------------------------------------------------------------- draft parsing

FM = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n", re.S)


def parse_value(v):
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        return [x.strip().strip("\"'") for x in v[1:-1].split(",") if x.strip()]
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def parse_draft(path):
    text = Path(path).read_text(encoding="utf-8")
    m = FM.match(text)
    if not m:
        die(f"{rel(path)} has no front matter (--- block at the top). Start from the story template.", 3)
    meta = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        line = re.split(r"\s{2,}#", line, maxsplit=1)[0]          # inline comment needs 2+ spaces before #
        k, v = line.split(":", 1)
        meta[k.strip()] = parse_value(v)
    return meta, text[m.end():], text


def update_front_matter(path, updates):
    text = Path(path).read_text(encoding="utf-8")
    m = FM.match(text)
    lines = m.group(1).splitlines()
    for k, v in updates.items():
        val = "[" + ", ".join(v) + "]" if isinstance(v, list) else str(v)
        for i, line in enumerate(lines):
            if re.match(rf"^{re.escape(k)}\s*:", line):
                lines[i] = f"{k}: {val}"
                break
        else:
            lines.append(f"{k}: {val}")
    Path(path).write_text("---\n" + "\n".join(lines) + "\n---\n" + text[m.end():], encoding="utf-8")


def as_list(v):
    if v in (None, ""):
        return []
    return v if isinstance(v, list) else [x.strip() for x in str(v).split(",") if x.strip()]


def strip_comments(md):
    return re.sub(r"<!--.*?-->\s*\n?", "", md, flags=re.S)


def split_sections(body):
    """Return (preamble, [(heading, text)]) for '## ' sections."""
    parts = re.split(r"(?m)^##[ \t]+(.+?)[ \t]*$", body)
    pre, secs = parts[0], []
    for i in range(1, len(parts), 2):
        secs.append((parts[i].strip(), parts[i + 1]))
    return pre, secs


def norm(h):
    return re.sub(r"[^a-z0-9]", "", h.lower())


# --------------------------------------------------------------------------- markdown -> Jira wiki markup

ESC = re.compile(r"([{}\[\]*^~|])")


def inline(text):
    keep = []

    def stash(s):
        keep.append(s)
        return f"\x00{len(keep) - 1}\x00"

    text = re.sub(r"`([^`]+)`", lambda m: stash("{{" + ESC.sub(r"\\\1", m.group(1)) + "}}"), text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                  lambda m: stash("[" + ESC.sub(r"\\\1", m.group(1)) + "|" + m.group(2) + "]"), text)
    text = re.sub(r"<(https?://[^>\s]+)>", lambda m: stash("[" + m.group(1) + "]"), text)
    text = re.sub(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", lambda m: "\x02" + m.group(2) + "\x02", text)
    text = re.sub(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])", lambda m: "\x03" + m.group(1) + "\x03", text)
    text = re.sub(r"(?<!\w)_(?=\S)([^_\n]+?)(?<=\S)_(?!\w)", lambda m: "\x03" + m.group(1) + "\x03", text)
    text = re.sub(r"~~(?=\S)(.+?)(?<=\S)~~", lambda m: "\x04" + m.group(1) + "\x04", text)
    text = ESC.sub(r"\\\1", text)
    text = text.replace("\x02", "*").replace("\x03", "_").replace("\x04", "-")
    return re.sub(r"\x00(\d+)\x00", lambda m: keep[int(m.group(1))], text)


def split_row(row):
    inner = row.strip()
    inner = inner[1:] if inner.startswith("|") else inner
    inner = inner[:-1] if inner.endswith("|") and not inner.endswith("\\|") else inner
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", inner)]


def convert_table(rows):
    cells = [split_row(r) for r in rows]
    out, body = [], cells
    if len(cells) >= 2 and cells[1] and all(re.fullmatch(r":?-+:?", c) for c in cells[1] if c):
        out.append("||" + "||".join(inline(c) or " " for c in cells[0]) + "||")
        body = cells[2:]
    for r in body:
        out.append("|" + "|".join(inline(c) or " " for c in r) + "|")
    return out


def md_to_wiki(md):
    md = strip_comments(md)
    lines, out = md.split("\n"), []
    i, in_code = 0, False
    indents, kinds = [], []
    while i < len(lines):
        line = lines[i].rstrip("\r")
        fence = re.match(r"^\s*```\s*([\w+-]*)\s*$", line)
        if fence:
            if in_code:
                out.append("{code}")
            else:
                out.append("{code:%s}" % fence.group(1) if fence.group(1) else "{code}")
            in_code = not in_code
            i += 1
            continue
        if in_code:
            out.append(line)
            i += 1
            continue
        if line.strip().startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i].strip())
                i += 1
            out.extend(convert_table(rows))
            indents, kinds = [], []
            continue
        item = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", line)
        if item and not re.fullmatch(r"\s*([-*_])\s*(\1\s*){2,}", line):
            ind = len(item.group(1).replace("\t", "    "))
            while indents and indents[-1] > ind:
                indents.pop()
            if not indents or indents[-1] < ind:
                indents.append(ind)
            depth = len(indents)
            kind = "#" if item.group(2)[0].isdigit() else "*"
            kinds = kinds[:depth - 1] + [kind]
            kinds += ["*"] * (depth - len(kinds))
            content = item.group(3)
            box = re.match(r"^\[( |x|X)\]\s+(.*)$", content)
            if box:
                content = ("☑ " if box.group(1).lower() == "x" else "☐ ") + inline(box.group(2))
            else:
                content = inline(content)
            out.append("".join(kinds) + " " + content)
            i += 1
            continue
        if line.strip():
            indents, kinds = [], []
        h = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if h:
            out.append(f"h{len(h.group(1))}. {inline(h.group(2))}")
        elif re.fullmatch(r"\s*([-*_])\s*(\1\s*){2,}", line):
            out.append("----")
        elif line.lstrip().startswith(">"):
            out.append("bq. " + inline(line.lstrip()[1:].strip()))
        else:
            out.append(inline(line))
        i += 1
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


# --------------------------------------------------------------------------- build & lint

def resolve_target(cfg, meta, project=None, issue_type=None):
    proj = project or meta.get("project") or cfg["default_project"]
    itype = issue_type or meta.get("issue_type") or cfg["default_issue_type"]
    return proj, itype


def build(cfg, meta, body, draft_path):
    """Return (fields, wiki_description, lint) where lint = {'errors': [...], 'warnings': [...], 'ok': [...]}."""
    errors, warnings, ok = [], [], []
    summary = str(meta.get("summary", "")).strip()
    if not summary:
        errors.append("front matter 'summary' is empty")
    elif "TODO" in summary or "<" in summary:
        errors.append("summary still has a template placeholder")
    elif len(summary) > 255:
        errors.append(f"summary is {len(summary)} chars (Jira max 255)")
    else:
        ok.append(f"summary ({len(summary)} chars)")

    clean = strip_comments(body)
    clean = re.sub(r"\A\s*#[ \t]+[^\n]*\n", "", clean, count=1)   # H1 title duplicates the summary
    pre, secs = split_sections(clean)
    names = {norm(h): (h, t) for h, t in secs}

    required_sections = (["Description", "Acceptance criteria", "Dependencies / links"]
                         if meta.get("story_format") == "concise"
                         else cfg["required_sections"])
    missing = [s for s in required_sections if norm(s) not in names]
    if missing:
        errors.append("missing required sections: " + ", ".join(missing))
    else:
        ok.append(f"all {len(required_sections)} required sections present ({len(secs)} sections)")

    for h, t in secs:
        if not t.strip():
            warnings.append(f"section '{h}' is empty")

    concise = meta.get("story_format") == "concise"
    if concise:
        extra_secs = [h for h, _ in secs if norm(h) not in {norm(s) for s in required_sections}]
        if extra_secs:
            errors.append("concise story allows only Description, Acceptance criteria, Dependencies / links; "
                          "remove: " + ", ".join(extra_secs))
        desc = names.get(norm("Description"))
        if desc:
            subs = re.findall(r"(?m)^###[ \t]+(.+?)[ \t]*$", desc[1])
            allowed_subs = {norm(s) for s in CONCISE_SUBSECTIONS}
            unknown = [s for s in subs if norm(s) not in allowed_subs]
            if unknown:
                errors.append("Description has subsections outside the concise format: " + ", ".join(unknown))
            missing_subs = [s for s in CONCISE_REQUIRED_SUBSECTIONS if norm(s) not in {norm(x) for x in subs}]
            if missing_subs:
                errors.append("Description is missing: " + ", ".join(missing_subs))
        internal = sorted(set(m.group(0) for m in INTERNAL_REF.finditer(clean)
                              if not FILE_PATTERN.search(m.group(0))))
        if internal:
            errors.append("story references working files that must not reach Jira: " + ", ".join(internal[:5]))

    ac = names.get(norm("Acceptance criteria"))
    if ac:
        items = re.findall(r"(?m)^\s*[-*]\s+(?:\[[ xX]\]\s+)?(.+)$", ac[1])
        if not items:
            errors.append("Acceptance criteria has no list items")
        else:
            bad = [x for x in items if not all(w in x.lower() for w in ("given", "when", "then"))]
            if bad:
                warnings.append(f"{len(bad)} of {len(items)} acceptance criteria are not Given/When/Then")
            else:
                ok.append(f"{len(items)} acceptance criteria, all Given/When/Then")

    todo = re.findall(r"(?m)^.*\bTODO\b.*$", clean)
    if todo:
        errors.append(f"{len(todo)} template TODO placeholder(s) left, e.g. '{todo[0].strip()[:80]}'")
    tbc = re.findall(r"⚠\s*TBC", clean)
    if tbc:
        warnings.append(f"{len(tbc)} item(s) marked ⚠ TBC (open questions travel with the story)")

    # acceptance criteria into its own field, if the Jira project has one
    ac_field = (cfg.get("fields") or {}).get("acceptance_criteria")
    desc_md = clean
    extra = {}
    if ac_field and ac:
        desc_md = re.sub(rf"(?ms)^##[ \t]+{re.escape(ac[0])}[ \t]*$.*?(?=^##[ \t]|\Z)", "", clean)
        extra[ac_field] = md_to_wiki(ac[1])
    wiki = md_to_wiki(desc_md)
    if len(wiki) > DESCRIPTION_LIMIT:
        errors.append(f"description is {len(wiki)} chars (Jira max {DESCRIPTION_LIMIT}); move the column "
                      f"spec to an attachment and reference it")
    else:
        ok.append(f"description {len(wiki):,} chars")

    labels = as_list(meta.get("labels")) or list(cfg.get("default_labels", []))
    fixed = [re.sub(r"\s+", "-", l) for l in labels]
    if fixed != labels:
        warnings.append("labels cannot contain spaces; replaced with '-'")

    fields = {"summary": summary, "description": wiki, "labels": fixed}
    comps = as_list(meta.get("components")) or list(cfg.get("default_components", []))
    if comps:
        fields["components"] = [{"name": c} for c in comps]
    if meta.get("priority"):
        fields["priority"] = {"name": meta["priority"]}
    parent = str(meta.get("parent") or "").strip()
    if parent:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]+-\d+", parent):
            errors.append(f"parent '{parent}' is not a Jira key")
        elif cfg.get("epic_link_field"):
            fields[cfg["epic_link_field"]] = parent
        else:
            fields["parent"] = {"key": parent}
    sp_field = (cfg.get("fields") or {}).get("story_points")
    if sp_field and str(meta.get("story_points") or "").strip():
        try:
            fields[sp_field] = float(meta["story_points"])
        except ValueError:
            errors.append(f"story_points '{meta['story_points']}' is not a number")
    fields.update(extra)
    fields.update(cfg.get("default_fields") or {})

    # attachments
    att_cfg = cfg.get("attachments") or {}
    allowed_ext = [e.lower() for e in att_cfg.get("allowed_extensions", [])]
    max_mb = float(att_cfg.get("max_mb", 10))
    files = []
    for a in as_list(meta.get("attachments")):
        p = Path(a)
        if not p.is_absolute():
            p = (Path(draft_path).parent / a) if (Path(draft_path).parent / a).exists() else ROOT / a
        if not p.exists():
            errors.append(f"attachment not found: {a}")
        elif not p.is_file():
            errors.append(f"attachment is not a file: {a}")
        elif allowed_ext and p.suffix.lower() not in allowed_ext:
            errors.append(f"attachment type not allowed: {p.name}")
        elif p.stat().st_size > max_mb * 1024 * 1024:
            errors.append(f"attachment over {max_mb:g} MB: {p.name}")
        elif meta.get("story_format") == "concise" and (
                p.suffix.lower() in (".csv", ".md") or ".jira" in p.resolve().parts):
            errors.append(f"attachment is a working/reference file, attach the original document instead: {p.name}")
        else:
            files.append(p)
    if files and not att_cfg.get("enabled", True):
        warnings.append("attachments are disabled in config; they will not be uploaded")
        files = []
    return fields, wiki, {"errors": errors, "warnings": warnings, "ok": ok}, files


def check_target(cfg, proj, itype, parent=None, offline=False):
    """Validate project/type against config and (unless offline) Jira. Returns (project_info, problems)."""
    problems = []
    if proj not in cfg["allowed_projects"]:
        problems.append(f"project '{proj}' is not in allowed_projects {cfg['allowed_projects']}")
    if itype not in cfg["allowed_issue_types"]:
        problems.append(f"issue type '{itype}' is not in allowed_issue_types {cfg['allowed_issue_types']}")
    if offline or proj not in cfg["allowed_projects"]:
        note = "(offline: not checked)" if offline else "(not checked: project not allowed)"
        return {"key": proj, "name": note, "issue_types": []}, problems
    info = get_project(cfg, proj)
    names = {t["name"].lower(): t for t in info["issue_types"]}
    t = names.get(itype.lower())
    if not t:
        problems.append(f"project {proj} has no issue type '{itype}'")
    elif t["subtask"] and not parent:
        problems.append(f"'{itype}' is a sub-task type and needs a parent")
    return info, problems


def fmt_size(n):
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


def print_report(cfg, meta, info, itype, fields, lint, files, problems, wiki_path, payload_path):
    allowed_here = [t["name"] for t in info["issue_types"] if not t["subtask"]]
    usable = [t for t in cfg["allowed_issue_types"] if not allowed_here or t in allowed_here]
    print("TARGET")
    print(f"  Jira:        {cfg['base_url']} ({cfg['deployment']})")
    print(f"  Project:     {info['key']} - {info['name']}   (allowed: {', '.join(cfg['allowed_projects'])})")
    print(f"  Issue type:  {itype}   (allowed here: {', '.join(usable) or '-'})")
    parent = fields.get("parent", {}).get("key") if isinstance(fields.get("parent"), dict) else \
        fields.get(cfg.get("epic_link_field") or "_none")
    print(f"  Parent:      {parent or '-'}")
    print(f"  Labels:      {', '.join(fields.get('labels', [])) or '-'}")
    print(f"  Components:  {', '.join(c['name'] for c in fields.get('components', [])) or '-'}")
    print(f"  Attachments: " + (", ".join(f"{p.name} ({fmt_size(p.stat().st_size)})" for p in files) or "-"))
    print("CONTENT")
    print(f"  Summary:     {fields.get('summary')}")
    print(f"  Rendered:    {rel(wiki_path)}")
    print(f"  Payload:     {rel(payload_path)}")
    print("LINT")
    for x in lint["ok"]:
        print(f"  OK    {x}")
    for x in lint["warnings"]:
        print(f"  WARN  {x}")
    for x in lint["errors"] + problems:
        print(f"  FAIL  {x}")
    status = meta.get("status", "draft")
    print(f"STATUS: {status}" + ("" if status == "approved" else "  (a human must approve before create)"))
    if meta.get("jira_key"):
        print(f"ALREADY CREATED: {meta['jira_key']} {meta.get('jira_url', '')}")


# --------------------------------------------------------------------------- commands

def cmd_check(cfg, args):
    print(f"Config:   {rel(CONFIG_PATH)}")
    print(f"Jira:     {cfg['base_url']} ({cfg['deployment']})")
    try:
        me = api(cfg, "GET", "/rest/api/2/myself")
    except JiraError as e:
        die(e.explain(), 1)
    print(f"User:     {me.get('displayName') or me.get('name')} ({me.get('emailAddress') or me.get('name', '')})")
    rc = 0
    for proj in cfg["allowed_projects"]:
        try:
            info = get_project(cfg, proj)
        except SystemExit:
            rc = 1
            continue
        names = [t["name"] for t in info["issue_types"] if not t["subtask"]]
        missing = [t for t in cfg["allowed_issue_types"] if t not in names]
        print(f"Project:  {info['key']} - {info['name']}; issue types: {', '.join(names)}")
        if missing:
            print(f"  WARN  allowed_issue_types not in {proj}: {', '.join(missing)}")
    print("Check complete." if rc == 0 else "Check finished with errors.")
    return rc


def prepare(cfg, args, project, itype):
    draft = Path(args.draft)
    if not draft.exists():
        die(f"Draft not found: {args.draft}", 2)
    meta, body, _ = parse_draft(draft)
    fields, wiki, lint, files = build(cfg, meta, body, draft)
    proj, itype = resolve_target(cfg, meta, project, itype)
    info, problems = check_target(cfg, proj, itype, meta.get("parent"), getattr(args, "offline", False))
    fields["project"] = {"key": proj}
    fields["issuetype"] = {"name": itype}
    wiki_path = draft.with_name("preview.jira.txt")
    payload_path = draft.with_name("payload.json")
    wiki_path.write_text(wiki, encoding="utf-8")
    payload_path.write_text(json.dumps({"fields": fields}, indent=2, ensure_ascii=False), encoding="utf-8")
    return draft, meta, info, proj, itype, fields, lint, files, problems, wiki_path, payload_path


def cmd_preview(cfg, args):
    draft, meta, info, proj, itype, fields, lint, files, problems, wp, pp = prepare(cfg, args, args.project, args.type)
    print_report(cfg, meta, info, itype, fields, lint, files, problems, wp, pp)
    return 3 if (lint["errors"] or problems) else 0


def cmd_create(cfg, args):
    draft, meta, info, proj, itype, fields, lint, files, problems, wp, pp = prepare(
        cfg, args, args.confirm_project, args.confirm_type)
    if meta.get("jira_key"):
        die(f"Already created as {meta['jira_key']} {meta.get('jira_url', '')}. Not creating a duplicate.", 3)
    if meta.get("status") != "approved":
        die(f"Draft status is '{meta.get('status', 'draft')}'. A human must review and approve it in chat "
            f"before it is created.", 3)
    if lint["errors"] or problems:
        print_report(cfg, meta, info, itype, fields, lint, files, problems, wp, pp)
        die("Fix the FAIL items above before creating.", 3)

    try:
        res = api(cfg, "POST", "/rest/api/2/issue", body={"fields": fields})
    except JiraError as e:
        die(f"Create failed: {e.explain()}", 1)
    key = res.get("key")
    url = f"{cfg['base_url']}/browse/{key}"
    update_front_matter(draft, {
        "status": "created", "jira_key": key, "jira_url": url, "project": proj, "issue_type": itype,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    print(f"CREATED {key}  {url}")

    failed = upload_attachments(cfg, key, files)
    uploaded = [rel(p) for p in files if p not in failed]
    if uploaded:
        update_front_matter(draft, {"uploaded_attachments": uploaded})
    if failed:
        print("The story was created; attach the files above by hand.")
    return 0


def upload_attachments(cfg, key, files):
    failed = []
    for p in files:
        boundary = uuid.uuid4().hex
        name = re.sub(r'["\r\n]', "_", p.name)
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        raw = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
               f"Content-Type: {ctype}\r\n\r\n").encode() + p.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        try:
            api(cfg, "POST", f"/rest/api/2/issue/{key}/attachments", raw=raw,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "X-Atlassian-Token": "no-check"})
            print(f"  attached {p.name}")
        except JiraError as e:
            failed.append(p)
            print(f"  WARN  could not attach {p.name}: {e.explain()}")
    return failed


def cmd_attach(cfg, args):
    draft = Path(args.draft)
    if not draft.exists():
        die(f"Draft not found: {args.draft}", 2)
    meta, body, _ = parse_draft(draft)
    key = str(meta.get("jira_key") or "").strip()
    if meta.get("status") != "created" or not re.fullmatch(r"[A-Z][A-Z0-9_]+-\d+", key):
        die("Attachments can only be uploaded from a draft already marked created with a Jira key.", 3)
    if args.confirm_issue != key:
        die(f"--confirm-issue must match the created issue key {key}.", 3)

    _, _, lint, files = build(cfg, meta, body, draft)
    if lint["errors"]:
        die("Cannot attach files because the draft has validation errors: " + "; ".join(lint["errors"]), 3)
    uploaded = {str(Path(p).resolve()) for p in as_list(meta.get("uploaded_attachments"))}
    files = [p for p in files if str(p.resolve()) not in uploaded]
    if not files:
        die("No new valid attachments are listed in the draft.", 3)
    expected = sorted(p.name for p in files)
    if sorted(args.confirm_files) != expected:
        die("--confirm-files must list exactly the filenames shown for this draft: " + ", ".join(expected), 3)

    print(f"ATTACHING to {key}: {', '.join(expected)}")
    failed = upload_attachments(cfg, key, files)
    successful = [str(p.resolve()) for p in files if p not in failed]
    if successful:
        update_front_matter(draft, {"uploaded_attachments": sorted(uploaded | set(successful))})
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser(description="Create a Jira story from an approved draft (REST API v2).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="verify config, credentials, projects and issue types")
    p = sub.add_parser("preview", help="lint + render + show target; writes nothing to Jira")
    p.add_argument("draft")
    p.add_argument("--project")
    p.add_argument("--type")
    p.add_argument("--offline", action="store_true", help="skip Jira calls (lint and render only)")
    c = sub.add_parser("create", help="create the issue; needs status: approved and explicit confirmation")
    c.add_argument("draft")
    c.add_argument("--confirm-project", required=True)
    c.add_argument("--confirm-type", required=True)
    a = sub.add_parser("attach", help="upload confirmed attachments to an already-created issue")
    a.add_argument("draft")
    a.add_argument("--confirm-issue", required=True)
    a.add_argument("--confirm-files", required=True, nargs="+")
    args = ap.parse_args()
    cfg = load_config()
    sys.exit({"check": cmd_check, "preview": cmd_preview, "create": cmd_create,
              "attach": cmd_attach}[args.cmd](cfg, args))


if __name__ == "__main__":
    main()
