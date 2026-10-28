from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))

from pet_physics import (  # noqa: E402
    BodyGeometry,
    DEFAULT_PHYSICS,
    DragSample,
    DragTracker,
    Rect,
    ThrowBody,
    clamp_window_to_monitor,
    estimate_release_velocity,
    landing_scale,
    landing_strength,
    monitor_index_at_point,
    monitor_index_for_rect,
    step_throw,
)


BODY = BodyGeometry(left=90, top=100, right=230, bottom=274)
MONITOR = Rect(0, 0, 800, 800)


class ReleaseVelocityTests(unittest.TestCase):
    def test_slow_release_stays_below_throw_gate(self):
        velocity = estimate_release_velocity(
            [DragSample(0.0, 0.0, 0.0), DragSample(0.05, 10.0, 0.0)],
            0.05,
        )
        self.assertIsNone(velocity)

    def test_fast_release_keeps_pointer_direction(self):
        velocity = estimate_release_velocity(
            [DragSample(0.0, 0.0, 0.0), DragSample(0.05, 100.0, 50.0)],
            0.05,
        )
        self.assertIsNotNone(velocity)
        self.assertGreater(velocity.vx, 0)
        self.assertGreater(velocity.vy, 0)
        self.assertGreaterEqual(velocity.speed, 500)
        self.assertLess(velocity.speed, 3200)

    def test_stale_trail_does_not_throw(self):
        velocity = estimate_release_velocity(
            [DragSample(0.0, 0.0, 0.0), DragSample(0.05, 100.0, 0.0)],
            0.30,
        )
        self.assertIsNone(velocity)

    def test_throw_power_scales_release_speed(self):
        samples = [
            DragSample(0.0, 0.0, 0.0),
            DragSample(0.05, 150.0, 0.0),
        ]
        normal = estimate_release_velocity(samples, 0.05, throw_power=1.0)
        strong = estimate_release_velocity(samples, 0.05, throw_power=1.5)
        self.assertIsNotNone(normal)
        self.assertIsNotNone(strong)
        self.assertGreater(strong.speed, normal.speed)


class DragTrackerTests(unittest.TestCase):
    def test_click_is_separate_from_drag_threshold(self):
        tracker = DragTracker(threshold=5)
        tracker.press(100, 100, 200, 300, 0.0)
        self.assertFalse(tracker.move(103, 103, 0.01))
        self.assertTrue(tracker.move(108, 100, 0.02))
        self.assertTrue(tracker.dragged)

    def test_release_returns_dragged_state(self):
        tracker = DragTracker(threshold=5)
        tracker.press(100, 100, 200, 300, 0.0)
        tracker.move(120, 100, 0.03)
        release = tracker.release(145, 100, 0.06)
        self.assertTrue(release.dragged)
        self.assertIsNotNone(release.velocity)

    def test_window_position_tracks_pointer_offset(self):
        tracker = DragTracker(threshold=5)
        tracker.press(100, 100, 200, 300, 0.0)
        self.assertEqual(tracker.window_position(145, 70), (245, 270))


class MonitorTests(unittest.TestCase):
    def test_point_and_body_monitor_lookup(self):
        monitors = [Rect(-800, 0, 0, 800), Rect(0, 0, 800, 800)]
        self.assertEqual(monitor_index_at_point(monitors, -10, 100), 0)
        self.assertEqual(monitor_index_at_point(monitors, 10, 100), 1)
        self.assertEqual(
            monitor_index_for_rect(Rect(-200, 100, -50, 300), monitors),
            0,
        )

    def test_clamp_uses_visible_body_not_window_edges(self):
        x, y = clamp_window_to_monitor(-500, 900, BODY, MONITOR)
        self.assertEqual(x, -90)
        self.assertEqual(y, 526)


