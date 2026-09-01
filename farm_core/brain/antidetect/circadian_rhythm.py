"""
Circadian Rhythm — Daily activity pattern modeling.

Generates per-persona daily activity schedules with chronotype support
(night_owl, early_bird, standard), weekend shifts, and session duration
based on time of day.
"""
import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Literal, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except ImportError:
    try:
        from backports.zoneinfo import ZoneInfo
    except ImportError:
        ZoneInfo = None  # type: ignore[misc,assignment]


@dataclass
class ActivityWindow:
    start_hour: int
    end_hour: int
    activity_level: float  # 0.0–1.0
    session_duration_range: Tuple[int, int]  # minutes


CHRONOTYPE_SCHEDULES: Dict[str, List[ActivityWindow]] = {
    "night_owl": [
        ActivityWindow(0, 1, 0.8, (20, 40)),
        ActivityWindow(1, 9, 0.0, (1, 2)),
        ActivityWindow(9, 10, 0.2, (3, 5)),
        ActivityWindow(10, 12, 0.3, (5, 10)),
        ActivityWindow(12, 13, 0.5, (10, 15)),
        ActivityWindow(13, 17, 0.2, (3, 5)),
        ActivityWindow(17, 19, 0.5, (15, 20)),
        ActivityWindow(19, 22, 0.9, (25, 40)),
        ActivityWindow(22, 24, 0.7, (15, 30)),
    ],
    "early_bird": [
        ActivityWindow(6, 7, 0.4, (5, 10)),
        ActivityWindow(7, 9, 0.5, (5, 10)),
        ActivityWindow(9, 12, 0.2, (3, 5)),
        ActivityWindow(12, 13, 0.5, (10, 15)),
        ActivityWindow(13, 17, 0.2, (3, 5)),
        ActivityWindow(17, 19, 0.5, (10, 15)),
        ActivityWindow(19, 21, 0.9, (20, 30)),
        ActivityWindow(21, 22, 0.4, (5, 10)),
        ActivityWindow(22, 6, 0.0, (0, 0)),
    ],
    "standard": [
        ActivityWindow(7, 8, 0.3, (5, 10)),
        ActivityWindow(8, 9, 0.4, (5, 10)),
        ActivityWindow(9, 12, 0.2, (3, 5)),
        ActivityWindow(12, 13, 0.5, (10, 15)),
        ActivityWindow(13, 17, 0.2, (3, 5)),
        ActivityWindow(17, 19, 0.5, (10, 15)),
        ActivityWindow(19, 22, 0.8, (20, 35)),
        ActivityWindow(22, 23, 0.5, (10, 15)),
        ActivityWindow(23, 7, 0.0, (0, 0)),
    ],
}


def _circular_mean(angles: List[float], period: float = 24.0) -> float:
    """Circular mean for hour-of-day values."""
    s = sum(math.sin(2 * math.pi * a / period) for a in angles)
    c = sum(math.cos(2 * math.pi * a / period) for a in angles)
    return (math.atan2(s, c) * period / (2 * math.pi)) % period


def _kde_evaluate(samples: List[float], x: float, bandwidth: float = 1.5) -> float:
    """Gaussian KDE on circular domain [0, 24) for hour-of-day data."""
    if not samples:
        return 0.0
    n = len(samples)
    total = 0.0
    for s in samples:
        diff = abs(x - s)
        diff = min(diff, 24.0 - diff)
        total += math.exp(-0.5 * (diff / bandwidth) ** 2)
    return total / (n * bandwidth * math.sqrt(2 * math.pi))


