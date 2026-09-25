"""Offline scientific formula reference and calculator for SolarOS."""

import formula_catalog
import formula_engine


KEY_BACKSPACE = 8
KEY_LF = 10
KEY_ENTER = 13
KEY_DELETE_CHAR = 127


def fit(text, pixel_width, character_width=7):
    maximum = max(1, pixel_width // character_width)
    if len(text) <= maximum:
        return text
    if maximum <= 3:
        return text[:maximum]
    return text[:maximum - 3] + "..."


def format_value(value):
    if -0.000000000001 < value < 0.000000000001:
        value = 0.0
    magnitude = abs(value)
    if magnitude >= 1000000000.0 or (
            magnitude != 0.0 and magnitude < 0.000001):
        return "%.6e" % value
    return "%.7g" % value


def parse_number(text):
    if text in ("", "+", "-", ".", "+.", "-."):
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def variable_by_key(entry, key):
    for variable in entry["variables"]:
        if variable[0] == key:
            return variable
    return None


def validate_value(variable, value):
    rule = variable[3]
    if rule == formula_catalog.POSITIVE and value <= 0.0:
        return "%s must be greater than zero" % variable[0]
    if rule == formula_catalog.NONNEGATIVE and value < 0.0:
        return "%s cannot be negative" % variable[0]
    return None


def new_calculation_state():
    return {
        "inputs": {},
        "computed_key": None,
        "computed_value": None,
        "status": "Enter values; leave one unknown",
    }


def recalculate(entry, state):
    state["computed_key"] = None
    state["computed_value"] = None
    variables = entry["variables"]
    inputs = state["inputs"]
    missing = [variable for variable in variables if variable[0] not in inputs]
    if len(missing) > 1:
        count = len(missing) - 1
        state["status"] = "%d more input%s needed" % (
            count, "" if count == 1 else "s")
        return
    if len(missing) == 0:
        state["status"] = "All are inputs; clear one to solve"
        return
    target = missing[0]
    expression = entry["solvers"].get(target[0])
    if expression is None:
        state["status"] = "Reference only for %s" % target[0]
        return
    try:
        result = formula_engine.solve(expression, inputs, entry["constants"])
    except (ArithmeticError, formula_engine.FormulaError,
            ValueError, OverflowError) as error:
        state["status"] = "Cannot solve: %s" % str(error)
        return
    validation = validate_value(target, result)
    if validation is not None:
        state["status"] = "Cannot solve: " + validation
        return
    state["computed_key"] = target[0]
    state["computed_value"] = result
    state["status"] = "Calculated %s in %s" % (target[0], target[2])


def set_user_value(entry, state, key, text):
    inputs = state["inputs"]
    old_computed_key = state["computed_key"]
    old_computed_value = state["computed_value"]
    if text == "":
        if key in inputs:
            del inputs[key]
            if (old_computed_key is not None and old_computed_key != key and
                    old_computed_value is not None):
                inputs[old_computed_key] = old_computed_value
        recalculate(entry, state)
        return None

    value = parse_number(text)
    if value is None:
        return "Enter a valid number"
    variable = variable_by_key(entry, key)
    error = validate_value(variable, value)
    if error is not None:
        return error
    inputs[key] = value
    recalculate(entry, state)
    return None


def displayed_value(state, key):
    if key in state["inputs"]:
        return format_value(state["inputs"][key]), "*"
    if key == state["computed_key"]:
        return format_value(state["computed_value"]), "="
    return "--", "?"


def build_tree(entries):
    roots = []
    for entry in entries:
        children = roots
        path = []
        parent_id = None
        for title in entry["path"]:
            path.append(title)
            node_id = "group:" + "/".join(path)
            group = None
            for candidate in children:
                if candidate["id"] == node_id:
                    group = candidate
                    break
            if group is None:
                group = {
                    "id": node_id,
                    "title": title,
                    "children": [],
                    "parent": parent_id,
                }
                children.append(group)
            children = group["children"]
            parent_id = node_id
        children.append({
            "id": "formula:" + entry["id"],
            "title": entry["title"],
            "formula": entry,
            "parent": parent_id,
        })
    return roots


def visible_tree(roots, expanded):
    visible = []

    def append_nodes(nodes, depth):
        for node in nodes:
            visible.append((node, depth))
            if "children" in node and node["id"] in expanded:
                append_nodes(node["children"], depth + 1)

    append_nodes(roots, 0)
    return visible


def find_visible(visible, node_id):
    for index, item in enumerate(visible):
        if item[0]["id"] == node_id:
            return index
    return 0


def tree_left(roots, expanded, selected):
    visible = visible_tree(roots, expanded)
    node = visible[selected][0]
    if "children" in node and node["id"] in expanded:
        expanded.remove(node["id"])
        return find_visible(visible_tree(roots, expanded), node["id"])
    if node["parent"] is not None:
        return find_visible(visible, node["parent"])
    return selected


def tree_right(roots, expanded, selected):
    visible = visible_tree(roots, expanded)
    node = visible[selected][0]
    if "children" not in node:
        return selected
    if node["id"] not in expanded:
        expanded.add(node["id"])
        return find_visible(visible_tree(roots, expanded), node["id"])
    if node["children"]:
        return min(selected + 1, len(visible) - 1)
    return selected


def tree_toggle(roots, expanded, selected):
    visible = visible_tree(roots, expanded)
    node = visible[selected][0]
    if "children" not in node:
        return selected, node["formula"]
    if node["id"] in expanded:
        expanded.remove(node["id"])
    else:
        expanded.add(node["id"])
    return find_visible(visible_tree(roots, expanded), node["id"]), None


def layout_mode(width, height):
    if width >= 280 and height >= 220:
        return "full"
    if height >= 100:
        return "compact"
    return "tiny"


def draw_tree(gfx, roots, expanded, selected, scroll, width, height):
    mode = layout_mode(width, height)
    margin = 8 if mode == "full" else 3
    header_height = 26 if mode == "full" else 14
    footer_height = 19 if height >= 100 else 0
    row_height = 19 if mode == "full" else 14
    font = gfx.FONT_MONO_14 if mode == "full" else gfx.FONT_MONO_12
    bold = gfx.FONT_BOLD_18 if mode == "full" else gfx.FONT_BOLD_12
    char_width = 7 if mode == "full" else 6
    visible = visible_tree(roots, expanded)
    selected = max(0, min(selected, len(visible) - 1))
    rows = max(1, (height - header_height - footer_height) // row_height)
    if selected < scroll:
        scroll = selected
    elif selected >= scroll + rows:
        scroll = selected - rows + 1
    scroll = max(0, min(scroll, max(0, len(visible) - rows)))

    gfx.clear(gfx.WHITE)
    gfx.color(gfx.BLACK)
    gfx.font(bold)
    heading = "Formulas"
    if width >= 180:
        heading += "  %d/%d" % (selected + 1, len(visible))
    gfx.text(margin, header_height - 6 if mode == "full" else 10,
             fit(heading, width - margin * 2, char_width))

    gfx.font(font)
    for row in range(rows):
        item_index = scroll + row
        if item_index >= len(visible):
            break
        node, depth = visible[item_index]
        y = header_height + row * row_height
        is_selected = item_index == selected
        if is_selected:
            gfx.color(gfx.BLACK)
            gfx.fill_rect(margin, y, width - margin * 2, row_height - 1)
            gfx.color(gfx.WHITE)
        else:
            gfx.color(gfx.BLACK)
        if "children" in node:
            prefix = "- " if node["id"] in expanded else "+ "
        else:
            prefix = "  "
        indent = depth * (12 if mode == "full" else 7)
        available = width - margin * 2 - indent - 2
        text = prefix + node["title"]
        gfx.text(margin + indent + 2, y + row_height - 5,
                 fit(text, available, char_width))

    if footer_height:
        gfx.color(gfx.BLACK)
        gfx.font(gfx.FONT_MONO_12)
        gfx.text(margin, height - 5,
                 fit("Up/Down line | Right open | Left collapse | Enter select",
                     width - margin * 2, 6))
    gfx.present()
    return selected, scroll


def draw_formula_graphic(gfx, ast, selected_key, left, top, width, height,
                         fonts):
    box = formula_engine.fit_layout(ast, width - 8, height - 6)
    box_height = box["ascent"] + box["descent"]
    gfx.color(gfx.DARK)
    gfx.rect(left, top, width, height)
    gfx.color(gfx.BLACK)
    if box["width"] <= width - 8 and box_height <= height - 6:
        x = left + (width - box["width"]) // 2
        baseline = top + (height - box_height) // 2 + box["ascent"]
        for command in formula_engine.drawing_commands(
                box, x, baseline, selected_key):
            if command[0] == "text":
                gfx.font(fonts[command[1]])
                gfx.text(command[2], command[3], command[4])
            elif command[0] == "line":
                gfx.line(command[1], command[2], command[3], command[4])
            elif command[0] == "dot":
                gfx.fill_circle(command[1], command[2], command[3])
        return

    text = formula_engine.inline_text(ast)
    gfx.font(gfx.FONT_BOLD_12)
    gfx.text(left + 4, top + height // 2 + 4,
             fit(text, width - 8, 6))


def draw_card(gfx, entry, ast, state, selected, editing, edit_text,
              width, height):
    mode = layout_mode(width, height)
    margin = 8 if mode == "full" else 3
    fonts = (gfx.FONT_BOLD_20, gfx.FONT_BOLD_18, gfx.FONT_BOLD_16,
             gfx.FONT_BOLD_14, gfx.FONT_BOLD_12)
    variable = entry["variables"][selected]

    gfx.clear(gfx.WHITE)
    gfx.color(gfx.BLACK)
    if mode == "full":
        gfx.font(gfx.FONT_BOLD_18)
        gfx.text(margin, 19, fit(entry["title"], width - margin * 2, 9))
        formula_top = 25
        formula_height = 78
    elif mode == "compact":
        gfx.font(gfx.FONT_BOLD_14)
        gfx.text(margin, 12, fit(entry["title"], width - margin * 2, 7))
        formula_top = 16
        formula_height = max(34, min(54, height // 2 - 7))
    else:
        gfx.font(gfx.FONT_BOLD_12)
        gfx.text(margin, 9, fit(entry["title"], width - margin * 2, 6))
        formula_top = 11
        formula_height = max(18, height - 40)

    draw_formula_graphic(gfx, ast, variable[0], margin, formula_top,
                         width - margin * 2, formula_height, fonts)

    if mode == "full":
        variables_top = formula_top + formula_height + 7
        info_height = 55
        footer_height = 17
        available = height - variables_top - info_height - footer_height
        row_height = max(24, min(31, available // len(entry["variables"])))
        for index, item in enumerate(entry["variables"]):
            y = variables_top + index * row_height
            is_selected = index == selected
            if is_selected:
                gfx.color(gfx.BLACK)
                gfx.fill_rect(margin, y, width - margin * 2, row_height - 1)
                gfx.color(gfx.WHITE)
            else:
                gfx.color(gfx.DARK)
                gfx.line(margin, y + row_height - 1,
                         width - margin - 1, y + row_height - 1)
                gfx.color(gfx.BLACK)
            value, marker = displayed_value(state, item[0])
            if editing and is_selected:
                value = (edit_text or "") + "_"
                marker = ">"
            gfx.font(gfx.FONT_BOLD_14)
            gfx.text(margin + 5, y + row_height - 9,
                     fit(item[0] + marker, 45, 7))
            gfx.font(gfx.FONT_MONO_12)
            gfx.text(margin + 55, y + row_height - 9,
                     fit(item[1], 112, 6))
            value_text = value + " " + item[2]
            gfx.text(margin + 172, y + row_height - 9,
                     fit(value_text, width - margin * 2 - 177, 6))

        info_top = variables_top + row_height * len(entry["variables"]) + 4
        gfx.color(gfx.BLACK)
        gfx.font(gfx.FONT_BOLD_12)
        gfx.text(margin, info_top + 10,
                 fit("%s [%s]" % (variable[1], variable[2]),
                     width - margin * 2, 6))
        gfx.font(gfx.FONT_MONO_12)
        status = ("Editing: type value, Enter save, Esc cancel" if editing
                  else state["status"])
        gfx.text(margin, info_top + 24,
                 fit(status, width - margin * 2, 6))
        gfx.text(margin, info_top + 38,
                 fit(entry["note"], width - margin * 2, 6))
        gfx.text(margin, height - 5,
                 fit("Arrows variable | Enter edit | C clear | R reset | Esc back",
                     width - margin * 2, 6))
    else:
        field_top = formula_top + formula_height + 2
        field_height = 25 if mode == "compact" else 14
        gfx.color(gfx.BLACK)
        gfx.fill_rect(margin, field_top, width - margin * 2, field_height)
        gfx.color(gfx.WHITE)
        gfx.font(gfx.FONT_BOLD_12)
        value, marker = displayed_value(state, variable[0])
        if editing:
            value = (edit_text or "") + "_"
            marker = ">"
        line = "%s%s %s %s" % (variable[0], marker, value, variable[2])
        gfx.text(margin + 4, field_top + field_height - 4,
                 fit(line, width - margin * 2 - 8, 6))
        gfx.color(gfx.BLACK)
        gfx.font(gfx.FONT_MONO_12)
        if mode == "compact":
            info_y = field_top + field_height + 12
            gfx.text(margin, info_y,
                     fit(variable[1], width - margin * 2, 6))
            gfx.text(margin, info_y + 14,
                     fit("Editing" if editing else state["status"],
                         width - margin * 2, 6))
            if info_y + 28 < height:
                gfx.text(margin, height - 4,
                         fit("Arrows | Enter edit | Esc back",
                             width - margin * 2, 6))
        else:
            gfx.text(margin, height - 2,
                     fit("Edit" if editing else state["status"],
                         width - margin * 2, 6))
    gfx.present()


def numeric_character_allowed(text, character):
    if character in "0123456789":
        return True
    if character == ".":
        tail = text.lower().split("e")[-1]
        return "." not in tail
    if character in "eE":
        return "e" not in text.lower() and any(ch.isdigit() for ch in text)
    if character in "+-":
        return text == "" or text[-1:] in ("e", "E")
    return False


def run():
    import solaros
    from solaros import gfx

    roots = build_tree(formula_catalog.FORMULAS)
    expanded = set()
    selected_tree = 0
    tree_scroll = 0
    screen = "tree"
    entry = None
    ast = None
    state = None
    selected_variable = 0
    editing = False
    edit_text = ""
    edit_original = ""
    replace_on_type = False

    gfx.begin()
    try:
        width, height = gfx.size()
        selected_tree, tree_scroll = draw_tree(
            gfx, roots, expanded, selected_tree, tree_scroll, width, height)
        while not solaros.should_exit():
            key = gfx.getch(250)
            if key is None:
                continue

            if screen == "tree":
                visible = visible_tree(roots, expanded)
                changed = False
                if key in (ord("q"), ord("Q"), gfx.KEY_ESCAPE):
                    break
                if key == gfx.KEY_UP:
                    selected_tree = max(0, selected_tree - 1)
                    changed = True
                elif key == gfx.KEY_DOWN:
                    selected_tree = min(len(visible) - 1, selected_tree + 1)
                    changed = True
                elif key == getattr(gfx, "KEY_PAGE_UP", -1001):
                    selected_tree = max(0, selected_tree - 8)
                    changed = True
                elif key == getattr(gfx, "KEY_PAGE_DOWN", -1002):
                    selected_tree = min(len(visible) - 1, selected_tree + 8)
                    changed = True
                elif key == gfx.KEY_LEFT:
                    selected_tree = tree_left(roots, expanded, selected_tree)
                    changed = True
                elif key == gfx.KEY_RIGHT:
                    selected_tree = tree_right(roots, expanded, selected_tree)
                    changed = True
                elif key in (KEY_ENTER, KEY_LF):
                    selected_tree, chosen = tree_toggle(
                        roots, expanded, selected_tree)
                    if chosen is not None:
                        entry = chosen
                        ast = formula_engine.parse(entry["expression"])
                        state = new_calculation_state()
                        selected_variable = 0
                        editing = False
                        screen = "card"
                        draw_card(gfx, entry, ast, state, selected_variable,
                                  editing, edit_text, width, height)
                        continue
                    changed = True
                if changed:
                    selected_tree, tree_scroll = draw_tree(
                        gfx, roots, expanded, selected_tree, tree_scroll,
                        width, height)
                continue

            changed = False
            if editing:
                if key == gfx.KEY_ESCAPE:
                    editing = False
                    edit_text = edit_original
                    changed = True
                elif key in (KEY_ENTER, KEY_LF):
                    variable = entry["variables"][selected_variable]
                    error = set_user_value(entry, state, variable[0], edit_text)
                    if error is None:
                        editing = False
                    else:
                        state["status"] = error
                    changed = True
                elif key in (KEY_BACKSPACE, KEY_DELETE_CHAR,
                             getattr(gfx, "KEY_DELETE", -1003)):
                    edit_text = "" if replace_on_type else edit_text[:-1]
                    replace_on_type = False
                    changed = True
                elif 0 <= key <= 127:
                    character = chr(key)
                    if numeric_character_allowed(
                            "" if replace_on_type else edit_text, character):
                        if replace_on_type:
                            edit_text = ""
                        if len(edit_text) < 16:
                            edit_text += character
                            replace_on_type = False
                            changed = True
            else:
                if key in (ord("q"), ord("Q")):
                    break
                if key == gfx.KEY_ESCAPE:
                    screen = "tree"
                    selected_tree, tree_scroll = draw_tree(
                        gfx, roots, expanded, selected_tree, tree_scroll,
                        width, height)
                    continue
                if key in (gfx.KEY_LEFT, gfx.KEY_UP):
                    selected_variable = (
                        selected_variable - 1) % len(entry["variables"])
                    changed = True
                elif key in (gfx.KEY_RIGHT, gfx.KEY_DOWN):
                    selected_variable = (
                        selected_variable + 1) % len(entry["variables"])
                    changed = True
                elif key in (KEY_ENTER, KEY_LF):
                    variable = entry["variables"][selected_variable]
                    value, _ = displayed_value(state, variable[0])
                    edit_text = "" if value == "--" else value
                    edit_original = edit_text
                    replace_on_type = True
                    editing = True
                    changed = True
                elif key in (ord("c"), ord("C"), KEY_DELETE_CHAR,
                             getattr(gfx, "KEY_DELETE", -1003)):
                    variable = entry["variables"][selected_variable]
                    set_user_value(entry, state, variable[0], "")
                    changed = True
                elif key in (ord("r"), ord("R")):
                    state = new_calculation_state()
                    changed = True

            if changed:
                draw_card(gfx, entry, ast, state, selected_variable,
                          editing, edit_text, width, height)
    finally:
        gfx.end()


if __name__ == "__main__":
    run()
