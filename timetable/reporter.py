"""Format and print timetable results."""

import json
import csv
import io
from collections import defaultdict
from typing import Dict, List, Optional

from .models import Assignment, Conflict, TimetableConfig

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _day_label(day: int) -> str:
    if 1 <= day <= len(DAY_NAMES):
        return DAY_NAMES[day - 1]
    return f"Day {day}"


# ---------------------------------------------------------------------------
# Timetable grid
# ---------------------------------------------------------------------------


def format_timetable_text(
    assignments: List[Assignment],
    config: TimetableConfig,
    show_room: bool = True,
    show_teacher: bool = True,
) -> str:
    """
    Render the timetable as a plain-text grid.

    Rows = periods, Columns = days.
    Each cell lists the subjects (with teacher / room) running in that slot.
    """
    # Build lookup: slot -> list of assignments
    by_slot: Dict = defaultdict(list)
    for a in assignments:
        by_slot[(a.day, a.period)].append(a)

    days = list(range(1, config.days_per_week + 1))
    periods = list(range(1, config.periods_per_day + 1))

    # Column widths
    day_labels = [_day_label(d) for d in days]

    # Build cell contents
    def cell_text(day: int, period: int) -> str:
        items = by_slot.get((day, period), [])
        if not items:
            return ""
        lines = []
        for a in items:
            parts = [a.subject]
            if show_teacher:
                parts.append(f"({a.teacher})")
            if show_room:
                parts.append(f"[{a.room}]")
            lines.append(" ".join(parts))
        return " | ".join(lines)

    # Compute column widths
    period_label_width = max(len(f"P{p}") for p in periods)
    col_widths = []
    for d in days:
        w = len(_day_label(d))
        for p in periods:
            w = max(w, len(cell_text(d, p)))
        col_widths.append(max(w, 4))

    sep = (
        "+" + "+".join("-" * (w + 2) for w in [period_label_width] + col_widths) + "+"
    )

    lines = [f"\n{'=' * len(sep)}", f"  {config.name}", "=" * len(sep)]

    # Header row
    header = (
        "| "
        + " " * period_label_width
        + " | "
        + " | ".join(f"{label:^{w}}" for label, w in zip(day_labels, col_widths))
        + " |"
    )
    lines += [sep, header, sep]

    # Data rows
    for p in periods:
        cells = [cell_text(d, p) for d in days]
        row = (
            f"| P{p:<{period_label_width - 1}} | "
            + " | ".join(f"{c:<{w}}" for c, w in zip(cells, col_widths))
            + " |"
        )
        lines.append(row)
        lines.append(sep)

    return "\n".join(lines) + "\n"


def format_timetable_by_teacher(
    assignments: List[Assignment],
    config: TimetableConfig,
) -> str:
    """Show a separate mini-grid for each teacher."""
    teacher_names = sorted({a.teacher for a in assignments})
    sections = []
    for teacher in teacher_names:
        teacher_assignments = [a for a in assignments if a.teacher == teacher]
        sections.append(f"\n--- {teacher} ---")
        sections.append(
            format_timetable_text(
                teacher_assignments, config, show_teacher=False, show_room=True
            )
        )
    return "\n".join(sections)


def format_timetable_by_room(
    assignments: List[Assignment],
    config: TimetableConfig,
) -> str:
    """Show a separate mini-grid for each room."""
    room_names = sorted({a.room for a in assignments})
    sections = []
    for room in room_names:
        room_assignments = [a for a in assignments if a.room == room]
        sections.append(f"\n--- {room} ---")
        sections.append(
            format_timetable_text(
                room_assignments, config, show_teacher=True, show_room=False
            )
        )
    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Conflicts
# ---------------------------------------------------------------------------


def format_conflicts(conflicts: List[Conflict]) -> str:
    if not conflicts:
        return "No conflicts found.\n"

    hard = [c for c in conflicts if c.severity == "hard"]
    soft = [c for c in conflicts if c.severity == "soft"]

    lines = ["\n=== Conflicts / Warnings ==="]
    if hard:
        lines.append(f"\nHARD conflicts ({len(hard)}):")
        for c in hard:
            lines.append(f"  {c}")
    if soft:
        lines.append(f"\nSoft warnings ({len(soft)}):")
        for c in soft:
            lines.append(f"  {c}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def format_summary(
    assignments: List[Assignment],
    conflicts: List[Conflict],
    config: TimetableConfig,
) -> str:
    total = config.days_per_week * config.periods_per_day
    scheduled = len(assignments)
    hard = sum(1 for c in conflicts if c.severity == "hard")
    soft = sum(1 for c in conflicts if c.severity == "soft")

    teachers_used = len({a.teacher for a in assignments})
    rooms_used = len({a.room for a in assignments})

    lines = [
        "\n=== Summary ===",
        f"  Timetable name   : {config.name}",
        f"  Days per week    : {config.days_per_week}",
        f"  Periods per day  : {config.periods_per_day}",
        f"  Total slots      : {total}",
        f"  Sessions placed  : {scheduled}",
        f"  Teachers active  : {teachers_used}",
        f"  Rooms used       : {rooms_used}",
        f"  Hard conflicts   : {hard}",
        f"  Soft warnings    : {soft}",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON / CSV export
# ---------------------------------------------------------------------------


def to_json(
    assignments: List[Assignment],
    conflicts: List[Conflict],
    config: TimetableConfig,
) -> str:
    """Serialise results to a JSON string."""
    data = {
        "timetable": {
            "name": config.name,
            "days_per_week": config.days_per_week,
            "periods_per_day": config.periods_per_day,
        },
        "sessions": [
            {
                "subject": a.subject,
                "column": a.column,
                "teacher": a.teacher,
                "room": a.room,
                "day": a.day,
                "period": a.period,
            }
            for a in sorted(assignments, key=lambda a: (a.day, a.period, a.subject))
        ],
        "conflicts": [
            {
                "severity": c.severity,
                "category": c.category,
                "description": c.description,
                "day": c.day,
                "period": c.period,
                "subjects": c.subjects,
            }
            for c in conflicts
        ],
    }
    return json.dumps(data, indent=2)


def to_csv(assignments: List[Assignment]) -> str:
    """Serialise sessions to a CSV string."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["day", "period", "column", "subject", "teacher", "room"])
    for a in sorted(assignments, key=lambda a: (a.day, a.period, a.subject)):
        writer.writerow([a.day, a.period, a.column, a.subject, a.teacher, a.room])
    return output.getvalue()
