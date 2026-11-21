"""Step 1: raw CSV -> cleaned CSV + JSON summaries in data/processed/.

    python run_pipeline.py [path/to/raw.csv]
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from pipeline import analytics, cleaning

BASE = Path(__file__).parent
RAW = BASE / "data" / "raw" / "Sample - Superstore.csv"
OUT = BASE / "data" / "processed"


def run(raw_path: Path = RAW) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    raw, encoding = cleaning.load_raw(raw_path)
    df, report = cleaning.clean(raw, encoding)

    clean_path = OUT / "superstore_clean.csv"
    df.to_csv(clean_path, index=False)
    (OUT / "cleaning_report.json").write_text(json.dumps(report.to_dict(), indent=2))
    summary = analytics.dashboard(df, metric="sales", dim="category")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    logging.info("Wrote %s (%d rows)", clean_path, len(df))
    return clean_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        run(Path(sys.argv[1]) if len(sys.argv) > 1 else RAW)
    except (FileNotFoundError, ValueError) as exc:
        logging.error("%s", exc)
        sys.exit(1)