class LandingAnimationTests(unittest.TestCase):
    def test_impact_strength_is_bounded(self):
        self.assertGreater(landing_strength(0), 0)
        self.assertLessEqual(landing_strength(5000), 0.10)

    def test_landing_starts_and_ends_at_full_size(self):
        self.assertEqual(landing_scale(0.0, 0.12), (1.0, 1.0))
        self.assertEqual(landing_scale(1.0, 0.12), (1.0, 1.0))

    def test_compression_widens_and_flattens(self):
        scale_x, scale_y = landing_scale(0.30, 0.12)
        self.assertGreater(scale_x, 1.0)
        self.assertLess(scale_y, 1.0)

    def test_landing_scale_has_no_extreme_overshoot(self):
        for step in range(101):
            scale_x, scale_y = landing_scale(step / 100, 0.18)
            self.assertGreater(scale_x, 0.90)
            self.assertLess(scale_x, 1.12)
            self.assertGreater(scale_y, 0.80)
            self.assertLess(scale_y, 1.08)


class ThrowStepTests(unittest.TestCase):
    def test_gravity_moves_the_pet_down(self):
        result = step_throw(
            ThrowBody(100, 100, 0, 0),
            0.016,
            BODY,
            [MONITOR],
        )
        self.assertGreater(result.body.vy, 0)
        self.assertGreater(result.body.y, 100)

    def test_wall_bounce_changes_horizontal_direction(self):
        result = step_throw(
            ThrowBody(-80, 200, -1000, 0),
            0.05,
            BODY,
            [MONITOR],
        )
        self.assertTrue(result.hit_wall)
        self.assertEqual(result.body.x, -90)
        self.assertGreater(result.body.vx, 0)

    def test_floor_collision_reports_landing_and_bounces(self):
        result = step_throw(
            ThrowBody(100, 500, 0, 1000),
            0.05,
            BODY,
            [MONITOR],
        )
        self.assertTrue(result.landed)
        self.assertEqual(result.body.y, 526)
        self.assertLess(result.body.vy, 0)

    def test_small_ground_velocity_sleeps(self):
        result = step_throw(
            ThrowBody(100, 526, 10, 0),
            0.016,
            BODY,
            [MONITOR],
        )
        self.assertTrue(result.at_rest)
        self.assertEqual(result.body.vx, 0)
        self.assertEqual(result.body.vy, 0)

    def test_large_frame_delta_is_capped(self):
        result = step_throw(
            ThrowBody(-80, 200, -100000, 0),
            10.0,
            BODY,
            [MONITOR],
        )
        self.assertGreaterEqual(result.body.x, -90)
        self.assertLessEqual(result.body.x, 570)
        self.assertTrue(result.hit_wall)

    def test_adjacent_monitor_gets_a_whole_window_handoff(self):
        monitors = [Rect(-800, 0, 0, 800), Rect(0, 0, 800, 800)]
        result = step_throw(
            ThrowBody(-231, 200, 1000, 0),
            0.05,
            BODY,
            monitors,
        )
        self.assertEqual(result.body.monitor_index, 1)
        self.assertEqual(result.body.x, -90)
        self.assertFalse(result.hit_wall)

    def test_monitor_handoff_ignores_enumeration_order(self):
        monitors = [Rect(0, 0, 800, 800), Rect(-800, 0, 0, 800)]
        result = step_throw(
            ThrowBody(-231, 200, 1000, 0, monitor_index=1),
            0.05,
            BODY,
            monitors,
        )
        self.assertEqual(result.body.monitor_index, 0)
        self.assertEqual(result.body.x, -90)

    def test_outer_edge_still_bounces(self):
        result = step_throw(
            ThrowBody(-80, 200, -1000, 0),
            0.05,
            BODY,
            [MONITOR],
        )
        self.assertTrue(result.hit_wall)
        self.assertGreater(result.body.vx, 0)

    def test_restitution_values_are_bounded(self):
        self.assertGreater(DEFAULT_PHYSICS.restitution_x, 0)
        self.assertLess(DEFAULT_PHYSICS.restitution_x, 1)
        self.assertGreater(DEFAULT_PHYSICS.restitution_y, 0)
        self.assertLess(DEFAULT_PHYSICS.restitution_y, 1)


if __name__ == "__main__":
    unittest.main()
