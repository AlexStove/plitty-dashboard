"""
Hand Model — Per-persona thumb comfort zone and touch offset model.

Each persona gets a unique hand model based on handedness, hand size,
and grip style. Touches are offset toward the comfort zone, with error
increasing as targets move further from it.
"""
import math
import random
from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass
class HandProfile:
    handedness: str  # "right" | "left"
    hand_size: str   # "small" | "medium" | "large"
    grip_style: str  # "one_hand" | "two_hand" | "cradle"


class HandModel:
    """Generates per-persona touch offsets based on hand ergonomics."""

    FARM_DISTRIBUTIONS = {
        "right": 0.88, "left": 0.12,
        "one_hand": 0.49, "cradle": 0.36, "two_hand": 0.15,
        "small": 0.25, "medium": 0.50, "large": 0.25,
    }

    GRIP_TILT_PROFILES = {
        "one_hand": {"pitch": (65.0, 8.0), "roll": (5.0, 3.0)},
        "two_hand": {"pitch": (50.0, 6.0), "roll": (0.0, 2.0)},
        "cradle": {"pitch": (55.0, 10.0), "roll": (3.0, 4.0)},
    }

    def __init__(self, persona: Dict, persona_seed: int = 0):
        rng = random.Random(persona_seed)

        self.handedness = persona.get("handedness") or (
            "right" if rng.random() < self.FARM_DISTRIBUTIONS["right"] else "left"
        )
        self.hand_size = persona.get("hand_size") or rng.choices(
            ["small", "medium", "large"],
            weights=[0.25, 0.50, 0.25],
        )[0]
        self.grip_style = persona.get("grip_style") or rng.choices(
            ["one_hand", "two_hand", "cradle"],
            weights=[0.49, 0.15, 0.36],
        )[0]

        self._rng = random.Random(persona_seed + 7)
        self._init_comfort_zone(rng)
        self._init_pressure_profile(rng)

    def _init_comfort_zone(self, rng: random.Random):
        if self.handedness == "right" and self.grip_style == "one_hand":
            cx, cy = 0.65, 0.55
            rx, ry = 0.30, 0.35
        elif self.handedness == "left" and self.grip_style == "one_hand":
            cx, cy = 0.35, 0.55
            rx, ry = 0.30, 0.35
        else:
            cx, cy = 0.50, 0.50
            rx, ry = 0.45, 0.45

        size_mod = {"small": -0.04, "medium": 0.0, "large": 0.04}[self.hand_size]
        rx += size_mod
        ry += size_mod

        self.comfort_center_x = cx + rng.gauss(0, 0.03)
        self.comfort_center_y = cy + rng.gauss(0, 0.03)
        self.comfort_radius_x = rx
        self.comfort_radius_y = ry

        self.base_error_sigma = rng.uniform(2.5, 4.0)
        self.edge_error_scale = rng.uniform(6.0, 10.0)

    def _init_pressure_profile(self, rng: random.Random):
        self._pressure_center = rng.uniform(0.55, 0.75)
        self._pressure_edge = rng.uniform(0.30, 0.45)
        self._pressure_jitter = rng.uniform(0.03, 0.08)

    def apply_offset(
        self, target_x: float, target_y: float,
        screen_w: int, screen_h: int,
    ) -> Tuple[float, float]:
        norm_x = target_x / screen_w
        norm_y = target_y / screen_h

        dist_x = abs(norm_x - self.comfort_center_x) / self.comfort_radius_x
        dist_y = abs(norm_y - self.comfort_center_y) / self.comfort_radius_y
        error_scale = (dist_x + dist_y) / 2

        sigma = self.base_error_sigma + error_scale * self.edge_error_scale

        offset_x = random.gauss(0, sigma)
        offset_y = random.gauss(0, sigma)

        return (target_x + offset_x, target_y + offset_y)

    def get_finger_fatigue(self, session_minutes: float) -> float:
        half_life = 30.0
        decay = 0.15 * (1.0 - math.exp(-session_minutes / half_life))
        jitter = self._rng.gauss(0, 0.01)
        return max(0.70, min(1.0, 1.0 - decay + jitter))

    def apply_offset_with_fatigue(
        self, target_x: float, target_y: float,
        screen_w: int, screen_h: int,
        session_minutes: float,
    ) -> Tuple[float, float]:
        fatigue = self.get_finger_fatigue(session_minutes)
        fatigue_multiplier = 1.0 + (1.0 - fatigue) * 3.5

        norm_x = target_x / screen_w
        norm_y = target_y / screen_h

        dist_x = abs(norm_x - self.comfort_center_x) / self.comfort_radius_x
        dist_y = abs(norm_y - self.comfort_center_y) / self.comfort_radius_y
        error_scale = (dist_x + dist_y) / 2

        sigma = (self.base_error_sigma + error_scale * self.edge_error_scale) * fatigue_multiplier

        offset_x = self._rng.gauss(0, sigma)
        offset_y = self._rng.gauss(0, sigma)

        drift_x = self._rng.gauss(0, session_minutes * 0.05)
        drift_y = self._rng.gauss(0, session_minutes * 0.05)

        return (target_x + offset_x + drift_x, target_y + offset_y + drift_y)

    def get_thumb_reach_probability(
        self, target_x: float, target_y: float,
        screen_w: int, screen_h: int,
    ) -> float:
        norm_x = target_x / screen_w
        norm_y = target_y / screen_h

        if self.handedness == "right" and self.grip_style == "one_hand":
            pivot_x, pivot_y = 0.85, 0.95
            max_reach = {"small": 0.55, "medium": 0.65, "large": 0.75}[self.hand_size]
        elif self.handedness == "left" and self.grip_style == "one_hand":
            pivot_x, pivot_y = 0.15, 0.95
            max_reach = {"small": 0.55, "medium": 0.65, "large": 0.75}[self.hand_size]
        else:
            return min(1.0, 0.92 + self._rng.gauss(0, 0.02))

        dist = math.sqrt((norm_x - pivot_x) ** 2 + (norm_y - pivot_y) ** 2)
        ratio = dist / max_reach

        if ratio < 0.6:
            prob = 0.98
        elif ratio < 0.85:
            prob = 0.98 - (ratio - 0.6) * 0.4
        elif ratio < 1.0:
            prob = 0.88 - (ratio - 0.85) * 2.0
        else:
            prob = max(0.05, 0.58 - (ratio - 1.0) * 1.5)

        return max(0.0, min(1.0, prob + self._rng.gauss(0, 0.02)))

    def switch_grip_probability(self, session_minutes: float) -> float:
        if self.grip_style == "two_hand":
            return 0.0

        base_rate = 0.005
        fatigue_boost = max(0.0, (session_minutes - 10.0) / 60.0) * 0.15
        prob = base_rate + fatigue_boost

        if self.hand_size == "small":
            prob *= 1.4
        elif self.hand_size == "large":
            prob *= 0.7

        return min(0.35, max(0.0, prob + self._rng.gauss(0, 0.005)))

    def get_phone_tilt_angle(self) -> Tuple[float, float]:
        profile = self.GRIP_TILT_PROFILES[self.grip_style]
        pitch = self._rng.gauss(*profile["pitch"])
        roll = self._rng.gauss(*profile["roll"])

        if self.handedness == "left":
            roll = -roll

        size_pitch_mod = {"small": 5.0, "medium": 0.0, "large": -3.0}[self.hand_size]
        pitch += size_pitch_mod

        return (round(pitch, 2), round(roll, 2))

    def get_touch_pressure_modifier(
        self, target_x: float, target_y: float,
        screen_w: int, screen_h: int,
    ) -> float:
        norm_x = target_x / screen_w
        norm_y = target_y / screen_h

        dist_x = abs(norm_x - self.comfort_center_x) / self.comfort_radius_x
        dist_y = abs(norm_y - self.comfort_center_y) / self.comfort_radius_y
        dist = (dist_x + dist_y) / 2.0

        pressure = self._pressure_center - dist * (self._pressure_center - self._pressure_edge)
        pressure += self._rng.gauss(0, self._pressure_jitter)

        return max(0.15, min(1.0, pressure))

    def to_dict(self) -> Dict:
        return {
            "handedness": self.handedness,
            "hand_size": self.hand_size,
            "grip_style": self.grip_style,
            "comfort_center_x": self.comfort_center_x,
            "comfort_center_y": self.comfort_center_y,
            "comfort_radius_x": self.comfort_radius_x,
            "comfort_radius_y": self.comfort_radius_y,
            "base_error_sigma": self.base_error_sigma,
            "edge_error_scale": self.edge_error_scale,
            "pressure_center": self._pressure_center,
            "pressure_edge": self._pressure_edge,
            "pressure_jitter": self._pressure_jitter,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "HandModel":
        instance = cls.__new__(cls)
        instance.handedness = data["handedness"]
        instance.hand_size = data["hand_size"]
        instance.grip_style = data["grip_style"]
        instance.comfort_center_x = data["comfort_center_x"]
        instance.comfort_center_y = data["comfort_center_y"]
        instance.comfort_radius_x = data["comfort_radius_x"]
        instance.comfort_radius_y = data["comfort_radius_y"]
        instance.base_error_sigma = data["base_error_sigma"]
        instance.edge_error_scale = data["edge_error_scale"]
        instance._pressure_center = data["pressure_center"]
        instance._pressure_edge = data["pressure_edge"]
        instance._pressure_jitter = data["pressure_jitter"]
        instance._rng = random.Random()
        return instance

    @classmethod
    def generate_random_profile(cls, rng: random.Random = None) -> HandProfile:
        rng = rng or random.Random()
        return HandProfile(
            handedness="right" if rng.random() < 0.88 else "left",
            hand_size=rng.choices(["small", "medium", "large"], weights=[25, 50, 25])[0],
            grip_style=rng.choices(["one_hand", "two_hand", "cradle"], weights=[49, 15, 36])[0],
        )
