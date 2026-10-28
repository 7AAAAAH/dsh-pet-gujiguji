import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))

spec = importlib.util.spec_from_file_location(
    "pet_window_settings",
    ROOT / "desktop" / "pet-window.pyw",
)
pet_window = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pet_window)


class PetSettingsTests(unittest.TestCase):
    def _window(self, path):
        window = object.__new__(pet_window.PetWindow)
        window.settings_path = path
        return window

    def test_missing_settings_use_interaction_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            window = self._window(Path(directory) / "settings.json")
            self.assertEqual(
                window._load_settings(),
                (
                    pet_window.DEFAULT_SIZE_PERCENT,
                    pet_window.DEFAULT_OPACITY_PERCENT,
                    pet_window.DEFAULT_THROW_POWER_PERCENT,
                    False,
                    False,
                    pet_window.DEFAULT_IDLE_INTERVAL_PERCENT,
                ),
            )

    def test_interaction_settings_are_clamped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(
                json.dumps(
                    {
                        "sizePercent": 999,
                        "opacityPercent": 1,
                        "throwPowerPercent": 999,
                        "reducedMotion": "true",
                        "lockPosition": "yes",
                        "idleIntervalPercent": 999,
                    }
                ),
                "utf-8",
            )
            window = self._window(path)
            self.assertEqual(
                window._load_settings(),
                (
                    pet_window.MAX_SIZE_PERCENT,
                    pet_window.MIN_OPACITY_PERCENT,
                    pet_window.MAX_THROW_POWER_PERCENT,
                    True,
                    True,
                    pet_window.MAX_IDLE_INTERVAL_PERCENT,
                ),
            )

    def test_interaction_settings_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            window = self._window(path)
            window.size_percent = 80
            window.opacity_percent = 60
            window.throw_power_percent = 140
            window.reduced_motion = True
            window.lock_position = True
            window.idle_interval_percent = 175
            window._save_settings()

            saved = self._window(path)._load_settings()
            self.assertEqual(saved, (80, 60, 140, True, True, 175))

    def test_idle_interval_scales_the_random_window(self):
        window = object.__new__(pet_window.PetWindow)
        window.idle_interval_percent = 200
        self.assertEqual(
            window._idle_delay_bounds(),
            (
                pet_window.IDLE_GESTURE_MIN_DELAY_MS * 2,
                pet_window.IDLE_GESTURE_MAX_DELAY_MS * 2,
            ),
        )


if __name__ == "__main__":
    unittest.main()
