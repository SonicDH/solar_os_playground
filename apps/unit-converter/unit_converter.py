"""Interactive unit converter for SolarOS."""


# A unit is (label, scale, offset), where base = value * scale + offset.
# A type is (name, left label, right label, left units, right units,
#            left default, right default).
CONVERSION_TYPES = (
    ("Length", "SI", "Imperial",
     (("km", 1000.0, 0.0), ("m", 1.0, 0.0), ("dm", 0.1, 0.0),
      ("cm", 0.01, 0.0), ("mm", 0.001, 0.0)),
     (("mi", 1609.344, 0.0), ("yd", 0.9144, 0.0),
      ("ft", 0.3048, 0.0), ("in", 0.0254, 0.0)),
     1, 2),
    ("Mass", "SI", "Imperial",
     (("t", 1000.0, 0.0), ("kg", 1.0, 0.0), ("g", 0.001, 0.0),
      ("mg", 0.000001, 0.0)),
     (("long ton", 1016.0469088, 0.0), ("st", 6.35029318, 0.0),
      ("lb", 0.45359237, 0.0), ("oz", 0.028349523125, 0.0)),
     1, 2),
    ("Temperature", "SI", "Imperial",
     (("deg C", 1.0, 273.15), ("K", 1.0, 0.0)),
     (("deg F", 5.0 / 9.0, 255.3722222222222),
      ("deg R", 5.0 / 9.0, 0.0)),
     0, 0),
    ("Angle", "Radians", "Degrees",
     (("rad", 1.0, 0.0), ("mrad", 0.001, 0.0)),
     (("deg", 0.017453292519943295, 0.0),
      ("arcmin", 0.0002908882086657216, 0.0),
      ("arcsec", 0.00000484813681109536, 0.0)),
     0, 0),
    ("Area", "SI", "Imperial",
     (("km^2", 1000000.0, 0.0), ("ha", 10000.0, 0.0),
      ("m^2", 1.0, 0.0), ("cm^2", 0.0001, 0.0),
      ("mm^2", 0.000001, 0.0)),
     (("mi^2", 2589988.110336, 0.0), ("acre", 4046.8564224, 0.0),
      ("yd^2", 0.83612736, 0.0), ("ft^2", 0.09290304, 0.0),
      ("in^2", 0.00064516, 0.0)),
     2, 3),
    ("Volume", "SI", "Imperial",
     (("m^3", 1000.0, 0.0), ("L", 1.0, 0.0),
      ("mL", 0.001, 0.0)),
     (("imp gal", 4.54609, 0.0), ("imp qt", 1.1365225, 0.0),
      ("imp pt", 0.56826125, 0.0), ("fl oz", 0.0284130625, 0.0),
      ("ft^3", 28.316846592, 0.0), ("in^3", 0.016387064, 0.0)),
     1, 0),
    ("Speed", "SI", "Imperial",
     (("km/h", 1.0 / 3.6, 0.0), ("m/s", 1.0, 0.0)),
     (("mph", 0.44704, 0.0), ("ft/s", 0.3048, 0.0)),
     0, 0),
    ("Pressure", "SI", "Imperial",
     (("MPa", 1000000.0, 0.0), ("kPa", 1000.0, 0.0),
      ("Pa", 1.0, 0.0), ("bar", 100000.0, 0.0)),
     (("psi", 6894.757293168, 0.0), ("inHg", 3386.389, 0.0)),
     1, 0),
    ("Force", "SI", "Imperial",
     (("kN", 1000.0, 0.0), ("N", 1.0, 0.0)),
     (("lbf", 4.4482216152605, 0.0),),
     1, 0),
    ("Power", "SI", "Imperial",
     (("MW", 1000000.0, 0.0), ("kW", 1000.0, 0.0),
      ("W", 1.0, 0.0)),
     (("hp", 745.6998715822702, 0.0),
      ("BTU/h", 0.2930710701722222, 0.0)),
     1, 0),
    ("Energy", "SI", "Imperial",
     (("MJ", 1000000.0, 0.0), ("kJ", 1000.0, 0.0),
      ("J", 1.0, 0.0)),
     (("BTU", 1055.05585262, 0.0), ("ft-lb", 1.3558179483314, 0.0)),
     1, 0),
)

KEY_BACKSPACE = 8
KEY_TAB = 9
KEY_LF = 10
KEY_ENTER = 13
KEY_SPACE = 32
KEY_DELETE_CHAR = 127

