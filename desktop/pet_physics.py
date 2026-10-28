"""Pure drag and throw physics for the desktop pet.

This module intentionally has no tkinter or Pillow dependency so the interaction
rules can be tested without opening a GUI.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence


@dataclass(frozen=True)
class Rect:
    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return max(0.0, self.right - self.left)

    @property
    def height(self) -> float:
        return max(0.0, self.bottom - self.top)

    @property
    def center(self) -> tuple[float, float]:
        return ((self.left + self.right) / 2, (self.top + self.bottom) / 2)

    def contains(self, x: float, y: float) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom

    def intersection_area(self, other: "Rect") -> float:
        width = max(0.0, min(self.right, other.right) - max(self.left, other.left))
        height = max(0.0, min(self.bottom, other.bottom) - max(self.top, other.top))
        return width * height


@dataclass(frozen=True)
class BodyGeometry:
    """Visible body bounds relative to the window's top-left corner."""

    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return max(1.0, self.right - self.left)

    @property
    def height(self) -> float:
        return max(1.0, self.bottom - self.top)

    def bounds_at(self, x: float, y: float) -> Rect:
        return Rect(
            x + self.left,
            y + self.top,
            x + self.right,
            y + self.bottom,
        )


@dataclass(frozen=True)
class DragSample:
    time: float
    x: float
    y: float


@dataclass(frozen=True)
class Velocity:
    vx: float
    vy: float

    @property
    def speed(self) -> float:
        return math.hypot(self.vx, self.vy)


@dataclass(frozen=True)
class DragRelease:
    dragged: bool
    velocity: Velocity | None


@dataclass(frozen=True)
class ThrowBody:
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    monitor_index: int = 0


@dataclass(frozen=True)
class PhysicsParams:
    gravity: float = 1650.0
    restitution_x: float = 0.34
    restitution_y: float = 0.22
    ground_friction: float = 7.2
    air_drag: float = 0.22
    stop_bounce_speed: float = 70.0
    rest_speed_x: float = 18.0
    rest_speed_y: float = 1.0
    max_dt: float = 0.05
    seam_tolerance: float = 2.0


@dataclass(frozen=True)
class StepResult:
    body: ThrowBody
    landed: bool
    hit_wall: bool
    hit_ceiling: bool
    impact_speed: float
    at_rest: bool


DEFAULT_PHYSICS = PhysicsParams()


def monitor_index_at_point(
    monitors: Sequence[Rect],
    x: float,
    y: float,
    fallback: int = 0,
) -> int:
    if not monitors:
        raise ValueError("at least one monitor is required")
    fallback = min(max(0, fallback), len(monitors) - 1)
    for index, monitor in enumerate(monitors):
        if monitor.contains(x, y):
            return index
    return fallback


def monitor_index_for_rect(
    rect: Rect,
    monitors: Sequence[Rect],
    fallback: int = 0,
) -> int:
    if not monitors:
        raise ValueError("at least one monitor is required")
    fallback = min(max(0, fallback), len(monitors) - 1)
    center_x, center_y = rect.center
    for index, monitor in enumerate(monitors):
        if monitor.contains(center_x, center_y):
            return index

    overlaps = [(monitor.intersection_area(rect), index) for index, monitor in enumerate(monitors)]
    best_overlap, best_index = max(overlaps, default=(0.0, fallback))
    return best_index if best_overlap > 0 else fallback


def clamp_window_to_monitor(
    x: float,
    y: float,
    geometry: BodyGeometry,
    monitor: Rect,
    padding: float = 0.0,
) -> tuple[float, float]:
    min_x = monitor.left - geometry.left + padding
    max_x = monitor.right - geometry.right - padding
    min_y = monitor.top - geometry.top + padding
    max_y = monitor.bottom - geometry.bottom - padding
    return (
        _clamp_axis(x, min_x, max_x),
        _clamp_axis(y, min_y, max_y),
    )