class CircadianRhythm:
    """Per-persona daily activity schedule with chronotype."""

    def __init__(self, persona: Dict, persona_seed: int = 0):
        rng = random.Random(persona_seed)

        age = persona.get("age", 25)
        if age < 25:
            default_chrono = rng.choices(
                ["night_owl", "standard", "early_bird"], weights=[50, 40, 10],
            )[0]
        elif age < 35:
            default_chrono = rng.choices(
                ["night_owl", "standard", "early_bird"], weights=[25, 50, 25],
            )[0]
        else:
            default_chrono = rng.choices(
                ["night_owl", "standard", "early_bird"], weights=[10, 40, 50],
            )[0]

        self.chronotype = persona.get("chronotype", default_chrono)
        self.schedule = CHRONOTYPE_SCHEDULES[self.chronotype]

        self.jitter_minutes = rng.randint(10, 40)
        self.weekend_shift_hours = rng.uniform(1.0, 2.5)
        self.weekend_duration_mult = rng.uniform(1.3, 2.0)
        self.night_wakeup_prob = rng.uniform(0.03, 0.10)

    def get_activity_level(self, dt: datetime) -> float:
        hour = dt.hour
        is_weekend = dt.weekday() >= 5

        if is_weekend:
            hour = int((hour - self.weekend_shift_hours) % 24)

        for window in self.schedule:
            start, end = window.start_hour, window.end_hour
            if start <= end:
                if start <= hour < end:
                    return window.activity_level
            else:
                if hour >= start or hour < end:
                    return window.activity_level
        return 0.0

    def get_session_duration(self, dt: datetime) -> int:
        """Session duration in minutes for the given time."""
        hour = dt.hour
        is_weekend = dt.weekday() >= 5

        if is_weekend:
            hour = int((hour - self.weekend_shift_hours) % 24)

        for window in self.schedule:
            start, end = window.start_hour, window.end_hour
            in_window = False
            if start <= end:
                in_window = start <= hour < end
            else:
                in_window = hour >= start or hour < end

            if in_window:
                lo, hi = window.session_duration_range
                if lo == 0 and hi == 0:
                    return 0
                duration = random.randint(lo, hi)
                if is_weekend:
                    duration = int(duration * self.weekend_duration_mult)
                return duration

        return 0

    def should_start_session(self, dt: datetime) -> bool:
        """Probabilistic check whether a session should start now."""
        level = self.get_activity_level(dt)
        if level <= 0:
            return random.random() < self.night_wakeup_prob
        return random.random() < level

    def get_next_session_time(self, after: datetime) -> datetime:
        """Find the next plausible session start time."""
        candidate = after + timedelta(minutes=random.randint(5, 30))
        for _ in range(288):  # up to 24h in 5-min increments
            if self.should_start_session(candidate):
                jitter = timedelta(minutes=random.randint(-self.jitter_minutes, self.jitter_minutes))
                return candidate + jitter
            candidate += timedelta(minutes=5)
        return candidate

    def get_sessions_per_day(self, dt: datetime) -> int:
        """Expected number of sessions for the given day."""
        total = sum(
            w.activity_level * max(1, (w.end_hour - w.start_hour) % 24)
            for w in self.schedule
            if w.activity_level > 0
        )
        sessions = int(total * random.uniform(0.7, 1.3))
        if dt.weekday() >= 5:
            sessions = int(sessions * 1.3)
        return max(1, sessions)

    @classmethod
    def from_data(cls, sessions: List[Dict], timezone: Optional[str] = None) -> "CircadianRhythm":
        """Learn schedule from real session timestamps.

        Args:
            sessions: list of dicts with 'start_time' (datetime or ISO string)
                      and optionally 'duration_minutes'.
            timezone: IANA timezone string (e.g. 'America/New_York').
        """
        instance = cls.__new__(cls)
        instance.chronotype = "learned"
        instance.jitter_minutes = 15
        instance.weekend_shift_hours = 0.0
        instance.weekend_duration_mult = 1.0
        instance.night_wakeup_prob = 0.05

        tz = None
        if timezone and ZoneInfo is not None:
            tz = ZoneInfo(timezone)
        instance._timezone = tz

        hours: List[float] = []
        weekend_hours: List[float] = []
        durations_by_hour: Dict[int, List[int]] = {h: [] for h in range(24)}

        for s in sessions:
            ts = s.get("start_time")
            if ts is None:
                continue
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            if tz and ts.tzinfo is None:
                ts = ts.replace(tzinfo=tz)
            elif tz:
                ts = ts.astimezone(tz)

            h = ts.hour + ts.minute / 60.0
            if ts.weekday() >= 5:
                weekend_hours.append(h)
            else:
                hours.append(h)

            dur = s.get("duration_minutes", 15)
            durations_by_hour[ts.hour].append(dur)

        all_hours = hours + weekend_hours
        if not all_hours:
            instance.schedule = CHRONOTYPE_SCHEDULES["standard"]
            instance._kde_bandwidth = 1.0
            instance._session_hours: List[float] = []
            instance._weekend_phase_shift = 0.0
            return instance

        instance._session_hours = all_hours
        instance._kde_bandwidth = 1.5

        if hours and weekend_hours:
            weekday_mean = _circular_mean(hours, 24.0)
            weekend_mean = _circular_mean(weekend_hours, 24.0)
            shift = (weekend_mean - weekday_mean) % 24.0
            if shift > 12:
                shift -= 24.0
            instance._weekend_phase_shift = shift
            instance.weekend_shift_hours = shift
        else:
            instance._weekend_phase_shift = 0.0

        windows: List[ActivityWindow] = []
        for h in range(24):
            level = _kde_evaluate(all_hours, float(h) + 0.5, instance._kde_bandwidth)
            durs = durations_by_hour.get(h, [])
            if durs:
                avg_dur = sum(durs) / len(durs)
                spread = max(5, int(avg_dur * 0.3))
                dur_range = (max(1, int(avg_dur - spread)), int(avg_dur + spread))
            else:
                dur_range = (5, 15)
            windows.append(ActivityWindow(h, (h + 1) % 24, level, dur_range))

        max_level = max(w.activity_level for w in windows) or 1.0
        for w in windows:
            w.activity_level = w.activity_level / max_level

        instance.schedule = windows
        return instance

    def poisson_next_session(self, after: datetime) -> datetime:
        """Sample next session using inhomogeneous Poisson process with KDE-estimated rate."""
        if not hasattr(self, "_session_hours") or not self._session_hours:
            return self.get_next_session_time(after)

        max_rate = max(
            _kde_evaluate(self._session_hours, h + 0.5, self._kde_bandwidth)
            for h in range(24)
        ) or 1.0

        candidate = after
        for _ in range(2000):
            gap_minutes = -math.log(max(1e-12, random.random())) / (max_rate + 1e-12) * 60
            candidate += timedelta(minutes=max(1.0, gap_minutes))

            if candidate > after + timedelta(hours=24):
                break

            h = candidate.hour + candidate.minute / 60.0
            is_weekend = candidate.weekday() >= 5
            if is_weekend and hasattr(self, "_weekend_phase_shift"):
                h = (h - self._weekend_phase_shift) % 24.0

            local_rate = _kde_evaluate(self._session_hours, h, self._kde_bandwidth)
            if random.random() < local_rate / max_rate:
                return candidate

        return candidate

    def localize(self, dt: datetime, timezone: Optional[str] = None) -> datetime:
        """Convert datetime to the persona's timezone, handling DST transitions."""
        tz = getattr(self, "_timezone", None)
        if timezone and ZoneInfo is not None:
            tz = ZoneInfo(timezone)
        if tz is None:
            return dt
        if dt.tzinfo is None:
            from datetime import timezone as _tz
            dt = dt.replace(tzinfo=_tz.utc)
        return dt.astimezone(tz)
