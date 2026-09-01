"""
Cognitive Decision Model — Hick's Law, Fitts's Law, and Attention Model.

Implements human-like delays for information processing, motor movement,
and visual attention based on cognitive science research.
"""
import math
import random
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple


@dataclass
class CognitiveProfile:
    speed_tier: str = "medium"
    hick_base: float = 350.0
    hick_increment: float = 150.0
    fitts_a: float = 50.0
    fitts_b: float = 150.0
    reading_speed_ms_per_word: float = 250.0
    visual_perception_ms: float = 350.0
    context_switch_ms: float = 2000.0
    fatigue_sensitivity: float = 1.0
    distraction_tendency: float = 0.5
    scan_pattern: str = "f_pattern"
    saccade_speed: float = 0.5
    microsaccade_sigma: float = 0.02

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "CognitiveProfile":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class CognitiveModel:
    """Models human cognitive processing delays."""

    def __init__(self, persona_seed: int = 0):
        rng = random.Random(persona_seed)
        speed = rng.choices(["fast", "medium", "slow"], weights=[25, 50, 25])[0]

        self.hick_base = {"fast": 200, "medium": 350, "slow": 500}[speed]
        self.hick_increment = {"fast": 80, "medium": 150, "slow": 250}[speed]
        self.fitts_a = rng.gauss(50, 10)
        self.fitts_b = rng.gauss(150, 20)
        self.reading_speed_ms_per_word = {"fast": 180, "medium": 250, "slow": 350}[speed]
        self.visual_perception_ms = rng.gauss(350, 80)
        self.context_switch_ms = rng.gauss(2000, 500)
        self._fatigue_sensitivity = rng.uniform(0.7, 1.3)
        self._distraction_tendency = rng.uniform(0.3, 0.7)
        self._rng = random.Random(persona_seed + 13)

        self.profile = CognitiveProfile(
            speed_tier=speed,
            hick_base=self.hick_base,
            hick_increment=self.hick_increment,
            fitts_a=self.fitts_a,
            fitts_b=self.fitts_b,
            reading_speed_ms_per_word=self.reading_speed_ms_per_word,
            visual_perception_ms=self.visual_perception_ms,
            context_switch_ms=self.context_switch_ms,
            fatigue_sensitivity=self._fatigue_sensitivity,
            distraction_tendency=self._distraction_tendency,
        )

    def decision_delay(self, num_options: int) -> float:
        """Hick's Law: RT = a + b * log2(n + 1)"""
        delay = self.hick_base + self.hick_increment * math.log2(num_options + 1)
        return max(50, delay * random.gauss(1.0, 0.15))

    def movement_time(self, distance_px: float, target_width_px: float) -> float:
        """Fitts's Law: MT = a + b * log2(2D/W + 1)"""
        if target_width_px <= 0:
            target_width_px = 1
        index_of_difficulty = math.log2(2 * distance_px / target_width_px + 1)
        mt = self.fitts_a + self.fitts_b * index_of_difficulty
        return max(80, mt * random.gauss(1.0, 0.1))

    def reading_delay(self, text: str) -> float:
        """Estimated reading time based on word count."""
        words = len(text.split())
        return words * self.reading_speed_ms_per_word * random.gauss(1.0, 0.1)

    def perception_delay(self) -> float:
        """Minimum time before first action after seeing new content."""
        return max(100, random.gauss(self.visual_perception_ms, 80))

    def context_switch_delay(self) -> float:
        """Delay when returning from another app or screen."""
        return max(300, random.gauss(self.context_switch_ms, 400))

    def video_decision_delay(self, watched_percent: float) -> float:
        """Time between end-of-video and action (like/skip)."""
        base = 500 if watched_percent > 0.8 else 200
        return max(100, random.gauss(base + watched_percent * 1000, 300))

    def fatigue_factor(self, session_minutes: float) -> float:
        rate = self._fatigue_sensitivity * 0.015
        factor = 1.0 + rate * session_minutes
        jitter = self._rng.gauss(0, 0.02)
        return min(1.8, max(1.0, factor + jitter))

    def familiarity_speedup(self, times_seen: int) -> float:
        if times_seen <= 0:
            return 1.0
        speedup = 1.0 / (1.0 + 0.15 * math.log(times_seen + 1))
        return max(0.4, min(1.0, speedup + self._rng.gauss(0, 0.02)))

    def information_overload_delay(self, num_items: int) -> float:
        if num_items <= 5:
            return 0.0
        excess = num_items - 5
        delay = 80.0 * math.log2(excess + 1) * self._fatigue_sensitivity
        return max(0.0, delay + self._rng.gauss(0, 30))

    def distraction_probability(self, session_minutes: float) -> float:
        base = 0.02 * self._distraction_tendency
        growth = 0.003 * session_minutes * self._distraction_tendency
        prob = base + growth
        return max(0.0, min(0.5, prob + self._rng.gauss(0, 0.005)))

    def hesitation_before_action(self, action_type: str, confidence: float) -> float:
        risk_weights = {
            "follow": 1.4, "like": 0.6, "comment": 1.8, "share": 1.6,
            "scroll": 0.2, "tap": 0.4, "purchase": 2.5, "unfollow": 2.0,
            "report": 2.2, "save": 0.8, "open_comments": 0.5,
        }
        risk = risk_weights.get(action_type, 1.0)
        uncertainty = max(0.1, 1.0 - confidence)
        base_hesitation = 200.0 * risk * uncertainty
        return max(0.0, base_hesitation * self._rng.gauss(1.0, 0.2))


