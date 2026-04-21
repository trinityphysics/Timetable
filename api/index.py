"""
Vercel-compatible Flask web application for the Timetable Scheduler.

Routes
------
GET  /          — Serve the single-page frontend.
POST /api/schedule — Accept a JSON timetable config and return schedule results.
"""

import json
import os
import sys

# Ensure the repo root is on the path so that the `timetable` package can be
# imported regardless of which directory Vercel executes this module from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, render_template, request

from timetable.config_loader import parse_config, validate_config
from timetable.reporter import to_json as timetable_to_json
from timetable.scheduler import Scheduler

app = Flask(__name__, template_folder="../templates")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/schedule", methods=["POST"])
def schedule():
    """
    Accept a JSON timetable configuration and return the scheduled timetable.

    Request body : JSON object matching the TimetableConfig schema.
    Response     : JSON with keys ``sessions``, ``conflicts``, ``timetable``.
    """
    if not request.is_json:
        return jsonify({"error": "Request body must be JSON."}), 400

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON in request body."}), 400

    try:
        config = parse_config(data)
    except Exception as exc:
        return jsonify({"error": f"Failed to parse config: {exc}"}), 422

    issues = validate_config(config)
    hard_issues = [i for i in issues if not i.startswith("WARNING")]
    warnings = [i for i in issues if i.startswith("WARNING")]

    if hard_issues:
        return jsonify({"error": "Config validation failed.", "details": hard_issues}), 422

    scheduler = Scheduler(config)
    assignments, conflicts = scheduler.schedule()

    result = json.loads(timetable_to_json(assignments, conflicts, config))
    result["warnings"] = warnings
    return jsonify(result)