def estimate_release_velocity(
    samples: Sequence[DragSample],
    now: float,
    throw_power: float = 1.0,
    min_throw_speed: float = 460.0,
    soft_speed_limit: float = 3200.0,
    sample_window: float = 0.150,
) -> Velocity | None:
    """Estimate pointer velocity from the recent drag trail.

    Endpoint speed and the fastest recent segment each contribute 50 percent.
    A final flick can add up to 60 percent before the result is soft-limited.
    """

    deltas = [sample for sample in samples if 0.0 <= now - sample.time <= sample_window]
    if len(deltas) < 2:
        return None

    first = deltas[0]
    last = deltas[-1]
    if now - last.time > sample_window or last.time - first.time < 0.020:
        return None

    dt = last.time - first.time
    vx = (last.x - first.x) / dt
    vy = (last.y - first.y) / dt
    base_speed = math.hypot(vx, vy)
    if base_speed < 1e-6:
        return None

    segments: list[tuple[float, float]] = []
    previous = first
    for sample in deltas[1:]:
        segment_dt = sample.time - previous.time
        if segment_dt >= 0.008:
            speed = math.hypot(sample.x - previous.x, sample.y - previous.y) / segment_dt
            segments.append((speed, sample.time))
            previous = sample

    peak = max((speed for speed, _ in segments), default=base_speed)
    acceleration = 0.0
    if len(segments) >= 2:
        start_speed, start_time = segments[0]
        end_speed, end_time = segments[-1]
        elapsed = max(0.020, end_time - start_time)
        acceleration = (end_speed - start_speed) / elapsed

    acceleration_boost = 1.0 + min(1.0, max(0.0, acceleration) / 8000.0) * 0.6
    before_limit = (base_speed * 0.5 + peak * 0.5) * acceleration_boost
    speed = soft_speed_limit * (1.0 - math.exp(-before_limit / soft_speed_limit))
    speed *= min(2.0, max(0.2, throw_power))
    if speed < min_throw_speed:
        return None

    scale = speed / base_speed
    return Velocity(vx * scale, vy * scale)


def landing_strength(impact_speed: float) -> float:
    """Map a floor impact to a restrained squash amount."""
    normalized = _clamp_axis((abs(impact_speed) - 250.0) / 1250.0, 0.0, 1.0)
    return 0.03 + normalized * 0.07


def landing_scale(progress: float, strength: float) -> tuple[float, float]:
    """Return horizontal and vertical scale for a bottom-anchored landing."""
    progress = _clamp_axis(progress, 0.0, 1.0)
    strength = _clamp_axis(strength, 0.0, 0.30)
    if progress in (0.0, 1.0) or strength == 0.0:
        return (1.0, 1.0)
    if progress < 0.45:
        amount = _ease_out_cubic(progress / 0.45)
        scale_y = 1.0 - strength * amount
    else:
        amount = _ease_out_back((progress - 0.45) / 0.55)
        scale_y = 1.0 - strength + strength * amount
    scale_x = 1.0 + (1.0 - scale_y) * 0.52
    return (scale_x, scale_y)


class DragTracker:
    """Collect pointer samples while preserving single-click semantics."""

    def __init__(self, threshold: float = 5.0):
        self.threshold = max(0.0, threshold)
        self.press_pointer: tuple[float, float] | None = None
        self.press_window: tuple[float, float] | None = None
        self.samples: list[DragSample] = []
        self.dragged = False

    def press(
        self,
        pointer_x: float,
        pointer_y: float,
        window_x: float,
        window_y: float,
        now: float,
    ) -> None:
        self.press_pointer = (pointer_x, pointer_y)
        self.press_window = (window_x, window_y)
        self.samples = [DragSample(now, window_x, window_y)]
        self.dragged = False

    def move(self, pointer_x: float, pointer_y: float, now: float) -> bool:
        if self.press_pointer is None or self.press_window is None:
            return False
        dx = pointer_x - self.press_pointer[0]
        dy = pointer_y - self.press_pointer[1]
        if math.hypot(dx, dy) >= self.threshold:
            self.dragged = True

        window_x = self.press_window[0] + dx
        window_y = self.press_window[1] + dy
        self.samples.append(DragSample(now, window_x, window_y))
        cutoff = now - 1.0
        if len(self.samples) > 4 and self.samples[0].time < cutoff:
            self.samples = [sample for sample in self.samples if sample.time >= cutoff]
        return self.dragged

    def window_position(
        self,
        pointer_x: float,
        pointer_y: float,
    ) -> tuple[float, float] | None:
        if self.press_pointer is None or self.press_window is None:
            return None
        return (
            self.press_window[0] + pointer_x - self.press_pointer[0],
            self.press_window[1] + pointer_y - self.press_pointer[1],
        )

    def release(
        self,
        pointer_x: float,
        pointer_y: float,
        now: float,
        throw_power: float = 1.0,
    ) -> DragRelease:
        self.move(pointer_x, pointer_y, now)
        dragged = self.dragged
        velocity = estimate_release_velocity(self.samples, now, throw_power)
        self.reset()
        return DragRelease(dragged, velocity)

    def reset(self) -> None:
        self.press_pointer = None
        self.press_window = None
        self.samples = []
        self.dragged = False


