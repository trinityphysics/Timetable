"""Load and validate timetable configuration from JSON."""

import json
from typing import Any, Dict, List, Tuple

from .models import Column, Room, Subject, Teacher, TimetableConfig


def load_config(path: str) -> TimetableConfig:
    """Load a TimetableConfig from a JSON file."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return parse_config(data)


def parse_config(data: Dict[str, Any]) -> TimetableConfig:
    """Parse a raw dictionary (e.g. from JSON) into a TimetableConfig."""
    config = TimetableConfig(
        name=data.get("name", "Timetable"),
        days_per_week=int(data.get("days_per_week", 5)),
        periods_per_day=int(data.get("periods_per_day", 6)),
    )

    for t in data.get("teachers", []):
        unavailable = [_to_slot(p) for p in t.get("unavailable", [])]
        config.teachers.append(Teacher(name=t["name"], unavailable=unavailable))

    for r in data.get("rooms", []):
        config.rooms.append(Room(name=r["name"], capacity=r.get("capacity", 30)))

    for c in data.get("columns", []):
        unavailable = [_to_slot(p) for p in c.get("unavailable", [])]
        config.columns.append(Column(name=c["name"], unavailable=unavailable))

    for s in data.get("subjects", []):
        preferred = [_to_slot(p) for p in s.get("preferred_periods", [])]
        config.subjects.append(
            Subject(
                name=s["name"],
                column=s["column"],
                teacher=s["teacher"],
                periods_per_week=int(s.get("periods_per_week", 1)),
                room=s.get("room"),
                preferred_periods=preferred,
            )
        )

    return config


def validate_config(config: TimetableConfig) -> List[str]:
    """
    Validate a TimetableConfig.

    Returns a list of human-readable error strings.
    An empty list means the configuration is valid.
    """
    errors: List[str] = []

    teacher_names = {t.name for t in config.teachers}
    room_names = {r.name for r in config.rooms}
    column_names = {c.name for c in config.columns}

    if config.days_per_week < 1:
        errors.append("days_per_week must be at least 1.")
    if config.periods_per_day < 1:
        errors.append("periods_per_day must be at least 1.")

    total_slots = config.days_per_week * config.periods_per_day

    # Validate subjects
    seen_names: set = set()
    for s in config.subjects:
        if s.name in seen_names:
            errors.append(f"Duplicate subject name: '{s.name}'.")
        seen_names.add(s.name)

        if s.teacher not in teacher_names:
            errors.append(
                f"Subject '{s.name}': teacher '{s.teacher}' is not listed in teachers."
            )
        if s.column not in column_names:
            errors.append(
                f"Subject '{s.name}': column '{s.column}' is not listed in columns."
            )
        if s.room and s.room not in room_names:
            errors.append(
                f"Subject '{s.name}': room '{s.room}' is not listed in rooms."
            )
        if s.periods_per_week < 1:
            errors.append(
                f"Subject '{s.name}': periods_per_week must be at least 1."
            )
        if s.periods_per_week > total_slots:
            errors.append(
                f"Subject '{s.name}': periods_per_week ({s.periods_per_week}) "
                f"exceeds total slots ({total_slots})."
            )
        for slot in s.preferred_periods:
            if not _valid_slot(slot, config):
                errors.append(
                    f"Subject '{s.name}': preferred period {slot} is out of range."
                )

    # Validate teacher unavailability slots
    for t in config.teachers:
        for slot in t.unavailable:
            if not _valid_slot(slot, config):
                errors.append(
                    f"Teacher '{t.name}': unavailable slot {slot} is out of range."
                )

    # Validate column unavailability slots
    for c in config.columns:
        for slot in c.unavailable:
            if not _valid_slot(slot, config):
                errors.append(
                    f"Column '{c.name}': unavailable slot {slot} is out of range."
                )

    # Warn about teachers shared across columns (possible multiple-delivery issue)
    teacher_columns: Dict[str, set] = {}
    for s in config.subjects:
        teacher_columns.setdefault(s.teacher, set()).add(s.column)
    for teacher, cols in teacher_columns.items():
        if len(cols) > 1:
            errors.append(
                f"WARNING: Teacher '{teacher}' appears in multiple columns "
                f"({', '.join(sorted(cols))}). This may cause scheduling conflicts."
            )

    return errors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_slot(raw) -> Tuple[int, int]:
    """Convert a list/tuple [day, period] to a (day, period) tuple."""
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        return (int(raw[0]), int(raw[1]))
    raise ValueError(f"Cannot convert {raw!r} to a (day, period) slot.")


def _valid_slot(slot: Tuple[int, int], config: TimetableConfig) -> bool:
    day, period = slot
    return 1 <= day <= config.days_per_week and 1 <= period <= config.periods_per_day
