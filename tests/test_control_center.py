from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "apps" / "control-center" / "control_center.py"


class FakeGfx:
    WHITE = 1
    BLACK = 0
    LIGHT = 2
    FONT_BOLD_18 = 18
    FONT_BOLD_14 = 14
    FONT_MONO_14 = 14
    FONT_MONO_12 = 12
    KEY_ESCAPE = 27
    KEY_UP = 128
    KEY_DOWN = 129
    KEY_LEFT = 130
    KEY_RIGHT = 131
    KEY_DELETE = 132
    KEY_PAGE_UP = 133
    KEY_PAGE_DOWN = 134

    def __init__(self, keys=()):
        self.keys = list(keys)
        self.current_color = None
        self.lines = []

    def getch(self, _timeout):
        return self.keys.pop(0)

    def clear(self, _color):
        pass

    def color(self, color):
        self.current_color = color

    def fill_rect(self, _x, _y, _width, _height):
        pass

    def rect(self, _x, _y, _width, _height):
        pass

    def line(self, x1, y1, x2, y2):
        self.lines.append((self.current_color, x1, y1, x2, y2))

    def icon(self, _x, _y, _name, _size):
        pass

    def font(self, _font):
        pass

    def text(self, _x, _y, _text):
        pass

    def refresh(self):
        pass


def load_app(keys=()):
    fake_gfx = FakeGfx(keys)
    fake_solaros = types.ModuleType("solaros")
    fake_solaros.gfx = fake_gfx
    fake_solaros.should_exit = lambda: False
    previous = sys.modules.get("solaros")
    sys.modules["solaros"] = fake_solaros
    try:
        spec = importlib.util.spec_from_file_location("control_center_test", APP_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            del sys.modules["solaros"]
        else:
            sys.modules["solaros"] = previous
    return module, fake_gfx


class ControlCenterTest(unittest.TestCase):
    def test_group_boundary_recolors_the_existing_separator(self):
        module, fake_gfx = load_app()

        module.draw_menu_row(400, 62, ("Job", "stopped"), False, True)

        self.assertEqual(fake_gfx.lines, [(fake_gfx.BLACK, 11, 103, 389, 103)])

    def test_prefix_match_is_case_insensitive_and_uses_first_match(self):
        module, _ = load_app()
        rows = [("Display", ""), ("DAQ", ""), ("Download", "")]

        self.assertEqual(module.first_prefix_match(rows, "d"), 0)
        self.assertEqual(module.first_prefix_match(rows, "da"), 1)
        self.assertIsNone(module.first_prefix_match(rows, "z"))

    def test_menu_accumulates_typed_prefix(self):
        module, _ = load_app([ord("d"), ord("a"), 13])
        rows = [("Display", ""), ("DAQ", ""), ("Download", "")]

        choice = module.menu(400, 300, "Jobs", rows, typeahead=True)

        self.assertEqual(choice, 1)

    def test_typeahead_reserves_q_for_job_names(self):
        module, _ = load_app([ord("q"), 13])
        rows = [("Alpha", ""), ("Queue", "")]

        choice = module.menu(400, 300, "Jobs", rows, typeahead=True)

        self.assertEqual(choice, 1)

    def test_jobs_are_grouped_active_first_with_alphabetic_subgroups(self):
        module, _ = load_app()
        jobs = [
            {"name": "zulu", "state": "stopped"},
            {"name": "beta", "state": "running"},
            {"name": "alpha", "state": "starting"},
            {"name": "delta", "state": "failed"},
        ]

        jobs, divider_before = module.group_jobs(jobs)

        self.assertEqual([item["name"] for item in jobs],
                         ["alpha", "beta", "delta", "zulu"])
        self.assertEqual(divider_before, 2)

    def test_no_selects_sequential_argument_fields(self):
        module, _ = load_app()
        module.message = lambda *_args: ord("n")
        entered = iter(["radio0", "meshcore-eu868", ""])
        module.edit_text = lambda *_args, **_kwargs: next(entered)

        self.assertEqual(module.choose_job_arguments(400, 300, "meshcore"),
                         ["radio0", "meshcore-eu868"])

    def test_argument_escape_cancels_job_start(self):
        module, _ = load_app()
        module.message = lambda *_args: ord("n")
        module.edit_text = lambda *_args, **_kwargs: None

        self.assertIsNone(module.choose_job_arguments(400, 300, "daq"))

    def test_custom_arguments_are_forwarded_to_jobs_api(self):
        module, _ = load_app()
        starts = []
        module.solaros.jobs = types.SimpleNamespace(
            start=lambda *args: starts.append(args),
            stop=lambda _name: None,
        )
        module.choose_job_arguments = lambda *_args: ["radio0", "meshcore-eu868"]
        module.message = lambda *_args: None

        module.change_job(400, 300, {"name": "meshcore", "state": "stopped"})

        self.assertEqual(starts,
                         [("meshcore", ["radio0", "meshcore-eu868"])])


if __name__ == "__main__":
    unittest.main()
