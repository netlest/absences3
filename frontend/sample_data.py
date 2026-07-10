"""
sample_data.py

Stand-in for the data that image.py pulls from the database (Object / VAbsence /
Holiday). Replace get_month_data() with real queries when wiring this into the
`absences` Flask/SQLAlchemy app.

Return shape expected by calendar_grid.build_context():
    objects  : ["Adam Zaleski", ...]                      # row labels, in order
    absences : [{"object": <label>, "day": int,
                 "duration": int, "color": "#rrggbb",
                 "caption": str}, ...]
    holidays : {day:int -> description:str}
"""

import calendar
from datetime import date, timedelta

# Row labels shown in the two example PNGs.
OBJECTS = [
    "Adam  Zaleski",
    "Kinga Zaleska",
    "Alicja Zaleska",
    "Ferie",
    "Wakacje",
    "Taxus",
    "Wiesia",
]

# A few sample absences so the grid clearly demonstrates coloured blocks,
# multi-day spans and captions. Keyed by (year, month).
_ABSENCES = {
    (2026, 7): [
        {"object": "Adam  Zaleski", "day": 6,  "duration": 36, "color": "#7ec8e3", "caption": "Urlop"},
        {"object": "Kinga Zaleska", "day": 20, "duration": 3, "color": "#f6b26b", "caption": "L4"},
        {"object": "Wakacje",       "day": 13, "duration": 10, "color": "#93c47d", "caption": "Wakacje"},
    ],
    (2026, 9): [
        {"object": "Ferie",  "day": 14, "duration": 5, "color": "#93c47d", "caption": "Ferie"},
        {"object": "Taxus",  "day": 3,  "duration": 2, "color": "#f6b26b", "caption": "Serwis"},
    ],
}

# Recurring / fixed holidays -> {(month) or (year, month): {day: desc}}.
# Simple example: keyed by (year, month).
_HOLIDAYS = {
    (2026, 7): {},
    (2026, 9): {},
    (2026, 5): {1: "Swieto Pracy", 3: "Konstytucja 3 Maja"},
    (2026, 11): {11: "Swieto Niepodleglosci"},
    (2026, 12): {25: "Boze Narodzenie", 26: "Boze Narodzenie"},
}


def get_month_data(year: int, month: int):
    """Return (objects, absences, holidays) for the requested month.

    An absence may span past the end of the month it is registered under
    (e.g. day 6 + duration 35). Any part of it that overlaps the requested
    month is returned, clipped to that month's boundaries.
    """
    objects = OBJECTS

    month_start = date(year, month, 1)
    month_end = date(year, month, calendar.monthrange(year, month)[1])

    absences = []
    for (y, m), items in _ABSENCES.items():
        for a in items:
            start = date(y, m, a["day"])
            end = start + timedelta(days=int(a.get("duration", 1) or 1) - 1)
            if end < month_start or start > month_end:
                continue
            clip_start = max(start, month_start)
            clip_end = min(end, month_end)
            absences.append(
                {**a, "day": clip_start.day,
                 "duration": (clip_end - clip_start).days + 1}
            )

    holidays = _HOLIDAYS.get((year, month), {})
    return objects, absences, holidays
