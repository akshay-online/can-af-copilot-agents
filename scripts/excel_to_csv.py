"""Convert each sheet of an Excel workbook into a separate CSV file.

Usage:
    python excel_to_csv.py <excel_file> [output_dir]

A folder named after the Excel file is created (inside output_dir, defaulting
to the Excel file's directory), and each sheet is written as <sheet_name>.csv.
"""

import argparse
import re
import sys
from pathlib import Path

import pandas as pd


def safe_filename(name: str) -> str:
    # Strip characters that are invalid in Windows/Unix file names.
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name)).strip(" .")
    return cleaned or "sheet"


def convert(excel_path: Path, output_root: Path | None = None) -> Path:
    if not excel_path.is_file():
        raise FileNotFoundError(f"Excel file not found: {excel_path}")

    output_root = output_root or excel_path.parent
    output_dir = output_root / safe_filename(excel_path.stem)
    output_dir.mkdir(parents=True, exist_ok=True)

    sheets = pd.read_excel(excel_path, sheet_name=None, dtype=str)

    used_names: set[str] = set()
    for sheet_name, df in sheets.items():
        base = safe_filename(sheet_name)
        name, i = base, 1
        while name.lower() in used_names:
            i += 1
            name = f"{base}_{i}"
        used_names.add(name.lower())

        csv_path = output_dir / f"{name}.csv"
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"Wrote {csv_path}")

    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert Excel sheets to CSV files.")
    parser.add_argument("excel_file", type=Path, help="Path to the .xlsx/.xls file")
    parser.add_argument("output_dir", type=Path, nargs="?", help="Optional output root directory")
    args = parser.parse_args()

    try:
        out = convert(args.excel_file, args.output_dir)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Done. CSV files are in: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


## usage

# Example:
#     python excel_to_csv.py workbook.xlsx
#     python excel_to_csv.py workbook.xlsx output_directory
# install
#     pip install pandas openpyxl