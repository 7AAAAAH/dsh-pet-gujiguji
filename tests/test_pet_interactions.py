import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))

spec = importlib.util.spec_from_file_location(
    "pet_window_interactions",
    ROOT / "desktop" / "pet-window.pyw",
)
pet_window = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pet_window)


class FakeRoot:
    def __init__(self, events):
        self.events = events
        self.delayed = None

    def update_idletasks(self):
        self.events.append("paint")

    def after(self, delay, callback):
        self.events.append(("schedule", delay))
        self.delayed = callback
        return "job"


class FakeBubble:
    def __init__(self, events):
        self.events = events
        self.restored = False

    def restore(self):
        self.restored = True
        self.events.append("restore-bubble")


class DoubleClickTests(unittest.TestCase):
    def test_gesture_is_painted_before_dsh_window_work(self):
        events = []
        window = object.__new__(pet_window.PetWindow)
        window.dragged = False
        window.root = FakeRoot(events)
        window.bubble = FakeBubble(events)
        window._cancel_single_click = lambda: events.append("cancel-single")
        window._bubble_should_restore = lambda: True
        window._next_double_click_gesture = lambda: "head-tilt"
        window._start_gesture = lambda pose: events.append(("gesture", pose))
        window._toggle_dsh_window = lambda: events.append("toggle-dsh")
        window._log = lambda _message: None

        result = window._on_double_click(None)

        self.assertEqual(result, "break")
        self.assertEqual(
            events,
            [
                "cancel-single",
                ("gesture", "head-tilt"),
                "paint",
                ("schedule", 0),
            ],
        )

        window.root.delayed()
        self.assertEqual(
            events[-2:],
            ["toggle-dsh", "restore-bubble"],
        )


class StateMigrationTests(unittest.TestCase):
    def test_newest_legacy_state_is_used_during_upgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            new_path = root / "dsh-pet-gujiguji" / "state.json"
            old_path = root / "dsh-light-feather" / "state.json"
            new_path.parent.mkdir()
            old_path.parent.mkdir()
            new_path.write_text(
                json.dumps({"status": "idle", "task": "old snapshot"}),
                "utf-8",
            )
            old_path.write_text(
                json.dumps({"status": "running", "task": "live task"}),
                "utf-8",
            )
            os.utime(new_path, (100, 100))
            os.utime(old_path, (200, 200))

            window = object.__new__(pet_window.PetWindow)
            window.state_path = new_path
            with patch.dict(os.environ, {"APPDATA": str(root)}):
                state = window._read_state()

            self.assertEqual(state["status"], "running")
            self.assertEqual(state["task"], "live task")


if __name__ == "__main__":
    unittest.main()
