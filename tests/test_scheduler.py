"""Tests for the scheduler module."""

import pytest
from collections import defaultdict

from timetable.models import Column, Room, Subject, Teacher, TimetableConfig
from timetable.scheduler import Scheduler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_config(
    days=5,
    periods=6,
    teachers=None,
    rooms=None,
    columns=None,
    subjects=None,
):
    config = TimetableConfig(
        name="Test",
        days_per_week=days,
        periods_per_day=periods,
        teachers=teachers or [],
        rooms=rooms or [],
        columns=columns or [],
        subjects=subjects or [],
    )
    return config


def two_subject_config():
    """Two independent columns, each with one subject and 2 periods/week."""
    return make_config(
        teachers=[Teacher("Teacher A"), Teacher("Teacher B")],
        rooms=[Room("Room 1"), Room("Room 2")],
        columns=[Column("Col 1"), Column("Col 2")],
        subjects=[
            Subject("Math", "Col 1", "Teacher A", periods_per_week=2, room="Room 1"),
            Subject("English", "Col 2", "Teacher B", periods_per_week=2, room="Room 2"),
        ],
    )


# ---------------------------------------------------------------------------
# Basic scheduling
# ---------------------------------------------------------------------------


def test_basic_scheduling_produces_correct_count():
    config = two_subject_config()
    assignments, conflicts = Scheduler(config).schedule()
    # 2 subjects × 2 periods each = 4 assignments
    assert len(assignments) == 4


def test_basic_scheduling_no_hard_conflicts():
    config = two_subject_config()
    _, conflicts = Scheduler(config).schedule()
    hard = [c for c in conflicts if c.severity == "hard"]
    assert hard == [], f"Unexpected hard conflicts: {hard}"


def test_all_periods_scheduled():
    """Every (subject, instance) pair must appear exactly once."""
    config = two_subject_config()
    assignments, _ = Scheduler(config).schedule()

    subject_counts = defaultdict(int)
    for a in assignments:
        subject_counts[a.subject] += 1

    for subj in config.subjects:
        assert subject_counts[subj.name] == subj.periods_per_week, (
            f"{subj.name}: expected {subj.periods_per_week} sessions, "
            f"got {subject_counts[subj.name]}"
        )


# ---------------------------------------------------------------------------
# Teacher constraint: no double-booking
# ---------------------------------------------------------------------------


def test_teacher_not_double_booked_within_same_column():
    """A teacher shared by two subjects in the same column must never appear
    at the same slot in both assignments.

    When it is physically impossible to schedule (same teacher required for
    both simultaneous subjects), the scheduler must report hard conflicts
    rather than silently producing a double-booked timetable.
    """
    config = make_config(
        teachers=[Teacher("T")],
        rooms=[Room("R1"), Room("R2")],
        columns=[Column("E")],
        subjects=[
            Subject("Math",    "E", "T", periods_per_week=2, room="R1"),
            Subject("Science", "E", "T", periods_per_week=2, room="R2"),
        ],
    )
    assignments, conflicts = Scheduler(config).schedule()

    # The conflict must be reported — the column is unschedulable
    hard = [c for c in conflicts if c.severity == "hard"]
    assert hard, "Expected hard conflicts for unschedulable same-teacher column, got none"

    # Whatever assignments were produced must not double-book the teacher
    slots_per_teacher = defaultdict(list)
    for a in assignments:
        slots_per_teacher[a.teacher].append(a.slot)

    for teacher, slots in slots_per_teacher.items():
        assert len(slots) == len(set(slots)), (
            f"Teacher '{teacher}' double-booked within same column at slots {slots}"
        )


def test_teacher_not_double_booked():
    """A teacher must not appear in two assignments at the same slot."""
    config = make_config(
        teachers=[Teacher("T")],
        rooms=[Room("R1"), Room("R2")],
        columns=[Column("A"), Column("B")],
        subjects=[
            Subject("Math", "A", "T", periods_per_week=3, room="R1"),
            Subject("Science", "B", "T", periods_per_week=3, room="R2"),
        ],
    )
    assignments, _ = Scheduler(config).schedule()

    slots_per_teacher = defaultdict(list)
    for a in assignments:
        slots_per_teacher[a.teacher].append(a.slot)

    for teacher, slots in slots_per_teacher.items():
        assert len(slots) == len(set(slots)), (
            f"Teacher '{teacher}' double-booked at {slots}"
        )


