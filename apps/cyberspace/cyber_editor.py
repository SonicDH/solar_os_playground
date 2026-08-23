"""Host-testable UTF-8 editor model and SolarOS TUI editors."""

from cyber_text import utf8_len
from cyber_components import logo_lines


KEY_ENTER = (10, 13)
KEY_BACKSPACE = (8, 127)
KEY_CTRL_D = 4
KEY_CTRL_N = 14
KEY_CTRL_S = 19
KEY_TAB = 9


class EditorModel:
    def __init__(self, text="", limit=32768):
        self.text = text
        self.cursor = len(text)
        self.limit = limit

    def insert(self, value):
        candidate = self.text[:self.cursor] + value + self.text[self.cursor:]
        if utf8_len(candidate) > self.limit:
            return False
        self.text = candidate
        self.cursor += len(value)
        return True

    def backspace(self):
        if self.cursor == 0:
            return False
        self.text = self.text[:self.cursor - 1] + self.text[self.cursor:]
        self.cursor -= 1
        return True

    def delete(self):
        if self.cursor >= len(self.text):
            return False
        self.text = self.text[:self.cursor] + self.text[self.cursor + 1:]
        return True

    def move(self, amount):
        self.cursor = min(len(self.text), max(0, self.cursor + amount))


def editor_layout(text, cursor, width):
    width = max(1, width)
    lines = []
    current = ""
    cursor_row = 0
    cursor_col = 0
    for index in range(len(text) + 1):
        if index == cursor:
            cursor_row = len(lines)
            cursor_col = len(current)
        if index == len(text):
            break
        character = text[index]
        if character == "\n":
            lines.append(current)
            current = ""
        else:
            current += character
            if len(current) >= width:
                lines.append(current)
                current = ""
    lines.append(current)
    return lines, cursor_row, cursor_col


def single_line(label, text="", limit=128, masked=False):
    import solaros
    from solaros import tui
    model = EditorModel(text, min(limit, 190))
    view = 0
    rows, cols = tui.size()
    width = max(1, cols - 2)
    tui.clear()
    tui.title(label)
    tui.help("Enter accept  Esc cancel")
    dirty = True
    while not solaros.should_exit():
        if dirty:
            tui.input(rows // 2, 1, width, "", model.text, model.cursor, view,
                      tui.NORMAL, masked)
            tui.refresh()
            dirty = False
        key = tui.getch(250)
        if key is None:
            continue
        if key in KEY_ENTER:
            return model.text
        if key == tui.KEY_ESCAPE:
            return None
        value, cursor, view, _ = tui.input_edit(
            model.text, model.cursor, view, key, width, min(limit + 1, 191))
        model.text = value
        model.cursor = cursor
        dirty = True
    return None


