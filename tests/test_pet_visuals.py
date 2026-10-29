from copy import copy
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))

spec = importlib.util.spec_from_file_location(
    "pet_window",
    ROOT / "desktop" / "pet-window.pyw",
)
pet_window = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pet_window)


class PetVisualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sheet = Image.open(ROOT / "assets" / "spritesheet.png").convert("RGBA")
        cls.poses = {}
        for pose_name in pet_window.POSE_NAMES:
            cls.poses[pose_name] = [
                Image.open(
                    ROOT / "assets" / "poses" / f"{pose_name}_{index}.png"
                ).convert("RGBA")
                for index in range(pet_window.POSE_FRAME_COUNTS[pose_name])
            ]

        measured = cls._make_window()
        measured.row_bounds = {}
        measured.gesture_bounds = {}
        measured.pose_bounds = measured._measure_pose_bounds()
        cls.row_bounds = measured.row_bounds
        cls.gesture_bounds = measured.gesture_bounds
        cls.pose_bounds = measured.pose_bounds

    @classmethod
    def _make_window(cls):
        window = object.__new__(pet_window.PetWindow)
        window.sheet = cls.sheet
        window.poses = cls.poses
        if hasattr(cls, "row_bounds"):
            window.row_bounds = copy(cls.row_bounds)
            window.gesture_bounds = copy(cls.gesture_bounds)
            window.pose_bounds = cls.pose_bounds
        window.physics_body = None
        window.flight_frame = pet_window.FLIGHT_TAKEOFF_START_FRAME
        window.flight_landing_frame = pet_window.FLIGHT_LANDING_FRAMES[0]
        window.flight_phase = "takeoff"
        window.landing_started = None
        window.landing_strength = 0.0
        window.reduced_motion = False
        window.lock_position = False
        window.last_double_click_pose = None
        window.grab_active = False
        window.completion_jumps_remaining = 0
        window.completion_frame = 0
        window.completion_between_jumps = False
        window.completion_pending = False
        window.drag_flight_active = False
        window.drag_flight_job = None
        window._log = lambda _message: None
        window.status = "idle"
        window.row = "idle"
        window.pose = "idle"
        window.frame = 0
        return window

    def test_takeoff_uses_visible_jumping_frame_and_bounds(self):
        window = self._make_window()
        window.physics_body = object()

        actual = window._current_pose_cell(320, 320)
        row_index = pet_window.ROW_INDEX[pet_window.FLIGHT_ROW]
        row = self.sheet.crop(
            (
                window.flight_frame * pet_window.CELL_W,
                row_index * pet_window.CELL_H,
                (window.flight_frame + 1) * pet_window.CELL_W,
                (row_index + 1) * pet_window.CELL_H,
            )
        )
        expected = pet_window.PetWindow._pose_cell(row)

        self.assertEqual(actual.tobytes(), expected.tobytes())
        self.assertEqual(
            window._active_body_bounds(),
            self.row_bounds[pet_window.FLIGHT_ROW],
        )

    def test_takeoff_skips_standing_edge_frames(self):
        self.assertEqual(pet_window.FLIGHT_TAKEOFF_FRAMES, (2,))
        self.assertNotIn(0, pet_window.FLIGHT_TAKEOFF_FRAMES)
        self.assertNotIn(4, pet_window.FLIGHT_TAKEOFF_FRAMES)

    def test_dragging_uses_takeoff_frame_and_bounds(self):
        window = self._make_window()
        window._render_frame = lambda: None
        window._set_drag_flight_active(True)

        self.assertTrue(window.drag_flight_active)
        actual = window._current_pose_cell(320, 320)
        row_index = pet_window.ROW_INDEX[pet_window.FLIGHT_ROW]
        row = self.sheet.crop(
            (
                window.flight_frame * pet_window.CELL_W,
                row_index * pet_window.CELL_H,
                (window.flight_frame + 1) * pet_window.CELL_W,
                (row_index + 1) * pet_window.CELL_H,
            )
        )
        expected = pet_window.PetWindow._pose_cell(row)

        self.assertEqual(actual.tobytes(), expected.tobytes())
        self.assertEqual(
            window._active_body_bounds(),
            self.row_bounds[pet_window.FLIGHT_ROW],
        )

        window.reduced_motion = True
        window._set_drag_flight_active(True)
        self.assertFalse(window.drag_flight_active)

    def test_drag_hold_timer_activates_takeoff(self):
        window = self._make_window()
        window.root = Mock()
        window.root.after.return_value = "drag-hold-job"
        window._render_frame = lambda: None
        window._log = lambda _message: None

        window._schedule_drag_flight_hold()

        delay, callback = window.root.after.call_args.args
        self.assertEqual(delay, pet_window.DRAG_FLIGHT_HOLD_MS)
        window.drag_tracker = SimpleNamespace(press_pointer=(100, 100))
        window.root.winfo_pointerxy.return_value = (120, 100)
        callback()
        self.assertTrue(window.drag_flight_active)
        self.assertEqual(
            window.flight_frame,
            pet_window.FLIGHT_TAKEOFF_START_FRAME,
        )

    def test_drag_motion_activates_takeoff_callback(self):
        window = self._make_window()
        window._render_frame = lambda: None
        window.drag_tracker = SimpleNamespace(dragged=True)
        window._move_drag_to = lambda _x, _y: True

        window._on_drag(SimpleNamespace(x_root=120, y_root=140))

        self.assertTrue(window.drag_flight_active)
        self.assertEqual(window.flight_frame, pet_window.FLIGHT_TAKEOFF_START_FRAME)

    def test_prelanding_uses_spread_wing_frames(self):
        window = self._make_window()
        window.physics_body = object()
        window.flight_phase = "landing"
        window.flight_landing_frame = 2

        actual = window._current_pose_cell(320, 320)
        expected = pet_window.PetWindow._pose_cell(
            self.poses[pet_window.FLIGHT_LANDING_POSE][2],
        ).resize(
            (320, 320),
            Image.Resampling.NEAREST,
        )

        self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_landed_flight_returns_to_standing_frame(self):
        window = self._make_window()
        window.physics_body = object()
        window.flight_phase = "landed"

        actual = window._current_pose_cell(320, 320)
        standing = self.sheet.crop(
            (0, 0, pet_window.CELL_W, pet_window.CELL_H)
        )
        expected = pet_window.PetWindow._pose_cell(
            standing,
        ).resize(
            (320, 320),
            Image.Resampling.NEAREST,
        )

        self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_descending_near_floor_switches_to_spread_wings(self):
        window = self._make_window()
        window._flight_floor_gap = lambda _body: 24.0
        window._flight_landing_gap_limit = lambda: 30.0
        window._log = lambda _message: None

        window._update_flight_phase(SimpleNamespace(vy=80.0), False)
        self.assertEqual(window.flight_phase, "landing")

        window.flight_phase = "takeoff"
        window._update_flight_phase(SimpleNamespace(vy=-80.0), False)
        self.assertEqual(window.flight_phase, "takeoff")

        window._update_flight_phase(SimpleNamespace(vy=80.0), True)
        self.assertEqual(window.flight_phase, "landed")

    def test_completion_reminder_uses_two_jumping_row_cycles(self):
        self.assertEqual(pet_window.COMPLETION_JUMP_COUNT, 2)
        window = self._make_window()
        window.completion_jumps_remaining = pet_window.COMPLETION_JUMP_COUNT

        actual = window._current_pose_cell(320, 320)
        row_index = pet_window.ROW_INDEX[pet_window.FLIGHT_ROW]
        row = self.sheet.crop(
            (
                0,
                row_index * pet_window.CELL_H,
                pet_window.CELL_W,
                (row_index + 1) * pet_window.CELL_H,
            )
        )
        expected = pet_window.PetWindow._scaled_completion_jump(
            window,
            pet_window.PetWindow._pose_cell(row),
        )

        self.assertEqual(actual.tobytes(), expected.tobytes())
        self.assertEqual(
            window._active_body_bounds(),
            self.row_bounds[pet_window.FLIGHT_ROW],
        )

    def test_completion_stands_between_the_two_jumps(self):
        window = self._make_window()
        window.completion_jumps_remaining = 1
        window.completion_between_jumps = True

        actual = window._current_pose_cell(320, 320)
        idle = self.sheet.crop(
            (0, 0, pet_window.CELL_W, pet_window.CELL_H)
        )
        expected = pet_window.PetWindow._pose_cell(idle).resize(
            (320, 320),
            Image.Resampling.NEAREST,
        )

        self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_completion_animation_ends_after_exactly_two_cycles(self):
        window = self._make_window()
        window.completion_jumps_remaining = pet_window.COMPLETION_JUMP_COUNT
        window._render_frame = lambda: None
        window._log = lambda _message: None
        window._schedule_idle_gesture = lambda: None
        frame_count = pet_window.ROW_FRAMES[
            pet_window.ROW_INDEX[pet_window.FLIGHT_ROW]
        ]
        cycles = 0
        for _step in range(frame_count * pet_window.COMPLETION_JUMP_COUNT * 3):
            if not window._completion_active():
                break
            previous_frame = window.completion_frame
            window._advance_completion_jump()
            if previous_frame == frame_count - 1 and window.completion_frame == 0:
                cycles += 1

        self.assertEqual(cycles, pet_window.COMPLETION_JUMP_COUNT)
        self.assertFalse(window._completion_active())

    def test_completion_sequence_parser_is_safe(self):
        self.assertEqual(
            pet_window.PetWindow._completion_sequence({"completionSeq": 4}),
            4,
        )
        self.assertEqual(
            pet_window.PetWindow._completion_sequence({"completionSeq": -3}),
            0,
        )
        self.assertEqual(
            pet_window.PetWindow._completion_sequence({"completionSeq": True}),
            0,
        )
        self.assertEqual(
            pet_window.PetWindow._completion_sequence({"completionSeq": "bad"}),
            0,
        )

    def test_idle_uses_standing_bounds_instead_of_all_poses(self):
        window = self._make_window()

        self.assertEqual(
            window._active_body_bounds(),
            self.row_bounds["idle"],
        )
        self.assertLess(
            self.row_bounds["idle"][2] - self.row_bounds["idle"][0],
            self.pose_bounds[2] - self.pose_bounds[0],
        )

    def test_wide_gesture_uses_its_own_bounds(self):
        window = self._make_window()
        window.pose = "cheer"

        self.assertEqual(
            window._active_body_bounds(),
            self.gesture_bounds["cheer"],
        )

    def test_reduced_motion_uses_the_quiet_running_row(self):
        window = self._make_window()
        window.reduced_motion = True
        window.status = "running"
        window.row = "running"

        self.assertEqual(window._current_animation_row(), "running")
        self.assertEqual(
            window._active_body_bounds(),
            self.row_bounds["running"],
        )

    def test_reduced_motion_disables_running_bob(self):
        window = self._make_window()
        window.status = "running"
        window.row = "running"
        row_index = pet_window.ROW_INDEX["running"]
        cell = None
        for frame in range(pet_window.ROW_FRAMES[row_index]):
            candidate = self.sheet.crop(
                (
                    frame * pet_window.CELL_W,
                    row_index * pet_window.CELL_H,
                    (frame + 1) * pet_window.CELL_W,
                    (row_index + 1) * pet_window.CELL_H,
                )
            )
            candidate = pet_window.PetWindow._pose_cell(candidate)
            bbox = candidate.getchannel("A").getbbox()
            if bbox and bbox[3] < pet_window.POSE_BASELINE:
                cell = candidate
                break

        self.assertIsNotNone(cell, "expected a lifted frame in the running row")
        reduced = window._scaled_running_jump(cell)
        self.assertFalse(
            reduced.tobytes() == cell.tobytes(),
            "work bob should be reduced before landing on the baseline",
        )

        window.reduced_motion = True
        self.assertEqual(window._scaled_running_jump(cell).tobytes(), cell.tobytes())

    def test_grab_feedback_can_be_disabled(self):
        window = self._make_window()
        window.grab_active = True

        self.assertEqual(
            window._current_pose_scale(),
            (pet_window.GRAB_SCALE_X, pet_window.GRAB_SCALE_Y),
        )
        window.reduced_motion = True
        self.assertEqual(window._current_pose_scale(), (1.0, 1.0))

    def test_double_click_cycles_only_head_gestures(self):
        window = self._make_window()
        previous = None
        for _index in range(12):
            pose = window._next_double_click_gesture()
            self.assertIn(pose, pet_window.DOUBLE_CLICK_POSES)
            self.assertNotEqual(pose, previous)
            previous = pose

    def test_no_pose_extends_below_the_shared_floor_line(self):
        for name, bounds in self.row_bounds.items():
            with self.subTest(row=name):
                self.assertLessEqual(bounds[3], pet_window.POSE_BASELINE)
        for name, bounds in self.gesture_bounds.items():
            with self.subTest(gesture=name):
                self.assertEqual(bounds[3], pet_window.POSE_BASELINE)


if __name__ == "__main__":
    unittest.main()