class AttentionModel:
    """Simulates human visual attention (gaze point movement)."""

    def __init__(self, persona_seed: int = 0):
        rng = random.Random(persona_seed)
        self.gaze_x = 0.5
        self.gaze_y = 0.4
        self.saccade_speed = rng.uniform(0.3, 0.8)
        self.microsaccade_sigma = rng.uniform(0.01, 0.03)
        self._scan_pattern = rng.choice(["f_pattern", "z_pattern"])
        self._rng = random.Random(persona_seed + 17)

    def update_gaze(self, salient_elements: List[Dict]):
        """Move gaze toward most salient UI element."""
        if salient_elements:
            target = max(salient_elements, key=lambda e: e.get("salience", 0))
            tx = target.get("center_x", 0.5)
            ty = target.get("center_y", 0.5)
            self.gaze_x += (tx - self.gaze_x) * self.saccade_speed
            self.gaze_y += (ty - self.gaze_y) * self.saccade_speed

        self.gaze_x += random.gauss(0, self.microsaccade_sigma)
        self.gaze_y += random.gauss(0, self.microsaccade_sigma)
        self.gaze_x = max(0.0, min(1.0, self.gaze_x))
        self.gaze_y = max(0.0, min(1.0, self.gaze_y))

    def time_to_notice(self, element_x: float, element_y: float) -> float:
        """Time to notice an element based on distance from gaze."""
        distance = math.sqrt(
            (self.gaze_x - element_x) ** 2
            + (self.gaze_y - element_y) ** 2
        )
        notice_ms = 100 + distance * 2000
        return max(50, notice_ms * random.gauss(1.0, 0.2))

    def get_scan_path(self, elements: List[Dict]) -> List[Tuple[float, float]]:
        path: List[Tuple[float, float]] = []

        if self._scan_pattern == "f_pattern":
            sorted_els = sorted(elements, key=lambda e: (e.get("y", 0.5), e.get("x", 0.5)))
            rows: Dict[int, List[Dict]] = {}
            for el in sorted_els:
                row_key = int(el.get("y", 0.5) * 10)
                rows.setdefault(row_key, []).append(el)

            for row_idx, row_key in enumerate(sorted(rows.keys())):
                row = sorted(rows[row_key], key=lambda e: e.get("x", 0.5))
                if row_idx < 2:
                    for el in row:
                        px = el.get("x", 0.5) + self._rng.gauss(0, 0.01)
                        py = el.get("y", 0.5) + self._rng.gauss(0, 0.01)
                        path.append((max(0.0, min(1.0, px)), max(0.0, min(1.0, py))))
                else:
                    subset = row[:max(1, len(row) // 3)]
                    for el in subset:
                        px = el.get("x", 0.5) + self._rng.gauss(0, 0.01)
                        py = el.get("y", 0.5) + self._rng.gauss(0, 0.01)
                        path.append((max(0.0, min(1.0, px)), max(0.0, min(1.0, py))))
        else:
            if not elements:
                return path
            top_left = min(elements, key=lambda e: e.get("x", 0.5) + e.get("y", 0.5))
            path.append((top_left.get("x", 0.0) + self._rng.gauss(0, 0.01),
                         top_left.get("y", 0.0) + self._rng.gauss(0, 0.01)))

            top_right = max(elements, key=lambda e: e.get("x", 0.5) - e.get("y", 0.5))
            path.append((top_right.get("x", 1.0) + self._rng.gauss(0, 0.01),
                         top_right.get("y", 0.0) + self._rng.gauss(0, 0.01)))

            bottom_left = max(elements, key=lambda e: -e.get("x", 0.5) + e.get("y", 0.5))
            path.append((bottom_left.get("x", 0.0) + self._rng.gauss(0, 0.01),
                         bottom_left.get("y", 1.0) + self._rng.gauss(0, 0.01)))

            bottom_right = max(elements, key=lambda e: e.get("x", 0.5) + e.get("y", 0.5))
            path.append((bottom_right.get("x", 1.0) + self._rng.gauss(0, 0.01),
                         bottom_right.get("y", 1.0) + self._rng.gauss(0, 0.01)))

        return path

    def fatigue_blur(self, session_minutes: float) -> float:
        blur = 1.0 + 0.03 * session_minutes
        return min(3.0, max(1.0, blur + self._rng.gauss(0, 0.05)))

    def notification_distraction(
        self, current_gaze_x: float, current_gaze_y: float,
    ) -> Tuple[float, float, float]:
        notif_x = 0.5 + self._rng.gauss(0, 0.1)
        notif_y = 0.02 + self._rng.gauss(0, 0.01)
        notif_x = max(0.0, min(1.0, notif_x))
        notif_y = max(0.0, min(0.1, notif_y))

        dist = math.sqrt((current_gaze_x - notif_x) ** 2 + (current_gaze_y - notif_y) ** 2)
        duration_ms = 800.0 + dist * 1500.0 + self._rng.gauss(0, 200)
        duration_ms = max(400.0, duration_ms)

        return (notif_x, notif_y, duration_ms)
