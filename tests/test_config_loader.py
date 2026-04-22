"""Tests for config_loader module."""

import json
import os
import tempfile

import pytest

from timetable.config_loader import load_config, parse_config, validate_config
from timetable.models import TimetableConfig


# ---------------------------------------------------------------------------
# parse_config
# ---------------------------------------------------------------------------


def _minimal_data():
    return {
        "name": "Test",
        "days_per_week": 5,
        "periods_per_day": 6,
        "teachers": [{"name": "Teacher A"}],
        "rooms": [{"name": "Room 1"}],
        "columns": [{"name": "Col 1"}],
        "subjects": [
            {
                "name": "Math",
                "column": "Col 1",
                "teacher": "Teacher A",
                "periods_per_week": 2,
                "room": "Room 1",
            }
        ],
    }


def test_parse_config_basic():
    data = _minimal_data()
    config = parse_config(data)
    assert config.name == "Test"
    assert config.days_per_week == 5
    assert config.periods_per_day == 6
    assert len(config.teachers) == 1
    assert config.teachers[0].name == "Teacher A"
    assert len(config.subjects) == 1
    assert config.subjects[0].name == "Math"


def test_parse_config_defaults():
    config = parse_config({})
    assert config.days_per_week == 5
    assert config.periods_per_day == 6


def test_parse_config_unavailable_slots():
    data = _minimal_data()
    data["teachers"][0]["unavailable"] = [[1, 2], [3, 4]]
    config = parse_config(data)
    assert (1, 2) in config.teachers[0].unavailable
    assert (3, 4) in config.teachers[0].unavailable


def test_parse_config_column_pinned_slots():
    """pinned_slots in a columns entry must be parsed and stored on the Column object."""
    data = _minimal_data()
    data["columns"][0]["pinned_slots"] = [[1, 1], [2, 3], [4, 5]]
    config = parse_config(data)
    assert config.columns[0].pinned_slots == [(1, 1), (2, 3), (4, 5)]


def test_parse_config_column_pinned_slots_empty_by_default():
    """Columns without pinned_slots should default to an empty list."""
    config = parse_config(_minimal_data())
    assert config.columns[0].pinned_slots == []


def test_parse_config_preferred_periods():
    data = _minimal_data()
    data["subjects"][0]["preferred_periods"] = [[2, 3], [4, 5]]
    config = parse_config(data)
    assert (2, 3) in config.subjects[0].preferred_periods


# ---------------------------------------------------------------------------
# validate_config
# ---------------------------------------------------------------------------


def test_validate_config_valid():
    config = parse_config(_minimal_data())
    errors = validate_config(config)
    # Only warnings expected (none in this config)
    hard_errors = [e for e in errors if not e.startswith("WARNING")]
    assert hard_errors == []


def test_validate_config_missing_teacher():
    data = _minimal_data()
    data["subjects"][0]["teacher"] = "Ghost Teacher"
    config = parse_config(data)
    errors = validate_config(config)
    assert any("Ghost Teacher" in e for e in errors)


def test_validate_config_missing_column():
    data = _minimal_data()
    data["subjects"][0]["column"] = "No Such Column"
    config = parse_config(data)
    errors = validate_config(config)
    assert any("No Such Column" in e for e in errors)


def test_validate_config_missing_room():
    data = _minimal_data()
    data["subjects"][0]["room"] = "Phantom Room"
    config = parse_config(data)
    errors = validate_config(config)
    assert any("Phantom Room" in e for e in errors)


def test_validate_config_out_of_range_slot():
    data = _minimal_data()
    data["teachers"][0]["unavailable"] = [[99, 99]]
    config = parse_config(data)
    errors = validate_config(config)
    assert any("out of range" in e.lower() for e in errors)


