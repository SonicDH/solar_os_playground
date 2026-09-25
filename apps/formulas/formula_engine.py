"""Small MathTeX parser, evaluator, and monochrome layout engine."""

import math


FONT_METRICS = (
    (10, 22, 17),
    (9, 20, 15),
    (8, 18, 14),
    (7, 16, 12),
    (6, 14, 10),
)

def _log10(value):
    return math.log(value) / math.log(10.0)


FUNCTIONS = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "log": _log10,
    "ln": math.log,
    "abs": abs,
}

SYMBOL_COMMANDS = (
    "alpha", "beta", "gamma", "delta", "theta", "lambda", "mu",
    "nu", "pi", "rho", "sigma", "tau", "phi", "omega",
)


class FormulaError(ValueError):
    pass


def _is_alpha(character):
    return ("a" <= character <= "z") or ("A" <= character <= "Z")


def _is_digit(character):
    return "0" <= character <= "9"


def tokenize(source):
    tokens = []
    index = 0
    length = len(source)
    while index < length:
        character = source[index]
        if character in " \t\r\n":
            index += 1
            continue
        if _is_digit(character) or (
                character == "." and index + 1 < length and
                _is_digit(source[index + 1])):
            start = index
            index += 1
            while index < length and _is_digit(source[index]):
                index += 1
            if index < length and source[index] == ".":
                index += 1
                while index < length and _is_digit(source[index]):
                    index += 1
            if index < length and source[index] in "eE":
                exponent = index
                index += 1
                if index < length and source[index] in "+-":
                    index += 1
                digit_start = index
                while index < length and _is_digit(source[index]):
                    index += 1
                if digit_start == index:
                    raise FormulaError("invalid exponent at column %d" % exponent)
            tokens.append(("NUMBER", source[start:index]))
            continue
        if _is_alpha(character):
            start = index
            index += 1
            while index < length and (
                    _is_alpha(source[index]) or _is_digit(source[index])):
                index += 1
            tokens.append(("IDENT", source[start:index]))
            continue
        if character == "\\":
            start = index
            index += 1
            command_start = index
            while index < length and _is_alpha(source[index]):
                index += 1
            if command_start == index:
                raise FormulaError("expected command at column %d" % start)
            command = source[command_start:index]
            if command == "cdot" or command == "times":
                tokens.append(("*", command))
            else:
                tokens.append(("COMMAND", command))
            continue
        if character in "+-*/^_=(),{}":
            tokens.append((character, character))
            index += 1
            continue
        raise FormulaError("unsupported character %r at column %d" %
                           (character, index))
    tokens.append(("EOF", ""))
    return tokens


