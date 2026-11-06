"""Convert a Word (.docx) document into a Markdown (.md) file.

Usage:
    python word_to_md.py <word_file> [output_dir]

The Markdown file is written as <output_dir>/<document_name>.md (output_dir
defaults to the Word file's directory). Embedded images are extracted into
<output_dir>/<document_name>_images/ and referenced from the Markdown.

Supports headings, paragraphs, bold/italic/strikethrough/monospace text,
hyperlinks, bulleted and numbered (nested) lists, quotes, tables and images.
"""

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import quote

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.text.run import Run

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
V_NS = "urn:schemas-microsoft-com:vml"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"

MONO_FONTS = {"courier", "courier new", "consolas", "lucida console", "monaco", "menlo", "source code pro"}
INLINE_CONTAINERS = {"ins", "smartTag", "fldSimple", "customXml", "sdt", "sdtContent"}
# Placeholder for manual line breaks; resolved differently in paragraphs, lists and tables.
BR = "\x00BR\x00"
EDGE_BREAKS = re.compile(rf"^(?:\s|{re.escape(BR)})+|(?:\s|{re.escape(BR)})+$")
BLOCK_START = re.compile(r"^(#{1,6}\s|[-+]\s|\d+[.)]\s|>)")


def w(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


def safe_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name)).strip(" .")
    return cleaned or "document"


def escape_md(text: str) -> str:
    return re.sub(r"([\\`*_\[\]<>])", r"\\\1", text)


