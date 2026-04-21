"""
Interactive review mode.

When the ``--interactive`` flag is passed, the user is asked to approve or
reject each *soft* conflict.  Hard conflicts are always reported but never
suppressed interactively (they require a configuration fix).
"""

from typing import List, Tuple

from .models import Conflict


def review_soft_conflicts(
    conflicts: List[Conflict],
) -> Tuple[List[Conflict], List[Conflict]]:
    """
    Walk the user through every soft conflict.

    Returns:
        accepted  – conflicts the user said are acceptable
        rejected  – conflicts the user said need fixing
    """
    soft = [c for c in conflicts if c.severity == "soft"]
    if not soft:
        print("No soft conflicts to review.")
        return [], []

    print(
        f"\n{'=' * 60}\n"
        f"Interactive review: {len(soft)} soft warning(s) found.\n"
        "You will be asked whether each is acceptable.\n"
        f"{'=' * 60}"
    )

    accepted: List[Conflict] = []
    rejected: List[Conflict] = []

    for i, conflict in enumerate(soft, 1):
        print(f"\n[{i}/{len(soft)}] {conflict}")
        while True:
            answer = input("  Accept this? (y/n/skip) [y]: ").strip().lower()
            if answer in ("", "y", "yes"):
                accepted.append(conflict)
                print("  → Accepted.")
                break
            elif answer in ("n", "no"):
                rejected.append(conflict)
                print("  → Flagged for review.")
                break
            elif answer in ("s", "skip"):
                print("  → Skipped (treated as accepted).")
                accepted.append(conflict)
                break
            else:
                print("  Please enter y, n, or skip.")

    print(
        f"\nReview complete: {len(accepted)} accepted, {len(rejected)} flagged.\n"
    )
    return accepted, rejected


def further_checks(assignments, config) -> None:
    """
    Optional further checks prompted interactively.

    Currently checks:
    • teacher daily load distribution
    • subjects without room preferences vs. capacity
    """
    from collections import defaultdict

    print("\n=== Further Checks ===")

    # Check teacher daily loads
    teacher_day_load: dict = defaultdict(lambda: defaultdict(int))
    for a in assignments:
        teacher_day_load[a.teacher][a.day] += 1

    print("\n[Check 1] Teacher daily period counts:")
    overloaded = []
    for teacher, days in sorted(teacher_day_load.items()):
        for day, count in sorted(days.items()):
            label = f"  {teacher}: Day {day} → {count} period(s)"
            print(label)
            if count > config.periods_on_day(day) * 0.7:
                overloaded.append((teacher, day, count))

    if overloaded:
        print("\n  The following teacher-day combinations look heavy (>70% of periods):")
        for teacher, day, count in overloaded:
            n = config.periods_on_day(day)
            print(f"    {teacher} on day {day}: {count}/{n}")
        answer = input("  Proceed anyway? (y/n) [y]: ").strip().lower()
        if answer in ("n", "no"):
            print("  → Flagged. Adjust the config to reduce daily loads.")
        else:
            print("  → Accepted.")
    else:
        print("  All teacher daily loads look reasonable.")

    # Check subjects assigned to rooms at capacity
    print("\n[Check 2] Room capacity vs subject assignments:")
    room_map = {r.name: r for r in config.rooms}
    for a in assignments:
        room = room_map.get(a.room)
        if room:
            # We don't track student counts in this model, so just show info
            print(f"  {a.subject} → {a.room} (capacity {room.capacity})")
    print("  (Student counts are not modelled; verify capacities manually.)")

    print("\n=== Further checks done ===\n")