FOCUS_SIDE = (0, 0, 1, 1)
FOCUS_IS_UNIT = (False, True, False, True)


def parse_value(text):
    if text in ("", "-", ".", "-."):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def format_value(value):
    if -0.000000000001 < value < 0.000000000001:
        value = 0.0
    magnitude = abs(value)
    if magnitude >= 1000000000 or (magnitude != 0 and magnitude < 0.000001):
        return "%.5e" % value
    # SolarOS uses single-precision floats. Seven significant digits avoid
    # exposing representation noise such as 2.54 cm becoming 0.999999992 in.
    return "%.7g" % value


def fit(text, pixel_width, character_width=7):
    max_chars = max(1, pixel_width // character_width)
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return text[:max_chars - 3] + "..."


def convert_value(value, source_unit, target_unit):
    base_value = value * source_unit[1] + source_unit[2]
    return (base_value - target_unit[2]) / target_unit[1]


def units_for(conversion_type, side):
    return conversion_type[3] if side == 0 else conversion_type[4]


def recalculate(conversion_type, values, unit_indices, source_side):
    source_value = parse_value(values[source_side])
    target_side = 1 - source_side
    if source_value is None:
        values[target_side] = ""
        return
    source_unit = units_for(conversion_type, source_side)[unit_indices[source_side]]
    target_unit = units_for(conversion_type, target_side)[unit_indices[target_side]]
    values[target_side] = format_value(
        convert_value(source_value, source_unit, target_unit))


def reset_converter(conversion_type):
    unit_indices = [conversion_type[5], conversion_type[6]]
    values = ["1", ""]
    recalculate(conversion_type, values, unit_indices, 0)
    return values, unit_indices


def picker_visible_rows(height):
    if height < 105:
        return max(1, (height - 12) // 16)
    if height < 220:
        return max(1, (height - 38) // 19)
    return max(1, (height - 54) // 21)


def draw_picker(gfx, width, height, selected):
    margin = 8 if width >= 200 else 4
    visible = min(len(CONVERSION_TYPES), picker_visible_rows(height))
    start = min(max(0, selected - visible + 1),
                max(0, len(CONVERSION_TYPES) - visible))
    tiny = height < 105
    compact = height < 220

    gfx.clear(gfx.WHITE)
    gfx.color(gfx.BLACK)

    if tiny:
        list_top = 12
        row_height = 16
        text_offset = 12
        character_width = 7
        gfx.font(gfx.FONT_BOLD)
        heading = "Type %d/%d" % (selected + 1, len(CONVERSION_TYPES))
        gfx.text(margin, 9, fit(heading, width - margin * 2, character_width))
    elif compact:
        list_top = 20
        row_height = 19
        text_offset = 15
        character_width = 7
        gfx.font(gfx.FONT_BOLD_12)
        gfx.text(margin, 14, "Conversion type")
        gfx.font(gfx.FONT_BOLD_14)
    else:
        list_top = 31
        row_height = 21
        text_offset = 16
        character_width = 7
        gfx.font(gfx.FONT_BOLD_18)
        gfx.text(margin, 22, "Conversion type")
        counter = "%d / %d" % (selected + 1, len(CONVERSION_TYPES))
        gfx.font(gfx.FONT_BOLD_14)
        gfx.text(max(margin, width - margin - len(counter) * 7), 20, counter)

    row_width = width - margin * 2
    for row in range(visible):
        index = start + row
        y = list_top + row * row_height
        selected_row = index == selected
        if selected_row:
            gfx.color(gfx.BLACK)
            gfx.fill_rect(margin, y, row_width, row_height - 1)
            gfx.color(gfx.WHITE)
        else:
            gfx.color(gfx.BLACK)
        gfx.text(margin + 6, y + text_offset,
                 fit(CONVERSION_TYPES[index][0], row_width - 12,
                     character_width))

    if not tiny:
        gfx.font(gfx.FONT_MONO_12)
        gfx.text(margin, height - 5,
                 fit("Up/Down choose | Enter open | Q quit",
                     width - margin * 2))
    gfx.present()


def draw_field(gfx, x, y, width, height, label, value, selected,
               tiny, compact):
    if selected:
        gfx.color(gfx.BLACK)
        gfx.fill_rect(x, y, width, height)
        gfx.color(gfx.WHITE)
    else:
        gfx.color(gfx.DARK)
        gfx.rect(x, y, width, height)
        gfx.color(gfx.BLACK)

    if tiny:
        gfx.font(gfx.FONT_SMALL)
        gfx.text(x + 5, y + height * 2 // 3,
                 fit(value, width - 10, 6))
    else:
        gfx.font(gfx.FONT_MONO_12)
        gfx.text(x + 7, y + 15, fit(label, width - 14))
        gfx.font(gfx.FONT_BOLD_14 if compact else gfx.FONT_BOLD_20)
        baseline = y + min(height - 8, 34 if compact else 48)
        gfx.text(x + 7, baseline,
                 fit(value, width - 14, 8 if compact else 11))


def draw_converter(gfx, width, height, type_index, values, unit_indices,
                   focus, source_side):
    conversion_type = CONVERSION_TYPES[type_index]
    unit_labels = (
        conversion_type[3][unit_indices[0]][0],
        conversion_type[4][unit_indices[1]][0],
    )
    margin = 8 if width >= 200 else 4
    tiny = height < 105
    compact = height < 220

    gfx.clear(gfx.WHITE)
    gfx.color(gfx.BLACK)

    if tiny:
        gfx.font(gfx.FONT_SMALL)
        heading = "%s %d/4" % (conversion_type[0], focus + 1)
        gfx.text(margin, 9, fit(heading, width - margin * 2, 6))
        top = 12
        gap = 3
        row_height = max(12, (height - top - gap) // 2)
        unit_width = max(34, (width - margin * 2) * 34 // 100)
    else:
        gfx.font(gfx.FONT_BOLD_12 if compact else gfx.FONT_BOLD_18)
        gfx.text(margin, 14 if compact else 22,
                 conversion_type[0] + " converter")
        if not compact:
            gfx.font(gfx.FONT_MONO_12)
            gfx.text(margin, 42,
                     fit("Edit either value; select a unit with Up/Down",
                         width - margin * 2))
        top = 22 if compact else 54
        gap = 6 if compact else 10
        footer = 18 if compact else 42
        row_height = max(36, min(86, (height - top - footer - gap) // 2))
        unit_width = max(72, min(110, (width - margin * 2) * 28 // 100))

    field_gap = 5 if compact or tiny else 8
    row_width = width - margin * 2
    value_width = row_width - unit_width - field_gap
    second_top = top + row_height + gap

    for side, row_top in ((0, top), (1, second_top)):
        side_name = conversion_type[1] if side == 0 else conversion_type[2]
        value_focus = 0 if side == 0 else 2
        unit_focus = value_focus + 1
        value = values[side] or "--"
        if tiny:
            value = ("A: " if side == 0 else "B: ") + value
        draw_field(gfx, margin, row_top, value_width, row_height,
                   side_name + " value", value, focus == value_focus,
                   tiny, compact)
        draw_field(gfx, margin + value_width + field_gap, row_top,
                   unit_width, row_height, side_name + " unit",
                   unit_labels[side], focus == unit_focus, tiny, compact)

    if not tiny:
        gfx.font(gfx.FONT_MONO_12)
        active = conversion_type[1] if source_side == 0 else conversion_type[2]
        if compact:
            gfx.text(margin, height - 5,
                     fit("Left/Right fields | Up/Down unit | Esc back",
                         width - margin * 2))
        else:
            gfx.text(margin, height - 22,
                     fit("Source: %s | Left/Right fields | Up/Down unit" % active,
                         width - margin * 2))
            gfx.text(margin, height - 7,
                     fit("Type value | C clear | R reset | Esc types | Q quit",
                         width - margin * 2))
    gfx.present()


def run():
    import solaros
    from solaros import gfx

    gfx.begin()
    try:
        width, height = gfx.size()
        type_index = 0
        values, unit_indices = reset_converter(CONVERSION_TYPES[type_index])
        source_side = 0
        focus = 0
        replace_on_type = True
        screen = "picker"

        draw_picker(gfx, width, height, type_index)
        while not solaros.should_exit():
            key = gfx.getch(250)
            if key is None:
                continue

            changed = False
            if key in (ord("q"), ord("Q")):
                break

            if screen == "picker":
                page = max(1, picker_visible_rows(height) - 1)
                if key == gfx.KEY_ESCAPE:
                    break
                if key == gfx.KEY_UP:
                    type_index = (type_index - 1) % len(CONVERSION_TYPES)
                    changed = True
                elif key == gfx.KEY_DOWN:
                    type_index = (type_index + 1) % len(CONVERSION_TYPES)
                    changed = True
                elif key == getattr(gfx, "KEY_PAGE_UP", -1001):
                    type_index = max(0, type_index - page)
                    changed = True
                elif key == getattr(gfx, "KEY_PAGE_DOWN", -1002):
                    type_index = min(len(CONVERSION_TYPES) - 1,
                                     type_index + page)
                    changed = True
                elif key == getattr(gfx, "KEY_HOME", -1004):
                    type_index = 0
                    changed = True
                elif key == getattr(gfx, "KEY_END", -1005):
                    type_index = len(CONVERSION_TYPES) - 1
                    changed = True
                elif key in (gfx.KEY_RIGHT, KEY_ENTER, KEY_LF, KEY_SPACE):
                    values, unit_indices = reset_converter(
                        CONVERSION_TYPES[type_index])
                    source_side = 0
                    focus = 0
                    replace_on_type = True
                    screen = "converter"
                    changed = True
            elif key == gfx.KEY_ESCAPE:
                screen = "picker"
                changed = True
            elif key in (gfx.KEY_LEFT, gfx.KEY_RIGHT, KEY_TAB):
                step = -1 if key == gfx.KEY_LEFT else 1
                focus = (focus + step) % 4
                replace_on_type = not FOCUS_IS_UNIT[focus]
                changed = True
            elif key in (gfx.KEY_UP, gfx.KEY_DOWN) and FOCUS_IS_UNIT[focus]:
                side = FOCUS_SIDE[focus]
                side_units = units_for(CONVERSION_TYPES[type_index], side)
                step = -1 if key == gfx.KEY_UP else 1
                unit_indices[side] = (unit_indices[side] + step) % len(side_units)
                recalculate(CONVERSION_TYPES[type_index], values,
                            unit_indices, source_side)
                changed = True
            elif key in (gfx.KEY_UP, gfx.KEY_DOWN):
                focus = (focus + 2) % 4
                replace_on_type = True
                changed = True
            elif key in (KEY_ENTER, KEY_LF, KEY_SPACE) and FOCUS_IS_UNIT[focus]:
                side = FOCUS_SIDE[focus]
                side_units = units_for(CONVERSION_TYPES[type_index], side)
                unit_indices[side] = (unit_indices[side] + 1) % len(side_units)
                recalculate(CONVERSION_TYPES[type_index], values,
                            unit_indices, source_side)
                changed = True
            elif key in (ord("r"), ord("R")):
                values, unit_indices = reset_converter(CONVERSION_TYPES[type_index])
                source_side = 0
                focus = 0
                replace_on_type = True
                changed = True
            elif not FOCUS_IS_UNIT[focus]:
                side = FOCUS_SIDE[focus]
                if key in (ord("c"), ord("C"), KEY_DELETE_CHAR,
                           getattr(gfx, "KEY_DELETE", -1003)):
                    values[side] = ""
                    source_side = side
                    replace_on_type = False
                    recalculate(CONVERSION_TYPES[type_index], values,
                                unit_indices, source_side)
                    changed = True
                elif key == KEY_BACKSPACE:
                    values[side] = "" if replace_on_type else values[side][:-1]
                    source_side = side
                    replace_on_type = False
                    recalculate(CONVERSION_TYPES[type_index], values,
                                unit_indices, source_side)
                    changed = True
                elif 48 <= key <= 57:
                    current = "" if replace_on_type else values[side]
                    if len(current) < 14:
                        values[side] = current + chr(key)
                        source_side = side
                        replace_on_type = False
                        recalculate(CONVERSION_TYPES[type_index], values,
                                    unit_indices, source_side)
                        changed = True
                elif key == ord("."):
                    current = "" if replace_on_type else values[side]
                    if "." not in current and len(current) < 14:
                        if current in ("", "-"):
                            current += "0"
                        values[side] = current + "."
                        source_side = side
                        replace_on_type = False
                        recalculate(CONVERSION_TYPES[type_index], values,
                                    unit_indices, source_side)
                        changed = True
                elif key == ord("-"):
                    current = "" if replace_on_type else values[side]
                    if current == "":
                        values[side] = "-"
                        source_side = side
                        replace_on_type = False
                        recalculate(CONVERSION_TYPES[type_index], values,
                                    unit_indices, source_side)
                        changed = True

            if changed:
                if screen == "picker":
                    draw_picker(gfx, width, height, type_index)
                else:
                    draw_converter(gfx, width, height, type_index, values,
                                   unit_indices, focus, source_side)
    finally:
        gfx.end()


if __name__ == "__main__":
    run()
