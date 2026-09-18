"""Graphical system status and safe service controls for SolarOS."""

import gc

import solaros
from solaros import gfx


HEADER_H = 62
FOOTER_H = 25
ROW_H = 42
INFO_ROW_H = 25
KEY_ENTER = 13
KEY_LF = 10
KEY_BACKSPACE = 8
KEY_DELETE_CHAR = 127
MAX_JOB_ARGS = 8
MAX_JOB_ARG_LEN = 159

HEADER_ICONS = {
    "Control Center": "cog",
    "System overview": "dashboard",
    "Background jobs": "pulse",
    "Wi-Fi controls": "wifi",
    "Wi-Fi": "wifi",
    "Disconnect Wi-Fi": "wifi",
    "Stop Wi-Fi": "power-standby",
    "Storage": "hard-drive",
    "Storage capacity": "pie-chart",
    "Storage status": "hard-drive",
    "Hardware": "tablet",
    "Start job": "media-play",
    "Stop job": "media-stop",
    "Job updated": "circle-check",
    "Job unchanged": "warning",
}


def clean(value, fallback="", limit=180):
    if not isinstance(value, str):
        value = fallback
    value = " ".join(value.replace("\r", " ").replace("\n", " ").split())
    return value[:limit] or fallback


def clip(value, count):
    value = clean(value)
    if len(value) <= count:
        return value
    return value[:max(1, count - 1)] + "~"


def wait_key():
    while not solaros.should_exit():
        key = gfx.getch(250)
        if key is not None:
            return key
    return gfx.KEY_ESCAPE


