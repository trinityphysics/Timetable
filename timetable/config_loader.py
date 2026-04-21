"""Load and validate timetable configuration from JSON."""

import json
from typing import Any, Dict, List, Tuple

from .models import Class, Column, Room, Subject, Teacher, TimetableConfig, YearGroup


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

    # Per-day period counts (keys may arrive as strings from JSON)
    raw_day_lengths = data.get("day_lengths", {})
    config.day_lengths = {int(k): int(v) for k, v in raw_day_lengths.items()}

    # Tutor-time slots (list of [day, period] pairs)
    config.tutor_time_slots = [
        _to_slot(s) for s in data.get("tutor_time_slots", [])
    ]

    for t in data.get("teachers", []):
        unavailable = [_to_slot(p) for p in t.get("unavailable", [])]
        config.teachers.append(
            Teacher(
                name=t["name"],
                unavailable=unavailable,
                non_contact_entitlement=int(t.get("non_contact_entitlement", 0)),
            )
        )

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
                teacher=s.get("teacher", ""),
                periods_per_week=int(s.get("periods_per_week", 1)),
                room=s.get("room"),
                preferred_periods=preferred,
            )
        )

    # --- New Step 1: Year groups ------------------------------------------------
    for yg in data.get("year_groups", []):
        period_map = [
            (int(e[0]), int(e[1]), str(e[2]))
            for e in yg.get("period_map", [])
        ]
        config.year_groups.append(YearGroup(name=yg["name"], period_map=period_map))

    # --- New Step 3: Classes ----------------------------------------------------
    for cls in data.get("classes", []):
        # Backward-compat: accept legacy ``pinned_teacher`` field.
        allowed = cls.get("allowed_teachers")
        if not allowed:
            pt = cls.get("pinned_teacher") or ""
            allowed = [pt] if pt else []
        config.classes.append(
            Class(
                year_group=cls["year_group"],
                subject=cls.get("subject", ""),
                level=cls.get("level", ""),
                column=cls.get("column", ""),
                sections=int(cls.get("sections", 1)),
                allowed_teachers=allowed,
                # 0 signals "auto-derive from period map"
                periods_per_week=int(cls.get("periods_per_week", 0)),
                room=cls.get("room"),
            )
        )

    # If classes were provided but no explicit subjects, expand classes → subjects
    if config.classes and not config.subjects:
        for cls in config.classes:
            codes = cls.codes()
            n = len(codes)
            teachers = cls.allowed_teachers

            # Resolve per-section teacher assignments
            if len(teachers) == 1:
                # Single teacher pinned to every section
                assigned: List[str] = [teachers[0]] * n
            elif len(teachers) == n:
                # Per-section hard rule (entries may be "" for "any")
                assigned = [t or "" for t in teachers]
            elif len(teachers) == 0:
                assigned = [""] * n
            else:
                # Pool — assign empty (any); pool matching not yet in scheduler
                assigned = [""] * n

            # Auto-derive periods_per_week from year-group period map
            ppw = cls.periods_per_week
            if not ppw:
                yg_obj = next(
                    (y for y in config.year_groups if y.name == cls.year_group), None
                )
                if yg_obj and cls.column:
                    ppw = sum(1 for _, _, c in yg_obj.period_map if c == cls.column) or 1
                else:
                    ppw = 1

            for code, teacher in zip(codes, assigned):
                config.subjects.append(
                    Subject(
                        name=code,
                        column=cls.column,
                        teacher=teacher,
                        periods_per_week=ppw,
                        room=cls.room,
                    )
                )

    # If year_groups were provided but no explicit columns, auto-derive column names
    # and pin each column to the exact slots specified in the period_map.
    if config.year_groups and not config.columns:
        # Collect ordered (slot) lists per column across all year groups
        col_slots: Dict[str, List[Tuple[int, int]]] = {}
        for yg in config.year_groups:
            for day, period, col_name in yg.period_map:
                if col_name:
                    slot = (day, period)
                    if col_name not in col_slots:
                        col_slots[col_name] = []
                    if slot not in col_slots[col_name]:
                        col_slots[col_name].append(slot)

        seen_cols: set = set()
        for col_name, slots in col_slots.items():
            seen_cols.add(col_name)
            config.columns.append(Column(name=col_name, pinned_slots=slots))
        # Also collect column names from classes (no pinned slots — free scheduling)
        for cls in config.classes:
            if cls.column and cls.column not in seen_cols:
                seen_cols.add(cls.column)
                config.columns.append(Column(name=cls.column))

    return config


def validate_config(config: TimetableConfig) -> List[str]:
    """
    Validate a TimetableConfig.

    Returns a list of human-readable error strings.
    An empty list means the configuration is valid.
    Strings beginning with "WARNING" are non-blocking advisories.
    """
    errors: List[str] = []

    teacher_names = {t.name for t in config.teachers}
    room_names = {r.name for r in config.rooms}
    column_names = {c.name for c in config.columns}

    if config.days_per_week < 1:
        errors.append("days_per_week must be at least 1.")
    if config.periods_per_day < 1:
        errors.append("periods_per_day must be at least 1.")

    # Validate per-day lengths
    for day, length in config.day_lengths.items():
        if not (1 <= day <= config.days_per_week):
            errors.append(
                f"day_lengths: day {day} is out of range "
                f"(1–{config.days_per_week})."
            )
        if length < 1:
            errors.append(
                f"day_lengths: day {day} must have at least 1 period."
            )

    total_slots = config.total_slots()

    # Validate tutor time slots
    for slot in config.tutor_time_slots:
        if not _valid_slot(slot, config):
            errors.append(
                f"tutor_time_slots: slot {slot} is out of range."
            )

    # Validate subjects
    seen_names: set = set()
    for s in config.subjects:
        if s.name in seen_names:
            errors.append(f"Duplicate subject name: '{s.name}'.")
        seen_names.add(s.name)

        if not s.teacher:
            errors.append(
                f"WARNING: Subject '{s.name}' has no teacher assigned; "
                "it will be scheduled without a teacher constraint."
            )
        elif s.teacher not in teacher_names:
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
        if s.teacher:
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
    return 1 <= day <= config.days_per_week and 1 <= period <= config.periods_on_day(day)
