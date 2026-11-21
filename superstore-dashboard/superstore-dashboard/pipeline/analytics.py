"""Aggregations, KPIs and statistical insights computed on the cleaned data.

All functions take an already-filtered DataFrame and return plain Python
structures (dict / list) so they can be serialised straight to JSON.
"""
from __future__ import annotations

import calendar

import numpy as np
import pandas as pd

from .cleaning import DISCOUNT_LABELS

METRICS = {"sales": "Sales", "profit": "Profit", "quantity": "Quantity"}
DIMENSIONS = {
    "category": "Category",
    "sub_category": "Sub-Category",
    "region": "Region",
    "segment": "Segment",
    "ship_mode": "Ship Mode",
    "state": "State",
}


def _num(x, digits: int = 2) -> float:
    return round(float(x), digits)


def _div(a, b) -> float:
    return float(a) / float(b) if b else 0.0


def _growth(last, prev):
    return _num((last - prev) / abs(prev) * 100, 1) if prev else None


# --------------------------------------------------------------------------- filters
def apply_filters(df, years=None, regions=None, categories=None, segments=None):
    mask = pd.Series(True, index=df.index)
    if years:
        mask &= df["Year"].isin(years)
    if regions:
        mask &= df["Region"].isin(regions)
    if categories:
        mask &= df["Category"].isin(categories)
    if segments:
        mask &= df["Segment"].isin(segments)
    return df[mask]


def filter_options(df) -> dict:
    return {
        "years": sorted(int(y) for y in df["Year"].unique()),
        "regions": sorted(df["Region"].unique().tolist()),
        "categories": sorted(df["Category"].unique().tolist()),
        "segments": sorted(df["Segment"].unique().tolist()),
    }


# --------------------------------------------------------------------------- KPIs
def kpis(df) -> dict:
    if df.empty:
        return {k: 0 for k in (
            "sales", "profit", "margin", "orders", "customers", "avg_order_value",
            "avg_ship_days", "loss_share")} | {"sales_growth": None, "profit_growth": None,
                                               "growth_label": None}
    sales, profit = df["Sales"].sum(), df["Profit"].sum()
    orders = df["Order ID"].nunique()
    out = {
        "sales": _num(sales),
        "profit": _num(profit),
        "margin": _num(_div(profit, sales) * 100, 1),
        "orders": int(orders),
        "customers": int(df["Customer ID"].nunique()),
        "avg_order_value": _num(_div(sales, orders)),
        "avg_ship_days": _num(df["ShipDays"].mean(), 1),
        "loss_share": _num(df["IsLoss"].mean() * 100, 1),
        "sales_growth": None,
        "profit_growth": None,
        "growth_label": None,
    }
    yearly = df.groupby("Year")[["Sales", "Profit"]].sum().sort_index()
    if len(yearly) >= 2:
        prev, last = yearly.iloc[-2], yearly.iloc[-1]
        out["sales_growth"] = _growth(last["Sales"], prev["Sales"])
        out["profit_growth"] = _growth(last["Profit"], prev["Profit"])
        out["growth_label"] = f"{yearly.index[-1]} vs {yearly.index[-2]}"
    return out


# --------------------------------------------------------------------------- trend
def trend(df, metric: str) -> dict:
    """Monthly series + 3-month moving average + least-squares linear trend."""
    empty = {"labels": [], "values": [], "moving_avg": [], "trend": [], "slope": 0}
    if df.empty:
        return empty
    col = METRICS[metric]
    months = pd.period_range(df["YearMonth"].min(), df["YearMonth"].max(), freq="M").astype(str)
    series = df.groupby("YearMonth")[col].sum().reindex(months, fill_value=0.0)
    y = series.to_numpy(dtype=float)
    moving = series.rolling(3, min_periods=1).mean().to_numpy()
    slope = intercept = 0.0
    if len(y) >= 2:
        slope, intercept = np.polyfit(np.arange(len(y)), y, 1)
    fitted = intercept + slope * np.arange(len(y))
    return {
        "labels": list(months),
        "values": [_num(v) for v in y],
        "moving_avg": [_num(v) for v in moving],
        "trend": [_num(v) for v in fitted],
        "slope": _num(slope),
    }


# --------------------------------------------------------------------------- breakdowns
def breakdown(df, dim: str, metric: str, limit: int = 10) -> dict:
    if df.empty:
        return {"labels": [], "sales": [], "profit": [], "quantity": [], "margin": []}
    g = df.groupby(DIMENSIONS[dim]).agg(
        sales=("Sales", "sum"), profit=("Profit", "sum"), quantity=("Quantity", "sum")
    )
    g["margin"] = g["profit"] / g["sales"] * 100
    g = g.sort_values(metric, ascending=False).head(limit)
    return {
        "labels": g.index.tolist(),
        "sales": [_num(v) for v in g["sales"]],
        "profit": [_num(v) for v in g["profit"]],
        "quantity": [int(v) for v in g["quantity"]],
        "margin": [_num(v, 1) for v in g["margin"]],
    }


def subcategories(df) -> dict:
    return breakdown(df, "sub_category", "profit", limit=50)


