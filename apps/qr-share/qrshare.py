"""QR Share app with a compact Model 2 encoder for reflective displays.

This encoder intentionally supports one portable profile: error correction L,
versions 1 through 15, and binary/UTF-8 byte payloads. It returns the symbol
modules without a quiet zone as rows of lists containing zero or one.
"""

import sys

import solaros
from solaros import gfx

MAX_VERSION = 15

# Each entry contains (block count, total codewords, data codewords) for QR-L.
_RS_BLOCKS = (
    (),
    ((1, 26, 19),),
    ((1, 44, 34),),
    ((1, 70, 55),),
    ((1, 100, 80),),
    ((1, 134, 108),),
    ((2, 86, 68),),
    ((2, 98, 78),),
    ((2, 121, 97),),
    ((2, 146, 116),),
    ((2, 86, 68), (2, 87, 69)),
    ((4, 101, 81),),
    ((2, 116, 92), (2, 117, 93)),
    ((4, 133, 107),),
    ((3, 145, 115), (1, 146, 116)),
    ((5, 109, 87), (1, 110, 88)),
)

_ALIGNMENT = (
    (),
    (),
    (6, 18),
    (6, 22),
    (6, 26),
    (6, 30),
    (6, 34),
    (6, 22, 38),
    (6, 24, 42),
    (6, 26, 46),
    (6, 28, 50),
    (6, 30, 54),
    (6, 32, 58),
    (6, 34, 62),
    (6, 26, 46, 66),
    (6, 26, 48, 70),
)

_GF_EXP = [0] * 512
_GF_LOG = [0] * 256
_value = 1
for _index in range(255):
    _GF_EXP[_index] = _value
    _GF_LOG[_value] = _index
    _value <<= 1
    if _value & 0x100:
        _value ^= 0x11D
for _index in range(255, 512):
    _GF_EXP[_index] = _GF_EXP[_index - 255]


class DataTooLongError(ValueError):
    pass


def _blocks(version):
    result = []
    for count, total, data in _RS_BLOCKS[version]:
        for _ in range(count):
            result.append((total, data))
    return result


def _data_capacity(version):
    return sum(data for _, data in _blocks(version))


def _append_bits(target, value, count):
    for bit in range(count - 1, -1, -1):
        target.append((value >> bit) & 1)


def _make_data(payload, version):
    capacity_bits = _data_capacity(version) * 8
    count_bits = 8 if version <= 9 else 16
    bits = []
    _append_bits(bits, 0x4, 4)
    _append_bits(bits, len(payload), count_bits)
    for value in payload:
        _append_bits(bits, value, 8)

    terminator = min(4, capacity_bits - len(bits))
    for _ in range(terminator):
        bits.append(0)
    while len(bits) % 8:
        bits.append(0)

    result = []
    for offset in range(0, len(bits), 8):
        value = 0
        for index in range(offset, offset + 8):
            value = (value << 1) | bits[index]
        result.append(value)

    pad = 0xEC
    while len(result) < capacity_bits // 8:
        result.append(pad)
        pad ^= 0xFD
    return result


def _gf_mul(left, right):
    if left == 0 or right == 0:
        return 0
    return _GF_EXP[_GF_LOG[left] + _GF_LOG[right]]


def _generator(degree):
    result = [1]
    for exponent in range(degree):
        factor = _GF_EXP[exponent]
        product = [0] * (len(result) + 1)
        for index in range(len(result)):
            value = result[index]
            product[index] ^= value
            product[index + 1] ^= _gf_mul(value, factor)
        result = product
    return result


def _remainder(data, degree):
    generator = _generator(degree)
    work = list(data) + [0] * degree
    for offset in range(len(data)):
        factor = work[offset]
        if factor:
            for index in range(len(generator)):
                coefficient = generator[index]
                work[offset + index] ^= _gf_mul(coefficient, factor)
    result = []
    for index in range(len(work) - degree, len(work)):
        result.append(work[index])
    return result