def test_teacher_unavailability_respected():
    """Teacher unavailability hard constraints must be honoured."""
    config = make_config(
        teachers=[Teacher("T", unavailable=[(1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6)])],
        rooms=[Room("R1")],
        columns=[Column("A")],
        subjects=[Subject("Math", "A", "T", periods_per_week=2)],
    )
    assignments, _ = Scheduler(config).schedule()

    for a in assignments:
        assert a.day != 1, f"Teacher scheduled on unavailable day: {a}"


# ---------------------------------------------------------------------------
# Column constraint: no same column in the same slot twice
# ---------------------------------------------------------------------------


def test_column_not_scheduled_twice_in_same_slot():
    config = make_config(
        teachers=[Teacher("T1"), Teacher("T2")],
        rooms=[Room("R1"), Room("R2")],
        columns=[Column("A")],
        subjects=[
            Subject("Math",  "A", "T1", periods_per_week=3, room="R1"),
            Subject("Sport", "A", "T2", periods_per_week=3, room="R2"),
        ],
    )
    assignments, _ = Scheduler(config).schedule()

    # Both subjects in Col A must share the same slots (that's the semantics)
    math_slots = {a.slot for a in assignments if a.subject == "Math"}
    sport_slots = {a.slot for a in assignments if a.subject == "Sport"}
    assert math_slots == sport_slots, (
        "Subjects in the same column must share identical slots."
    )


# ---------------------------------------------------------------------------
# Room allocation
# ---------------------------------------------------------------------------


def test_room_conflict_produces_soft_warning_or_substitution():
    """When the preferred room is taken, a soft conflict should be raised."""
    config = make_config(
        teachers=[Teacher("T1"), Teacher("T2")],
        rooms=[Room("R1"), Room("R2")],
        columns=[Column("A"), Column("B")],
        subjects=[
            Subject("Math",    "A", "T1", periods_per_week=1, room="R1"),
            Subject("Science", "B", "T2", periods_per_week=1, room="R1"),
        ],
    )
    assignments, conflicts = Scheduler(config).schedule()

    # Must still produce 2 assignments
    assert len(assignments) == 2

    # If both end up in the same slot, one will get a room substitution warning
    by_slot = defaultdict(list)
    for a in assignments:
        by_slot[a.slot].append(a)

    for slot, items in by_slot.items():
        if len(items) == 2:
            rooms_used = [a.room for a in items]
            assert len(set(rooms_used)) == 2, (
                f"Two subjects share a room at slot {slot}: {rooms_used}"
            )


# ---------------------------------------------------------------------------
# Soft constraints
# ---------------------------------------------------------------------------


def test_preferred_period_soft_conflict():
    """A subject NOT placed in its preferred slot should trigger a soft warning."""
    # Make only one possible slot (1,1) but prefer (2,2)
    config = make_config(
        days=1,
        periods=1,
        teachers=[Teacher("T")],
        rooms=[Room("R")],
        columns=[Column("A")],
        subjects=[
            Subject("Math", "A", "T", periods_per_week=1, preferred_periods=[(2, 2)])
        ],
    )
    _, conflicts = Scheduler(config).schedule()
    soft_cats = [c.category for c in conflicts if c.severity == "soft"]
    assert "preferred_period_miss" in soft_cats


def test_multiple_teacher_delivery_flagged():
    """
    If somehow the same subject gets two different teachers (not possible via
    normal config but we test the post-check directly).
    """
    from timetable.models import Assignment, Conflict
    from timetable.scheduler import Scheduler

    config = make_config(
        teachers=[Teacher("T1"), Teacher("T2")],
        rooms=[Room("R")],
        columns=[Column("A")],
        subjects=[Subject("Math", "A", "T1", periods_per_week=1)],
    )
    scheduler = Scheduler(config)
    # Manually inject a conflicting assignment with a different teacher
    scheduler.assignments = [
        Assignment("Math", "A", "T1", "R", 1, 1),
        Assignment("Math", "A", "T2", "R", 1, 2),
    ]
    scheduler._check_soft_constraints()
    hard = [c for c in scheduler.conflicts if c.severity == "hard"]
    assert any(c.category == "multiple_teacher_delivery" for c in hard)


