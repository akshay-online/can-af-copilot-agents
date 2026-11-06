#!/usr/bin/env python3
"""Turn requirement inputs (Word, Excel, CSV, Markdown, text) into Markdown Copilot can read.
Python standard library only.

  python read_inputs.py <file-or-folder> [...] --out .jira/drafts/<slug>/inputs [--max-rows 300]

  .docx  headings, paragraphs, lists and tables, in document order (tracked deletions excluded)
  .xlsx  every sheet as a Markdown table; dates converted; hidden sheets marked
  .csv   headers, column count and row count only. Data values are never written out
  .md / .txt  copied as-is
Writes one <name>.md per input plus _index.md, and prints the index.
"""
import argparse
import csv
import io
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def cell_md(s):
    return str(s).replace("|", "\\|").replace("\r", "").replace("\n", "<br>").strip()


def md_table(rows):
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [list(r) + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(cell_md(c) or " " for c in rows[0]) + " |",
           "|" + "---|" * width]
    out += ["| " + " | ".join(cell_md(c) for c in r) + " |" for r in rows[1:]]
    return "\n".join(out)


# ------------------------------------------------------------------ docx

def docx_to_md(path):
    with zipfile.ZipFile(path) as z:
        doc = ET.fromstring(z.read("word/document.xml"))
        styles = {}
        if "word/styles.xml" in z.namelist():
            for st in ET.fromstring(z.read("word/styles.xml")).iter(W + "style"):
                name = st.find(W + "name")
                styles[st.get(W + "styleId")] = (name.get(W + "val") if name is not None else "").lower()

    def run_text(el):
        parts = []
        for node in el.iter():
            if node.tag == W + "t":
                parts.append(node.text or "")
            elif node.tag == W + "tab":
                parts.append("\t")
            elif node.tag in (W + "br", W + "cr"):
                parts.append("\n")
        return "".join(parts)

    def para(p):
        text = run_text(p).strip()
        if not text:
            return ""
        ppr = p.find(W + "pPr")
        sid, is_list, lvl = "", False, 0
        if ppr is not None:
            ps = ppr.find(W + "pStyle")
            sid = ps.get(W + "val") if ps is not None else ""
            num = ppr.find(W + "numPr")
            if num is not None:
                is_list = True
                il = num.find(W + "ilvl")
                lvl = int(il.get(W + "val")) if il is not None else 0
        name = styles.get(sid, sid.lower())
        m = re.match(r"heading\s*(\d)", name)
        if m:
            return "#" * min(int(m.group(1)) + 1, 6) + " " + text
        if name == "title":
            return "# " + text
        if is_list or "list" in name:
            return "  " * lvl + "- " + text
        return text

    out = []
    body = doc.find(W + "body")
    for el in body:
        if el.tag == W + "p":
            t = para(el)
            if t:
                out.append(t)
        elif el.tag == W + "tbl":
            rows = []
            for tr in el.iter(W + "tr"):
                rows.append([" / ".join(filter(None, (run_text(p).strip() for p in tc.iter(W + "p"))))
                             for tc in tr.findall(W + "tc")])
            if rows:
                out.append(md_table(rows))
    return "\n\n".join(out), {}


# ------------------------------------------------------------------ xlsx

BUILTIN_DATE = set(range(14, 23)) | {45, 46, 47}


def col_index(ref):
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def is_date_format(code):
    code = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", code or "").lower()
    return bool(re.search(r"[dmy]", code)) and "general" not in code