def _make_codewords(payload, version):
    data = _make_data(payload, version)
    data_blocks = []
    ecc_blocks = []
    offset = 0
    for total_count, data_count in _blocks(version):
        block = []
        for index in range(offset, offset + data_count):
            block.append(data[index])
        offset += data_count
        data_blocks.append(block)
        ecc_blocks.append(_remainder(block, total_count - data_count))

    result = []
    for index in range(max(len(block) for block in data_blocks)):
        for block in data_blocks:
            if index < len(block):
                result.append(block[index])
    for index in range(max(len(block) for block in ecc_blocks)):
        for block in ecc_blocks:
            if index < len(block):
                result.append(block[index])
    return result


def _set_function(modules, functions, x, y, dark):
    if 0 <= x < len(modules) and 0 <= y < len(modules):
        modules[y][x] = 1 if dark else 0
        functions[y][x] = 1


def _draw_finder(modules, functions, center_x, center_y):
    for dy in range(-4, 5):
        for dx in range(-4, 5):
            distance = max(abs(dx), abs(dy))
            _set_function(
                modules, functions, center_x + dx, center_y + dy,
                distance != 2 and distance != 4,
            )


def _draw_alignment(modules, functions, center_x, center_y):
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            distance = max(abs(dx), abs(dy))
            _set_function(
                modules, functions, center_x + dx, center_y + dy,
                distance != 1,
            )


def _draw_format(modules, functions, mask):
    size = len(modules)
    data = (1 << 3) | mask  # Error correction L has format selector 01.
    remainder = data
    for _ in range(10):
        remainder = (remainder << 1) ^ ((remainder >> 9) * 0x537)
    bits = ((data << 10) | remainder) ^ 0x5412

    def bit(index):
        return ((bits >> index) & 1) != 0

    for index in range(6):
        _set_function(modules, functions, 8, index, bit(index))
    _set_function(modules, functions, 8, 7, bit(6))
    _set_function(modules, functions, 8, 8, bit(7))
    _set_function(modules, functions, 7, 8, bit(8))
    for index in range(9, 15):
        _set_function(modules, functions, 14 - index, 8, bit(index))

    for index in range(8):
        _set_function(modules, functions, size - 1 - index, 8, bit(index))
    for index in range(8, 15):
        _set_function(modules, functions, 8, size - 15 + index, bit(index))
    _set_function(modules, functions, 8, size - 8, True)


def _draw_version(modules, functions, version):
    if version < 7:
        return
    remainder = version
    for _ in range(12):
        remainder = (remainder << 1) ^ ((remainder >> 11) * 0x1F25)
    bits = (version << 12) | remainder
    size = len(modules)
    for index in range(18):
        dark = ((bits >> index) & 1) != 0
        first = size - 11 + index % 3
        second = index // 3
        _set_function(modules, functions, first, second, dark)
        _set_function(modules, functions, second, first, dark)


def _function_patterns(version):
    size = version * 4 + 17
    modules = [[0] * size for _ in range(size)]
    functions = [[0] * size for _ in range(size)]
    _draw_finder(modules, functions, 3, 3)
    _draw_finder(modules, functions, size - 4, 3)
    _draw_finder(modules, functions, 3, size - 4)

    for index in range(8, size - 8):
        _set_function(modules, functions, 6, index, index % 2 == 0)
        _set_function(modules, functions, index, 6, index % 2 == 0)

    positions = _ALIGNMENT[version]
    last = len(positions) - 1
    finder_corners = ((0, 0), (0, last), (last, 0))
    for y_index in range(len(positions)):
        center_y = positions[y_index]
        for x_index in range(len(positions)):
            center_x = positions[x_index]
            if (x_index, y_index) not in finder_corners:
                _draw_alignment(modules, functions, center_x, center_y)

    _draw_format(modules, functions, 0)
    _draw_version(modules, functions, version)
    return modules, functions