# ---------------------------------------------------------------------------
# Example config integration test
# ---------------------------------------------------------------------------


def test_example_config_schedules_without_hard_conflicts():
    import os
    from timetable.config_loader import load_config

    example = os.path.join(
        os.path.dirname(__file__), "..", "config", "example.json"
    )
    config = load_config(example)
    assignments, conflicts = Scheduler(config).schedule()

    hard = [c for c in conflicts if c.severity == "hard"]
    assert hard == [], f"Hard conflicts in example config: {hard}"

    # All subjects should have their sessions scheduled
    subject_counts = defaultdict(int)
    for a in assignments:
        subject_counts[a.subject] += 1

    for subj in config.subjects:
        assert subject_counts[subj.name] == subj.periods_per_week, (
            f"{subj.name}: expected {subj.periods_per_week}, "
            f"got {subject_counts[subj.name]}"
        )


# ---------------------------------------------------------------------------
# Variable day lengths
# ---------------------------------------------------------------------------


def test_scheduler_uses_extra_period_on_longer_day():
    """When day 1 has 7 periods the scheduler can use slot (1, 7)."""
    config = make_config(
        days=5,
        periods=6,
        teachers=[Teacher("T")],
        rooms=[Room("R")],
        columns=[Column("A")],
        subjects=[Subject("Math", "A", "T", periods_per_week=6)],
    )
    config.day_lengths = {1: 7}

    assignments, conflicts = Scheduler(config).schedule()
    hard = [c for c in conflicts if c.severity == "hard"]
    assert hard == [], f"Unexpected hard conflicts: {hard}"
    assert len(assignments) == 6


def test_scheduler_does_not_use_slot_beyond_short_day():
    """If day 5 has only 3 periods, slot (5, 4) must never be assigned."""
    config = make_config(
        days=5,
        periods=6,
        teachers=[Teacher("T")],
        rooms=[Room("R")],
        columns=[Column("A")],
        subjects=[Subject("Math", "A", "T", periods_per_week=3)],
    )
    config.day_lengths = {5: 3}

    assignments, _ = Scheduler(config).schedule()
    for a in assignments:
        if a.day == 5:
            assert a.period <= 3, f"Slot (5, {a.period}) beyond day-5 length of 3"


# ---------------------------------------------------------------------------
# Pinned slots (period_map)
# ---------------------------------------------------------------------------


def test_pinned_slots_are_respected():
    """When a Column has pinned_slots, all assignments must fall in those slots."""
    from timetable.models import Column

    pinned = [(1, 3), (3, 5)]
    config = make_config(
        days=5,
        periods=6,
        teachers=[Teacher("T")],
        rooms=[Room("R")],
        columns=[Column("A", pinned_slots=pinned)],
        subjects=[Subject("Math", "A", "T", periods_per_week=2)],
    )
    assignments, conflicts = Scheduler(config).schedule()

    hard = [c for c in conflicts if c.severity == "hard"]
    assert hard == [], f"Unexpected hard conflicts: {hard}"
    assert len(assignments) == 2

    for a in assignments:
        assert (a.day, a.period) in pinned, (
            f"Assignment at ({a.day}, {a.period}) is not in pinned_slots {pinned}"
        )


def test_pinned_slots_create_gaps_in_timetable():
    """Pinned-slot columns must leave unpinned slots empty (no free scheduling)."""
    from timetable.models import Column

    pinned = [(2, 4), (4, 2)]
    config = make_config(
        days=5,
        periods=6,
        teachers=[Teacher("T")],
        rooms=[Room("R")],
        columns=[Column("A", pinned_slots=pinned)],
        subjects=[Subject("Math", "A", "T", periods_per_week=2)],
    )
    assignments, _ = Scheduler(config).schedule()

    used_slots = {(a.day, a.period) for a in assignments}
    # Only the two pinned slots should be used — all others remain empty
    assert used_slots == set(pinned), (
        f"Expected only pinned slots {set(pinned)}, got {used_slots}"
    )


