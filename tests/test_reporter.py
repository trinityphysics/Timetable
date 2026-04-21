"""Tests for the reporter module — day lengths and tutor-time notification."""

from timetable.models import Assignment, Column, Room, Subject, Teacher, TimetableConfig
from timetable.reporter import format_timetable_text, format_tutor_time_notification


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**kwargs):
    defaults = dict(
        name="Test",
        days_per_week=5,
        periods_per_day=6,
        teachers=[],
        rooms=[],
        subjects=[],
        columns=[],
    )
    defaults.update(kwargs)
    return TimetableConfig(**defaults)


# ---------------------------------------------------------------------------
# format_timetable_text with variable day lengths
# ---------------------------------------------------------------------------


def test_grid_shows_dash_for_short_day():
    """Cells beyond a day's period count should display '—'."""
    config = _make_config(
        days_per_week=2,
        periods_per_day=6,
        day_lengths={1: 7, 2: 5},
    )
    grid = format_timetable_text([], config, show_room=False, show_teacher=False)
    # Row P7 should exist (day 1 has 7 periods) and day 2 col should show "—"
    assert "P7" in grid
    assert "—" in grid


def test_grid_standard_day_no_dash():
    """When all days have equal lengths no '—' markers should appear."""
    config = _make_config(days_per_week=2, periods_per_day=3)
    grid = format_timetable_text([], config, show_room=False, show_teacher=False)
    assert "—" not in grid


def test_grid_shows_assignment_in_extra_period():
    """Assignments in extra periods (beyond the default) must be rendered."""
    config = _make_config(
        days_per_week=2,
        periods_per_day=6,
        day_lengths={1: 7},
        teachers=[Teacher("T")],
        columns=[Column("A")],
    )
    assignments = [Assignment("Math", "A", "T", "", 1, 7)]
    grid = format_timetable_text(assignments, config, show_room=False, show_teacher=False)
    assert "Math" in grid


# ---------------------------------------------------------------------------
# format_tutor_time_notification
# ---------------------------------------------------------------------------


def _simple_teacher_config(tutor_slots, scheduled_slots, unavailable=None):
    teacher = Teacher("Alice", unavailable=unavailable or [])
    config = _make_config(
        teachers=[teacher],
        tutor_time_slots=tutor_slots,
    )
    assignments = [
        Assignment("Math", "A", "Alice", "R1", d, p) for d, p in scheduled_slots
    ]
    return config, assignments


def test_tutor_time_empty_when_no_slots_configured():
    config = _make_config()
    result = format_tutor_time_notification([], config)
    assert result == ""


def test_tutor_time_available_when_slots_free():
    config, assignments = _simple_teacher_config(
        tutor_slots=[(1, 7), (2, 7)],
        scheduled_slots=[],  # teacher has no sessions
    )
    result = format_tutor_time_notification(assignments, config)
    assert "Alice" in result
    assert "tutor time" in result.lower()


def test_tutor_time_not_available_when_one_slot_occupied():
    config, assignments = _simple_teacher_config(
        tutor_slots=[(1, 7), (2, 7)],
        scheduled_slots=[(1, 7)],  # Mon P7 is taken
    )
    result = format_tutor_time_notification(assignments, config)
    # Alice should NOT appear as available
    assert "Alice" not in result


def test_tutor_time_not_available_when_slot_is_teacher_unavailable():
    config, assignments = _simple_teacher_config(
        tutor_slots=[(1, 7), (2, 7)],
        scheduled_slots=[],
        unavailable=[(1, 7)],  # teacher marks Mon P7 as unavailable
    )
    result = format_tutor_time_notification(assignments, config)
    assert "Alice" not in result


def test_tutor_time_slot_description_in_output():
    config, assignments = _simple_teacher_config(
        tutor_slots=[(1, 7), (2, 7)],
        scheduled_slots=[],
    )
    result = format_tutor_time_notification(assignments, config)
    assert "Mon P7" in result
    assert "Tue P7" in result


def test_tutor_time_no_teachers_available_message():
    """When no teacher is free, a 'no teachers available' message should appear."""
    config, assignments = _simple_teacher_config(
        tutor_slots=[(1, 7), (2, 7)],
        scheduled_slots=[(1, 7), (2, 7)],  # both slots occupied
    )
    result = format_tutor_time_notification(assignments, config)
    assert "No teachers" in result
