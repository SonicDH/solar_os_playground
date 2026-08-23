"""Incremental SSE parsing and bounded Firebase RTDB message merging."""

from cyber_api import query_string, safe_json_loads, url_encode


MAX_EVENT_BYTES = 16 * 1024
MAX_QUEUED_EVENTS = 16
MAX_MESSAGES = 50
RECONNECT_DELAYS_MS = (1000, 2000, 4000, 8000, 15000)
_MISSING = object()


class SSEError(Exception):
    pass


class SSEParser:
    def __init__(self, max_event_bytes=MAX_EVENT_BYTES):
        self.pending = b""
        self.event = None
        self.data_lines = []
        self.size = 0
        self.max_event_bytes = max_event_bytes

    def feed(self, chunk):
        if isinstance(chunk, str):
            chunk = chunk.encode("utf-8")
        self.pending += chunk
        output = []
        while b"\n" in self.pending:
            line, self.pending = self.pending.split(b"\n", 1)
            if line.endswith(b"\r"):
                line = line[:-1]
            output.extend(self._line(line))
        if len(self.pending) + self.size > self.max_event_bytes:
            self.reset()
            raise SSEError("SSE record exceeds {} bytes".format(self.max_event_bytes))
        return output

    def _line(self, line):
        self.size += len(line) + 1
        if self.size > self.max_event_bytes:
            self.reset()
            raise SSEError("SSE record exceeds {} bytes".format(self.max_event_bytes))
        if line == b"":
            if not self.data_lines and self.event is None:
                self.size = 0
                return []
            event = self.event or "message"
            data = b"\n".join(self.data_lines)
            self.event = None
            self.data_lines = []
            self.size = 0
            return [{"event": event, "data": data}]
        if line.startswith(b":"):
            return []
        field, separator, value = line.partition(b":")
        if separator and value.startswith(b" "):
            value = value[1:]
        if field == b"event":
            self.event = value.decode("utf-8", "replace")
        elif field == b"data":
            self.data_lines.append(value)
        return []

    def reset(self):
        self.pending = b""
        self.event = None
        self.data_lines = []
        self.size = 0


def _segments(path):
    if not path or path == "/":
        return []
    return [part.replace("~1", "/").replace("~0", "~")
            for part in path.strip("/").split("/")]


def _set_path(root, parts, value):
    if not parts:
        return value if value is not None else {}
    current = root
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    if value is None:
        current.pop(parts[-1], None)
    else:
        current[parts[-1]] = value
    return root


def _get_path(root, parts):
    current = root
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _same_path_value(root, parts, value):
    current = _get_path(root, parts)
    if current is _MISSING:
        return False
    if len(parts) == 1 and isinstance(current, dict) and isinstance(value, dict):
        current = dict(current)
        value = dict(value)
        current.pop("id", None)
        value.pop("id", None)
    return current == value


def apply_firebase(root, event_name, payload):
    if event_name in ("cancel", "auth_revoked"):
        raise SSEError(event_name)
    if event_name not in ("put", "patch"):
        return root
    if not isinstance(payload, dict) or "path" not in payload:
        raise SSEError("invalid Firebase event")
    path = _segments(payload.get("path"))
    data = payload.get("data")
    if event_name == "put":
        return _set_path(root, path, data)
    if not isinstance(data, dict):
        return _set_path(root, path, data)
    result = root
    for relative, value in data.items():
        result = _set_path(result, path + _segments(relative), value)
    return result