def safe_icon(x, y, name, size=32):
    try:
        gfx.icon(x, y, name, size)
    except Exception:
        inset = max(2, size // 8)
        gfx.rect(x + inset, y + inset, size - inset * 2, size - inset * 2)


def draw_counter(width, right):
    """Update the compact page counter without repainting the whole header."""
    if not right:
        return
    box_width = max(35, len(right) * 6 + 12)
    x = width - box_width - 8
    gfx.color(gfx.BLACK)
    gfx.fill_rect(x, 7, box_width, 18)
    gfx.color(gfx.WHITE)
    gfx.font(gfx.FONT_MONO_12)
    gfx.text(width - 14 - len(right) * 6, 20, right)


def draw_header(width, title, subtitle="", right="", icon=""):
    gfx.color(gfx.BLACK)
    gfx.fill_rect(0, 0, width, HEADER_H)
    gfx.color(gfx.WHITE)
    safe_icon(10, 15, icon or HEADER_ICONS.get(title, "cog"), 32)
    reserve = max(47, len(right) * 6 + 22) if right else 8
    gfx.font(gfx.FONT_BOLD_18)
    gfx.text(51, 31, clip(title, max(4, (width - 55 - reserve) // 9)))
    if subtitle:
        gfx.font(gfx.FONT_MONO_12)
        gfx.text(51, 50, clip(subtitle, max(4, (width - 59) // 6)))
    draw_counter(width, right)


def draw_footer(width, height, text):
    y = height - FOOTER_H
    gfx.color(gfx.BLACK)
    gfx.fill_rect(0, y, width, FOOTER_H)
    gfx.color(gfx.WHITE)
    gfx.font(gfx.FONT_MONO_12)
    gfx.text(7, y + 17, clip(text, max(4, (width - 14) // 6)))


def draw_row(width, y, primary, secondary, selected, icon="",
             solid_separator=False):
    # Keep the row background solid white. LIGHT is dithered on the reflective
    # LCD and reduces text contrast instead of reading as a gentle highlight.
    gfx.color(gfx.WHITE)
    gfx.fill_rect(4, y + 1, width - 8, ROW_H - 2)
    gfx.color(gfx.BLACK if solid_separator else gfx.LIGHT)
    gfx.line(11, y + ROW_H - 1, width - 11, y + ROW_H - 1)
    if selected:
        gfx.color(gfx.BLACK)
        gfx.fill_rect(4, y + 1, 5, ROW_H - 2)
        gfx.rect(4, y + 1, width - 8, ROW_H - 2)
    gfx.color(gfx.BLACK)
    content_x = 50 if icon else 14
    if icon:
        safe_icon(14, y + 5, icon, 32)
    gfx.font(gfx.FONT_BOLD_14)
    gfx.text(content_x, y + 18, clip(primary, max(4, (width - content_x - 30) // 7)))
    gfx.font(gfx.FONT_MONO_12)
    gfx.text(content_x, y + 34, clip(secondary, max(4, (width - content_x - 18) // 6)))
    if selected:
        safe_icon(width - 24, y + 13, "chevron-right", 16)


def draw_menu_row(width, y, row, selected, solid_separator=False):
    icon = row[2] if len(row) > 2 else ""
    draw_row(width, y, row[0], row[1], selected, icon, solid_separator)


def message(width, height, title, text, footer="Press any key"):
    gfx.clear(gfx.WHITE)
    draw_header(width, title)
    gfx.color(gfx.BLACK)
    gfx.font(gfx.FONT_MONO_14)
    words = clean(text, "", 900).split()
    columns = max(10, (width - 24) // 7)
    lines = []
    line = ""
    for word in words:
        if len(line) + len(word) + (1 if line else 0) <= columns:
            line += (" " if line else "") + word
        else:
            if line:
                lines.append(line)
            while len(word) > columns:
                lines.append(word[:columns])
                word = word[columns:]
            line = word
    if line:
        lines.append(line)
    y = HEADER_H + 24
    for line in lines[:max(1, (height - HEADER_H - FOOTER_H - 8) // 19)]:
        gfx.text(12, y, line)
        y += 19
    draw_footer(width, height, footer)
    gfx.refresh()
    return wait_key()


def confirm(width, height, title, text):
    return message(width, height, title, text,
                   "Y confirm   any other key cancels") in (ord("y"), ord("Y"))


def edit_text(width, height, title, label, limit=MAX_JOB_ARG_LEN):
    value = ""
    while not solaros.should_exit():
        gfx.clear(gfx.WHITE)
        draw_header(width, title, label,
                    "{}/{}".format(len(value), limit))
        gfx.color(gfx.BLACK)
        gfx.font(gfx.FONT_MONO_14)
        columns = max(8, (width - 24) // 7)
        shown = value + "_"
        lines = []
        while shown:
            lines.append(shown[:columns])
            shown = shown[columns:]
        available = max(1, (height - HEADER_H - FOOTER_H - 20) // 19)
        y = HEADER_H + 24
        for line in lines[-available:]:
            gfx.text(12, y, line)
            y += 19
        footer = ("Maximum length reached" if len(value) >= limit else
                  "Enter accept   Esc cancel   Backspace delete")
        draw_footer(width, height, footer)
        gfx.refresh()
        key = wait_key()
        if key == gfx.KEY_ESCAPE:
            return None
        if key in (KEY_ENTER, KEY_LF):
            return value.strip()
        if key in (KEY_BACKSPACE, KEY_DELETE_CHAR,
                   getattr(gfx, "KEY_DELETE", -1003)):
            value = value[:-1]
        elif isinstance(key, int) and 32 <= key <= 126 and len(value) < limit:
            value += chr(key)
    return None


def collect_job_arguments(width, height, name):
    arguments = []
    while len(arguments) < MAX_JOB_ARGS and not solaros.should_exit():
        number = len(arguments) + 1
        label = "Argument {}/{}; blank finishes".format(number, MAX_JOB_ARGS)
        value = edit_text(width, height, "Start " + name, label)
        if value is None:
            return None
        if not value:
            break
        arguments.append(value)
    return arguments


def choose_job_arguments(width, height, name):
    key = message(
        width, height, "Start job",
        "Start {} with its default settings? Choose No to enter arguments."
        .format(name),
        "Y defaults   N arguments   Esc cancel")
    if key in (ord("y"), ord("Y")):
        return []
    if key in (ord("n"), ord("N")):
        return collect_job_arguments(width, height, name)
    return None


def info_page(width, height, title, items, subtitle="System readings"):
    """Show compact aligned key/value readings instead of a text paragraph."""
    if not items:
        message(width, height, title, "No readings are available.")
        return
    start = 0
    visible = max(1, (height - HEADER_H - FOOTER_H) // INFO_ROW_H)
    maximum_start = max(0, len(items) - visible)
    while not solaros.should_exit():
        end = min(len(items), start + visible)
        counter = ("{}/{}".format(len(items), len(items)) if maximum_start == 0 else
                   "{}-{}/{}".format(start + 1, end, len(items)))
        gfx.clear(gfx.WHITE)
        draw_header(width, title, subtitle, counter)
        for index in range(start, end):
            y = HEADER_H + (index - start) * INFO_ROW_H
            label, value = items[index]
            gfx.color(gfx.WHITE)
            gfx.fill_rect(5, y, width - 10, INFO_ROW_H)
            gfx.color(gfx.BLACK)
            gfx.font(gfx.FONT_MONO_12)
            gfx.text(12, y + 17, clip(label.upper(), 17))
            gfx.font(gfx.FONT_BOLD_14)
            gfx.text(128, y + 18, clip(value, max(5, (width - 140) // 7)))
            gfx.line(10, y + INFO_ROW_H - 1, width - 10, y + INFO_ROW_H - 1)
        draw_footer(width, height,
                    "Up/Down scroll   Esc back" if maximum_start else "Press any key to return")
        gfx.refresh()
        key = wait_key()
        if maximum_start == 0 or key in (gfx.KEY_ESCAPE, gfx.KEY_LEFT, ord("q"), ord("Q")):
            return
        if key in (gfx.KEY_UP, ord("k")):
            start = max(0, start - 1)
        elif key in (gfx.KEY_DOWN, ord("j")):
            start = min(maximum_start, start + 1)
        elif key == getattr(gfx, "KEY_PAGE_UP", -1001):
            start = max(0, start - visible)
        elif key == getattr(gfx, "KEY_PAGE_DOWN", -1002):
            start = min(maximum_start, start + visible)


def api_call(module_name, function_name, fallback, *args):
    """Call an optional SolarOS service without resolving it before the guard."""
    try:
        module = getattr(solaros, module_name)
        function = getattr(module, function_name)
        return function(*args)
    except Exception:
        return fallback


def bytes_label(value):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return "unknown"
    if value >= 1048576:
        return "{} MiB".format(value // 1048576)
    if value >= 1024:
        return "{} KiB".format(value // 1024)
    return str(value) + " B"


def snapshot():
    battery = api_call("battery", "status", {})
    wifi = api_call("wifi", "status", {})
    usage = api_call("storage", "usage", {}, "/")
    storage_status = api_call("storage", "status", "unavailable")
    jobs = api_call("jobs", "list", [])
    apps = api_call("apps", "list", [])
    identity = api_call("identity", "format", "unknown")
    uptime = api_call("time", "uptime", 0)
    if not isinstance(battery, dict):
        battery = {}
    if not isinstance(wifi, dict):
        wifi = {}
    if not isinstance(usage, dict):
        usage = {}
    if not isinstance(jobs, list):
        jobs = []
    if not isinstance(apps, list):
        apps = []
    return {"battery": battery, "wifi": wifi, "usage": usage,
            "jobs": jobs, "apps": apps, "identity": clean(identity, "unknown", 80),
            "uptime": uptime, "storage_status": clean(storage_status, "unavailable", 80)}


def uptime_label(value):
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value) + "s"
    return clean(value, "unknown", 40)


def job_running(job):
    return job.get("state") in ("running", "starting")


def group_jobs(jobs):
    jobs.sort(key=lambda item: (not job_running(item),
                                clean(item.get("name", "")).lower()))
    running_count = len([item for item in jobs if job_running(item)])
    divider_before = running_count if 0 < running_count < len(jobs) else None
    return jobs, divider_before


def summary_rows(data):
    battery = data["battery"]
    wifi = data["wifi"]
    usage = data["usage"]
    running = len([job for job in data["jobs"] if isinstance(job, dict) and job_running(job)])
    percent = battery.get("percent")
    battery_text = (str(percent) + "%" if isinstance(percent, int) else "unavailable")
    if battery.get("charging_known") and battery.get("charging"):
        battery_text += " charging"
    wifi_text = clean(wifi.get("state", "unavailable"), "unavailable")
    if wifi.get("has_ip"):
        wifi_text += "  " + clean(wifi.get("ip", ""))
    storage_text = (bytes_label(usage.get("free_bytes")) + " free of " + bytes_label(usage.get("total_bytes"))
                    if usage else data["storage_status"])
    return [("Overview", data["identity"] + "  uptime " + uptime_label(data["uptime"]), "dashboard"),
            ("Jobs", "{} running of {} available".format(running, len(data["jobs"])), "pulse"),
            ("Wi-Fi", wifi_text, "wifi"),
            ("Storage", storage_text, "hard-drive"),
            ("Hardware", "Battery " + battery_text + "  Apps " + str(len(data["apps"])), "tablet")]


def first_prefix_match(rows, prefix):
    prefix = prefix.lower()
    for index, row in enumerate(rows):
        if clean(row[0]).lower().startswith(prefix):
            return index
    return None


def menu(width, height, title, rows, footer="Enter select   Esc back",
         divider_before=None, typeahead=False):
    if not rows:
        message(width, height, title, "No items are available.")
        return None
    selected = 0
    previous = None
    previous_start = None
    prefix = ""
    previous_prefix = None
    while not solaros.should_exit():
        visible = max(1, (height - HEADER_H - FOOTER_H) // ROW_H)
        start = (selected // visible) * visible
        if previous is None or previous_start != start or previous_prefix != prefix:
            gfx.clear(gfx.WHITE)
            subtitle = ("Find: " + prefix if prefix else
                        "{} item{}".format(len(rows), "" if len(rows) == 1 else "s"))
            draw_header(width, title, subtitle,
                        "{}/{}".format(selected + 1, len(rows)))
            draw_footer(width, height, footer)
            for index in range(start, min(len(rows), start + visible)):
                draw_menu_row(width, HEADER_H + (index - start) * ROW_H,
                              rows[index], index == selected,
                              index + 1 == divider_before)
        else:
            if start <= previous < start + visible:
                draw_menu_row(width, HEADER_H + (previous - start) * ROW_H,
                              rows[previous], False,
                              previous + 1 == divider_before)
            draw_menu_row(width, HEADER_H + (selected - start) * ROW_H,
                          rows[selected], True,
                          selected + 1 == divider_before)
            draw_counter(width, "{}/{}".format(selected + 1, len(rows)))
        gfx.refresh()
        previous = selected
        previous_start = start
        previous_prefix = prefix
        key = wait_key()
        if key in (gfx.KEY_ESCAPE, gfx.KEY_LEFT) or (
                not typeahead and key in (ord("q"), ord("Q"))):
            return None
        if key == gfx.KEY_UP or (not typeahead and key == ord("k")):
            selected = (selected - 1) % len(rows)
            prefix = ""
        elif key == gfx.KEY_DOWN or (not typeahead and key == ord("j")):
            selected = (selected + 1) % len(rows)
            prefix = ""
        elif key == getattr(gfx, "KEY_PAGE_UP", -1001):
            selected = max(0, selected - visible)
            prefix = ""
        elif key == getattr(gfx, "KEY_PAGE_DOWN", -1002):
            selected = min(len(rows) - 1, selected + visible)
            prefix = ""
        elif key in (KEY_ENTER, KEY_LF, gfx.KEY_RIGHT):
            return selected
        elif typeahead and key in (KEY_BACKSPACE, KEY_DELETE_CHAR):
            prefix = prefix[:-1]
            if prefix:
                match = first_prefix_match(rows, prefix)
                if match is not None:
                    selected = match
        elif typeahead and isinstance(key, int) and 32 <= key <= 126:
            character = chr(key).lower()
            candidate = prefix + character
            match = first_prefix_match(rows, candidate)
            if match is None and prefix:
                candidate = character
                match = first_prefix_match(rows, candidate)
            if match is not None:
                prefix = candidate
                selected = match
    return None


def overview(width, height, data):
    battery = data["battery"]
    wifi = data["wifi"]
    usage = data["usage"]
    percent = battery.get("percent")
    battery_value = (str(percent) + "%" if isinstance(percent, int) and
                     not isinstance(percent, bool) else "unavailable")
    items = [("Identity", data["identity"]),
             ("Uptime", uptime_label(data["uptime"])),
             ("Apps", str(len(data["apps"])) + " registered"),
             ("Jobs", str(len(data["jobs"])) + " available"),
             ("Wi-Fi", clean(wifi.get("state", "unavailable"), "unavailable")),
             ("Address", clean(wifi.get("ip", "none"), "none")),
             ("Battery", battery_value),
             ("Storage", (bytes_label(usage.get("free_bytes")) + " free"
                           if usage else data["storage_status"]))]
    info_page(width, height, "System overview", items)


def change_job(width, height, job):
    name = clean(job.get("name", ""))
    running = job_running(job)
    arguments = None
    if running:
        if not confirm(width, height, "Stop job", "Stop {}?".format(name)):
            return
    else:
        arguments = choose_job_arguments(width, height, name)
        if arguments is None:
            return
    try:
        if running:
            solaros.jobs.stop(name)
        elif arguments:
            solaros.jobs.start(name, arguments)
        else:
            solaros.jobs.start(name)
        message(width, height, "Job updated",
                name + " is now " + ("stopped." if running else "starting."))
    except Exception as error:
        message(width, height, "Job unchanged",
                clean(str(error), "SolarOS refused the request.", 500))


def jobs_screen(width, height):
    while not solaros.should_exit():
        jobs = api_call("jobs", "list", [])
        if not isinstance(jobs, list):
            jobs = []
        jobs = [item for item in jobs if isinstance(item, dict)]
        jobs, divider_before = group_jobs(jobs)
        rows = [(clean(item.get("name", "Unnamed job")),
                 clean(item.get("state", "unknown")) + "  " + clean(item.get("summary", ""))) for item in jobs]
        choice = menu(width, height, "Background jobs", rows,
                      "Type name  Enter start/stop  Esc back",
                      divider_before=divider_before, typeahead=True)
        if choice is None:
            return
        change_job(width, height, jobs[choice])
        gc.collect()


def wifi_screen(width, height):
    while not solaros.should_exit():
        status = api_call("wifi", "status", {})
        if not isinstance(status, dict):
            status = {}
        rows = [("Start / reconnect", "Use the preferred saved network"),
                ("Disconnect station", "Keep Wi-Fi enabled and retain profiles"),
                ("Stop Wi-Fi", "Turn the Wi-Fi service off"),
                ("Refresh status", clean(status.get("state", "unknown")) + "  " + clean(status.get("ip", "")))]
        choice = menu(width, height, "Wi-Fi controls", rows)
        if choice is None:
            return
        try:
            if choice == 0:
                solaros.wifi.start()
                solaros.wifi.connect_saved()
                message(width, height, "Wi-Fi", "Connection requested. It may take a moment to receive an address.")
            elif choice == 1 and confirm(width, height, "Disconnect Wi-Fi", "Disconnect from the current station network?"):
                solaros.wifi.disconnect()
            elif choice == 2 and confirm(width, height, "Stop Wi-Fi", "Stop Wi-Fi? Remote shells, display mirroring, and network jobs may disconnect."):
                solaros.wifi.stop()
        except Exception as error:
            message(width, height, "Wi-Fi unchanged", clean(str(error), "SolarOS refused the request.", 500))


def storage_screen(width, height):
    usage = api_call("storage", "usage", {}, "/")
    if not isinstance(usage, dict):
        usage = {}
    mounted = api_call("storage", "is_mounted", False)
    storage_status = api_call("storage", "status", "unavailable")
    capacity = (bytes_label(usage.get("used_bytes")) + " used; " +
                bytes_label(usage.get("free_bytes")) + " free") if usage else "Unavailable on this small-integer build"
    rows = [("Refresh block devices", "Rescan disks and partitions"),
            ("Mount default storage", "Currently " + ("mounted" if mounted else "not mounted")),
            ("Capacity", capacity),
            ("Storage status", clean(storage_status, "unavailable"))]
    choice = menu(width, height, "Storage", rows)
    if choice is None:
        return
    try:
        if choice == 0:
            solaros.storage.rescan()
            message(width, height, "Storage", "Block device scan completed.")
        elif choice == 1:
            if mounted:
                message(width, height, "Storage", "Default storage is already mounted. Control Center will not unmount the volume it is running from.")
            else:
                solaros.storage.mount()
                message(width, height, "Storage", "Default storage mounted.")
        elif choice == 2:
            if not usage:
                message(width, height, "Storage capacity", "This SolarOS MicroPython build cannot represent the SD card's byte counts without overflowing its small integer type. Storage is still usable.")
                return
            message(width, height, "Storage capacity",
                    bytes_label(usage.get("used_bytes")) + " used. " +
                    bytes_label(usage.get("free_bytes")) + " free. " +
                    bytes_label(usage.get("total_bytes")) + " total.")
        else:
            message(width, height, "Storage status", clean(storage_status, "unavailable"))
    except Exception as error:
        message(width, height, "Storage unchanged", clean(str(error), "SolarOS refused the request.", 500))


def hardware_screen(width, height, data):
    battery = data["battery"]
    items = []
    if battery:
        items.append(("Battery", str(battery.get("percent", "?")) + "%"))
        items.append(("Voltage", str(battery.get("voltage_mv", "?")) + " mV"))
        items.append(("External power", "Yes" if battery.get("external_power") else "No"))
        if battery.get("charging_known"):
            items.append(("Charging", "Yes" if battery.get("charging") else "No"))
        else:
            items.append(("Charging", "Unknown"))
    else:
        items.append(("Battery", "Service unavailable"))
    try:
        environment = solaros.sensors.environment()
        if isinstance(environment, dict):
            items.append(("Temperature", "{} C".format(environment.get("temperature_c", "?"))))
            items.append(("Humidity", "{}%".format(environment.get("humidity_percent", "?"))))
    except Exception:
        pass
    info_page(width, height, "Hardware", items, "Power and sensors")


def main():
    gfx.begin()
    try:
        width, height = gfx.size()
        while not solaros.should_exit():
            data = snapshot()
            choice = menu(width, height, "Control Center", summary_rows(data),
                          "Enter open   Q quit")
            if choice is None:
                break
            if choice == 0:
                overview(width, height, data)
            elif choice == 1:
                jobs_screen(width, height)
            elif choice == 2:
                wifi_screen(width, height)
            elif choice == 3:
                storage_screen(width, height)
            else:
                hardware_screen(width, height, data)
            del data
            gc.collect()
    finally:
        gfx.end()


if __name__ == "__main__":
    main()
