"""Data models for the timetabling application."""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# (day, period) — both 1-indexed
Slot = Tuple[int, int]


@dataclass
class Teacher:
    """A teacher who can deliver subjects."""

    name: str
    # Slots when this teacher is unavailable, e.g. [(1, 1), (3, 4)]
    unavailable: List[Slot] = field(default_factory=list)

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
    teacher: str
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
class TimetableConfig:
    """Complete timetable configuration supplied by the user."""

    name: str = "Timetable"
    days_per_week: int = 5
    periods_per_day: int = 6
    teachers: List[Teacher] = field(default_factory=list)
    rooms: List[Room] = field(default_factory=list)
    subjects: List[Subject] = field(default_factory=list)
    columns: List[Column] = field(default_factory=list)

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