def _mask_applies(mask, x, y):
    product = x * y
    if mask == 0:
        return (x + y) % 2 == 0
    if mask == 1:
        return y % 2 == 0
    if mask == 2:
        return x % 3 == 0
    if mask == 3:
        return (x + y) % 3 == 0
    if mask == 4:
        return (x // 3 + y // 2) % 2 == 0
    if mask == 5:
        return product % 2 + product % 3 == 0
    if mask == 6:
        return (product % 2 + product % 3) % 2 == 0
    return ((x + y) % 2 + product % 3) % 2 == 0


def _map_data(modules, functions, codewords, mask):
    size = len(modules)
    bit_length = len(codewords) * 8
    bit_index = 0
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5
        upward = ((right + 1) & 2) == 0
        for vertical in range(size):
            y = size - 1 - vertical if upward else vertical
            for offset in range(2):
                x = right - offset
                if functions[y][x]:
                    continue
                dark = False
                if bit_index < bit_length:
                    dark = ((codewords[bit_index >> 3] >> (7 - (bit_index & 7))) & 1) != 0
                if _mask_applies(mask, x, y):
                    dark = not dark
                modules[y][x] = 1 if dark else 0
                bit_index += 1
        right -= 2


def _penalty(modules):
    size = len(modules)
    result = 0
    for rows in (modules, zip(*modules)):
        for row in rows:
            previous = None
            run = 0
            for value in row:
                if value == previous:
                    run += 1
                    if run == 5:
                        result += 3
                    elif run > 5:
                        result += 1
                else:
                    previous = value
                    run = 1

    for y in range(size - 1):
        for x in range(size - 1):
            value = modules[y][x]
            if (modules[y][x + 1] == value and modules[y + 1][x] == value and
                    modules[y + 1][x + 1] == value):
                result += 3

    patterns = ((1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0),
                (0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1))
    for rows in (modules, zip(*modules)):
        for row in rows:
            values = tuple(row)
            for index in range(len(values) - 10):
                for pattern in patterns:
                    matched = True
                    for offset in range(11):
                        if values[index + offset] != pattern[offset]:
                            matched = False
                            break
                    if matched:
                        result += 40
                        break

    dark = sum(sum(row) for row in modules)
    total = size * size
    result += (abs(dark * 20 - total * 10) // total) * 10
    return result


def encode(data):
    payload = data if isinstance(data, bytes) else bytes(str(data), "utf-8")
    version = None
    for candidate in range(1, MAX_VERSION + 1):
        count_bits = 8 if candidate <= 9 else 16
        if len(payload) < (1 << count_bits):
            needed = 4 + count_bits + len(payload) * 8
            if needed <= _data_capacity(candidate) * 8:
                version = candidate
                break
    if version is None:
        raise DataTooLongError("QR Share supports at most 520 UTF-8 bytes")

    codewords = _make_codewords(payload, version)
    base, functions = _function_patterns(version)
    best = None
    best_score = None
    for mask in range(8):
        modules = [list(row) for row in base]
        _map_data(modules, functions, codewords, mask)
        _draw_format(modules, functions, mask)
        score = _penalty(modules)
        if best_score is None or score < best_score:
            best = modules
            best_score = score
    return best, version


KEY_Q = 113
KEY_R = 114
QUIET_ZONE = 4
HEADER_H = 22
FOOTER_H = 17
MAX_PAYLOAD_BYTES = 520


class FileTooLargeError(ValueError):
    pass


def ssh_public_key():
    keys = getattr(solaros, "ssh_keys", None)
    if keys is None:
        raise ValueError("SSH support is not installed")
    public_key = getattr(keys, "public_key", None)
    if public_key is None:
        raise ValueError("SSH QR sharing requires SolarOS 4.6.8")
    status = keys.status()
    if not status["public_key_exists"]:
        raise ValueError("no SSH public key; run: sshkey gen 2048")
    return bytes(public_key(), "utf-8")


def read_file(path):
    storage = getattr(solaros, "storage", None)
    read = getattr(storage, "read_file", None) if storage is not None else None
    if read is None:
        raise ValueError("file input requires an updated SolarOS 4.6.8 build")
    payload = read(path, MAX_PAYLOAD_BYTES + 1)
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise FileTooLargeError("file is too big; maximum is 520 bytes: " + path)
    return payload


def select_source(arguments):
    if not arguments or arguments == ["--ssh"]:
        return "SSH public key", ssh_public_key
    if arguments[0] == "--file":
        if len(arguments) != 2:
            raise ValueError("usage: qr-share --file PATH")
        path = arguments[1]
        return "File", lambda: read_file(path)
    if arguments[0] == "--text":
        if len(arguments) < 2:
            raise ValueError("usage: qr-share --text TEXT")
        parts = [arguments[index] for index in range(1, len(arguments))]
        text = " ".join(parts)
    else:
        text = " ".join(arguments)
    payload = bytes(text, "utf-8")
    return "Text", lambda: payload


def centered_text(width, y, text):
    gfx.text(max(0, (width - len(text) * 7) // 2), y, text)


def draw_generating(width, height):
    gfx.clear(gfx.WHITE)
    gfx.color(gfx.BLACK)
    gfx.font(gfx.FONT_BOLD_14)
    centered_text(width, 34, "QR Share")
    gfx.font(gfx.FONT_MONO_12)
    centered_text(width, height // 2, "Generating QR code, please wait...")
    gfx.refresh()


def draw_error(width, height, message):
    gfx.clear(gfx.WHITE)
    gfx.color(gfx.BLACK)
    gfx.font(gfx.FONT_BOLD_14)
    centered_text(width, 34, "QR Share")
    gfx.font(gfx.FONT_MONO_12)
    words = str(message).split()
    lines = []
    current = ""
    for word in words:
        candidate = word if not current else current + " " + word
        if len(candidate) <= max(12, (width - 20) // 7):
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    start_y = max(60, (height - len(lines) * 16) // 2)
    for index in range(len(lines)):
        centered_text(width, start_y + index * 16, lines[index])
    centered_text(width, height - 8, "R retry | ESC quit")
    gfx.refresh()


def draw_qr(width, height, title, payload):
    matrix, version = encode(payload)
    module_count = len(matrix) + QUIET_ZONE * 2
    available_h = height - HEADER_H - FOOTER_H
    scale = min(width // module_count, available_h // module_count)
    if scale < 2:
        raise ValueError("QR code is too large for this display")

    symbol_size = module_count * scale
    origin_x = (width - symbol_size) // 2 + QUIET_ZONE * scale
    origin_y = HEADER_H + (available_h - symbol_size) // 2 + QUIET_ZONE * scale

    gfx.clear(gfx.WHITE)
    gfx.color(gfx.BLACK)
    gfx.font(gfx.FONT_BOLD_14)
    centered_text(width, 16, title)

    for y in range(len(matrix)):
        row = matrix[y]
        run_start = None
        for x in range(len(row) + 1):
            dark = x < len(row) and row[x]
            if dark and run_start is None:
                run_start = x
            elif not dark and run_start is not None:
                gfx.fill_rect(
                    origin_x + run_start * scale,
                    origin_y + y * scale,
                    (x - run_start) * scale,
                    scale,
                )
                run_start = None

    gfx.font(gfx.FONT_MONO_12)
    status = "v{}-L  {} bytes  R reload  ESC quit".format(version, len(payload))
    centered_text(width, height - 7, status)
    gfx.refresh()


def main():
    arguments = [sys.argv[index] for index in range(1, len(sys.argv))]
    title, loader = select_source(arguments)
    gfx.begin()
    try:
        width, height = gfx.size()
        while not solaros.should_exit():
            try:
                draw_generating(width, height)
                draw_qr(width, height, title, loader())
            except (DataTooLongError, OSError, ValueError) as error:
                draw_error(width, height, error)

            while not solaros.should_exit():
                key = gfx.getch(250)
                if key == gfx.KEY_ESCAPE or key == KEY_Q:
                    return
                if key == KEY_R:
                    break
    finally:
        gfx.end()


main()