def discount_impact(df) -> list[dict]:
    if df.empty:
        return []
    g = df.groupby("DiscountBand").agg(
        lines=("Row ID", "count"), sales=("Sales", "sum"), profit=("Profit", "sum"),
        loss_share=("IsLoss", "mean"),
    )
    rows = []
    for band in DISCOUNT_LABELS:
        if band in g.index:
            r = g.loc[band]
            rows.append({
                "band": band,
                "lines": int(r["lines"]),
                "sales": _num(r["sales"]),
                "profit": _num(r["profit"]),
                "margin": _num(_div(r["profit"], r["sales"]) * 100, 1),
                "loss_share": _num(r["loss_share"] * 100, 1),
            })
    return rows


def worst_products(df, n: int = 8) -> list[dict]:
    if df.empty:
        return []
    g = df.groupby(["Product Name", "Sub-Category"]).agg(
        sales=("Sales", "sum"), profit=("Profit", "sum"), discount=("Discount", "mean"),
        units=("Quantity", "sum"),
    ).reset_index()
    g = g.sort_values("profit").head(n)
    return [
        {
            "product": r["Product Name"], "sub_category": r["Sub-Category"],
            "sales": _num(r["sales"]), "profit": _num(r["profit"]),
            "avg_discount": _num(r["discount"] * 100, 0), "units": int(r["units"]),
        }
        for _, r in g.iterrows()
    ]


# --------------------------------------------------------------------------- statistics
def profit_outliers(df, threshold: float = 3.5) -> pd.DataFrame:
    """Order lines whose profit is extreme *for their sub-category*.

    Uses the modified z-score (median / MAD) which, unlike a mean/std z-score,
    is not distorted by the very outliers it is trying to find.
    """
    if df.empty:
        return df
    key = df["Sub-Category"]
    median = df.groupby(key)["Profit"].transform("median")
    mad = (df["Profit"] - median).abs().groupby(key).transform("median").replace(0, np.nan)
    z = 0.6745 * (df["Profit"] - median) / mad
    return df[z.abs() > threshold]


def insights(df) -> list[str]:
    """Plain-language findings computed from the filtered data."""
    if df.empty:
        return ["No orders match the current filters."]
    out: list[str] = []

    cat = df.groupby("Category").agg(sales=("Sales", "sum"), profit=("Profit", "sum"))
    cat["margin"] = cat["profit"] / cat["sales"] * 100
    if len(cat) > 1:
        hi, lo = cat["margin"].idxmax(), cat["margin"].idxmin()
        out.append(f"{hi} earns the best margin ({cat.loc[hi, 'margin']:.1f}%); "
                   f"{lo} earns the lowest ({cat.loc[lo, 'margin']:.1f}%).")

    sub = df.groupby("Sub-Category")["Profit"].sum()
    losers = sub[sub < 0].sort_values()
    if len(losers):
        out.append(f"{len(losers)} sub-categories lose money overall. The worst are "
                   f"{', '.join(losers.index[:3])}, together losing ${-losers.sum():,.0f}.")

    bands = [b for b in discount_impact(df) if b["profit"] < 0]
    if bands:
        labels = [b["band"] for b in bands]
        names = labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]
        loss = -sum(b["profit"] for b in bands)
        lines = sum(b["lines"] for b in bands)
        out.append(f"Order lines in the {names} discount ranges lose money "
                   f"(${loss:,.0f} lost across {lines:,} lines).")

    reg = df.groupby("Region").agg(sales=("Sales", "sum"), profit=("Profit", "sum"))
    if len(reg) > 1:
        reg["margin"] = reg["profit"] / reg["sales"] * 100
        lo = reg["margin"].idxmin()
        out.append(f"{lo} is the weakest region at a {reg.loc[lo, 'margin']:.1f}% margin.")

    t = trend(df, "sales")
    if len(t["labels"]) >= 6:
        direction = "up" if t["slope"] >= 0 else "down"
        out.append(f"Monthly sales are trending {direction} by about ${abs(t['slope']):,.0f} per month.")

    month_totals = df.groupby("Month")["Sales"].sum().sort_values(ascending=False)
    if len(month_totals) >= 3:
        top = [calendar.month_name[m] for m in month_totals.index[:2]]
        share = month_totals.iloc[:2].sum() / month_totals.sum() * 100
        out.append(f"{top[0]} and {top[1]} are the strongest months, bringing in {share:.0f}% of sales.")

    n_out = len(profit_outliers(df))
    if n_out:
        out.append(f"{n_out:,} order lines ({n_out / len(df) * 100:.1f}%) have unusually high or "
                   f"low profit for their sub-category.")
    return out


def dashboard(df, metric: str, dim: str, limit: int = 10) -> dict:
    return {
        "kpis": kpis(df),
        "trend": trend(df, metric),
        "breakdown": breakdown(df, dim, metric, limit),
        "subcategories": subcategories(df),
        "discount": discount_impact(df),
        "worst_products": worst_products(df),
        "insights": insights(df),
        "rows": int(len(df)),
    }