def login_form(email="", remember=False, saved_email=None, has_saved=False):
    """Draw the logo, both credential fields, and selectable login buttons."""
    import solaros
    from solaros import tui

    email_model = EditorModel(email, 128)
    password_model = EditorModel("", 128)
    views = [0, 0]
    actions = ["email", "password", "remember", "login"]
    if saved_email:
        actions.append("restore")
    if has_saved:
        actions.append("forget")
    focus = 0
    dirty = True
    first_draw = True
    previous_focus = None

    def button_geometries(left, width, top):
        names = actions[3:]
        labels = {"login": "Login", "restore": "Saved login", "forget": "Forget saved"}
        widths = [len(labels[name]) + 4 for name in names]
        available = max(1, width)
        if sum(widths) + len(widths) - 1 > available:
            widths = [max(7, (available - len(widths) + 1) // len(widths))
                      for _ in widths]
        result = {}
        col = left
        for name, width in zip(names, widths):
            width = min(width, max(1, left + available - col))
            result[name] = (top, col, 3, width, labels[name])
            col += width + 1
        return result

    def draw_control(index, selected, geometry):
        rows, cols, field_top, form_col, box_width, inner_width, buttons = geometry
        if index < 2:
            model = email_model if index == 0 else password_model
            masked = index == 1
            row = field_top + 1 + index * 3
            if selected:
                tui.input(row, form_col + 1, inner_width, "", model.text,
                          model.cursor, views[index], tui.INVERSE, masked)
            else:
                shown = "*" * len(model.text) if masked else model.text
                shown = shown[-inner_width:]
                tui.addstr(row, form_col + 1,
                           shown + " " * (inner_width - len(shown)),
                           tui.NORMAL)
            return
        name = actions[index]
        attr = tui.INVERSE | getattr(tui, "BOLD", 0) if selected else tui.NORMAL
        if name == "remember":
            label = "[{}] remember login token (plaintext)".format(
                "x" if remember else " ")
            tui.addstr(field_top + 6, form_col,
                       (label + " " * box_width)[:box_width], attr)
            return
        top, col, height, width, label = buttons[name]
        tui.box(top, col, height, width, attr)
        inside = max(1, width - 2)
        text = label[:inside]
        text = text.center(inside)
        tui.addstr(top + 1, col + 1, text, attr)

    while not solaros.should_exit():
        if dirty:
            rows, cols = tui.size()
            box_width = max(12, min(cols - 2, 48))
            form_col = max(0, (cols - box_width) // 2)
            inner_width = box_width - 2
            logo = logo_lines(max(1, cols)) if rows >= 18 else ["CYBERSPACE"]
            field_top = len(logo) + 1
            button_top = min(max(field_top + 7, rows - 5), rows - 4)
            buttons = button_geometries(form_col, box_width, button_top)
            geometry = (rows, cols, field_top, form_col, box_width,
                        inner_width, buttons)
            if first_draw:
                tui.clear()
                tui.help("Up/Down/Tab move  Enter select  Esc exit")
                bold = getattr(tui, "BOLD", tui.NORMAL)
                logo_col = max(0, (cols - max(len(line) for line in logo)) // 2)
                for index, line in enumerate(logo):
                    tui.addstr(index, logo_col, line, bold)
                subtitle = "social media de-imagined"
                tui.addstr(len(logo), max(0, (cols - len(subtitle)) // 2),
                           subtitle, bold)
                for index, label in enumerate(("Email", "Password")):
                    top = field_top + index * 3
                    tui.box(top, form_col, 3, box_width)
                    tui.addstr(top, form_col + 2, " " + label + " ", bold)
                for index in range(len(actions)):
                    if index != focus:
                        draw_control(index, False, geometry)
            elif previous_focus is not None and previous_focus != focus:
                draw_control(previous_focus, False, geometry)
            draw_control(focus, True, geometry)
            tui.refresh()
            dirty = False
            first_draw = False
            previous_focus = None

        key = tui.getch(250)
        if key is None:
            continue
        if key == tui.KEY_ESCAPE:
            password_model.text = ""
            return None
        old_focus = focus
        redraw_current = False
        if key == tui.KEY_DOWN or key == KEY_TAB:
            focus = (focus + 1) % len(actions)
        elif key == tui.KEY_UP:
            focus = (focus - 1) % len(actions)
        elif key in KEY_ENTER:
            action = actions[focus]
            if action == "email":
                focus = 1
            elif action == "password" or action == "login":
                password = password_model.text
                password_model.text = ""
                return {"action": "login", "email": email_model.text,
                        "password": password, "remember": remember}
            elif action == "remember":
                remember = not remember
                redraw_current = True
            else:
                password_model.text = ""
                return {"action": action, "email": email_model.text,
                        "remember": remember}
        elif focus < 2:
            model = email_model if focus == 0 else password_model
            value, cursor, view, _ = tui.input_edit(
                model.text, model.cursor, views[focus], key, inner_width, 129)
            model.text = value
            model.cursor = cursor
            views[focus] = view
            tui.input(field_top + 1 + focus * 3, form_col + 1, inner_width,
                      "", model.text,
                      model.cursor, views[focus], tui.INVERSE, focus == 1)
            tui.refresh()
            continue
        if focus != old_focus:
            previous_focus = old_focus
            dirty = True
        elif redraw_current:
            previous_focus = focus
            dirty = True
    password_model.text = ""
    return None


def multiline(title, text="", limit=32768, on_activity=None, on_tick=None):
    import solaros
    from solaros import tui
    model = EditorModel(text, limit)
    top = 0
    first_draw = True
    dirty = True
    previous_rows = []
    previous_top = 0
    previous_cursor_row = None
    previous_cursor_col = 0
    model_width = 1
    previous_geometry = None
    while not solaros.should_exit():
        if dirty:
            rows, cols = tui.size()
            body_rows = max(1, rows - 3)
            width = max(1, cols - 2)
            geometry = (rows, cols)
            geometry_changed = geometry != previous_geometry
            if first_draw or geometry_changed:
                tui.clear()
                tui.title(title)
                tui.help("Ctrl-S save  Enter newline  Esc cancel")
            lines, cursor_line, cursor_col = editor_layout(model.text, model.cursor, width)
            if cursor_line < top:
                top = cursor_line
            elif cursor_line >= top + body_rows:
                top = cursor_line - body_rows + 1

            visible_rows = []
            for index in range(body_rows):
                line_index = top + index
                line = lines[line_index][:width] if line_index < len(lines) else ""
                visible_rows.append(line)

            cursor_screen_row = None
            if cursor_line >= top and cursor_line < top + body_rows:
                cursor_screen_row = cursor_line - top

            full_body = first_draw or geometry_changed or top != previous_top
            if full_body and not first_draw and not geometry_changed:
                tui.fill(1, 0, body_rows, cols, " ", tui.NORMAL)
            changed_rows = []
            if full_body:
                changed_rows = list(range(body_rows))
            else:
                for index in range(body_rows):
                    previous = previous_rows[index] if index < len(previous_rows) else ""
                    if visible_rows[index] != previous:
                        changed_rows.append(index)
                if (previous_cursor_row is not None and
                        previous_cursor_row not in changed_rows):
                    changed_rows.append(previous_cursor_row)
                if (cursor_screen_row is not None and
                        cursor_screen_row not in changed_rows):
                    changed_rows.append(cursor_screen_row)

            for index in changed_rows:
                line = visible_rows[index]
                previous = previous_rows[index] if index < len(previous_rows) else ""
                clear_width = max(len(line), len(previous))
                old_cells = previous + " " * (clear_width - len(previous))
                new_cells = line + " " * (clear_width - len(line))
                start = 0
                while start < clear_width and old_cells[start] == new_cells[start]:
                    start += 1
                end = clear_width
                while end > start and old_cells[end - 1] == new_cells[end - 1]:
                    end -= 1
                if previous_cursor_row == index:
                    old_cursor_col = min(model_width - 1, previous_cursor_col)
                    start = min(start, old_cursor_col)
                    end = max(end, old_cursor_col + 1)
                if cursor_screen_row == index:
                    new_cursor_col = min(width - 1, cursor_col)
                    start = min(start, new_cursor_col)
                    end = max(end, new_cursor_col + 1)
                if end > clear_width:
                    new_cells += " " * (end - clear_width)
                if start < end:
                    tui.addstr(1 + index, 1 + start,
                               new_cells[start:end], tui.NORMAL)

            if cursor_screen_row is not None:
                cursor_character = " "
                if cursor_line < len(lines) and cursor_col < len(lines[cursor_line]):
                    cursor_character = lines[cursor_line][cursor_col]
                tui.addstr(1 + cursor_screen_row, 1 + min(cursor_col, width - 1),
                           cursor_character, tui.INVERSE)
            tui.refresh()
            previous_rows = visible_rows
            previous_top = top
            previous_cursor_row = cursor_screen_row
            previous_cursor_col = cursor_col
            model_width = width
            previous_geometry = geometry
            first_draw = False
            dirty = False
        key = tui.getch(250)
        if key is None:
            if on_tick is not None:
                on_tick()
            continue
        if on_activity is not None and key != tui.KEY_ESCAPE:
            on_activity()
        if key == tui.KEY_ESCAPE:
            return None
        if key == KEY_CTRL_S or key == KEY_CTRL_D:
            return model.text
        if key in KEY_ENTER or key == KEY_CTRL_N:
            model.insert("\n")
        elif key in KEY_BACKSPACE:
            model.backspace()
        elif key == tui.KEY_DELETE:
            model.delete()
        elif key == tui.KEY_LEFT:
            model.move(-1)
        elif key == tui.KEY_RIGHT:
            model.move(1)
        elif key == tui.KEY_HOME:
            model.cursor = 0
        elif key == tui.KEY_END:
            model.cursor = len(model.text)
        elif isinstance(key, int) and key >= 32 and key <= 0x10ffff:
            model.insert(chr(key))
        dirty = True
    return None
