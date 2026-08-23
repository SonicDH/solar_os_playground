"""Typed, bounded client for the Cyberspace API v0.8.6."""

import gc
import json

try:
    import binascii
except ImportError:  # pragma: no cover - MicroPython alias
    import ubinascii as binascii


BASE_URL = "https://api.cyberspace.online"
TIMEOUT_MS = 15000
RESPONSE_CAP = 96 * 1024
CONTENT_PAGE = 5
METADATA_PAGE = 10
CHAT_PAGE = 20


_SMALL_INT_MAX = "1073741823"
_SMALL_INT_MIN_ABS = "1073741824"


def _large_integer(token):
    negative = token.startswith("-")
    digits = token[1:] if negative else token
    digits = digits.lstrip("0") or "0"
    limit = _SMALL_INT_MIN_ABS if negative else _SMALL_INT_MAX
    return len(digits) > len(limit) or (len(digits) == len(limit) and digits > limit)


def _quote_large_integers(source):
    """Keep JSON integers lossless on MicroPython builds without long ints."""
    output = []
    index = 0
    in_string = False
    escaped = False
    length = len(source)
    while index < length:
        character = source[index]
        if in_string:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
            continue
        if character == '"':
            in_string = True
            output.append(character)
            index += 1
            continue
        if character == "-" or (character >= "0" and character <= "9"):
            start = index
            if character == "-":
                index += 1
                if index >= length or source[index] < "0" or source[index] > "9":
                    output.append(character)
                    continue
            while index < length and source[index] >= "0" and source[index] <= "9":
                index += 1
            integer_end = index
            if index < length and source[index] == ".":
                index += 1
                while index < length and source[index] >= "0" and source[index] <= "9":
                    index += 1
            if index < length and source[index] in "eE":
                index += 1
                if index < length and source[index] in "+-":
                    index += 1
                while index < length and source[index] >= "0" and source[index] <= "9":
                    index += 1
            token = source[start:index]
            if integer_end == index and _large_integer(token):
                output.extend(('"', token, '"'))
            else:
                output.append(token)
            continue
        output.append(character)
        index += 1
    return "".join(output)


def safe_json_loads(source):
    if isinstance(source, bytes):
        source = source.decode("utf-8")
    return json.loads(_quote_large_integers(source))


class ApiError(Exception):
    def __init__(self, message, status=0, code="CLIENT_ERROR", retry_after=None,
                 session_refreshed=False):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.retry_after = retry_after
        self.session_refreshed = session_refreshed

    def __str__(self):
        text = self.code + ": " + self.message
        if self.retry_after:
            text += " (retry after {})".format(self.retry_after)
        if self.session_refreshed:
            text += " Session refreshed; action was not repeated."
        return text


def url_encode(value):
    result = []
    for byte in str(value).encode("utf-8"):
        if ((byte >= 48 and byte <= 57) or (byte >= 65 and byte <= 90) or
                (byte >= 97 and byte <= 122) or byte in (45, 46, 95, 126)):
            result.append(chr(byte))
        else:
            result.append("%{:02X}".format(byte))
    return "".join(result)


def query_string(values):
    parts = []
    for key in sorted(values):
        value = values[key]
        if value is None:
            continue
        if isinstance(value, bool):
            value = "true" if value else "false"
        parts.append(url_encode(key) + "=" + url_encode(value))
    return "&".join(parts)


def path_value(value):
    return url_encode(value)


def _header(headers, name):
    for key in headers or {}:
        if str(key).lower() == name.lower():
            return headers[key]
    return None


def _days_before_year(year):
    prior = year - 1
    return 365 * prior + prior // 4 - prior // 100 + prior // 400


def utc_epoch(value):
    if not isinstance(value, dict) or not value.get("clock_integrity"):
        return None
    year = int(value["year"])
    month = int(value["month"])
    day = int(value["day"])
    month_days = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    days = _days_before_year(year) - _days_before_year(1970)
    for current in range(1, month):
        days += month_days[current - 1]
        if current == 2 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
            days += 1
    days += day - 1
    return (days * 86400 + int(value["hour"]) * 3600 +
            int(value["minute"]) * 60 + int(value["second"]))


