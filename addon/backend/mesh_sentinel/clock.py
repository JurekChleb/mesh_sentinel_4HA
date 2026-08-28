"""Injectable clock.

The correlation engine is deterministic and must be testable without sleeping.
Every component takes a ``Clock`` instead of calling ``time.time()`` directly.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


class Clock:
    """Wall clock, unix epoch seconds (UTC)."""

    def now(self) -> float:
        return time.time()


@dataclass
class FakeClock(Clock):
    """Manually advanced clock used by the test suite."""

    current: float = field(default=1_700_000_000.0)

    def now(self) -> float:
        return self.current

    def advance(self, seconds: float) -> float:
        self.current += seconds
        return self.current

    def set(self, value: float) -> float:
        self.current = value
        return self.current