def step_throw(
    body: ThrowBody,
    delta_seconds: float,
    geometry: BodyGeometry,
    monitors: Sequence[Rect],
    params: PhysicsParams = DEFAULT_PHYSICS,
) -> StepResult:
    """Advance one physics step without allowing monitor-boundary tunnelling."""

    if not monitors:
        raise ValueError("at least one monitor is required")
    dt = min(params.max_dt, max(0.0, delta_seconds))
    if dt <= 0.0:
        return StepResult(body, False, False, False, 0.0, False)

    monitor_index = min(max(0, body.monitor_index), len(monitors) - 1)
    current = monitors[monitor_index]
    previous_y = body.y
    previous_vy = body.vy

    vx = body.vx * math.exp(-params.air_drag * dt)
    vy = body.vy + params.gravity * dt
    x = body.x + vx * dt
    y = body.y + vy * dt

    candidate_bounds = geometry.bounds_at(x, y)
    center_monitor = monitor_index_for_rect(candidate_bounds, monitors, monitor_index)
    if center_monitor != monitor_index:
        monitor_index = center_monitor
        current = monitors[monitor_index]

    min_x, max_x = _horizontal_window_bounds(geometry, current)
    hit_wall = False
    if x > max_x and vx > 0:
        neighbor = _horizontal_neighbor(monitor_index, 1, monitors, candidate_bounds, params.seam_tolerance)
        if neighbor is None:
            x = max_x
            vx = -abs(vx) * params.restitution_x
            hit_wall = True
        else:
            monitor_index = neighbor
            current = monitors[monitor_index]
            min_x, max_x = _horizontal_window_bounds(geometry, current)
            x = min_x
    elif x < min_x and vx < 0:
        neighbor = _horizontal_neighbor(monitor_index, -1, monitors, candidate_bounds, params.seam_tolerance)
        if neighbor is None:
            x = min_x
            vx = abs(vx) * params.restitution_x
            hit_wall = True
        else:
            monitor_index = neighbor
            current = monitors[monitor_index]
            min_x, max_x = _horizontal_window_bounds(geometry, current)
            x = max_x

    min_y, max_y = _vertical_window_bounds(geometry, current)
    hit_ceiling = False
    landed = False
    impact_speed = abs(previous_vy)
    if y < min_y and vy < 0:
        y = min_y
        vy = abs(vy) * params.restitution_y
        hit_ceiling = True
    elif y > max_y and vy > 0:
        y = max_y
        landed = previous_y < max_y - 1.0
        if abs(vy) < params.stop_bounce_speed:
            vy = 0.0
        else:
            vy = -abs(vy) * params.restitution_y
        vx *= max(0.0, 1.0 - params.ground_friction * dt)

    x = _clamp_axis(x, min_x, max_x)
    y = _clamp_axis(y, min_y, max_y)

    at_rest = (
        y >= max_y - 0.5
        and abs(vx) < params.rest_speed_x
        and abs(vy) < params.rest_speed_y
    )
    if at_rest:
        vx = 0.0
        vy = 0.0

    updated = ThrowBody(x, y, vx, vy, monitor_index)
    return StepResult(
        updated,
        landed=landed,
        hit_wall=hit_wall,
        hit_ceiling=hit_ceiling,
        impact_speed=impact_speed,
        at_rest=at_rest,
    )


def _clamp_axis(value: float, minimum: float, maximum: float) -> float:
    if maximum < minimum:
        return (minimum + maximum) / 2.0
    return max(minimum, min(value, maximum))


def _ease_out_cubic(value: float) -> float:
    inverse = 1.0 - value
    return 1.0 - inverse * inverse * inverse


def _ease_out_back(value: float) -> float:
    overshoot = 1.70158
    shifted = value - 1.0
    return 1.0 + (overshoot + 1.0) * shifted**3 + overshoot * shifted**2


def _horizontal_window_bounds(
    geometry: BodyGeometry,
    monitor: Rect,
) -> tuple[float, float]:
    return (
        monitor.left - geometry.left,
        monitor.right - geometry.right,
    )


def _vertical_window_bounds(
    geometry: BodyGeometry,
    monitor: Rect,
) -> tuple[float, float]:
    return (
        monitor.top - geometry.top,
        monitor.bottom - geometry.bottom,
    )


def _horizontal_neighbor(
    current_index: int,
    direction: int,
    monitors: Sequence[Rect],
    body_bounds: Rect,
    tolerance: float,
) -> int | None:
    current = monitors[current_index]
    seam = current.right if direction > 0 else current.left
    candidates: list[tuple[float, int]] = []
    for index, monitor in enumerate(monitors):
        if index == current_index:
            continue
        if direction > 0:
            touches = monitor.left >= seam - tolerance and monitor.left <= seam + tolerance
        else:
            touches = monitor.right >= seam - tolerance and monitor.right <= seam + tolerance
        if not touches:
            continue
        overlap = max(
            0.0,
            min(body_bounds.bottom, monitor.bottom) - max(body_bounds.top, monitor.top),
        )
        if overlap > 0:
            candidates.append((overlap, index))
    return max(candidates, default=(0.0, -1))[1] if candidates else None