def jwt_expiry(token):
    try:
        payload = token.split(".")[1]
        payload += "=" * ((4 - len(payload) % 4) % 4)
        decoded = binascii.a2b_base64(payload.replace("-", "+").replace("_", "/"))
        document = json.loads(decoded.decode("utf-8"))
        expiry = document.get("exp")
        return int(expiry) if expiry is not None else None
    except (IndexError, KeyError, ValueError, TypeError, UnicodeError,
            OverflowError):
        return None


class Client:
    def __init__(self, http, now=None, session_store=None):
        self.http = http
        self.http_session = None
        if (hasattr(http, "session_open") and
                hasattr(http, "session_request") and
                hasattr(http, "session_close")):
            self.http_session = http.session_open(BASE_URL)
        self.now = now
        self.session_store = session_store
        self.id_token = None
        self.refresh_token = None
        self.rtdb_token = None
        self.rtdb_url = None
        self.email = None
        self.remember = False

    def _now(self):
        if self.now is not None:
            return self.now()
        try:
            import solaros
            return utc_epoch(solaros.time.utc_datetime())
        except (ImportError, AttributeError, OSError, KeyError, ValueError):
            return None

    def token_near_expiry(self):
        expiry = jwt_expiry(self.id_token or "")
        if expiry is None:
            return False
        now = self._now()
        return expiry is not None and now is not None and expiry - now <= 120

    def _decode(self, response):
        status = int(response.get("status_code", 0))
        if response.get("truncated"):
            raise ApiError("response exceeded 96 KiB", status,
                           "RESPONSE_TOO_LARGE")
        body = response.get("body", b"")
        try:
            if isinstance(body, bytes):
                body = body.decode("utf-8")
            document = safe_json_loads(body) if body else {}
        except (ValueError, TypeError, UnicodeError, OverflowError):
            raise ApiError("server returned invalid JSON", status, "INVALID_RESPONSE")
        if not isinstance(document, dict):
            raise ApiError("server returned a non-object response", status,
                           "INVALID_RESPONSE")
        if status < 200 or status >= 300 or "error" in document:
            error = document.get("error") or {}
            code = error.get("code") or "HTTP_{}".format(status)
            message = error.get("message") or "request failed"
            raise ApiError(str(message), status, str(code),
                           _header(response.get("headers"), "Retry-After"))
        return document

    def _perform(self, method, path, body=None, query=None, authenticated=True):
        if not path.startswith("/v1/"):
            raise ValueError("Cyberspace API path required")
        url = BASE_URL + path
        encoded_query = query_string(query or {})
        if encoded_query:
            url += "?" + encoded_query
        headers = {"Accept": "application/json"}
        encoded_body = None
        if body is not None:
            encoded_body = json.dumps(body)
            headers["Content-Type"] = "application/json"
        if authenticated:
            if not self.id_token:
                raise ApiError("login required", 401, "UNAUTHORIZED")
            headers["Authorization"] = "Bearer " + self.id_token
        if self.http_session is not None:
            response = self.http.session_request(
                self.http_session, method, url, encoded_body, headers,
                TIMEOUT_MS, RESPONSE_CAP)
        else:
            response = self.http.request(method, url, encoded_body, headers,
                                         TIMEOUT_MS, RESPONSE_CAP, False)
        document = self._decode(response)
        gc.collect()
        return document

    def close(self):
        if self.http_session is not None:
            try:
                self.http.session_close(self.http_session)
            finally:
                self.http_session = None

    def request(self, method, path, body=None, query=None, authenticated=True):
        method = method.upper()
        if authenticated and path != "/v1/auth/refresh" and self.token_near_expiry():
            self.refresh()
        try:
            return self._perform(method, path, body, query, authenticated)
        except ApiError as error:
            if authenticated and error.status == 401 and self.refresh_token:
                self.refresh()
                if method == "GET":
                    return self._perform(method, path, body, query, authenticated)
                error.session_refreshed = True
            raise

    def data(self, method, path, body=None, query=None, authenticated=True):
        return self.request(method, path, body, query, authenticated).get("data")

    def paged(self, path, limit, query=None):
        query = dict(query or {})
        current = max(1, int(limit))
        while True:
            query["limit"] = current
            try:
                return self.request("GET", path, query=query)
            except ApiError as error:
                if error.code != "RESPONSE_TOO_LARGE" or current <= 1:
                    raise
                current = max(1, current // 2)

    def apply_auth(self, data, email=None, remember=None):
        if not isinstance(data, dict) or not data.get("idToken"):
            raise ApiError("authentication response omitted idToken", 0,
                           "INVALID_RESPONSE")
        self.id_token = data["idToken"]
        if data.get("refreshToken"):
            self.refresh_token = data["refreshToken"]
        self.rtdb_token = data.get("rtdbToken")
        self.rtdb_url = data.get("rtdbUrl")
        if email is not None:
            self.email = email
        if remember is not None:
            self.remember = bool(remember)
            if not self.remember and self.session_store:
                self.session_store.clear()
        if self.remember and self.session_store and self.email and self.refresh_token:
            self.session_store.save(self.email, self.refresh_token)

    def login(self, email, password, remember=False):
        data = self.data("POST", "/v1/auth/login",
                         {"email": email, "password": password},
                         authenticated=False)
        self.apply_auth(data, email, remember)
        return data

    def saved_login(self):
        return self.session_store.load() if self.session_store else None

    def has_saved_login(self):
        if not self.session_store:
            return False
        exists = getattr(self.session_store, "exists", None)
        return exists() if exists is not None else self.saved_login() is not None

    def restore(self):
        saved = self.saved_login()
        if not saved:
            return False
        self.email = saved["email"]
        self.refresh_token = saved["refreshToken"]
        self.remember = True
        self.refresh()
        return True

    def forget_saved_login(self):
        self.logout()

    def refresh(self):
        if not self.refresh_token:
            raise ApiError("no refresh token", 401, "UNAUTHORIZED")
        document = self._perform("POST", "/v1/auth/refresh",
                                 {"refreshToken": self.refresh_token},
                                 authenticated=False)
        data = document.get("data", document)
        self.apply_auth(data)
        return data

    def logout(self):
        self.id_token = None
        self.refresh_token = None
        self.rtdb_token = None
        self.rtdb_url = None
        self.email = None
        self.remember = False
        if self.session_store:
            self.session_store.clear()

    def resend_verification(self):
        return self.data("POST", "/v1/auth/resend-verification",
                         {"idToken": self.id_token}, authenticated=False)

    # Feed, replies, watches, and bookmarks.
    def feed(self, cursor=None, limit=CONTENT_PAGE):
        return self.paged("/v1/posts", limit, {"cursor": cursor})

    def post(self, post_id):
        return self.data("GET", "/v1/posts/" + path_value(post_id))

    def post_by_slug(self, username, slug):
        return self.data("GET", "/v1/users/{}/posts/{}".format(
            path_value(username), path_value(slug)))

    def create_post(self, content, title=None, topics=None, public=False, nsfw=False):
        body = {"content": content, "isPublic": public, "isNSFW": nsfw}
        if title:
            body["title"] = title
        if topics:
            body["topics"] = topics
        return self.data("POST", "/v1/posts", body)

    def edit_post(self, post_id, values):
        return self.data("PATCH", "/v1/posts/" + path_value(post_id), values)

    def delete_post(self, post_id):
        return self.data("DELETE", "/v1/posts/" + path_value(post_id))

    def flag_post(self, post_id, reason=""):
        return self.data("POST", "/v1/posts/{}/flag".format(path_value(post_id)),
                         {"reason": reason})

    def replies(self, post_id, cursor=None, limit=CONTENT_PAGE):
        return self.paged("/v1/posts/{}/replies".format(path_value(post_id)), limit,
                          {"cursor": cursor})

    def reply(self, reply_id):
        return self.data("GET", "/v1/replies/" + path_value(reply_id))

    def create_reply(self, post_id, content, parent_reply_id=None):
        body = {"postId": post_id, "content": content}
        if parent_reply_id:
            body["parentReplyId"] = parent_reply_id
        return self.data("POST", "/v1/replies", body)

    def edit_reply(self, reply_id, content):
        return self.data("PATCH", "/v1/replies/" + path_value(reply_id),
                         {"content": content})

    def delete_reply(self, reply_id):
        return self.data("DELETE", "/v1/replies/" + path_value(reply_id))

    def flag_reply(self, reply_id, reason=""):
        return self.data("POST", "/v1/replies/{}/flag".format(path_value(reply_id)),
                         {"reason": reason})

    def watch_status(self, post_id):
        return self.data("GET", "/v1/posts/{}/watch".format(path_value(post_id)))

    def watch(self, post_id):
        return self.data("POST", "/v1/posts/{}/watch".format(path_value(post_id)))

    def unwatch(self, post_id):
        return self.data("DELETE", "/v1/posts/{}/watch".format(path_value(post_id)))

    def watches(self, cursor=None, limit=METADATA_PAGE):
        return self.paged("/v1/watches", limit, {"cursor": cursor})

    def bookmarks(self, cursor=None, limit=METADATA_PAGE):
        return self.paged("/v1/bookmarks", limit, {"cursor": cursor})

    def bookmark(self, target_id, target_type="post"):
        key = "postId" if target_type == "post" else "replyId"
        return self.data("POST", "/v1/bookmarks", {key: target_id, "type": target_type})

    def remove_bookmark(self, bookmark_id):
        return self.data("DELETE", "/v1/bookmarks/" + path_value(bookmark_id))

    # Profiles and social graph.
    def profile(self, username=None):
        suffix = path_value(username) if username else "me"
        return self.data("GET", "/v1/users/" + suffix)

    def user_guilds(self, username=None):
        suffix = path_value(username) if username else "me"
        return self.request("GET", "/v1/users/{}/guilds".format(suffix))

    def user_posts(self, username, cursor=None, limit=CONTENT_PAGE):
        return self.paged("/v1/users/{}/posts".format(path_value(username)), limit,
                          {"cursor": cursor})

    def user_replies(self, username, cursor=None, limit=CONTENT_PAGE):
        return self.paged("/v1/users/{}/replies".format(path_value(username)), limit,
                          {"cursor": cursor})

    def update_profile(self, values):
        return self.data("PATCH", "/v1/users/me", values)

    def poke(self, username):
        return self.data("POST", "/v1/users/{}/poke".format(path_value(username)))

    def follows(self, kind, cursor=None, user_id=None, limit=METADATA_PAGE):
        return self.paged("/v1/follows", limit,
                          {"type": kind, "cursor": cursor, "userId": user_id})

    def follow(self, user_id):
        return self.data("POST", "/v1/follows", {"followedId": user_id})

    def unfollow(self, follow_id):
        return self.data("DELETE", "/v1/follows/" + path_value(follow_id))

    # Guilds and discovery.
    def guilds(self, cursor=None, limit=METADATA_PAGE):
        return self.paged("/v1/guilds", limit, {"cursor": cursor})

    def guild(self, slug):
        return self.data("GET", "/v1/guilds/" + path_value(slug))

    def guild_members(self, slug, cursor=None, limit=METADATA_PAGE):
        return self.paged("/v1/guilds/{}/members".format(path_value(slug)), limit,
                          {"cursor": cursor})

    def guild_posts(self, slug, cursor=None, limit=CONTENT_PAGE):
        return self.paged("/v1/guilds/{}/posts".format(path_value(slug)), limit,
                          {"cursor": cursor})

    def create_guild_post(self, slug, content, title=None, topics=None):
        body = {"content": content}
        if title:
            body["title"] = title
        if topics:
            body["topics"] = topics
        return self.data("POST", "/v1/guilds/{}/posts".format(path_value(slug)), body)

    def guild_action(self, slug, action):
        if action not in ("join", "leave", "promote"):
            raise ValueError("unknown guild action")
        return self.data("POST", "/v1/guilds/{}/{}".format(path_value(slug), action))

    def topics(self):
        return self.request("GET", "/v1/topics")

    def topic_posts(self, slug, cursor=None, limit=CONTENT_PAGE):
        return self.paged("/v1/topics/{}/posts".format(path_value(slug)), limit,
                          {"cursor": cursor})

    def search(self, query, kind="all", page=None, limit=METADATA_PAGE):
        values = {"q": query, "type": kind}
        if kind != "all":
            values.update({"page": page or 0, "limit": limit})
        return self.request("GET", "/v1/search", query=values)

    # Notifications, notes, and settings.
    def notifications(self, cursor=None, unread=None, kinds=None, limit=METADATA_PAGE):
        return self.paged("/v1/notifications", limit,
                          {"cursor": cursor, "read": unread,
                           "type": ",".join(kinds) if kinds else None})

    def unread_count(self):
        return self.data("GET", "/v1/notifications/unread-count")

    def mark_notification(self, notification_id):
        return self.data("PATCH", "/v1/notifications/" + path_value(notification_id))

    def mark_all_notifications(self):
        return self.data("POST", "/v1/notifications/read-all")

    def notes(self, cursor=None, limit=CONTENT_PAGE):
        return self.paged("/v1/notes", limit, {"cursor": cursor})

    def note(self, note_id, revision=None):
        return self.data("GET", "/v1/notes/" + path_value(note_id),
                         query={"revision": revision})

    def note_revisions(self, note_id, cursor=None, limit=METADATA_PAGE):
        return self.paged("/v1/notes/{}/revisions".format(path_value(note_id)), limit,
                          {"cursor": cursor})

    def create_note(self, content, topics=None):
        body = {"content": content}
        if topics:
            body["topics"] = topics
        return self.data("POST", "/v1/notes", body)

    def update_note(self, note_id, content, topics=None):
        body = {"content": content}
        if topics is not None:
            body["topics"] = topics
        return self.data("PATCH", "/v1/notes/" + path_value(note_id), body)

    def delete_note(self, note_id):
        return self.data("DELETE", "/v1/notes/" + path_value(note_id))

    def settings(self):
        return self.data("GET", "/v1/settings")

    def update_settings(self, values):
        return self.data("PATCH", "/v1/settings", values)

    # C-Mail and cIRC.
    def start_cmail(self, username):
        return self.data("POST", "/v1/cmail", {"recipientUsername": username})

    def cmail(self):
        return self.request("GET", "/v1/cmail")

    def cmail_history(self, conversation_id, before=None, limit=CHAT_PAGE):
        return self.paged("/v1/cmail/" + path_value(conversation_id), limit,
                          {"before": before})

    def send_cmail(self, conversation_id, content):
        return self.data("POST", "/v1/cmail/" + path_value(conversation_id),
                         {"content": content})

    def cmail_read(self, conversation_id):
        return self.data("POST", "/v1/cmail/{}/read".format(path_value(conversation_id)))

    def cmail_typing(self, conversation_id, enabled=True):
        method = "POST" if enabled else "DELETE"
        return self.data(method, "/v1/cmail/{}/typing".format(path_value(conversation_id)))

    def cmail_typing_status(self, conversation_id):
        return self.data("GET", "/v1/cmail/{}/typing".format(path_value(conversation_id)))

    def circ_rooms(self):
        return self.request("GET", "/v1/circ")

    def circ_history(self, room_id, before=None, limit=CHAT_PAGE):
        return self.paged("/v1/circ/" + path_value(room_id), limit,
                          {"before": before})

    def send_circ(self, room_id, content):
        return self.data("POST", "/v1/circ/" + path_value(room_id),
                         {"content": content})

    def delete_circ(self, room_id, message_id):
        return self.data("DELETE", "/v1/circ/{}/messages/{}".format(
            path_value(room_id), path_value(message_id)))

    def flag_circ(self, room_id, message_id, reason=""):
        return self.data("POST", "/v1/circ/{}/messages/{}/flag".format(
            path_value(room_id), path_value(message_id)), {"reason": reason})

    def circ_read(self, room_id):
        return self.data("POST", "/v1/circ/{}/read".format(path_value(room_id)))

    def circ_users(self, room_id):
        return self.request("GET", "/v1/circ/{}/users".format(path_value(room_id)))

    def circ_presence(self, room_id, last_activity=None):
        body = {} if last_activity is None else {"lastActivity": last_activity}
        return self.data("POST", "/v1/circ/{}/presence".format(path_value(room_id)), body)

    def circ_leave(self, room_id):
        return self.data("DELETE", "/v1/circ/{}/presence".format(path_value(room_id)))