class _Parser:
    def __init__(self, source):
        self.tokens = tokenize(source)
        self.index = 0

    def current(self):
        return self.tokens[self.index]

    def accept(self, kind):
        if self.current()[0] != kind:
            return None
        token = self.current()
        self.index += 1
        return token

    def expect(self, kind):
        token = self.accept(kind)
        if token is None:
            raise FormulaError("expected %s, found %s" %
                               (kind, self.current()[0]))
        return token

    def parse(self):
        node = self.parse_relation()
        self.expect("EOF")
        return node

    def parse_relation(self):
        left = self.parse_addition()
        if self.accept("=") is not None:
            right = self.parse_addition()
            if self.current()[0] == "=":
                raise FormulaError("only one equality is supported")
            return ("eq", left, right)
        return left

    def parse_addition(self):
        node = self.parse_product()
        while self.current()[0] in ("+", "-"):
            operator = self.current()[0]
            self.index += 1
            node = ("add", operator, node, self.parse_product())
        return node

    def _starts_primary(self):
        return self.current()[0] in ("NUMBER", "IDENT", "COMMAND", "(", "{")

    def parse_product(self):
        node = self.parse_unary()
        while True:
            if self.current()[0] in ("*", "/"):
                operator = self.current()[0]
                self.index += 1
                right = self.parse_unary()
                if operator == "/":
                    node = ("div", node, right)
                else:
                    node = ("mul", True, node, right)
            elif self._starts_primary():
                node = ("mul", False, node, self.parse_unary())
            else:
                break
        return node

    def parse_unary(self):
        if self.accept("+") is not None:
            return self.parse_unary()
        if self.accept("-") is not None:
            return ("neg", self.parse_unary())
        return self.parse_postfix()

    def parse_postfix(self):
        node = self.parse_primary()
        while self.current()[0] in ("^", "_"):
            operator = self.current()[0]
            self.index += 1
            script = self.parse_script()
            if operator == "^":
                node = ("pow", node, script)
            else:
                node = ("sub", node, script)
        return node

    def parse_script(self):
        if self.accept("{") is not None:
            node = self.parse_addition()
            self.expect("}")
            return node
        return self.parse_unary()

    def parse_group(self, opening, closing, visible):
        self.expect(opening)
        node = self.parse_relation()
        self.expect(closing)
        if visible:
            return ("group", node)
        return node

    def parse_command_argument(self):
        if self.current()[0] == "{":
            return self.parse_group("{", "}", False)
        if self.current()[0] == "(":
            return self.parse_group("(", ")", True)
        return self.parse_unary()

    def parse_primary(self):
        token = self.accept("NUMBER")
        if token is not None:
            return ("num", token[1])
        token = self.accept("IDENT")
        if token is not None:
            return ("var", token[1])
        if self.current()[0] == "(":
            return self.parse_group("(", ")", True)
        if self.current()[0] == "{":
            return self.parse_group("{", "}", False)
        token = self.accept("COMMAND")
        if token is not None:
            command = token[1]
            if command == "frac":
                numerator = self.parse_group("{", "}", False)
                denominator = self.parse_group("{", "}", False)
                return ("div", numerator, denominator)
            if command == "sqrt":
                return ("func", command, self.parse_command_argument())
            if command in FUNCTIONS:
                return ("func", command, self.parse_command_argument())
            if command in SYMBOL_COMMANDS:
                return ("var", command)
            raise FormulaError("unsupported command \\%s" % command)
        raise FormulaError("expected a number, symbol, or group; found %s" %
                           self.current()[0])


def parse(source):
    return _Parser(source).parse()


def _symbol_name(node):
    if node[0] == "var":
        return node[1]
    if node[0] == "num":
        return node[1]
    if node[0] == "sub":
        left = _symbol_name(node[1])
        right = _symbol_name(node[2])
        if left is not None and right is not None:
            return left + "_" + right
    return None


def evaluate(node, values):
    kind = node[0]
    if kind == "num":
        return float(node[1])
    if kind == "var":
        name = node[1]
        if name == "pi":
            return math.pi
        if name == "e":
            return math.e
        if name not in values:
            raise FormulaError("missing value for %s" % name)
        return float(values[name])
    if kind == "sub":
        name = _symbol_name(node)
        if name is None or name not in values:
            raise FormulaError("missing value for %s" % (name or "subscript"))
        return float(values[name])
    if kind == "group":
        return evaluate(node[1], values)
    if kind == "neg":
        return -evaluate(node[1], values)
    if kind == "add":
        left = evaluate(node[2], values)
        right = evaluate(node[3], values)
        return left + right if node[1] == "+" else left - right
    if kind == "mul":
        return evaluate(node[2], values) * evaluate(node[3], values)
    if kind == "div":
        return evaluate(node[1], values) / evaluate(node[2], values)
    if kind == "pow":
        return evaluate(node[1], values) ** evaluate(node[2], values)
    if kind == "func":
        return FUNCTIONS[node[1]](evaluate(node[2], values))
    if kind == "eq":
        return evaluate(node[1], values) - evaluate(node[2], values)
    raise FormulaError("unknown syntax node %s" % kind)


