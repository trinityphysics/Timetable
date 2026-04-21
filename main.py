#!/usr/bin/env python3
"""
Timetable Scheduler — command-line entry point.

Usage examples
--------------
# Generate a timetable from a config file (text output to stdout)
python main.py config/example.json

# Also show per-teacher and per-room views
python main.py config/example.json --views teacher room

# Interactive review of soft conflicts
python main.py config/example.json --interactive

# Export results to JSON and CSV
python main.py config/example.json --output-json out/timetable.json --output-csv out/timetable.csv

# Validate config only (no scheduling)
python main.py config/example.json --validate-only
"""

import argparse
import os
import sys

from timetable.config_loader import load_config, validate_config
from timetable.interactive import further_checks, review_soft_conflicts
from timetable.reporter import (
    format_conflicts,
    format_summary,
    format_timetable_by_room,
    format_timetable_by_teacher,
    format_timetable_text,
    format_tutor_time_notification,
    to_csv,
    to_json,
)
from timetable.scheduler import Scheduler


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Constraint-based timetable scheduler.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("config", help="Path to the JSON configuration file.")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate the configuration; do not schedule.",
    )
    parser.add_argument(
        "--views",
        nargs="*",
        choices=["teacher", "room"],
        default=[],
        help="Additional views to display (teacher, room).",
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Interactively review soft conflicts after scheduling.",
    )
    parser.add_argument(
        "--further-checks",
        action="store_true",
        help="Run further interactive acceptability checks after scheduling.",
    )
    parser.add_argument(
        "--output-json",
        metavar="FILE",
        help="Write results to FILE in JSON format.",
    )
    parser.add_argument(
        "--output-csv",
        metavar="FILE",
        help="Write sessions to FILE in CSV format.",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    # --- Load config ---
    if not os.path.isfile(args.config):
        print(f"Error: Config file not found: {args.config}", file=sys.stderr)
        return 1

    try:
        config = load_config(args.config)
    except Exception as exc:
        print(f"Error loading config: {exc}", file=sys.stderr)
        return 1

    # --- Validate ---
    issues = validate_config(config)
    hard_issues = [i for i in issues if not i.startswith("WARNING")]
    warnings = [i for i in issues if i.startswith("WARNING")]

    if warnings:
        print("Configuration warnings:")
        for w in warnings:
            print(f"  {w}")

    if hard_issues:
        print("Configuration errors (fix before scheduling):")
        for e in hard_issues:
            print(f"  {e}")
        return 1

    if args.validate_only:
        print("Configuration is valid.")
        return 0

    # --- Schedule ---
    scheduler = Scheduler(config)
    assignments, conflicts = scheduler.schedule()

    # --- Print main timetable ---
    print(format_timetable_text(assignments, config))

    # --- Optional extra views ---
    if "teacher" in (args.views or []):
        print(format_timetable_by_teacher(assignments, config))
    if "room" in (args.views or []):
        print(format_timetable_by_room(assignments, config))

    # --- Conflicts ---
    print(format_conflicts(conflicts))

    # --- Summary ---
    print(format_summary(assignments, conflicts, config))

    # --- Tutor time ---
    tutor_msg = format_tutor_time_notification(assignments, config)
    if tutor_msg:
        print(tutor_msg)

    # --- Interactive review ---
    if args.interactive:
        accepted, rejected = review_soft_conflicts(conflicts)
        if rejected:
            print("\nThe following soft conflicts were flagged for fixing:")
            for c in rejected:
                print(f"  {c}")

    # --- Further checks ---
    if args.further_checks:
        further_checks(assignments, config)

    # --- Export ---
    if args.output_json:
        _write_file(args.output_json, to_json(assignments, conflicts, config))
        print(f"JSON output written to: {args.output_json}")

    if args.output_csv:
        _write_file(args.output_csv, to_csv(assignments))
        print(f"CSV output written to: {args.output_csv}")

    # Return non-zero exit code if there are hard conflicts
    hard = sum(1 for c in conflicts if c.severity == "hard")
    return 1 if hard else 0


def _write_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


if __name__ == "__main__":
    sys.exit(main())
