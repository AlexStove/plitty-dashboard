"""
Touch Biometrics — Realistic touch event generation.

Implements:
- Cubic Bezier swipe curves with ease-in-out
- Per-persona touch pressure and area profiles
- Micro-jitter during long press
- Gyroscope synchronization with touch events
"""
import math
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class TouchPoint:
    x: float
    y: float
    pressure: float = 0.45
    size: float = 0.15
    timestamp_offset_ms: float = 0.0


class BezierSwipe:
    """Cubic Bezier swipe with humanistic ease-in-out."""

    def __init__(self, persona_seed: int = 0):
        rng = random.Random(persona_seed)
        self.ctrl_jitter = rng.uniform(15, 40)
        self.step_range = (rng.randint(14, 20), rng.randint(22, 32))
        self.micro_sigma = rng.uniform(0.8, 2.0)

    def generate(
        self,
        start_x: float, start_y: float,
        end_x: float, end_y: float,
        duration_ms: int = 300,
    ) -> List[TouchPoint]:
        ctrl1_x = start_x + random.uniform(-self.ctrl_jitter, self.ctrl_jitter)
        ctrl1_y = start_y + (end_y - start_y) * random.uniform(0.2, 0.4)
        ctrl2_x = end_x + random.uniform(-self.ctrl_jitter, self.ctrl_jitter)
        ctrl2_y = start_y + (end_y - start_y) * random.uniform(0.6, 0.8)

        steps = random.randint(*self.step_range)
        points: List[TouchPoint] = []

        for i in range(steps + 1):
            t = i / steps
            t_eased = t * t * (3 - 2 * t)  # smoothstep

            x = ((1 - t_eased) ** 3 * start_x
                 + 3 * (1 - t_eased) ** 2 * t_eased * ctrl1_x
                 + 3 * (1 - t_eased) * t_eased ** 2 * ctrl2_x
                 + t_eased ** 3 * end_x)

            y = ((1 - t_eased) ** 3 * start_y
                 + 3 * (1 - t_eased) ** 2 * t_eased * ctrl1_y
                 + 3 * (1 - t_eased) * t_eased ** 2 * ctrl2_y
                 + t_eased ** 3 * end_y)

            x += random.gauss(0, self.micro_sigma)
            y += random.gauss(0, self.micro_sigma)

            pressure = random.gauss(0.45, 0.08)
            pressure = max(0.1, min(0.9, pressure))

            points.append(TouchPoint(
                x=x, y=y,
                pressure=pressure,
                size=random.gauss(0.15, 0.03),
                timestamp_offset_ms=t * duration_ms,
            ))

        return points


class TouchPressure:
    """Per-persona touch pressure and area model."""

    def __init__(self, persona_seed: int = 0):
        rng = random.Random(persona_seed)
        self.mean_pressure = rng.gauss(0.45, 0.08)
        self.sigma_pressure = rng.uniform(0.08, 0.15)
        self.mean_size = rng.gauss(0.15, 0.03)
        self.sigma_size = rng.uniform(0.02, 0.05)
        self.right_handed = rng.random() < 0.88
        self.x_bias = rng.gauss(3 if self.right_handed else -3, 2)
        self.y_bias = rng.gauss(2, 1.5)

    def apply(self, target_x: float, target_y: float,
              screen_w: int, screen_h: int) -> TouchPoint:
        norm_y = target_y / screen_h
        center_dist = abs(0.5 - norm_y)
        pressure = random.gauss(
            self.mean_pressure + 0.05 * (0.5 - center_dist),
            self.sigma_pressure,
        )
        pressure = max(0.1, min(0.9, pressure))
        size = random.gauss(self.mean_size, self.sigma_size)
        size = max(0.05, min(0.3, size))

        offset_x = random.gauss(self.x_bias, 4)
        offset_y = random.gauss(self.y_bias, 3.5)

        return TouchPoint(
            x=target_x + offset_x,
            y=target_y + offset_y,
            pressure=pressure,
            size=size,
        )


class MicroJitter:
    """Micro-jitter injection during long press / hold."""

    def __init__(self, persona_seed: int = 0):
        rng = random.Random(persona_seed)
        self.sigma_xy = rng.uniform(0.8, 1.8)
        self.interval_range = (rng.randint(25, 45), rng.randint(60, 90))

    def generate(self, x: float, y: float, duration_ms: int) -> List[TouchPoint]:
        points: List[TouchPoint] = []
        elapsed = 0.0
        while elapsed < duration_ms:
            dx = random.gauss(0, self.sigma_xy)
            dy = random.gauss(0, self.sigma_xy)
            points.append(TouchPoint(
                x=x + dx, y=y + dy,
                pressure=random.gauss(0.45, 0.06),
                size=random.gauss(0.15, 0.02),
                timestamp_offset_ms=elapsed,
            ))
            interval = random.randint(*self.interval_range)
            elapsed += interval
        return points


class GyroSync:
    """Synchronize gyroscope data with touch events."""

    def __init__(self, persona_seed: int = 0):
        rng = random.Random(persona_seed)
        self.base_noise = rng.uniform(0.0002, 0.0008)
        self.swipe_coupling = rng.uniform(0.0015, 0.003)

    def swipe_gyro(self, swipe_velocity: float) -> Dict[str, float]:
        pitch_delta = swipe_velocity * self.swipe_coupling * random.uniform(0.7, 1.3)
        roll_delta = swipe_velocity * self.swipe_coupling * 0.5 * random.uniform(-1, 1)
        return {
            "x": random.gauss(roll_delta, self.base_noise),
            "y": random.gauss(pitch_delta, self.base_noise * 2),
            "z": random.gauss(0, self.base_noise * 0.6),
        }

    def idle_gyro(self) -> Dict[str, float]:
        return {
            "x": random.gauss(0, self.base_noise),
            "y": random.gauss(0, self.base_noise),
            "z": random.gauss(0, self.base_noise * 0.5),
        }

    def tap_gyro(self) -> Dict[str, float]:
        return {
            "x": random.gauss(0, self.base_noise * 3),
            "y": random.gauss(0.001, self.base_noise * 3),
            "z": random.gauss(0, self.base_noise),
        }