def collect_symbols(node, result=None):
    if result is None:
        result = set()
    kind = node[0]
    if kind == "var":
        if node[1] not in ("pi", "e"):
            result.add(node[1])
    elif kind == "sub":
        name = _symbol_name(node)
        if name is not None:
            result.add(name)
        else:
            collect_symbols(node[1], result)
            collect_symbols(node[2], result)
    elif kind in ("group", "neg"):
        collect_symbols(node[1], result)
    elif kind in ("div", "pow", "eq"):
        collect_symbols(node[1], result)
        collect_symbols(node[2], result)
    elif kind in ("add", "mul"):
        collect_symbols(node[2], result)
        collect_symbols(node[3], result)
    elif kind == "func":
        collect_symbols(node[2], result)
    return result


def font_metrics(level):
    return FONT_METRICS[max(0, min(len(FONT_METRICS) - 1, level))]


def _box(width, ascent, descent, items):
    return {
        "width": int(width),
        "ascent": int(ascent),
        "descent": int(descent),
        "items": items,
    }


def _text_box(text, level, tag=None):
    width, height, baseline = font_metrics(level)
    return _box(len(text) * width, baseline, height - baseline,
                [("text", level, 0, 0, text, tag)])


def _horizontal(parts):
    x = 0
    ascent = 0
    descent = 0
    items = []
    for part in parts:
        if isinstance(part, int):
            x += part
            continue
        items.append(("box", part, x, 0))
        x += part["width"]
        ascent = max(ascent, part["ascent"])
        descent = max(descent, part["descent"])
    return _box(x, ascent, descent, items)