class DocxToMarkdown:
    def __init__(self, docx_path: Path, output_dir: Path):
        self.doc = Document(str(docx_path))
        name = safe_filename(docx_path.stem)
        self.md_path = output_dir / f"{name}.md"
        self.image_dir = output_dir / f"{name}_images"
        self.images: dict[str, str] = {}
        self.num_formats = self._load_numbering()

    # ---------- document structure ----------

    def convert(self) -> Path:
        out: list[str] = []
        prev_kind = None
        for kind, text in self._iter_blocks(self.doc.element.body):
            if out:
                out.append("\n" if kind == prev_kind == "list" else "\n\n")
            out.append(text)
            prev_kind = kind

        self.md_path.parent.mkdir(parents=True, exist_ok=True)
        self.md_path.write_text("".join(out) + "\n", encoding="utf-8")
        return self.md_path

    def _iter_blocks(self, container):
        for child in container.iterchildren():
            if child.tag == w("p"):
                block = self._paragraph(child)
                if block:
                    yield block
            elif child.tag == w("tbl"):
                table = self._table(child)
                if table:
                    yield "table", table
            elif child.tag == w("sdt"):
                content = child.find(w("sdtContent"))
                if content is not None:
                    yield from self._iter_blocks(content)

    def _paragraph(self, p):
        para = Paragraph(p, self.doc)
        style = para.style.name if para.style is not None else ""
        level = self._heading_level(style)
        text = EDGE_BREAKS.sub("", self._render_inline(p, para, plain=level > 0))
        if not text:
            return None

        if level:
            return "heading", f"{'#' * min(level, 6)} {text.replace(BR, ' ')}"

        list_info = self._list_info(p, para, style)
        if list_info:
            ordered, ilvl = list_info
            indent = "    " * ilvl
            marker = "1." if ordered else "-"
            body = text.replace(BR, "  \n" + indent + " " * (len(marker) + 1))
            return "list", f"{indent}{marker} {body}"

        if style.lower().startswith(("quote", "intense quote")):
            return "quote", "> " + text.replace(BR, "  \n> ")

        if BLOCK_START.match(text):
            text = "\\" + text
        return "para", text.replace(BR, "  \n")

    @staticmethod
    def _heading_level(style: str) -> int:
        s = style.lower()
        if s == "title":
            return 1
        m = re.match(r"heading\s*(\d)", s)
        return int(m.group(1)) if m else 0

    # ---------- lists ----------

    def _load_numbering(self) -> dict[tuple[str, str], str]:
        try:
            numbering = self.doc.part.numbering_part.element
        except (KeyError, NotImplementedError):
            return {}

        abstract: dict[str, dict[str, str]] = {}
        for an in numbering.iterchildren(w("abstractNum")):
            levels = {}
            for lvl in an.iterchildren(w("lvl")):
                fmt = lvl.find(w("numFmt"))
                levels[lvl.get(w("ilvl"))] = fmt.get(w("val")) if fmt is not None else "decimal"
            abstract[an.get(w("abstractNumId"))] = levels

        formats = {}
        for num in numbering.iterchildren(w("num")):
            ref = num.find(w("abstractNumId"))
            if ref is None:
                continue
            for ilvl, fmt in abstract.get(ref.get(w("val")), {}).items():
                formats[(num.get(w("numId")), ilvl)] = fmt
        return formats

    def _list_info(self, p, para, style: str):
        s = style.lower()
        m = re.search(r"(\d+)$", s) if s.startswith("list") else None
        style_level = str(int(m.group(1)) - 1) if m else "0"

        sources = [p]
        if para.style is not None:
            sources.append(para.style.element)
        for src in sources:
            num_pr = src.find(f"{w('pPr')}/{w('numPr')}")
            if num_pr is None:
                continue
            num_id = num_pr.find(w("numId"))
            nid = num_id.get(w("val")) if num_id is not None else None
            if nid == "0":
                return None
            if nid:
                ilvl_el = num_pr.find(w("ilvl"))
                ilvl = ilvl_el.get(w("val")) if ilvl_el is not None else style_level
                fmt = self.num_formats.get((nid, ilvl), self.num_formats.get((nid, "0"), "bullet"))
                return fmt not in ("bullet", "none"), int(ilvl)

        if s.startswith(("list bullet", "list number")):
            return s.startswith("list number"), int(style_level)
        return None

    # ---------- inline content ----------

    def _render_inline(self, container, para, plain: bool) -> str:
        segments: list[tuple[tuple | None, str]] = []
        self._collect(container, para, plain, segments)
        return self._format_segments(segments)

    def _collect(self, container, para, plain, segments):
        for child in container.iterchildren():
            tag = child.tag
            if tag == w("r"):
                self._collect_run(child, para, plain, segments)
            elif tag == w("hyperlink"):
                label = EDGE_BREAKS.sub("", self._render_inline(child, para, plain))
                url = self._hyperlink_url(child)
                if label:
                    segments.append((None, f"[{label}]({url})" if url else label))
            elif tag in {w(t) for t in INLINE_CONTAINERS}:
                self._collect(child, para, plain, segments)

    def _collect_run(self, r, para, plain, segments):
        fmt = (False, False, False, False) if plain else self._run_format(Run(r, para))
        for child in r.iterchildren():
            tag = child.tag
            if tag == w("t"):
                segments.append((fmt, child.text or ""))
            elif tag == w("tab"):
                segments.append((fmt, " "))
            elif tag in (w("br"), w("cr")):
                if child.get(w("type")) != "page":
                    segments.append((None, BR))
            elif tag in (w("drawing"), w("pict"), w("object"), f"{{{MC_NS}}}AlternateContent"):
                image = self._image(child)
                if image:
                    segments.append((None, image))

    @staticmethod
    def _run_format(run: Run) -> tuple:
        style = run.style.name.lower() if run.style is not None else ""
        font = (run.font.name or "").lower()
        bold = bool(run.bold) or style == "strong"
        italic = bool(run.italic) or style == "emphasis"
        strike = bool(run.font.strike) or bool(run.font.double_strike)
        code = font in MONO_FONTS or "code" in style
        return bold, italic, strike, code

    @staticmethod
    def _format_segments(segments) -> str:
        merged: list[list] = []
        for fmt, text in segments:
            if merged and fmt is not None and merged[-1][0] == fmt:
                merged[-1][1] += text
            else:
                merged.append([fmt, text])

        out = []
        for fmt, text in merged:
            if fmt is None:
                out.append(text)
                continue
            lead, core, trail = re.match(r"^(\s*)(.*?)(\s*)$", text, re.S).groups()
            if not core:
                out.append(text)
                continue
            bold, italic, strike, code = fmt
            if code:
                tick = "``" if "`" in core else "`"
                core = f"{tick}{core}{tick}"
            else:
                core = escape_md(core)
            if strike:
                core = f"~~{core}~~"
            if italic:
                core = f"*{core}*"
            if bold:
                core = f"**{core}**"
            out.append(f"{lead}{core}{trail}")
        return "".join(out)

    def _hyperlink_url(self, link) -> str | None:
        rid = link.get(f"{{{R_NS}}}id")
        anchor = link.get(w("anchor"))
        if rid:
            rel = self.doc.part.rels.get(rid)
            if rel is not None:
                url = rel.target_ref
                return f"{url}#{anchor}" if anchor else url
        return f"#{anchor}" if anchor else None

    # ---------- images ----------

    def _image(self, elem) -> str | None:
        rid = None
        for blip in elem.iter(f"{{{A_NS}}}blip"):
            rid = blip.get(f"{{{R_NS}}}embed") or blip.get(f"{{{R_NS}}}link")
            break
        if not rid:
            for data in elem.iter(f"{{{V_NS}}}imagedata"):
                rid = data.get(f"{{{R_NS}}}id")
                break
        if not rid:
            return None

        alt = ""
        for doc_pr in elem.iter(f"{{{WP_NS}}}docPr"):
            alt = doc_pr.get("descr") or doc_pr.get("title") or ""
            break

        ref = self._save_image(rid)
        if not ref:
            return None
        alt = " ".join(alt.split()) or "image"
        return f"![{escape_md(alt)}]({ref})"

    def _save_image(self, rid: str) -> str | None:
        if rid in self.images:
            return self.images[rid]
        rel = self.doc.part.rels.get(rid)
        if rel is None:
            return None
        if rel.is_external:
            ref = rel.target_ref
        else:
            part = rel.target_part
            ext = Path(str(part.partname)).suffix or ".png"
            self.image_dir.mkdir(parents=True, exist_ok=True)
            filename = f"image{len(self.images) + 1}{ext}"
            (self.image_dir / filename).write_bytes(part.blob)
            ref = f"{quote(self.image_dir.name)}/{filename}"
        self.images[rid] = ref
        return ref

    # ---------- tables ----------

    def _table(self, tbl) -> str | None:
        table = Table(tbl, self.doc)
        rows = []
        for row in table.rows:
            cells, prev_tc = [], None
            for cell in row.cells:
                # Horizontally merged cells are returned repeatedly; show content once.
                cells.append("" if cell._tc is prev_tc else self._cell_text(cell))
                prev_tc = cell._tc
            rows.append(cells)

        rows = [r for r in rows if r]
        if not rows:
            return None
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]

        lines = [
            "| " + " | ".join(rows[0]) + " |",
            "| " + " | ".join(["---"] * width) + " |",
        ]
        lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        return "\n".join(lines)

    def _cell_text(self, cell) -> str:
        parts = []
        for p in cell._tc.iter(w("p")):
            para = Paragraph(p, self.doc)
            style = para.style.name if para.style is not None else ""
            text = EDGE_BREAKS.sub("", self._render_inline(p, para, plain=False))
            if not text:
                continue
            if self._list_info(p, para, style):
                text = "• " + text
            parts.append(text)
        text = "<br>".join(parts).replace(BR, "<br>").replace("\n", " ")
        return text.replace("|", "\\|")


def convert(word_path: Path, output_dir: Path | None = None) -> Path:
    if not word_path.is_file():
        raise FileNotFoundError(f"Word file not found: {word_path}")
    if word_path.suffix.lower() != ".docx":
        raise ValueError("Only .docx files are supported. Re-save .doc files as .docx in Word first.")
    return DocxToMarkdown(word_path, output_dir or word_path.parent).convert()


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert a Word (.docx) document to Markdown.")
    parser.add_argument("word_file", type=Path, help="Path to the .docx file")
    parser.add_argument("output_dir", type=Path, nargs="?", help="Optional output directory")
    args = parser.parse_args()

    try:
        md_path = convert(args.word_file, args.output_dir)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Done. Markdown written to: {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


## usage

# Example:
#     python word_to_md.py document.docx
#     python word_to_md.py document.docx output_directory
# install
#     pip install python-docx
