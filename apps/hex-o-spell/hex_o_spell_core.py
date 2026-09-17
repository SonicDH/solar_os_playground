"""Pure interaction state for the Hex-O-Spell Playground app."""


GROUPS = (
    ("<", "A", "B", "C", "D", "E"),
    ("<", "F", "G", "H", "I", "J"),
    ("<", "K", "L", "M", "N", "O"),
    ("<", "P", "Q", "R", "S", "T"),
    ("<", "U", "V", "W", "X", "Y"),
    ("<", ".", "?", "DEL", "_", "Z"),
)

# Clockwise from down, matching the original Processing/browser interaction.
# Integer vectors avoid requiring floating-point trigonometry on the device.
DIRECTIONS = (
    (0, 1000),
    (866, 500),
    (866, -500),
    (0, -1000),
    (-866, -500),
    (-866, 500),
)

SETTINGS_AUTO = 0
SETTINGS_DWELL = 1
SETTINGS_PAIR = 2
SETTINGS_DONE = 3
SETTINGS_EXIT = 4


def nearest_direction(x, y):
    winner = 0
    best = None
    for index, direction in enumerate(DIRECTIONS):
        score = x * direction[0] + y * direction[1]
        if best is None or score > best:
            winner = index
            best = score
    return winner


def joystick_direction(x, y, deadzone):
    """Return the highlighted direction, or center for a neutral joystick."""
    if x * x + y * y < deadzone * deadzone:
        return None
    return nearest_direction(x, y)


def cycle_direction(selected, step):
    """Cycle one cell around the ring, starting at either end from center."""
    if step not in (-1, 1):
        raise ValueError("step must be -1 or 1")
    if selected is None:
        return 0 if step > 0 else len(DIRECTIONS) - 1
    return (selected + step) % len(DIRECTIONS)


def point_in_hex(x, y, radius, half_height):
    """Return whether a center-relative point is inside a flat-top hexagon."""
    x = abs(x)
    y = abs(y)
    if x > radius or y > half_height:
        return False
    edge = radius - y * radius // (2 * half_height)
    return x <= edge


def move_settings_focus(selected, direction):
    """Move through the settings rows and the two-button bottom row."""
    if direction == "up":
        if selected in (SETTINGS_DONE, SETTINGS_EXIT):
            return SETTINGS_PAIR
        return max(SETTINGS_AUTO, selected - 1)
    if direction == "down":
        if selected < SETTINGS_PAIR:
            return selected + 1
        if selected == SETTINGS_PAIR:
            return SETTINGS_DONE
        return selected
    if direction == "left" and selected == SETTINGS_EXIT:
        return SETTINGS_DONE
    if direction == "right" and selected == SETTINGS_DONE:
        return SETTINGS_EXIT
    return selected


class HexOSpellState:
    def __init__(self):
        self.level = "groups"
        self.selection = None
        self.active_group = 0

    def select(self, direction):
        if direction < 0 or direction >= len(DIRECTIONS):
            raise ValueError("direction must be 0..5")
        changed = self.selection != direction
        self.selection = direction
        return changed

    def center(self):
        changed = self.selection is not None
        self.selection = None
        return changed

    def labels(self):
        if self.level == "groups":
            return GROUPS
        return tuple((value,) for value in GROUPS[self.active_group])

    def trigger(self):
        """Advance the selector and return a keyboard action, if any."""
        if self.selection is None:
            return None
        if self.level == "groups":
            self.active_group = self.selection
            self.level = "characters"
            return None

        value = GROUPS[self.active_group][self.selection]
        if value == "<":
            self.level = "groups"
            return None
        if value == "DEL":
            return "\b"
        if value == "_":
            return " "
        return value

    def activate(self, direction):
        """Select and immediately trigger one direction, as touch input does."""
        self.select(direction)
        return self.trigger()


class DwellTrigger:
    def __init__(self, duration_ms):
        self.duration_ms = duration_ms
        self.source = None
        self.direction = None
        self.started_ms = 0
        self.locked = False

    def arm(self, source, direction, now_ms):
        if self.source == source and self.direction == direction:
            return False
        self.source = source
        self.direction = direction
        self.started_ms = now_ms
        self.locked = False
        return True

    def cancel(self, source=None):
        if source is not None and source != self.source:
            return False
        changed = self.source is not None
        self.source = None
        self.direction = None
        self.started_ms = 0
        self.locked = False
        return changed

    def progress(self, now_ms):
        if self.source is None or self.locked:
            return 0
        elapsed = now_ms - self.started_ms
        if elapsed <= 0:
            return 0
        if elapsed >= self.duration_ms:
            return 1000
        return elapsed * 1000 // self.duration_ms

    def ready(self, now_ms):
        return (
            self.source is not None
            and not self.locked
            and now_ms - self.started_ms >= self.duration_ms
        )

    def lock(self):
        self.locked = True