class MessageWindow:
    def __init__(self, limit=MAX_MESSAGES):
        self.limit = limit
        self.root = {}
        self.queued = []
        self.reconciled = False
        self.overflowed = False

    def start_reconcile(self):
        self.reconciled = False
        self.queued = []
        self.overflowed = False

    def queue_live(self, event, payload):
        if not self.reconciled:
            if len(self.queued) >= MAX_QUEUED_EVENTS:
                self.overflowed = True
                self.queued = []
                return False
            self.queued.append((event, payload))
            return False
        changed = self._merge_live(event, payload)
        return self._trim() or changed

    def _merge_live(self, event, payload):
        """Merge a query-window root snapshot without dropping REST history."""
        if (event in ("put", "patch") and isinstance(payload, dict) and
                payload.get("path") in ("", "/") and
                isinstance(payload.get("data"), dict)):
            changed = False
            for relative, value in payload["data"].items():
                parts = _segments(relative)
                if not _same_path_value(self.root, parts, value):
                    changed = True
                self.root = _set_path(self.root, parts, value)
            return changed
        if event not in ("put", "patch") or not isinstance(payload, dict):
            self.root = apply_firebase(self.root, event, payload)
            return False
        base = _segments(payload.get("path"))
        data = payload.get("data")
        if event == "patch" and isinstance(data, dict):
            changed = any(not _same_path_value(
                              self.root, base + _segments(relative), value)
                          for relative, value in data.items())
        else:
            changed = not _same_path_value(self.root, base, data)
        self.root = apply_firebase(self.root, event, payload)
        return changed

    def reconcile(self, records):
        root = self.root if isinstance(self.root, dict) else {}
        for record in records or []:
            if isinstance(record, dict) and record.get("id"):
                root[str(record["id"])] = record
        self.root = root
        if not self.overflowed:
            for event, payload in self.queued:
                self._merge_live(event, payload)
        self.queued = []
        self.reconciled = True
        self._trim()

    def add_history(self, records):
        if not isinstance(self.root, dict):
            self.root = {}
        for record in records or []:
            if isinstance(record, dict) and record.get("id"):
                self.root[str(record["id"])] = record
        self._trim()

    def _trim(self):
        if not isinstance(self.root, dict):
            self.root = {}
            return True
        ordered = sorted(self.root.items(), key=lambda pair: _timestamp(pair[1]))
        changed = False
        while len(ordered) > self.limit:
            key, _ = ordered.pop(0)
            self.root.pop(key, None)
            changed = True
        return changed

    def records(self):
        if not isinstance(self.root, dict):
            return []
        values = []
        for key, value in self.root.items():
            if isinstance(value, dict):
                copy = dict(value)
                copy.setdefault("id", key)
                values.append(copy)
        values.sort(key=_timestamp)
        return values


def _timestamp(value):
    if not isinstance(value, dict):
        return (0, 0, "")
    raw = value.get("timestamp") or value.get("createdAt") or 0
    text = str(raw)
    decimal = bool(text)
    for character in text:
        if character < "0" or character > "9":
            decimal = False
            break
    if not decimal:
        return (0, 0, text)
    text = text.lstrip("0") or "0"
    return (1, len(text), text)


class RealtimeStream:
    def __init__(self, http, rtdb_url, token, node, identifier):
        self.http = http
        self.rtdb_url = rtdb_url.rstrip("/")
        self.token = token
        self.node = node
        self.identifier = identifier
        self.handle = None
        self.parser = SSEParser()
        self.reconnect_count = 0
        self.disconnected = False
        self.validated = False

    def url(self):
        query = query_string({"auth": self.token, "orderBy": '"timestamp"',
                              "limitToLast": 1})
        return "{}/{}/{}.json?{}".format(
            self.rtdb_url, self.node, url_encode(self.identifier), query)

    def open(self):
        self.close()
        self.handle = self.http.stream_open(
            "GET", self.url(), None, {"Accept": "text/event-stream"},
            15000, False)
        self.parser.reset()
        self.disconnected = False
        self.validated = False

    def validate(self, timeout_ms=15000):
        parsed = []
        for index in range(20):
            parsed.extend(self.read(timeout_ms if index == 0 else 1000))
            if self.validated:
                return parsed
        raise SSEError("stream response not received")

    def read(self, timeout_ms=0):
        if self.handle is None:
            return []
        event = self.http.stream_read(self.handle, timeout_ms)
        if not event:
            return []
        kind = event.get("type")
        if kind == "response":
            status = int(event.get("status_code", 0))
            if status < 200 or status >= 300:
                raise SSEError("stream HTTP {}".format(status))
            self.validated = True
            return []
        if kind == "data":
            parsed = []
            for record in self.parser.feed(event.get("data", b"")):
                event_name = record["event"]
                try:
                    payload = safe_json_loads(record["data"])
                except (ValueError, TypeError, UnicodeError, OverflowError):
                    raise SSEError("invalid SSE JSON")
                if event_name in ("cancel", "auth_revoked"):
                    raise SSEError(event_name)
                parsed.append((event_name, payload))
            return parsed
        if kind in ("complete", "error"):
            self.disconnected = True
            raise SSEError(event.get("error_name") or "stream closed")
        return []

    def retry_delay(self):
        if self.reconnect_count >= len(RECONNECT_DELAYS_MS):
            self.disconnected = True
            return None
        delay = RECONNECT_DELAYS_MS[self.reconnect_count]
        self.reconnect_count += 1
        return delay

    def connected(self):
        self.reconnect_count = 0
        self.disconnected = False

    def close(self):
        if self.handle is not None:
            try:
                self.http.stream_close(self.handle)
            finally:
                self.handle = None