def xlsx_to_md(path, max_rows):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        pr = wb.find(S + "workbookPr")
        base = datetime(1904, 1, 1) if pr is not None and pr.get("date1904") in ("1", "true") \
            else datetime(1899, 12, 30)
        rels = {r.get("Id"): r.get("Target")
                for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).iter(PR + "Relationship")}
        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(S + "si"):
                shared.append("".join(t.text or "" for t in si.iter(S + "t")
                                      if not any(t in rph.iter() for rph in si.findall(S + "rPh"))))
        date_styles = set()
        if "xl/styles.xml" in names:
            st = ET.fromstring(z.read("xl/styles.xml"))
            custom = {int(n.get("numFmtId")): n.get("formatCode") for n in st.iter(S + "numFmt")}
            xfs = st.find(S + "cellXfs")
            for i, xf in enumerate(xfs.findall(S + "xf") if xfs is not None else []):
                fid = int(xf.get("numFmtId", 0))
                if fid in BUILTIN_DATE or (fid in custom and is_date_format(custom[fid])):
                    date_styles.add(i)

        parts, meta = [], {"sheets": []}
        for sh in wb.iter(S + "sheet"):
            target = rels.get(sh.get(R + "id"), "")
            target = target.lstrip("/") if target.startswith("/") else "xl/" + target
            if target not in names:
                continue
            ws = ET.fromstring(z.read(target))
            grid = {}
            for row in ws.iter(S + "row"):
                for c in row.findall(S + "c"):
                    ref, t, style = c.get("r"), c.get("t"), int(c.get("s", 0))
                    v = c.find(S + "v")
                    val = v.text if v is not None else ""
                    if t == "s" and val:
                        val = shared[int(val)]
                    elif t == "inlineStr":
                        val = "".join(x.text or "" for x in c.iter(S + "t"))
                    elif t == "b":
                        val = "TRUE" if val == "1" else "FALSE"
                    elif t in (None, "n") and val and style in date_styles:
                        try:
                            d = base + timedelta(days=float(val))
                            val = d.strftime("%Y-%m-%d") if float(val).is_integer() else d.strftime("%Y-%m-%d %H:%M:%S")
                        except (ValueError, OverflowError):
                            pass
                    elif t in (None, "n") and val:
                        try:
                            f = float(val)
                            val = str(int(f)) if f.is_integer() and abs(f) < 1e15 else str(round(f, 10))
                        except ValueError:
                            pass
                    if val not in ("", None):
                        rnum = int(re.search(r"\d+", ref).group(0))
                        grid.setdefault(rnum, {})[col_index(ref)] = val
            name = sh.get("name")
            hidden = sh.get("state") in ("hidden", "veryHidden")
            title = f"## Sheet: {name}" + (" (hidden)" if hidden else "")
            if not grid:
                parts.append(title + "\n\n_(empty)_")
                meta["sheets"].append(f"{name} (empty)")
                continue
            ncols = max(max(r) for r in grid.values()) + 1
            rows = [[grid[r].get(c, "") for c in range(ncols)] for r in sorted(grid)]
            # drop columns that are empty everywhere
            keep = [c for c in range(ncols) if any(r[c] for r in rows)]
            rows = [[r[c] for c in keep] for r in rows]
            note = ""
            if len(rows) - 1 > max_rows:
                note = f"\n\n_Truncated: showing {max_rows} of {len(rows) - 1} rows. This sheet looks like data, " \
                       f"not a spec; use the header row only._"
                rows = rows[:max_rows + 1]
            parts.append(f"{title}\n\n{md_table(rows)}{note}")
            meta["sheets"].append(f"{name} ({len(grid)} rows" + (", hidden" if hidden else "") + ")")
    return "\n\n".join(parts), meta


# ------------------------------------------------------------------ csv

def csv_to_md(path):
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sample = text[:20000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;|\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    rows = [r for r in rows if any(c.strip() for c in r)]
    header = rows[0] if rows else []
    delim = {"\t": "TAB", ",": "comma", ";": "semicolon", "|": "pipe"}.get(dialect.delimiter, dialect.delimiter)
    lines = [f"- Delimiter: {delim}", f"- Encoding: {enc}", f"- Columns: {len(header)}",
             f"- Data rows (excluding header): {max(len(rows) - 1, 0)}", "",
             "Data values are not shown on purpose. Header row:", "",
             md_table([["#", "Column"]] + [[str(i + 1), h.strip()] for i, h in enumerate(header)])]
    return "\n".join(lines), {"columns": len(header), "rows": max(len(rows) - 1, 0)}


# ------------------------------------------------------------------ main

SUPPORTED = {".docx": "Word", ".xlsx": "Excel", ".xlsm": "Excel", ".csv": "CSV", ".md": "Markdown", ".txt": "Text"}
UNSUPPORTED = {".doc": "save it as .docx", ".xls": "save it as .xlsx", ".pdf": "save it as .docx or paste the text",
               ".pptx": "export the relevant slides as text"}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-rows", type=int, default=300)
    a = ap.parse_args()

    files = []
    for p in map(Path, a.paths):
        if p.is_dir():
            files += sorted(f for f in p.rglob("*") if f.is_file() and not f.name.startswith(("~$", ".")))
        elif p.exists():
            files.append(p)
        else:
            print(f"WARN  not found: {p}")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    index = ["# Inputs", "", "| File | Type | Size | Converted to | Notes |", "|---|---|---|---|---|"]
    for f in files:
        ext = f.suffix.lower()
        size = f"{f.stat().st_size / 1024:.0f} KB"
        if ext not in SUPPORTED:
            hint = UNSUPPORTED.get(ext, "not a requirements format")
            index.append(f"| {cell_md(f.name)} | {ext or '-'} | {size} | - | skipped: {hint} |")
            continue
        try:
            if ext == ".docx":
                body, meta = docx_to_md(f)
                note = ""
            elif ext in (".xlsx", ".xlsm"):
                body, meta = xlsx_to_md(f, a.max_rows)
                note = "sheets: " + "; ".join(meta["sheets"])
            elif ext == ".csv":
                body, meta = csv_to_md(f)
                note = f"{meta['columns']} columns, {meta['rows']} rows (headers only)"
            else:
                body, note = f.read_text(encoding="utf-8", errors="replace"), ""
        except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
            index.append(f"| {cell_md(f.name)} | {SUPPORTED[ext]} | {size} | - | could not read: {cell_md(e)} |")
            continue
        target = out / (f.name + ".md")
        target.write_text(f"# {f.name}\n\nSource: `{f}`\n\n{body}\n", encoding="utf-8")
        index.append(f"| {cell_md(f.name)} | {SUPPORTED[ext]} | {size} | `{target.name}` | {cell_md(note)} |")
    (out / "_index.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    print("\n".join(index))
    print(f"\nWritten to {out}")


if __name__ == "__main__":
    main()
