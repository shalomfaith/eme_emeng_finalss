"""Step 2: Flask server exposing the processed data as a JSON API + dashboard page.

    python app.py      ->  http://127.0.0.1:5000
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import pandas as pd
from flask import Flask, jsonify, render_template, request

import run_pipeline
from pipeline import analytics

BASE = Path(__file__).parent
CLEAN_CSV = BASE / "data" / "processed" / "superstore_clean.csv"


@lru_cache(maxsize=1)
def get_data() -> pd.DataFrame:
    """Load the cleaned dataset once; build it first if it does not exist yet."""
    if not CLEAN_CSV.exists():
        logging.info("Processed data not found - running pipeline")
        run_pipeline.run()
    return pd.read_csv(CLEAN_CSV, parse_dates=["Order Date", "Ship Date"])


def _list_arg(name: str, cast=str) -> list:
    raw = request.args.get(name, "")
    try:
        return [cast(v) for v in raw.split(",") if v.strip()]
    except ValueError:
        raise ValueError(f"Invalid value for '{name}'")


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/health")
    def health():
        return jsonify(status="ok", rows=len(get_data()))

    @app.get("/api/filters")
    def filters():
        return jsonify(analytics.filter_options(get_data()))

    @app.get("/api/dashboard")
    def dashboard():
        metric = request.args.get("metric", "sales")
        dim = request.args.get("dim", "category")
        if metric not in analytics.METRICS:
            raise ValueError(f"metric must be one of {list(analytics.METRICS)}")
        if dim not in analytics.DIMENSIONS:
            raise ValueError(f"dim must be one of {list(analytics.DIMENSIONS)}")
        df = analytics.apply_filters(
            get_data(),
            years=_list_arg("years", int),
            regions=_list_arg("regions"),
            categories=_list_arg("categories"),
            segments=_list_arg("segments"),
        )
        return jsonify(analytics.dashboard(df, metric, dim))

    @app.errorhandler(ValueError)
    def bad_request(err):
        return jsonify(error=str(err)), 400

    @app.errorhandler(404)
    def not_found(_):
        return jsonify(error="Not found"), 404

    @app.errorhandler(Exception)
    def server_error(err):
        logging.exception("Unhandled error")
        return jsonify(error="Something went wrong on the server."), 500

    return app


app = create_app()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(debug=False, port=5000)
