---
name: spec-file-conversion
description: Convert requirement Word documents (.docx) to Markdown and Excel workbooks (.xlsx/.xlsm) into one CSV per sheet. Use when preparing files from docs/ or another requirements folder for story drafting.
---

# Spec file conversion

Use the repository's existing converters to prepare Word and Excel inputs for the story-writer. Write all generated files beneath the current draft's `inputs/` output directory; do not write converted artifacts back into `docs/` or beside the source files.

The scripts require `python-docx` for Word conversion and `pandas` plus `openpyxl` for Excel conversion. If a converter reports a missing module, ask before installing dependencies, then install the named package with `python -m pip install <package>` and retry.

## Word documents

For each `.docx` file, run:

```powershell
python scripts/word_to_md.py <word-file> .jira/drafts/<slug>/inputs
```

This writes `<document-name>.md` into the output directory and extracts embedded images into a sibling `<document-name>_images/` folder. Read the Markdown output for requirements. The converter supports `.docx`; ask for a `.docx` copy if a source is `.doc`.

## Excel workbooks

For each `.xlsx` or `.xlsm` workbook, run:

```powershell
python scripts/excel_to_csv.py <workbook-file> .jira/drafts/<slug>/inputs
```

This creates `.jira/drafts/<slug>/inputs/<workbook-name>/` and writes one CSV per worksheet there. Read the CSVs when they contain column specifications or other requirements. Treat sample/data sheets as source context only: do not copy row values into the Jira story. Ask for `.xlsx` or `.xlsm` if the source is an unsupported legacy `.xls` workbook.

## Other input files

For `.csv` sample files, do not read or quote row values. Use the story-writer skill's `read_inputs.py` on the CSV file to produce a Markdown summary containing only the headers and row count, with output directed to the same draft `inputs/` directory. Read existing `.md` and `.txt` requirements directly.

Keep the original source locations available for the post-creation attachment step. Attachment paths may be repo-relative (for example `docs/<folder>/requirements.docx`) or absolute for an external/shared folder, provided the Jira script's running machine can read them. Converted artifacts belong under `.jira/drafts/<slug>/inputs/`; do not modify source files in `docs/` or upload converted copies unless the user selects them.
