import importlib.util
from pathlib import Path
import sys
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
APP_DIR = REPOSITORY / "apps/formulas"
sys.dont_write_bytecode = True
sys.path.insert(0, str(APP_DIR))

import formula_catalog
import formula_engine

SPEC = importlib.util.spec_from_file_location("formulas_app", APP_DIR / "formulas.py")
assert SPEC is not None and SPEC.loader is not None
formulas_app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(formulas_app)


class FakeGfx:
    WHITE = 0
    DARK = 1
    BLACK = 2
    FONT_MONO_12 = 12
    FONT_MONO_14 = 14
    FONT_BOLD_12 = 112
    FONT_BOLD_14 = 114
    FONT_BOLD_16 = 116
    FONT_BOLD_18 = 118
    FONT_BOLD_20 = 120

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.present_count = 0

    def clear(self, _color):
        pass

    def color(self, _color):
        pass

    def font(self, _font):
        pass

    def text(self, _x, _y, _text):
        pass

    def line(self, _x0, _y0, _x1, _y1):
        pass

    def rect(self, _x, _y, width, height):
        self.assert_dimensions(width, height)

    def fill_rect(self, _x, _y, width, height):
        self.assert_dimensions(width, height)

    def fill_circle(self, _x, _y, radius):
        self.assert_dimensions(radius, radius)

    def present(self):
        self.present_count += 1

    @staticmethod
    def assert_dimensions(width, height):
        if width < 0 or height < 0:
            raise AssertionError("negative drawing dimensions")


class FormulaEngineTest(unittest.TestCase):
    def test_fraction_power_subscript_and_implicit_multiplication(self):
        node = formula_engine.parse(r"E_k = \frac{m v^2}{2}")
        self.assertEqual(
            formula_engine.collect_symbols(node), {"E_k", "m", "v"})
        residual = formula_engine.evaluate(
            node, {"E_k": 9.0, "m": 2.0, "v": 3.0})
        self.assertAlmostEqual(residual, 0.0)

    def test_safe_functions_and_scientific_notation(self):
        value = formula_engine.solve(
            r"\sqrt{2 E / m}", {"E": 9.0e0, "m": 2.0})
        self.assertEqual(value, 3.0)

    def test_unknown_commands_are_rejected(self):
        with self.assertRaises(formula_engine.FormulaError):
            formula_engine.parse(r"\input{secret}")

    def test_graphic_layout_and_inline_fallback(self):
        node = formula_engine.parse(r"R = \frac{R_1 R_2}{R_1 + R_2}")
        box = formula_engine.fit_layout(node, 384, 74)
        self.assertLessEqual(box["width"], 384)
        self.assertLessEqual(box["ascent"] + box["descent"], 74)
        commands = formula_engine.drawing_commands(box, 8, 70, "R_1")
        self.assertTrue(any(command[0] == "line" for command in commands))
        self.assertIn("/", formula_engine.inline_text(node))


class FormulaCatalogTest(unittest.TestCase):
    def test_catalog_is_unique_parseable_and_self_consistent(self):
        identifiers = set()
        for entry in formula_catalog.FORMULAS:
            self.assertNotIn(entry["id"], identifiers)
            identifiers.add(entry["id"])
            self.assertTrue(entry["path"])
            self.assertTrue(entry["note"])

            variables = {variable[0] for variable in entry["variables"]}
            constants = set(entry["constants"])
            display = formula_engine.parse(entry["expression"])
            self.assertEqual(
                formula_engine.collect_symbols(display), variables | constants,
                entry["id"])
            self.assertEqual(set(entry["solvers"]), variables, entry["id"])
            self.assertEqual(set(entry["example"]), variables, entry["id"])

            box = formula_engine.fit_layout(display, 384, 74)
            self.assertLessEqual(box["width"], 384, entry["id"])
            self.assertLessEqual(
                box["ascent"] + box["descent"], 74, entry["id"])

            for target in variables:
                expression = formula_engine.parse(entry["solvers"][target])
                allowed = (variables - {target}) | constants
                self.assertLessEqual(
                    formula_engine.collect_symbols(expression), allowed,
                    "%s solving %s" % (entry["id"], target))
                known = dict(entry["example"])
                expected = known.pop(target)
                actual = formula_engine.solve(
                    entry["solvers"][target], known, entry["constants"])
                tolerance = max(abs(expected) * 0.000001, 1.0e-30)
                self.assertLessEqual(
                    abs(actual - expected), tolerance,
                    "%s solving %s" % (entry["id"], target))

    def test_catalog_has_broad_field_reference_sections(self):
        roots = {entry["path"][0] for entry in formula_catalog.FORMULAS}
        self.assertEqual(
            roots,
            {"Mathematics", "Mechanics", "Matter and fluids",
             "Thermodynamics", "Electricity", "Waves and radio",
             "Chemistry", "Navigation and space"})
        self.assertGreaterEqual(len(formula_catalog.FORMULAS), 30)


