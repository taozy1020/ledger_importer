"""The only place that reads the wall clock.

Recency decay and journal timestamps both depend on today's date, so a test
that pins the clock can assert exact numbers instead of tolerances.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


class SystemClock:
    def today(self) -> date:
        return date.today()


@dataclass(frozen=True, slots=True)
class FixedClock:
    """A clock that never moves. Use this in tests and in replays."""

    day: date

    def today(self) -> date:
        return self.day