def test_year_group_period_map_pins_column_slots():
    """Config derived from year_group period_map must pin each column's slots."""
    from timetable.config_loader import parse_config

    data = {
        "days_per_week": 5,
        "periods_per_day": 6,
        "teachers": [{"name": "Ms. A"}, {"name": "Mr. B"}],
        "rooms": [{"name": "R1"}, {"name": "R2"}],
        "year_groups": [
            {
                "name": "S4",
                "period_map": [
                    [1, 2, "E"],
                    [3, 4, "E"],
                    [2, 1, "F"],
                    [4, 3, "F"],
                ],
            }
        ],
        "classes": [
            {
                "year_group": "S4",
                "subject": "Physics",
                "level": "Higher",
                "column": "E",
                "allowed_teachers": ["Ms. A"],
            },
            {
                "year_group": "S4",
                "subject": "Chemistry",
                "level": "Higher",
                "column": "F",
                "allowed_teachers": ["Mr. B"],
            },
        ],
    }
    config = parse_config(data)
    assignments, conflicts = Scheduler(config).schedule()

    hard = [c for c in conflicts if c.severity == "hard"]
    assert hard == [], f"Unexpected hard conflicts: {hard}"

    col_e_slots = {(a.day, a.period) for a in assignments if a.column == "E"}
    col_f_slots = {(a.day, a.period) for a in assignments if a.column == "F"}

    assert col_e_slots == {(1, 2), (3, 4)}, (
        f"Column E must be at pinned slots {{(1,2),(3,4)}}, got {col_e_slots}"
    )
    assert col_f_slots == {(2, 1), (4, 3)}, (
        f"Column F must be at pinned slots {{(2,1),(4,3)}}, got {col_f_slots}"
    )



def test_pinned_slots_via_api_config_json():
    """
    Columns sent as part of a JSON config payload (e.g. from the 5-step wizard
    frontend) with a ``pinned_slots`` key must be stored on the Column object
    and respected by the scheduler.
    """
    from timetable.config_loader import parse_config

    data = {
        "days_per_week": 5,
        "periods_per_day": 6,
        "teachers": [{"name": "Ms. A", "non_contact_entitlement": 0, "unavailable": []}],
        "rooms": [],
        "columns": [
            {"name": "COL_0", "pinned_slots": [[1, 2], [3, 4], [5, 1]], "unavailable": []},
        ],
        "subjects": [
            {"name": "Subj-1", "column": "COL_0", "teacher": "Ms. A", "periods_per_week": 3},
        ],
    }
    config = parse_config(data)
    assert config.columns[0].pinned_slots == [(1, 2), (3, 4), (5, 1)]

    assignments, conflicts = Scheduler(config).schedule()
    hard = [c for c in conflicts if c.severity == "hard"]
    assert hard == [], f"Unexpected hard conflicts: {hard}"

    used = {(a.day, a.period) for a in assignments}
    assert used == {(1, 2), (3, 4), (5, 1)}, (
        f"Expected slots {{(1,2),(3,4),(5,1)}}, got {used}"
    )


def test_pinned_slots_teacher_conflict_via_json():
    """
    When a teacher is unavailable at a pinned slot, a hard conflict is reported.
    This validates the Step 4 Auto-Assign workflow in the 5-step wizard.
    """
    from timetable.config_loader import parse_config

    # Teacher unavailable at Day 1 P1, but column is pinned to 4 slots including (1,1)
    data = {
        "days_per_week": 5,
        "periods_per_day": 6,
        "teachers": [
            {"name": "Mr. B", "non_contact_entitlement": 0, "unavailable": [[1, 1]]},
        ],
        "rooms": [],
        "columns": [
            {"name": "COL_0", "pinned_slots": [[1, 1], [2, 2], [3, 3], [4, 4]], "unavailable": []},
        ],
        "subjects": [
            {"name": "Subj-1", "column": "COL_0", "teacher": "Mr. B", "periods_per_week": 4},
        ],
    }
    config = parse_config(data)
    _, conflicts = Scheduler(config).schedule()
    hard = [c for c in conflicts if c.severity == "hard"]
    # One of the four pinned slots is blocked → exactly one session unschedulable
    assert len(hard) == 1
    assert hard[0].category == "unschedulable"