class FormulaAppLogicTest(unittest.TestCase):
    def test_tree_expands_moves_to_child_and_collapses(self):
        roots = formulas_app.build_tree(formula_catalog.FORMULAS)
        expanded = set()
        self.assertEqual(len(formulas_app.visible_tree(roots, expanded)), 8)
        selected = formulas_app.tree_right(roots, expanded, 0)
        self.assertEqual(selected, 0)
        self.assertGreater(len(formulas_app.visible_tree(roots, expanded)), 8)
        selected = formulas_app.tree_right(roots, expanded, selected)
        self.assertEqual(selected, 1)
        selected = formulas_app.tree_left(roots, expanded, selected)
        self.assertEqual(selected, 0)
        selected = formulas_app.tree_left(roots, expanded, selected)
        self.assertEqual(selected, 0)
        self.assertEqual(len(formulas_app.visible_tree(roots, expanded)), 8)

    def test_values_auto_solve_and_retarget(self):
        entry = next(item for item in formula_catalog.FORMULAS
                     if item["id"] == "speed")
        state = formulas_app.new_calculation_state()
        self.assertIsNone(formulas_app.set_user_value(entry, state, "d", "100"))
        self.assertIsNone(formulas_app.set_user_value(entry, state, "t", "20"))
        self.assertEqual(state["computed_key"], "v")
        self.assertEqual(state["computed_value"], 5.0)

        self.assertIsNone(formulas_app.set_user_value(entry, state, "d", ""))
        self.assertEqual(state["computed_key"], "d")
        self.assertEqual(state["computed_value"], 100.0)
        self.assertEqual(state["inputs"]["v"], 5.0)

    def test_scientific_number_editor_and_display_modes(self):
        self.assertEqual(formulas_app.parse_number("6.62607015e-34"),
                         6.62607015e-34)
        self.assertTrue(formulas_app.numeric_character_allowed("6.6", "e"))
        self.assertTrue(formulas_app.numeric_character_allowed("6.6e", "-"))
        self.assertFalse(formulas_app.numeric_character_allowed("6.6e-3", "e"))
        self.assertEqual(formulas_app.layout_mode(400, 300), "full")
        self.assertEqual(formulas_app.layout_mode(200, 128), "compact")
        self.assertEqual(formulas_app.layout_mode(128, 64), "tiny")

    def test_tree_and_card_render_at_supported_layout_sizes(self):
        roots = formulas_app.build_tree(formula_catalog.FORMULAS)
        entry = next(item for item in formula_catalog.FORMULAS
                     if item["id"] == "parallel-resistance")
        ast = formula_engine.parse(entry["expression"])
        state = formulas_app.new_calculation_state()
        for width, height in ((400, 300), (200, 128), (128, 64)):
            gfx = FakeGfx(width, height)
            formulas_app.draw_tree(
                gfx, roots, set(), 0, 0, width, height)
            formulas_app.draw_card(
                gfx, entry, ast, state, 0, False, "", width, height)
            self.assertEqual(gfx.present_count, 2)


if __name__ == "__main__":
    unittest.main()