def layout(node, level=0, tag=None):
    level = max(0, min(len(FONT_METRICS) - 1, level))
    kind = node[0]
    char_width = font_metrics(level)[0]
    if kind == "num":
        return _text_box(node[1], level, tag)
    if kind == "var":
        return _text_box(node[1], level, tag or node[1])
    if kind == "sub":
        symbol = _symbol_name(node)
        base = layout(node[1], level, symbol or tag)
        subscript = layout(node[2], min(4, level + 2), symbol or tag)
        shift = max(4, base["descent"] + 3)
        return _box(
            base["width"] + subscript["width"],
            base["ascent"],
            max(base["descent"], shift + subscript["descent"]),
            [("box", base, 0, 0),
             ("box", subscript, base["width"], shift)],
        )
    if kind == "group":
        child = layout(node[1], level)
        return _horizontal((_text_box("(", level), child,
                            _text_box(")", level)))
    if kind == "neg":
        return _horizontal((_text_box("-", level), layout(node[1], level)))
    if kind == "add":
        return _horizontal((layout(node[2], level), char_width,
                            _text_box(node[1], level), char_width,
                            layout(node[3], level)))
    if kind == "mul":
        left = layout(node[2], level)
        right = layout(node[3], level)
        if node[1]:
            dot = _box(char_width, 1, 1,
                       [("dot", char_width // 2, -char_width // 3, 1)])
            return _horizontal((left, char_width // 2, dot,
                                char_width // 2, right))
        return _horizontal((left, max(2, char_width // 2), right))
    if kind == "eq":
        return _horizontal((layout(node[1], level), char_width,
                            _text_box("=", level), char_width,
                            layout(node[2], level)))
    if kind == "div":
        numerator = layout(node[1], min(4, level + 1))
        denominator = layout(node[2], min(4, level + 1))
        width = max(numerator["width"], denominator["width"]) + 8
        numerator_height = numerator["ascent"] + numerator["descent"]
        denominator_height = denominator["ascent"] + denominator["descent"]
        numerator_baseline = -3 - numerator["descent"]
        denominator_baseline = 3 + denominator["ascent"]
        return _box(
            width,
            numerator_height + 3,
            denominator_height + 3,
            [("box", numerator, (width - numerator["width"]) // 2,
              numerator_baseline),
             ("line", 1, 0, width - 2, 0),
             ("box", denominator, (width - denominator["width"]) // 2,
              denominator_baseline)],
        )
    if kind == "pow":
        base = layout(node[1], level)
        exponent = layout(node[2], min(4, level + 2))
        shift = max(6, base["ascent"] // 2)
        return _box(
            base["width"] + exponent["width"],
            max(base["ascent"], shift + exponent["ascent"]),
            max(base["descent"], max(0, exponent["descent"] - shift)),
            [("box", base, 0, 0),
             ("box", exponent, base["width"], -shift)],
        )
    if kind == "func":
        name = node[1]
        child = layout(node[2], level)
        if name != "sqrt":
            return _horizontal((_text_box(name, level),
                                _text_box("(", level), child,
                                _text_box(")", level)))
        root_width = char_width
        top = -child["ascent"] - 3
        bottom = child["descent"]
        return _box(
            root_width + child["width"] + 3,
            child["ascent"] + 3,
            child["descent"],
            [("line", 0, -2, 2, 1),
             ("line", 2, 1, 5, top + 4),
             ("line", 5, top + 4, root_width, top + 1),
             ("line", root_width, top, root_width + child["width"] + 2, top),
             ("box", child, root_width + 2, 0)],
        )
    raise FormulaError("cannot lay out syntax node %s" % kind)


def fit_layout(node, maximum_width, maximum_height):
    chosen = None
    for level in range(len(FONT_METRICS)):
        chosen = layout(node, level)
        chosen["level"] = level
        if (chosen["width"] <= maximum_width and
                chosen["ascent"] + chosen["descent"] <= maximum_height):
            return chosen
    return chosen


def drawing_commands(box, x, baseline, selected=None):
    commands = []

    def visit(current, origin_x, origin_y):
        for item in current["items"]:
            kind = item[0]
            if kind == "box":
                visit(item[1], origin_x + item[2], origin_y + item[3])
            elif kind == "text":
                _, level, dx, dy, text, tag = item
                commands.append(("text", level, origin_x + dx,
                                 origin_y + dy, text))
                if selected is not None and tag == selected:
                    width = len(text) * font_metrics(level)[0]
                    commands.append(("line", origin_x + dx,
                                     origin_y + dy + 2,
                                     origin_x + dx + width - 1,
                                     origin_y + dy + 2))
            elif kind == "line":
                commands.append(("line", origin_x + item[1],
                                 origin_y + item[2], origin_x + item[3],
                                 origin_y + item[4]))
            elif kind == "dot":
                commands.append(("dot", origin_x + item[1],
                                 origin_y + item[2], item[3]))

    visit(box, int(x), int(baseline))
    return commands


def inline_text(node):
    """Return a compact ASCII fallback for very small displays."""
    kind = node[0]
    if kind in ("num", "var"):
        return node[1]
    if kind == "sub":
        name = _symbol_name(node)
        if name is not None:
            return name
        return "%s_(%s)" % (inline_text(node[1]), inline_text(node[2]))
    if kind == "group":
        return "(" + inline_text(node[1]) + ")"
    if kind == "neg":
        return "-" + inline_text(node[1])
    if kind == "add":
        return "%s %s %s" % (inline_text(node[2]), node[1],
                              inline_text(node[3]))
    if kind == "mul":
        operator = " * " if node[1] else " "
        return inline_text(node[2]) + operator + inline_text(node[3])
    if kind == "div":
        return "(%s)/(%s)" % (inline_text(node[1]), inline_text(node[2]))
    if kind == "pow":
        return "%s^(%s)" % (inline_text(node[1]), inline_text(node[2]))
    if kind == "func":
        return "%s(%s)" % (node[1], inline_text(node[2]))
    if kind == "eq":
        return "%s = %s" % (inline_text(node[1]), inline_text(node[2]))
    raise FormulaError("cannot format syntax node %s" % kind)


def solve(expression, values, constants=None):
    environment = {}
    if constants:
        environment.update(constants)
    environment.update(values)
    result = evaluate(parse(expression), environment)
    if result != result or result in (float("inf"), float("-inf")):
        raise FormulaError("result is not finite")
    return result
