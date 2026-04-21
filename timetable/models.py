"""Data models for the timetabling application."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# (day, period) — both 1-indexed
Slot = Tuple[int, int]


@dataclass
class Teacher:
    """A teacher who can deliver subjects."""

    name: str
    # Slots when this teacher is unavailable, e.g. [(1, 1), (3, 4)]
    unavailable: List[Slot] = field(default_factory=list)
    # Number of non-contact (free) periods per week this teacher is entitled to
    non_contact_entitlement: int = 0

    def is_available(self, slot: Slot) -> bool:
        return slot not in self.unavailable


@dataclass
class Room:
    """A room where subjects can be taught."""

    name: str
    capacity: int = 30


@dataclass
class Subject:
    """A subject taught by one teacher, belonging to one column (option block)."""

    name: str
    # Which column/option-block this subject belongs to.
    # All subjects sharing a column are scheduled in the same time slots
    # (students pick exactly one subject per column).
    column: str
    # Teacher name; empty string means teacher is yet to be assigned.
    teacher: str = ""
    periods_per_week: int = 1
    # If set, this room is requested for every session of this subject.
    room: Optional[str] = None
    # Soft preference: [(day, period), ...]
    preferred_periods: List[Slot] = field(default_factory=list)


@dataclass
class Column:
    """
    An option block (column).  All subjects in the same column run
    simultaneously — students choose exactly one per column.
    """

    name: str
    # Slots when this column cannot be scheduled (e.g. assembly, sport)
    unavailable: List[Slot] = field(default_factory=list)


@dataclass
class YearGroup:
    """
    A school year group (e.g. S3, S4, S5).

    Stores the mapping of (day, period) → column letter so the timetable
    can show which column runs at each time slot for this year group.
    Each entry in *period_map* is a ``(day, period, column_name)`` tuple.
    """

    name: str
    # List of (day, period, column_name) mappings for this year group
    period_map: List[Tuple[int, int, str]] = field(default_factory=list)


@dataclass
class Class:
    """
    A class (group of students) to be scheduled.

    When *sections* > 1 the class is split into multiple groups, each
    receiving an auto-generated code.  Codes have the form::

        {year_group}-{subject_initial}-{level_abbrev}-{column}-{section}

    e.g. ``S5-P-H-E-1`` (S5, Physics, Higher, Column E, Section 1).

    *allowed_teachers* controls teacher assignment:

    - Empty list → any available teacher may be used.
    - 1 teacher  → that teacher is pinned to every section (hard rule).
    - len == sections (and > 1) → teacher[i] is assigned to section i+1
      as a hard 1-per-section rule.
    - len == sections (and == 1) → same as 1-teacher case above.
    - Any other length → any of the listed teachers may be used (pool).

    Individual entries may be ``""`` to mean "any" for that section when
    *allowed_teachers* is used as a per-section specification.
    """

    year_group: str
    subject: str
    level: str
    column: str
    sections: int = 1
    # See class docstring for semantics.
    allowed_teachers: List[str] = field(default_factory=list)
    periods_per_week: int = 1
    room: Optional[str] = None

    def codes(self) -> List[str]:
        """Return the generated class code(s) for this class.

        Format: ``{year_group}-{subject_initial}-{level_abbrev}-{column}-{section}``
        e.g. ``S5-P-H-E-1`` or ``S4-E-N5-A-2``.
        """
        subj_init = self.subject[0].upper() if self.subject else "X"
        lvl = self.level.strip().lower()
        if lvl in ("n5", "national 5"):
            level_abbrev = "N5"
        elif lvl in ("higher", "h"):
            level_abbrev = "H"
        elif lvl in ("ah", "advanced higher"):
            level_abbrev = "AH"
        else:
            raw = self.level[:2].upper() if self.level else ""
            level_abbrev = raw if len(raw) == 2 else (raw + "X" if raw else "XX")
        prefix = f"{self.year_group}-{subj_init}-{level_abbrev}-{self.column}"
        return [f"{prefix}-{i}" for i in range(1, self.sections + 1)]


@dataclass
class TimetableConfig:
    """Complete timetable configuration supplied by the user."""

    name: str = "Timetable"
    days_per_week: int = 5
    periods_per_day: int = 6
    teachers: List[Teacher] = field(default_factory=list)
    rooms: List[Room] = field(default_factory=list)
    subjects: List[Subject] = field(default_factory=list)
    columns: List[Column] = field(default_factory=list)
    # New structured input (Steps 1-3 of the wizard)
    year_groups: List[YearGroup] = field(default_factory=list)
    classes: List[Class] = field(default_factory=list)

    def all_slots(self) -> List[Slot]:
        """Return every (day, period) slot in the week."""
        return [
            (day, period)
            for day in range(1, self.days_per_week + 1)
            for period in range(1, self.periods_per_day + 1)
        ]


@dataclass
class Assignment:
    """A single scheduled lesson: one subject at one time slot."""

    subject: str
    column: str
    teacher: str
    room: str
    day: int
    period: int

    @property
    def slot(self) -> Slot:
        return (self.day, self.period)


@dataclass
class Conflict:
    """A scheduling issue found during or after scheduling."""

    # 'hard' = constraint cannot be satisfied (timetable is invalid)
    # 'soft' = preference not met (timetable works but is sub-optimal)
    severity: str
    category: str
    description: str
    day: Optional[int] = None
    period: Optional[int] = None
    subjects: List[str] = field(default_factory=list)

    def __str__(self) -> str:
        loc = ""
        if self.day is not None:
            loc = f" [Day {self.day}"
            if self.period is not None:
                loc += f", Period {self.period}"
            loc += "]"
        return f"[{self.severity.upper()}] {self.category}: {self.description}{loc}"
