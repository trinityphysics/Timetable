"""
Core timetable scheduler.

Algorithm
---------
1.  Group subjects by column.  All subjects in a column share the same set
    of time slots (students choose one subject per column, so they all run
    in parallel).

2.  Build a list of *tasks*: one (column, instance_index) pair per session
    that must be placed on the timetable.

3.  Order tasks from *most constrained* to *least constrained* (fewest valid
    slots first) to improve backtracking efficiency.

4.  Backtracking search: assign each task to a (day, period) slot satisfying
    all hard constraints.  When no slot exists the task is recorded as a hard
    conflict and the search continues (best-effort, so a partial timetable is
    always returned).

5.  Room allocation: after slots are decided, assign requested (or best
    available) rooms.

6.  Soft-constraint check: after the full timetable is built, flag soft
    violations (teacher overloads, preferred-period misses, multiple-teacher
    delivery of the same subject across different sessions).
"""

from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from .models import Assignment, Column, Conflict, Slot, Subject, TimetableConfig


class Scheduler:
    def __init__(self, config: TimetableConfig) -> None:
        self.config = config
        self.assignments: List[Assignment] = []
        self.conflicts: List[Conflict] = []

        # Fast-lookup maps
        self.teacher_map = {t.name: t for t in config.teachers}
        self.room_map = {r.name: r for r in config.rooms}
        self.column_map = {c.name: c for c in config.columns}

        self.all_slots: List[Slot] = config.all_slots()

        # subjects grouped by column name
        self._col_subjects: Dict[str, List[Subject]] = defaultdict(list)
        for s in config.subjects:
            self._col_subjects[s.column].append(s)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def schedule(self) -> Tuple[List[Assignment], List[Conflict]]:
        """Run the scheduler and return (assignments, conflicts)."""
        self.assignments = []
        self.conflicts = []

        # How many slots does each column need?
        col_periods: Dict[str, int] = {}
        for col_name, subjects in self._col_subjects.items():
            col_periods[col_name] = max(s.periods_per_week for s in subjects)

        # Warn about period-count mismatches within a column
        for col_name, subjects in self._col_subjects.items():
            counts = {s.periods_per_week for s in subjects}
            if len(counts) > 1:
                self.conflicts.append(
                    Conflict(
                        severity="soft",
                        category="period_count_mismatch",
                        description=(
                            f"Column '{col_name}' subjects have different "
                            f"periods_per_week values ({sorted(counts)}). "
                            "The column will be scheduled for the maximum value; "
                            "subjects with fewer periods will be assigned a subset."
                        ),
                        subjects=[s.name for s in subjects],
                    )
                )

        # Build tasks: (column_name, instance_index)
        tasks: List[Tuple[str, int]] = [
            (col, i) for col, n in col_periods.items() for i in range(n)
        ]

        # Order: most constrained first
        tasks = self._order_tasks(tasks)

        # Backtracking search
        slot_assignments: Dict[Tuple[str, int], Slot] = {}
        self._backtrack(tasks, 0, slot_assignments)

        # Build Assignment objects and allocate rooms
        self._build_assignments(slot_assignments)

        # Post-schedule soft checks
        self._check_soft_constraints()

        return self.assignments, self.conflicts

    # ------------------------------------------------------------------
    # Ordering heuristic
    # ------------------------------------------------------------------

    def _order_tasks(
        self, tasks: List[Tuple[str, int]]
    ) -> List[Tuple[str, int]]:
        """Sort tasks so the most constrained (fewest valid slots) come first."""
        empty: Dict[Tuple[str, int], Slot] = {}

        def domain_size(task: Tuple[str, int]) -> int:
            col, _ = task
            return len(self._valid_slots_for(col, set(), empty))

        return sorted(tasks, key=domain_size)

    # ------------------------------------------------------------------
    # Backtracking CSP solver
    # ------------------------------------------------------------------

    def _backtrack(
        self,
        tasks: List[Tuple[str, int]],
        idx: int,
        slot_assignments: Dict[Tuple[str, int], Slot],
    ) -> bool:
        """
        Assign slots to tasks[idx:] by backtracking.

        Returns True when *all remaining tasks* were placed.  On failure the
        unplaceable task is recorded as a hard conflict and the search
        continues (best-effort).
        """
        if idx == len(tasks):
            return True

        col_name, instance = tasks[idx]

        # Slots already used by other instances of this column
        used_by_col: Set[Slot] = {
            s for (c, _), s in slot_assignments.items() if c == col_name
        }

        candidates = self._rank_slots(
            col_name, instance, used_by_col, slot_assignments
        )

        for slot in candidates:
            if self._is_valid(col_name, slot, used_by_col, slot_assignments):
                slot_assignments[(col_name, instance)] = slot
                if self._backtrack(tasks, idx + 1, slot_assignments):
                    return True
                del slot_assignments[(col_name, instance)]

        # Could not place — record conflict and continue best-effort
        self.conflicts.append(
            Conflict(
                severity="hard",
                category="unschedulable",
                description=(
                    f"Cannot schedule column '{col_name}' "
                    f"session {instance + 1}: no valid slot found."
                ),
                subjects=[s.name for s in self._col_subjects.get(col_name, [])],
            )
        )
        # Continue without this task so downstream tasks still get placed
        return self._backtrack(tasks, idx + 1, slot_assignments)

    # ------------------------------------------------------------------
    # Constraint checking
    # ------------------------------------------------------------------

    def _is_valid(
        self,
        col_name: str,
        slot: Slot,
        used_by_col: Set[Slot],
        slot_assignments: Dict[Tuple[str, int], Slot],
    ) -> bool:
        """Return True if assigning *col_name* to *slot* satisfies all hard constraints."""
        day, period = slot

        # Column already uses this slot
        if slot in used_by_col:
            return False

        # Column unavailability
        col_obj = self.column_map.get(col_name)
        if col_obj and slot in col_obj.unavailable:
            return False

        subjects = self._col_subjects.get(col_name, [])

        # Collect teachers and rooms already committed at this slot
        teachers_at_slot: Set[str] = set()
        rooms_at_slot: Set[str] = set()
        for (other_col, _), other_slot in slot_assignments.items():
            if other_slot != slot:
                continue
            for os in self._col_subjects.get(other_col, []):
                teachers_at_slot.add(os.teacher)
                if os.room:
                    rooms_at_slot.add(os.room)

        for subj in subjects:
            # Teacher unavailability (skip if no teacher assigned yet)
            if subj.teacher:
                teacher = self.teacher_map.get(subj.teacher)
                if teacher and not teacher.is_available(slot):
                    return False

                # Teacher already teaching another column at this slot
                if subj.teacher in teachers_at_slot:
                    return False

            # Requested room already taken at this slot
            if subj.room and subj.room in rooms_at_slot:
                return False

        return True

    def _valid_slots_for(
        self,
        col_name: str,
        used_by_col: Set[Slot],
        slot_assignments: Dict[Tuple[str, int], Slot],
    ) -> List[Slot]:
        """Return all valid slots for *col_name* given current assignments."""
        return [
            s
            for s in self.all_slots
            if self._is_valid(col_name, s, used_by_col, slot_assignments)
        ]

    # ------------------------------------------------------------------
    # Slot ranking (soft preferences)
    # ------------------------------------------------------------------

    def _rank_slots(
        self,
        col_name: str,
        instance: int,
        used_by_col: Set[Slot],
        slot_assignments: Dict[Tuple[str, int], Slot],
    ) -> List[Slot]:
        """
        Return candidate slots sorted best-first.

        Higher score = better:
          +10  slot is preferred by at least one subject in the column
          +5   slot is on a day not yet used by this column (spread across week)
          +1   slot is in the first half of the day (earlier delivery preferred)
        """
        subjects = self._col_subjects.get(col_name, [])
        preferred: Set[Slot] = set()
        for s in subjects:
            preferred.update(s.preferred_periods)

        days_used = {d for d, _ in used_by_col}

        def score(slot: Slot) -> int:
            d, p = slot
            s = 0
            if slot in preferred:
                s += 10
            if d not in days_used:
                s += 5
            if p <= self.config.periods_on_day(d) // 2:
                s += 1
            return s

        return sorted(
            [s for s in self.all_slots if s not in used_by_col],
            key=lambda s: -score(s),
        )

    # ------------------------------------------------------------------
    # Build final Assignment objects + room allocation
    # ------------------------------------------------------------------

    def _build_assignments(
        self, slot_assignments: Dict[Tuple[str, int], Slot]
    ) -> None:
        """
        Convert (col, instance) → slot map into Assignment objects.

        Also allocate rooms: use the subject's requested room if available,
        otherwise pick any free room; flag a hard conflict if none exists.
        """
        room_names = [r.name for r in self.config.rooms]

        # rooms_used_at[slot] = set of room names already allocated at that slot
        rooms_used_at: Dict[Slot, Set[str]] = defaultdict(set)

        # Group tasks by slot for deterministic ordering
        ordered: List[Tuple[Tuple[str, int], Slot]] = sorted(
            slot_assignments.items(), key=lambda kv: kv[1]
        )

        for (col_name, instance), slot in ordered:
            subjects = self._col_subjects.get(col_name, [])

            for subj in subjects:
                # Skip this subject if it doesn't run in this many sessions
                if instance >= subj.periods_per_week:
                    continue

                assigned_room = self._allocate_room(
                    subj, slot, rooms_used_at, room_names
                )

                self.assignments.append(
                    Assignment(
                        subject=subj.name,
                        column=col_name,
                        teacher=subj.teacher,
                        room=assigned_room,
                        day=slot[0],
                        period=slot[1],
                    )
                )

    def _allocate_room(
        self,
        subj: Subject,
        slot: Slot,
        rooms_used_at: Dict[Slot, Set[str]],
        room_names: List[str],
    ) -> str:
        """Pick a room for *subj* at *slot*; record usage and return room name."""
        taken = rooms_used_at[slot]

        # Try requested room first
        if subj.room:
            if subj.room not in taken:
                taken.add(subj.room)
                return subj.room
            # Requested room is taken — try to find any free room
            for r in room_names:
                if r not in taken:
                    self.conflicts.append(
                        Conflict(
                            severity="soft",
                            category="room_substitution",
                            description=(
                                f"Subject '{subj.name}': requested room "
                                f"'{subj.room}' unavailable at "
                                f"day {slot[0]}, period {slot[1]}. "
                                f"Assigned '{r}' instead."
                            ),
                            day=slot[0],
                            period=slot[1],
                            subjects=[subj.name],
                        )
                    )
                    taken.add(r)
                    return r
            # No room at all — hard conflict
            self.conflicts.append(
                Conflict(
                    severity="hard",
                    category="no_room_available",
                    description=(
                        f"No room available for '{subj.name}' at "
                        f"day {slot[0]}, period {slot[1]}."
                    ),
                    day=slot[0],
                    period=slot[1],
                    subjects=[subj.name],
                )
            )
            return "UNASSIGNED"

        # No preference — take any free room
        for r in room_names:
            if r not in taken:
                taken.add(r)
                return r

        # No rooms configured / all taken
        if not room_names:
            return "No rooms configured"
        self.conflicts.append(
            Conflict(
                severity="hard",
                category="no_room_available",
                description=(
                    f"No room available for '{subj.name}' at "
                    f"day {slot[0]}, period {slot[1]}."
                ),
                day=slot[0],
                period=slot[1],
                subjects=[subj.name],
            )
        )
        return "UNASSIGNED"

    # ------------------------------------------------------------------
    # Post-schedule soft constraint checks
    # ------------------------------------------------------------------

    def _check_soft_constraints(self) -> None:
        """Append soft conflicts for workload and preference violations."""

        # --- Teacher consecutive-period overload ---
        MAX_CONSECUTIVE = 4
        teacher_slots_by_day: Dict[str, Dict[int, List[int]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for a in self.assignments:
            teacher_slots_by_day[a.teacher][a.day].append(a.period)

        for teacher_name, days in teacher_slots_by_day.items():
            for day, periods in days.items():
                periods_sorted = sorted(set(periods))
                run = 1
                for i in range(1, len(periods_sorted)):
                    if periods_sorted[i] == periods_sorted[i - 1] + 1:
                        run += 1
                        if run > MAX_CONSECUTIVE:
                            self.conflicts.append(
                                Conflict(
                                    severity="soft",
                                    category="teacher_consecutive_overload",
                                    description=(
                                        f"Teacher '{teacher_name}' has "
                                        f"{run} consecutive periods on day {day}."
                                    ),
                                    day=day,
                                )
                            )
                            break
                    else:
                        run = 1

        # --- Preferred period misses ---
        missed = []
        for a in self.assignments:
            subj = next(
                (s for s in self.config.subjects if s.name == a.subject), None
            )
            if subj and subj.preferred_periods and a.slot not in subj.preferred_periods:
                missed.append(a.subject)

        if missed:
            self.conflicts.append(
                Conflict(
                    severity="soft",
                    category="preferred_period_miss",
                    description=(
                        f"{len(missed)} session(s) not placed in their preferred "
                        f"period(s): {', '.join(missed)}."
                    ),
                    subjects=missed,
                )
            )

        # --- Multiple-teacher delivery check ---
        # Flag if the same subject's sessions are taught by different teachers
        # (in our model each subject has one teacher, so this acts as a sanity check).
        subj_teachers: Dict[str, Set[str]] = defaultdict(set)
        for a in self.assignments:
            subj_teachers[a.subject].add(a.teacher)
        for subj_name, teachers in subj_teachers.items():
            if len(teachers) > 1:
                self.conflicts.append(
                    Conflict(
                        severity="hard",
                        category="multiple_teacher_delivery",
                        description=(
                            f"Subject '{subj_name}' is being delivered by "
                            f"multiple teachers: {', '.join(sorted(teachers))}. "
                            "This violates the single-teacher constraint."
                        ),
                        subjects=[subj_name],
                    )
                )
