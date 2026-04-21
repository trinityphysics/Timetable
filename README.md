# Timetable

A constraint-based timetabling application.  Give it your teachers, rooms,
student columns (option blocks) and subjects — it will produce an optimised
timetable, report any hard conflicts that prevent a valid schedule, and flag
soft warnings for your review.

---

## Features

| Feature | Detail |
|---|---|
| **Columns / option blocks** | Group subjects that run in parallel; students pick one per column |
| **Teacher constraints** | Mark individual (day, period) slots as unavailable per teacher |
| **Room allocation** | Preferred rooms per subject; automatic fallback with warning |
| **Soft preferences** | Preferred periods per subject; spread across the week |
| **Conflict reporting** | Hard (invalid) and soft (sub-optimal) issues listed separately |
| **Interactive review** | `--interactive` walks you through every soft warning |
| **Further checks** | `--further-checks` prompts on teacher daily loads and room capacities |
| **Multiple output formats** | Terminal text grid, JSON (`--output-json`), CSV (`--output-csv`) |
| **Per-teacher / per-room views** | `--views teacher room` |
| **Multiple-teacher delivery check** | Flags if any subject ends up delivered by more than one teacher |

---

## Quick start

```bash
# Install (no heavy dependencies — only pytest for tests)
pip install -r requirements.txt

# Generate a timetable
python main.py config/example.json

# Show per-teacher and per-room views as well
python main.py config/example.json --views teacher room

# Interactively review soft conflicts
python main.py config/example.json --interactive

# Run further acceptability checks
python main.py config/example.json --further-checks

# Export to JSON and CSV
python main.py config/example.json --output-json out/timetable.json --output-csv out/timetable.csv

# Only validate config, do not schedule
python main.py config/example.json --validate-only

# Run tests
python -m pytest tests/ -v
```

---

## Configuration format

Configuration is a single JSON file.  See [`config/example.json`](config/example.json)
for a fully annotated example.

```jsonc
{
  "name": "My School Timetable",   // display name
  "days_per_week": 5,              // Mon–Fri = 5
  "periods_per_day": 6,            // periods 1–6

  // ── People ──────────────────────────────────────────────────────────────
  "teachers": [
    {
      "name": "Ms. Smith",
      // Slots when this teacher cannot be scheduled.
      // Each entry is [day, period] (both 1-indexed).
      "unavailable": [[1, 1], [5, 6]]
    }
  ],

  // ── Rooms ────────────────────────────────────────────────────────────────
  "rooms": [
    { "name": "Room 101",    "capacity": 30 },
    { "name": "Science Lab", "capacity": 25 }
  ],

  // ── Columns (option blocks) ───────────────────────────────────────────────
  // All subjects that share a column are scheduled at the same time slots.
  // Students choose exactly one subject per column.
  "columns": [
    {
      "name": "Column A",
      // Optional: slots when this whole column cannot run (e.g. assembly)
      "unavailable": [[3, 1]]
    },
    { "name": "Column B" }
  ],

  // ── Subjects ─────────────────────────────────────────────────────────────
  "subjects": [
    {
      "name": "Mathematics",
      "column": "Column A",        // must match a column name above
      "teacher": "Ms. Smith",      // must match a teacher name above
      "periods_per_week": 4,       // how many sessions per week
      "room": "Room 101",          // preferred/required room (optional)
      // Soft preference: schedule in these slots if possible
      "preferred_periods": [[1, 2], [2, 2], [3, 2]]
    },
    {
      "name": "Biology",
      "column": "Column A",
      "teacher": "Mr. Jones",
      "periods_per_week": 4,
      "room": "Science Lab"
    }
  ]
}
```

### Key rules

* A **column** is a set of subjects offered in parallel.  All subjects in the
  same column are scheduled to the same (day, period) slots.
* Every subject must reference a valid **column**, **teacher**, and (if given)
  **room** declared in the config.
* Slots are `[day, period]` where day 1 = Monday, period 1 = first lesson.
* If subjects in the same column have different `periods_per_week` values, the
  column is scheduled for the *maximum*; subjects with fewer periods use a
  subset of those slots.

---

## Constraint types

### Hard constraints (must be satisfied)
| Constraint | Description |
|---|---|
| Teacher availability | A teacher cannot be in two places at once |
| Teacher unavailability | Respects `unavailable` slots on each teacher |
| Column uniqueness | A column cannot be assigned to the same slot twice |
| Column unavailability | Respects `unavailable` slots on each column |
| Room uniqueness | Two subjects cannot share the same room in the same slot |

### Soft constraints (optimised, warnings raised on violation)
| Constraint | Description |
|---|---|
| Preferred periods | Subject sessions prefer specified (day, period) slots |
| Spread across week | Sessions prefer to be distributed across different days |
| Teacher load | Warns when a teacher has ≥4 consecutive periods on one day |
| Room substitution | Warns when the preferred room is unavailable and a different room is used |
| Multiple-teacher delivery | Warns (hard) if the same subject is somehow taught by more than one teacher |

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Schedule produced with no hard conflicts |
| `1` | Hard conflicts present, or config errors |

---

## Project structure

```
timetable/
  __init__.py
  models.py          # Data classes (Teacher, Room, Subject, Column, Assignment, Conflict)
  config_loader.py   # JSON loader and config validator
  scheduler.py       # Backtracking CSP scheduler + soft-constraint checks
  reporter.py        # Text / JSON / CSV output formatters
  interactive.py     # Interactive soft-conflict review and further-checks prompts
config/
  example.json       # Example school configuration
tests/
  test_config_loader.py
  test_scheduler.py
main.py              # CLI entry point
requirements.txt
```

---

## Running tests

```bash
python -m pytest tests/ -v
```
