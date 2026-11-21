"""Ingestion and cleansing of the raw Superstore CSV.

Every step records how many rows it touched, so the cleaning can be audited
and explained (see CleaningReport / data/processed/cleaning_report.json).
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

REQUIRED_COLUMNS = [
    "Row ID", "Order ID", "Order Date", "Ship Date", "Ship Mode", "Customer ID",
    "Customer Name", "Segment", "Country", "City", "State", "Postal Code", "Region",
    "Product ID", "Category", "Sub-Category", "Product Name", "Sales", "Quantity",
    "Discount", "Profit",
]
TEXT_COLUMNS = [
    "Order ID", "Ship Mode", "Customer ID", "Customer Name", "Segment", "Country",
    "City", "State", "Region", "Product ID", "Category", "Sub-Category", "Product Name",
]
NUMERIC_COLUMNS = ["Sales", "Quantity", "Discount", "Profit"]

# Discount bands used for the "does discounting hurt profit?" analysis.
DISCOUNT_BINS = [-0.001, 0.0, 0.10, 0.20, 0.30, 0.50, 1.0]
DISCOUNT_LABELS = ["None", "1-10%", "11-20%", "21-30%", "31-50%", "Over 50%"]


@dataclass
class CleaningReport:
    rows_in: int = 0
    rows_out: int = 0
    encoding_used: str = ""
    duplicate_rows_removed: int = 0
    unparseable_dates_removed: int = 0
    non_numeric_removed: int = 0
    invalid_values_removed: int = 0
    ship_before_order_removed: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def load_raw(path: str | Path) -> tuple[pd.DataFrame, str]:
    """Read the CSV, trying common encodings (the Superstore file is Latin-1)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Raw data file not found: {path}")
    last_error: Exception | None = None
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return pd.read_csv(path, encoding=encoding), encoding
        except UnicodeDecodeError as exc:
            last_error = exc
            log.warning("Could not read %s as %s, trying next encoding", path.name, encoding)
        except pd.errors.EmptyDataError as exc:
            raise ValueError(f"{path.name} is empty") from exc
    raise ValueError(f"Could not decode {path.name}") from last_error


def clean(df: pd.DataFrame, encoding: str = "") -> tuple[pd.DataFrame, CleaningReport]:
    """Validate, normalise and enrich the raw dataframe."""
    report = CleaningReport(rows_in=len(df), encoding_used=encoding)

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Dataset is missing required columns: {missing}")
    df = df[REQUIRED_COLUMNS].copy()

    # 1. Whitespace / text normalisation
    for col in TEXT_COLUMNS:
        df[col] = df[col].astype("string").str.strip()

    # 2. Duplicates (exact duplicates, and repeated Row IDs)
    before = len(df)
    df = df.drop_duplicates().drop_duplicates(subset="Row ID")
    report.duplicate_rows_removed = before - len(df)

    # 3. Dates (source format is month/day/year)
    for col in ("Order Date", "Ship Date"):
        df[col] = pd.to_datetime(df[col], format="%m/%d/%Y", errors="coerce")
    before = len(df)
    df = df.dropna(subset=["Order Date", "Ship Date"])
    report.unparseable_dates_removed = before - len(df)

    # 4. Numeric coercion
    for col in NUMERIC_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    before = len(df)
    df = df.dropna(subset=NUMERIC_COLUMNS + TEXT_COLUMNS)
    report.non_numeric_removed = before - len(df)

    # 5. Business-rule validation
    before = len(df)
    valid = (df["Sales"] > 0) & (df["Quantity"] > 0) & df["Discount"].between(0, 1)
    df = df[valid]
    report.invalid_values_removed = before - len(df)

    before = len(df)
    df = df[df["Ship Date"] >= df["Order Date"]]
    report.ship_before_order_removed = before - len(df)

    # 6. Postal codes lose leading zeros when read as integers (e.g. 06824 -> 6824)
    df["Postal Code"] = df["Postal Code"].astype(str).str.zfill(5)
    report.notes.append("Postal codes restored to 5 digits (leading zeros).")

    # 7. Feature engineering
    df["Year"] = df["Order Date"].dt.year
    df["Month"] = df["Order Date"].dt.month
    df["Quarter"] = df["Order Date"].dt.quarter
    df["YearMonth"] = df["Order Date"].dt.to_period("M").astype(str)
    df["ShipDays"] = (df["Ship Date"] - df["Order Date"]).dt.days
    df["ProfitMargin"] = np.where(df["Sales"] > 0, df["Profit"] / df["Sales"], 0.0)
    df["IsLoss"] = df["Profit"] < 0
    df["DiscountBand"] = pd.cut(
        df["Discount"], bins=DISCOUNT_BINS, labels=DISCOUNT_LABELS
    ).astype(str)

    df = df.sort_values(["Order Date", "Row ID"]).reset_index(drop=True)
    report.rows_out = len(df)
    log.info("Cleaned %d -> %d rows", report.rows_in, report.rows_out)
    return df, report
