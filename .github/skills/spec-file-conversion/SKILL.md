---
name: spec-file-conversion
description: Convert requirement Word documents (.docx) to Markdown and Excel workbooks (.xlsx/.xlsm) into one CSV per sheet. Use when preparing files from docs/ or another requirements folder for story drafting.
---

# Spec file conversion

Use the repository's existing converters to prepare Word and Excel inputs for the story-writer and feature-writer. Write generated files beneath `.jira/drafts/<set-slug>/inputs/<spec-folder-name>/`, where `<spec-folder-name>` is the name of the supplied specs directory. If the user supplies files rather than a directory, use their common parent directory's name; if there is no single common parent, ask which specs-folder name to use. Do not write converted artifacts back into `docs/` or beside source files. Converted files are reference material for the agent only: never name them in a Jira item and never attach them.

### Existing input/output check

Before conversion, inspect the target `inputs/<spec-folder-name>/` directory and determine the generated relative output paths. Compare any same-format source copies by content without displaying their contents. If a generated output path/name already exists, convert that source into a temporary staging directory under the same draft's `inputs/` area, then compare the staged output and existing output by content (for example, SHA-256); never stage over the existing file.

- If the same relative path/name and same content already exist, ask whether to use the existing inputs or reconvert the source documents and overwrite them.
- If a target path/name exists with different content, ask the same question before replacing anything.
- If only some outputs collide, explain which files conflict. Do not overwrite existing files unless the user explicitly chooses reconversion/overwrite. If the user chooses the existing inputs, use those existing files and do not run conversion over them.
- If the directory exists but there are no path/name collisions, add the new outputs without altering existing files.

When checking raw sample CSVs, do not inspect or disclose row values. Compare files without displaying their contents; use paths, names, and a content hash or equivalent byte comparison. Do not infer sameness from the filename alone. Resolve any ambiguity with the user before writing. Remove temporary staging outputs after the user chooses, and never read staged or existing sample CSV row values.

The scripts require `python-docx` for Word conversion and `pandas` plus `openpyxl` for Excel conversion. If a converter reports a missing module, ask before installing dependencies, then install the named package with `python -m pip install <package>` and retry.

## Word documents

For each `.docx` file, run:

```powershell
python scripts/word_to_md.py <word-file> .jira/drafts/<slug>/inputs/<spec-folder-name>
```

This writes `<document-name>.md` into the output directory and extracts embedded images into a sibling `<document-name>_images/` folder. Read the Markdown output for requirements. The converter supports `.docx`; ask for a `.docx` copy if a source is `.doc`.

## Excel workbooks

For each `.xlsx` or `.xlsm` workbook, run:

```powershell
python scripts/excel_to_csv.py <workbook-file> .jira/drafts/<slug>/inputs/<spec-folder-name>
```

This creates `.jira/drafts/<slug>/inputs/<spec-folder-name>/<workbook-name>/` and writes one CSV per worksheet there. Read the CSVs when they contain column specifications or other requirements. Treat sample/data sheets as source context only: do not copy row values into the Jira item. Ask for `.xlsx` or `.xlsm` if the source is an unsupported legacy `.xls` workbook.

## Other input files

For `.csv` sample files, do not read or quote row values. Use the story-writer skill's `read_inputs.py` on the CSV file to produce a Markdown summary containing only the headers and row count, with output directed to `.jira/drafts/<slug>/inputs/<spec-folder-name>/`. Read existing `.md` and `.txt` requirements directly.

Keep the original source locations available for the post-creation attachment step. Attachment paths may be repo-relative (for example `docs/<folder>/requirements.docx`) or absolute for an external/shared folder, provided the Jira script's running machine can read them. Converted artifacts belong under `.jira/drafts/<slug>/inputs/<spec-folder-name>/`; do not modify source files in `docs/` or upload converted copies unless the user selects them.