def test_validate_config_multi_column_teacher_no_warning():
    """Teachers appearing in multiple columns no longer generate a warning.
    Each class uses a unique internal column ID, so a teacher teaching several
    classes will always span multiple columns — the warning was removed."""
    data = _minimal_data()
    data["columns"].append({"name": "Col 2"})
    data["subjects"].append(
        {
            "name": "Science",
            "column": "Col 2",
            "teacher": "Teacher A",
            "periods_per_week": 1,
        }
    )
    config = parse_config(data)
    errors = validate_config(config)
    assert not any("multiple columns" in e for e in errors)


# ---------------------------------------------------------------------------
# load_config (file I/O)
# ---------------------------------------------------------------------------


def test_load_config_from_file():
    data = _minimal_data()
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as fh:
        json.dump(data, fh)
        tmp_path = fh.name
    try:
        config = load_config(tmp_path)
        assert config.name == "Test"
    finally:
        os.unlink(tmp_path)


def test_load_config_example_file():
    example = os.path.join(
        os.path.dirname(__file__), "..", "config", "example.json"
    )
    assert os.path.isfile(example), "example.json not found"
    config = load_config(example)
    assert config.name == "Example School Timetable"
    assert len(config.subjects) == 7
    assert len(config.teachers) == 4


# ---------------------------------------------------------------------------
# day_lengths and tutor_time_slots
# ---------------------------------------------------------------------------


def test_parse_config_day_lengths():
    data = _minimal_data()
    data["day_lengths"] = {"1": 7, "2": 7}
    config = parse_config(data)
    assert config.periods_on_day(1) == 7
    assert config.periods_on_day(2) == 7
    # Unspecified days fall back to periods_per_day (6)
    assert config.periods_on_day(3) == 6


def test_parse_config_day_lengths_integer_keys():
    """JSON may decode keys as strings; config_loader must handle both."""
    data = _minimal_data()
    data["day_lengths"] = {1: 5, 3: 4}  # integer keys
    config = parse_config(data)
    assert config.periods_on_day(1) == 5
    assert config.periods_on_day(3) == 4


def test_parse_config_tutor_time_slots():
    data = _minimal_data()
    data["tutor_time_slots"] = [[1, 7], [2, 7]]
    data["day_lengths"] = {"1": 7, "2": 7}
    config = parse_config(data)
    assert (1, 7) in config.tutor_time_slots
    assert (2, 7) in config.tutor_time_slots


def test_all_slots_respects_day_lengths():
    data = _minimal_data()
    data["day_lengths"] = {"1": 7, "2": 7}
    config = parse_config(data)
    slots = config.all_slots()
    # Day 1 and 2 should have period 7
    assert (1, 7) in slots
    assert (2, 7) in slots
    # Day 3 should not have period 7 (only 6 periods)
    assert (3, 7) not in slots


def test_total_slots_with_day_lengths():
    data = _minimal_data()
    data["day_lengths"] = {"1": 7, "2": 7}
    config = parse_config(data)
    # 7 + 7 + 6 + 6 + 6 = 32
    assert config.total_slots() == 32


def test_validate_config_day_lengths_out_of_range_day():
    data = _minimal_data()
    data["day_lengths"] = {"99": 3}
    config = parse_config(data)
    errors = validate_config(config)
    assert any("day 99" in e and "out of range" in e for e in errors)


def test_validate_config_day_lengths_zero_periods():
    data = _minimal_data()
    data["day_lengths"] = {"1": 0}
    config = parse_config(data)
    errors = validate_config(config)
    assert any("day 1" in e and "at least 1 period" in e for e in errors)


def test_validate_config_tutor_time_slot_out_of_range():
    data = _minimal_data()
    data["tutor_time_slots"] = [[1, 99]]
    config = parse_config(data)
    errors = validate_config(config)
    assert any("tutor_time_slots" in e and "out of range" in e for e in errors)


def test_validate_config_tutor_time_slot_in_day_length_range():
    """A tutor-time slot that is valid only because of day_lengths should pass."""
    data = _minimal_data()
    data["day_lengths"] = {"1": 7}
    data["tutor_time_slots"] = [[1, 7]]
    config = parse_config(data)
    errors = validate_config(config)
    assert not any("tutor_time_slots" in e for e in errors)
