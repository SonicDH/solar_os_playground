from __future__ import annotations

import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


APP = Path(__file__).resolve().parents[1] / "apps" / "cyberspace"
sys.path.insert(0, str(APP))

import cyber_api
from cyber_api import (ApiError, Client, jwt_expiry, query_string, safe_json_loads,
                       url_encode, utc_epoch)
from cyber_editor import EditorModel, editor_layout, login_form, multiline, single_line
from cyber_components import (TABS, conversation_card, format_clock,
                              human_activity, irc_message_rows, logo_lines,
                              message_bubble, post_card, post_permalink,
                              reply_card, room_card, tab_window)
from cyber_screens import (ROOT_MENU, SUBMENUS, chat_lines, cmail_title, grouped_search,
                           guild_lines, item_title, note_lines, notification_title,
                           post_lines, profile_lines, terminal_too_small)
from cyber_session import SessionStore
from cyber_sse import (MessageWindow, RECONNECT_DELAYS_MS, RealtimeStream, SSEError,
                       SSEParser, apply_firebase)
from cyber_text import (attachment_urls, decode_art, plain_markdown, render_message,
                        sanitize, title_text, utf8_len, wrap_text)


def response(status=200, document=None, **values):
    body = b"" if document is None else json.dumps(document).encode()
    result = {
        "status_code": status,
        "body": body,
        "headers": {},
        "truncated": False,
    }
    result.update(values)
    return result


class FakeHTTP:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def request(self, *args):
        self.calls.append(args)
        if not self.responses:
            return response(200, {"data": []})
        return self.responses.pop(0)


class FakeSessionHTTP(FakeHTTP):
    def __init__(self, responses=None):
        super().__init__(responses)
        self.opened = []
        self.closed = []

    def session_open(self, origin):
        self.opened.append(origin)
        return 7

    def session_request(self, *args):
        self.calls.append(args)
        if not self.responses:
            return response(200, {"data": []})
        return self.responses.pop(0)

    def session_close(self, handle):
        self.closed.append(handle)


class ApiTest(unittest.TestCase):
    def test_same_origin_requests_reuse_one_owned_http_session(self):
        http = FakeSessionHTTP([
            response(200, {"data": []}),
            response(200, {"data": []}),
        ])
        client = Client(http)
        client.id_token = "token"
        client.feed()
        client.cmail()
        self.assertEqual(http.opened, [cyber_api.BASE_URL])
        self.assertEqual([call[0] for call in http.calls], [7, 7])
        self.assertTrue(all(call[2].startswith(cyber_api.BASE_URL + "/v1/")
                            for call in http.calls))
        client.close()
        self.assertEqual(http.closed, [7])
        client.close()
        self.assertEqual(http.closed, [7])

    def test_encoding_and_query_are_utf8_safe_and_stable(self):
        self.assertEqual(url_encode("a b/☀"), "a%20b%2F%E2%98%80")
        self.assertEqual(query_string({"z": None, "b": True, "a": "x y"}),
                         "a=x%20y&b=true")

    def test_common_data_list_cursor_and_error_shapes(self):
        http = FakeHTTP([
            response(200, {"data": {"postId": "p1"}}),
            response(200, {"data": [{"postId": "p1"}], "cursor": "p0"}),
            response(429, {"error": {"code": "RATE_LIMITED", "message": "slow"}},
                     headers={"Retry-After": "12"}),
        ])
        client = Client(http)
        client.id_token = "token"
        self.assertEqual(client.data("GET", "/v1/posts/p1")["postId"], "p1")
        self.assertEqual(client.request("GET", "/v1/posts")["cursor"], "p0")
        with self.assertRaises(ApiError) as caught:
            client.request("GET", "/v1/posts")
        self.assertEqual(caught.exception.code, "RATE_LIMITED")
        self.assertEqual(caught.exception.retry_after, "12")

    def test_invalid_and_oversized_responses_are_bounded(self):
        http = FakeHTTP([
            response(200, None, body=b"not json"),
            response(200, {"data": []}, truncated=True),
        ])
        client = Client(http)
        client.id_token = "token"
        with self.assertRaisesRegex(ApiError, "invalid JSON"):
            client.request("GET", "/v1/posts")
        with self.assertRaises(ApiError) as caught:
            client.request("GET", "/v1/posts")
        self.assertEqual(caught.exception.code, "RESPONSE_TOO_LARGE")

    def test_large_response_integers_are_preserved_as_strings(self):
        body = (b'{"data":[{"conversationId":"c1","lastMessage":'
                b'{"timestamp":1755890000000}}]}')
        client = Client(FakeHTTP([response(200, None, body=body)]))
        client.id_token = "token"
        document = client.cmail()
        self.assertEqual(document["data"][0]["lastMessage"]["timestamp"],
                         "1755890000000")
        parsed = safe_json_loads(
            '{"inside":"1755890000000","small":42,"negative":-1073741825}')
        self.assertEqual(parsed, {"inside": "1755890000000", "small": 42,
                                  "negative": "-1073741825"})

    def test_oversized_page_retries_with_smaller_reads(self):
        http = FakeHTTP([
            response(200, {"data": []}, truncated=True),
            response(200, {"data": []}, truncated=True),
            response(200, {"data": [{"postId": "p1"}], "cursor": None}),
        ])
        client = Client(http)
        client.id_token = "token"
        result = client.feed(limit=5)
        self.assertEqual(result["data"][0]["postId"], "p1")
        self.assertIn("limit=5", http.calls[0][1])
        self.assertIn("limit=2", http.calls[1][1])
        self.assertIn("limit=1", http.calls[2][1])

    def test_proactive_refresh_uses_jwt_expiry(self):
        payload = base64.urlsafe_b64encode(json.dumps({"exp": 1050}).encode()).decode().rstrip("=")
        token = "x." + payload + ".y"
        http = FakeHTTP([
            response(200, {"idToken": "fresh", "rtdbUrl": "https://rtdb"}),
            response(200, {"data": []}),
        ])
        client = Client(http, now=lambda: 1000)
        client.id_token = token
        client.refresh_token = "refresh"
        client.feed()
        self.assertEqual(client.id_token, "fresh")
        self.assertTrue(http.calls[0][1].endswith("/v1/auth/refresh"))

    def test_limited_integer_build_skips_proactive_jwt_check(self):
        http = FakeHTTP([response(200, {"data": []})])
        now_called = []
        client = Client(http, now=lambda: now_called.append(True))
        client.id_token = "x.payload.y"
        with mock.patch.object(cyber_api.json, "loads",
                               side_effect=OverflowError("long int not supported")):
            self.assertFalse(client.token_near_expiry())
        self.assertEqual(now_called, [])
        client.feed()
        self.assertEqual(len(http.calls), 1)

    def test_unexpected_401_retries_one_get_only(self):
        http = FakeHTTP([
            response(401, {"error": {"code": "UNAUTHORIZED", "message": "expired"}}),
            response(200, {"idToken": "fresh", "rtdbUrl": "https://rtdb"}),
            response(200, {"data": [{"postId": "p1"}], "cursor": None}),
        ])
        client = Client(http)
        client.id_token = "old"
        client.refresh_token = "refresh"
        self.assertEqual(client.feed()["data"][0]["postId"], "p1")
        self.assertEqual([call[0] for call in http.calls], ["GET", "POST", "GET"])

    def test_unexpected_401_never_repeats_write(self):
        http = FakeHTTP([
            response(401, {"error": {"code": "UNAUTHORIZED", "message": "expired"}}),
            response(200, {"idToken": "fresh", "rtdbUrl": "https://rtdb"}),
        ])
        client = Client(http)
        client.id_token = "old"
        client.refresh_token = "refresh"
        with self.assertRaises(ApiError) as caught:
            client.create_post("hello")
        self.assertTrue(caught.exception.session_refreshed)
        self.assertEqual([call[0] for call in http.calls], ["POST", "POST"])

    def test_fixed_base_redirect_policy_and_typed_workflow_routes(self):
        http = FakeHTTP()
        client = Client(http)
        client.id_token = "token"
        calls = (
            lambda: client.replies("p"), lambda: client.watches(),
            lambda: client.bookmarks(), lambda: client.profile(),
            lambda: client.follows("followers"), lambda: client.guilds(),
            lambda: client.notifications(), lambda: client.notes(),
            lambda: client.settings(), lambda: client.cmail(),
            lambda: client.circ_rooms(), lambda: client.search("solar"),
        )
        for call in calls:
            call()
        self.assertTrue(all(call[1].startswith("https://api.cyberspace.online/v1/")
                            for call in http.calls))
        self.assertTrue(all(call[-1] is False for call in http.calls))

    def test_jwt_and_utc_epoch(self):
        payload = base64.urlsafe_b64encode(b'{"exp":12345}').decode().rstrip("=")
        self.assertEqual(jwt_expiry("a." + payload + ".b"), 12345)
        self.assertEqual(utc_epoch({"year": 1970, "month": 1, "day": 1,
                                    "hour": 0, "minute": 0, "second": 0,
                                    "clock_integrity": True}), 0)
        self.assertIsNone(utc_epoch({"clock_integrity": False}))


class SessionTest(unittest.TestCase):
    def test_opt_in_round_trip_logout_and_no_password(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            store = SessionStore(str(path))
            store.save("me@example.com", "refresh-secret")
            self.assertTrue(store.exists())
            self.assertEqual(store.load(), {"email": "me@example.com",
                                            "refreshToken": "refresh-secret"})
            contents = path.read_text()
            self.assertNotIn("password", contents.lower())
            self.assertNotIn("idtoken", contents.lower())
            store.clear()
            self.assertFalse(path.exists())
            self.assertFalse(store.exists())

    def test_corrupt_session_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            path.write_text("{broken")
            store = SessionStore(str(path))
            self.assertTrue(store.exists())
            self.assertIsNone(store.load())
            path.write_text('{"email":"x"}')
            self.assertIsNone(store.load())
            store.clear()
            self.assertFalse(store.exists())

    def test_login_password_is_sent_but_never_persisted(self):
        class RecordingStore:
            def __init__(self):
                self.saved = None

            def save(self, email, token):
                self.saved = (email, token)

        store = RecordingStore()
        http = FakeHTTP([response(200, {"data": {"idToken": "id", "refreshToken": "refresh",
                                                   "rtdbUrl": "https://rtdb"}})])
        client = Client(http, session_store=store)
        client.login("me@example.com", "password-secret", True)
        self.assertEqual(store.saved, ("me@example.com", "refresh"))
        self.assertNotIn("password-secret", repr(store.saved))

    def test_client_can_detect_and_forget_saved_login(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(str(Path(directory) / "session.json"))
            store.save("me@example.com", "refresh-secret")
            client = Client(FakeHTTP(), session_store=store)
            client.id_token = "id"
            client.refresh_token = "refresh-secret"
            client.email = "me@example.com"
            client.remember = True
            self.assertTrue(client.has_saved_login())
            self.assertEqual(client.saved_login()["email"], "me@example.com")
            client.forget_saved_login()
            self.assertFalse(client.has_saved_login())
            self.assertIsNone(client.id_token)
            self.assertIsNone(client.refresh_token)
            self.assertIsNone(client.email)

    def test_successful_login_without_remembering_removes_old_session(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(str(Path(directory) / "session.json"))
            store.save("old@example.com", "old-refresh")
            http = FakeHTTP([response(200, {"data": {
                "idToken": "new-id", "refreshToken": "new-refresh"
            }})])
            client = Client(http, session_store=store)
            client.login("new@example.com", "correct-password", False)
            self.assertFalse(store.exists())
            self.assertFalse(client.remember)


class LoginFormTest(unittest.TestCase):
    class FakeTUI:
        KEY_ESCAPE = 27
        KEY_DOWN = 258
        KEY_UP = 259
        KEY_LEFT = 260
        KEY_RIGHT = 261
        KEY_HOME = 262
        KEY_END = 263
        KEY_DELETE = 264
        INVERSE = 1
        NORMAL = 0

        def __init__(self, keys, dimensions=(24, 50)):
            self.keys = list(keys)
            self.dimensions = dimensions
            self.added = []
            self.inputs = []
            self.boxes = []
            self.clear_count = 0
            self.fill_count = 0
            self.refresh_count = 0

        def size(self):
            return self.dimensions

        def clear(self):
            self.clear_count += 1

        def title(self, _text):
            pass

        def addstr(self, *args):
            self.added.append(args)

        def box(self, *args):
            self.boxes.append(args)

        def fill(self, *_args):
            self.fill_count += 1

        def help(self, _text):
            pass

        def refresh(self):
            self.refresh_count += 1

        def getch(self, _timeout):
            return self.keys.pop(0)

        def input(self, *args):
            self.inputs.append(args)

        def input_edit(self, text, cursor, view, key, _width, _capacity):
            if 32 <= key <= 126:
                text = text[:cursor] + chr(key) + text[cursor:]
                cursor += 1
            return text, cursor, view, 0

    def run_form(self, keys, dimensions=(24, 50), **values):
        fake_tui = self.FakeTUI(keys, dimensions)
        fake_solaros = type("FakeSolaros", (), {
            "tui": fake_tui,
            "should_exit": staticmethod(lambda: False),
        })
        previous = sys.modules.get("solaros")
        sys.modules["solaros"] = fake_solaros
        try:
            result = login_form(**values)
        finally:
            if previous is None:
                del sys.modules["solaros"]
            else:
                sys.modules["solaros"] = previous
        return result, fake_tui

    def test_two_field_form_masks_password_and_submits(self):
        result, fake_tui = self.run_form(
            [self.FakeTUI.KEY_DOWN, ord("s"), ord("e"), ord("c"), 13],
            email="me@example.com")
        self.assertEqual(result["action"], "login")
        self.assertEqual(result["email"], "me@example.com")
        self.assertEqual(result["password"], "sec")
        self.assertTrue(any(call[-1] is True for call in fake_tui.inputs))
        self.assertEqual(fake_tui.clear_count, 1)

    def test_logo_rows_share_one_block_origin(self):
        _, fake_tui = self.run_form([self.FakeTUI.KEY_ESCAPE])
        logo = set(logo_lines(50))
        columns = [call[1] for call in fake_tui.added
                   if len(call) >= 3 and call[2] in logo]
        self.assertEqual(len(columns), 5)
        self.assertEqual(len(set(columns)), 1)

    def test_login_fields_are_centered_on_wide_terminals(self):
        _, fake_tui = self.run_form([self.FakeTUI.KEY_ESCAPE],
                                    dimensions=(24, 80))
        field_boxes = [call for call in fake_tui.boxes
                       if len(call) >= 4 and call[2:] == (3, 48)]
        self.assertEqual([call[1] for call in field_boxes], [16, 16])
        self.assertTrue(any(call[1] == 17 for call in fake_tui.inputs))

    def test_forget_action_is_available_even_for_corrupt_saved_file(self):
        result, _ = self.run_form(
            [self.FakeTUI.KEY_UP, 13], has_saved=True)
        self.assertEqual(result["action"], "forget")
        self.assertNotIn("password", result)

    def test_focus_changes_redraw_only_old_and_new_controls(self):
        result, fake_tui = self.run_form(
            [self.FakeTUI.KEY_DOWN, self.FakeTUI.KEY_DOWN,
             self.FakeTUI.KEY_ESCAPE])
        self.assertIsNone(result)
        self.assertLessEqual(len(fake_tui.added), 16)

    def test_typing_updates_only_single_line_input_row(self):
        result, fake_tui = self.run_editor(single_line, [ord("a"), ord("b"), 13],
                                           "Field")
        self.assertEqual(result, "ab")
        self.assertEqual(fake_tui.clear_count, 1)
        self.assertEqual(len(fake_tui.inputs), 3)

    def test_multiline_typing_redraws_only_changed_rows(self):
        result, fake_tui = self.run_editor(multiline, [ord("a"), ord("b"), 19],
                                           "Compose")
        self.assertEqual(result, "ab")
        self.assertEqual(fake_tui.clear_count, 1)
        self.assertEqual(fake_tui.fill_count, 0)
        self.assertLessEqual(len(fake_tui.added), 6)
        self.assertFalse(any(call[2] == "ab" for call in fake_tui.added))

    def run_editor(self, function, keys, *args):
        fake_tui = self.FakeTUI(keys)
        fake_solaros = type("FakeSolaros", (), {
            "tui": fake_tui,
            "should_exit": staticmethod(lambda: False),
        })
        previous = sys.modules.get("solaros")
        sys.modules["solaros"] = fake_solaros
        try:
            result = function(*args)
        finally:
            if previous is None:
                del sys.modules["solaros"]
            else:
                sys.modules["solaros"] = previous
        return result, fake_tui


class MenuRedrawTest(unittest.TestCase):
    def test_cursor_navigation_updates_rows_without_clearing_screen(self):
        fake_tui = LoginFormTest.FakeTUI([
            LoginFormTest.FakeTUI.KEY_DOWN,
            LoginFormTest.FakeTUI.KEY_DOWN,
            LoginFormTest.FakeTUI.KEY_ESCAPE,
        ])
        fake_solaros = type("FakeSolaros", (), {
            "tui": fake_tui,
            "should_exit": staticmethod(lambda: False),
        })
        previous_solaros = sys.modules.get("solaros")
        previous_ui = sys.modules.pop("cyber_ui", None)
        sys.modules["solaros"] = fake_solaros
        try:
            import cyber_ui
            controller = cyber_ui.Controller(None)
            result = controller.menu("Menu", (("One", 1), ("Two", 2), ("Three", 3)),
                                     "Esc back")
        finally:
            sys.modules.pop("cyber_ui", None)
            if previous_ui is not None:
                sys.modules["cyber_ui"] = previous_ui
            if previous_solaros is None:
                del sys.modules["solaros"]
            else:
                sys.modules["solaros"] = previous_solaros
        self.assertIsNone(result)
        self.assertEqual(fake_tui.clear_count, 1)
        self.assertEqual(fake_tui.refresh_count, 3)
        row_updates = [call[2] for call in fake_tui.added if call[0] in (1, 2, 3)]
        self.assertTrue(row_updates)
        self.assertTrue(all(len(text) < 20 for text in row_updates))


class PagedNavigationTest(unittest.TestCase):
    class FakeTUI(LoginFormTest.FakeTUI):
        BOLD = 2
        UNDERLINE = 4
        KEY_PAGE_UP = 265
        KEY_PAGE_DOWN = 266
        KEY_CTRL_LEFT = 0xA1
        KEY_CTRL_RIGHT = 0xA2

    def controller(self, keys, client=None):
        fake_tui = self.FakeTUI(keys, (13, 36))
        fake_solaros = type("FakeSolaros", (), {
            "tui": fake_tui,
            "should_exit": staticmethod(lambda: False),
        })
        previous_solaros = sys.modules.get("solaros")
        previous_ui = sys.modules.pop("cyber_ui", None)
        sys.modules["solaros"] = fake_solaros
        import cyber_ui

        def restore():
            sys.modules.pop("cyber_ui", None)
            if previous_ui is not None:
                sys.modules["cyber_ui"] = previous_ui
            if previous_solaros is None:
                del sys.modules["solaros"]
            else:
                sys.modules["solaros"] = previous_solaros

        self.addCleanup(restore)
        return cyber_ui, cyber_ui.Controller(client), fake_tui

    @staticmethod
    def card(item, _width):
        return [[(item["name"], "normal")]]

    def test_down_at_last_card_loads_and_selects_next_page(self):
        cyber_ui, controller, _ = self.controller([
            self.FakeTUI.KEY_DOWN, 13,
        ])
        load_more = mock.Mock(return_value=[{"name": "two"}])
        result = controller.card_select(
            "Cards", [{"name": "one"}], "Esc back", self.card,
            load_more=load_more)
        self.assertEqual(result["name"], "two")
        load_more.assert_called_once_with()

    def test_page_down_loads_and_advances_from_current_card(self):
        _, controller, _ = self.controller([
            self.FakeTUI.KEY_DOWN, self.FakeTUI.KEY_PAGE_DOWN, 13,
        ])
        load_more = mock.Mock(return_value=[{"name": "three"}, {"name": "four"}])
        result = controller.card_select(
            "Cards", [{"name": "one"}, {"name": "two"}],
            "Esc back", self.card, load_more=load_more)
        self.assertEqual(result["name"], "four")
        load_more.assert_called_once_with()

    def test_down_at_last_plain_row_loads_and_selects_next_page(self):
        _, controller, _ = self.controller([
            self.FakeTUI.KEY_DOWN, 13,
        ])
        load_more = mock.Mock(return_value=[{"name": "two"}])
        result = controller.select(
            "Rows", [{"name": "one"}], "Esc back", load_more=load_more)
        self.assertEqual(result["name"], "two")
        load_more.assert_called_once_with()

    def test_topic_posts_use_the_feed_card_renderer(self):
        class Client:
            @staticmethod
            def topics():
                return {"data": [{"slug": "solar"}]}

            @staticmethod
            def topic_posts(slug, cursor):
                return {"data": [{"postId": "p1"}], "cursor": None,
                        "slug": slug, "requested_cursor": cursor}

        cyber_ui, controller, _ = self.controller([], Client())
        with mock.patch.object(controller, "select",
                               return_value={"slug": "solar"}), \
                mock.patch.object(controller, "paged_card_select",
                                  return_value=None) as paged:
            controller.screen_topics()
        self.assertIs(paged.call_args.args[3], cyber_ui.post_card)
        document = paged.call_args.args[1]("next")
        self.assertEqual((document["slug"], document["requested_cursor"]),
                         ("solar", "next"))


class ThreadReaderTest(unittest.TestCase):
    def test_enter_on_thread_post_opens_scrollable_full_text_reader(self):
        fake_tui = LoginFormTest.FakeTUI([])
        fake_tui.BOLD = 2
        fake_tui.UNDERLINE = 4
        fake_tui.KEY_PAGE_UP = 265
        fake_tui.KEY_PAGE_DOWN = 266
        fake_tui.KEY_CTRL_LEFT = 0xA1
        fake_tui.KEY_CTRL_RIGHT = 0xA2
        fake_solaros = type("FakeSolaros", (), {
            "tui": fake_tui,
            "should_exit": staticmethod(lambda: False),
        })

        post = {
            "postId": "p1",
            "authorUsername": "puro",
            "content": "The complete post text that does not fit in its card.",
        }

        class Client:
            def post(self, _post_id):
                return dict(post)

            def replies(self, _post_id, _cursor, _limit):
                return {"data": [], "cursor": None}

        previous_solaros = sys.modules.get("solaros")
        previous_ui = sys.modules.pop("cyber_ui", None)
        sys.modules["solaros"] = fake_solaros
        try:
            import cyber_ui
            controller = cyber_ui.Controller(Client())
            selections = iter((dict(post), None))
            with mock.patch.object(
                    controller, "card_select",
                    side_effect=lambda *_args, **_kwargs: next(selections)), \
                    mock.patch.object(controller, "viewer",
                                      return_value=None) as viewer:
                controller.post_detail("p1")
        finally:
            sys.modules.pop("cyber_ui", None)
            if previous_ui is not None:
                sys.modules["cyber_ui"] = previous_ui
            if previous_solaros is None:
                del sys.modules["solaros"]
            else:
                sys.modules["solaros"] = previous_solaros

        viewer.assert_called_once()
        self.assertIn(post["content"], viewer.call_args.args[1])
        self.assertIn("Esc back", viewer.call_args.args[2])


class ChatComposerTest(unittest.TestCase):
    class FakeTUI(LoginFormTest.FakeTUI):
        BOLD = 2
        UNDERLINE = 4
        KEY_PAGE_UP = 265
        KEY_PAGE_DOWN = 266
        KEY_SHIFT_PAGE_UP = 0x9B
        KEY_SHIFT_PAGE_DOWN = 0x9C
        KEY_CTRL_LEFT = 0xA1
        KEY_CTRL_RIGHT = 0xA2

        def title(self, *_args):
            pass

        def tab(self, *_args):
            pass

    class FakeStream:
        def __init__(self, *_args):
            self.handle = None
            self.reconnect_count = 0

        def open(self):
            self.handle = 1

        def validate(self):
            return []

        def connected(self):
            pass

        def read(self, _timeout):
            return []

        def close(self):
            self.handle = None

        def retry_delay(self):
            return None

    class FakeClient:
        def __init__(self):
            self.http = object()
            self.rtdb_url = "https://example.invalid"
            self.id_token = "token"
            self.sent = []

        def cmail_history(self, *_args, **_kwargs):
            return {"data": []}

        def cmail_read(self, _identifier):
            pass

        def cmail_typing(self, _identifier, _enabled=True):
            return {"heartbeatMs": 3000}

        def cmail_typing_status(self, _identifier):
            return {"typing": False}

        def send_cmail(self, identifier, content):
            self.sent.append((identifier, content))

    class HistoryClient(FakeClient):
        def __init__(self):
            super().__init__()
            self.history_calls = []
            self.latest = [
                {"id": "m{}".format(index), "timestamp": index,
                 "senderUsername": "trinity", "content": "message {}".format(index)}
                for index in range(12)
            ]
            self.older = [
                {"id": "o{}".format(index), "timestamp": index - 20,
                 "senderUsername": "trinity", "content": "older {}".format(index)}
                for index in range(8)
            ]

        def _history(self, before):
            self.history_calls.append(before)
            if before is None:
                return {"data": self.latest, "cursor": "older-page"}
            return {"data": self.older, "cursor": None}

        def cmail_history(self, _identifier, before=None, _limit=20, **_kwargs):
            return self._history(before)

        def circ_history(self, _identifier, before=None, _limit=20, **_kwargs):
            return self._history(before)

        def circ_presence(self, _identifier, *_args):
            return {"heartbeatMs": 30000}

        def circ_read(self, _identifier):
            pass

        def circ_users(self, _identifier):
            return {"data": []}

        def circ_leave(self, _identifier):
            pass

    def test_chat_uses_persistent_bottom_input_and_enter_sends(self):
        fake_tui = self.FakeTUI([ord("h"), ord("i"), ord("1"), ord("2"),
                                 ord("3"), ord("q"), 13,
                                 self.FakeTUI.KEY_ESCAPE])
        clock = {"now": 0}

        def uptime_ms():
            clock["now"] += 100
            return clock["now"]

        fake_solaros = type("FakeSolaros", (), {
            "tui": fake_tui,
            "should_exit": staticmethod(lambda: False),
            "time": type("FakeTime", (), {"uptime_ms": staticmethod(uptime_ms)}),
        })
        previous_solaros = sys.modules.get("solaros")
        previous_ui = sys.modules.pop("cyber_ui", None)
        sys.modules["solaros"] = fake_solaros
        try:
            import cyber_ui
            client = self.FakeClient()
            controller = cyber_ui.Controller(client)
            controller.tabs_active = True
            controller.me = {"username": "neo", "userId": "u1"}
            with mock.patch.object(cyber_ui, "RealtimeStream", self.FakeStream):
                controller.chat("cmail", "c1", "Trinity")
        finally:
            sys.modules.pop("cyber_ui", None)
            if previous_ui is not None:
                sys.modules["cyber_ui"] = previous_ui
            if previous_solaros is None:
                del sys.modules["solaros"]
            else:
                sys.modules["solaros"] = previous_solaros
        self.assertEqual(client.sent, [("c1", "hi123q")])
        self.assertGreaterEqual(len(fake_tui.inputs), 3)
        self.assertEqual(fake_tui.clear_count, 1)

    def test_cmail_and_circ_page_keys_move_a_page_and_load_older_history(self):
        class FrameTUI(self.FakeTUI):
            def __init__(self, keys):
                super().__init__(keys)
                self.frames = []
                self.frame_start = 0

            def refresh(self):
                frame = []
                for call in self.added[self.frame_start:]:
                    if len(call) >= 3:
                        frame.append(call[2])
                self.frames.append(frame)
                self.frame_start = len(self.added)
                super().refresh()

        for kind in ("cmail", "circ"):
            with self.subTest(kind=kind):
                fake_tui = FrameTUI([
                    FrameTUI.KEY_SHIFT_PAGE_UP,
                    FrameTUI.KEY_SHIFT_PAGE_DOWN,
                    FrameTUI.KEY_PAGE_UP,
                    FrameTUI.KEY_PAGE_UP,
                    FrameTUI.KEY_PAGE_UP,
                    FrameTUI.KEY_ESCAPE,
                ])
                clock = {"now": 0}

                def uptime_ms():
                    clock["now"] += 100
                    return clock["now"]

                fake_solaros = type("FakeSolaros", (), {
                    "tui": fake_tui,
                    "should_exit": staticmethod(lambda: False),
                    "time": type("FakeTime", (), {
                        "uptime_ms": staticmethod(uptime_ms),
                    }),
                })
                previous_solaros = sys.modules.get("solaros")
                previous_ui = sys.modules.pop("cyber_ui", None)
                sys.modules["solaros"] = fake_solaros
                try:
                    import cyber_ui
                    client = self.HistoryClient()
                    controller = cyber_ui.Controller(client)
                    controller.tabs_active = True
                    controller.me = {"username": "neo", "userId": "u1"}
                    with mock.patch.object(cyber_ui, "RealtimeStream", self.FakeStream):
                        controller.chat(kind, "c1", "Chat",
                                        {"slug": "general"} if kind == "circ" else None)
                finally:
                    sys.modules.pop("cyber_ui", None)
                    if previous_ui is not None:
                        sys.modules["cyber_ui"] = previous_ui
                    if previous_solaros is None:
                        del sys.modules["solaros"]
                    else:
                        sys.modules["solaros"] = previous_solaros

                rendered = ["".join(frame) for frame in fake_tui.frames]
                self.assertIn("message 11", rendered[0])
                self.assertNotIn("message 11", rendered[1])
                self.assertIn("message 11", rendered[2])
                traversed = "".join(rendered[:5])
                for index in range(12):
                    self.assertIn("message {}".format(index), traversed)
                self.assertEqual(client.history_calls, [None, "older-page"])

    def test_ctrl_left_right_changes_tabs_from_an_open_chat(self):
        fake_tui = self.FakeTUI([self.FakeTUI.KEY_CTRL_RIGHT])
        clock = {"now": 0}

        def uptime_ms():
            clock["now"] += 100
            return clock["now"]

        fake_solaros = type("FakeSolaros", (), {
            "tui": fake_tui,
            "should_exit": staticmethod(lambda: False),
            "time": type("FakeTime", (), {"uptime_ms": staticmethod(uptime_ms)}),
        })
        previous_solaros = sys.modules.get("solaros")
        previous_ui = sys.modules.pop("cyber_ui", None)
        sys.modules["solaros"] = fake_solaros
        try:
            import cyber_ui
            controller = cyber_ui.Controller(self.FakeClient())
            controller.tabs_active = True
            controller.active_tab = 2
            with mock.patch.object(cyber_ui, "RealtimeStream", self.FakeStream):
                with self.assertRaises(cyber_ui._TabChange) as changed:
                    controller.chat("cmail", "c1", "Trinity")
            self.assertEqual(changed.exception.index, 3)
        finally:
            sys.modules.pop("cyber_ui", None)
            if previous_ui is not None:
                sys.modules["cyber_ui"] = previous_ui
            if previous_solaros is None:
                del sys.modules["solaros"]
            else:
                sys.modules["solaros"] = previous_solaros

    def test_plain_right_stays_in_the_open_chat_editor(self):
        fake_tui = self.FakeTUI([self.FakeTUI.KEY_RIGHT,
                                 self.FakeTUI.KEY_ESCAPE])
        clock = {"now": 0}

        def uptime_ms():
            clock["now"] += 100
            return clock["now"]

        fake_solaros = type("FakeSolaros", (), {
            "tui": fake_tui,
            "should_exit": staticmethod(lambda: False),
            "time": type("FakeTime", (), {"uptime_ms": staticmethod(uptime_ms)}),
        })
        previous_solaros = sys.modules.get("solaros")
        previous_ui = sys.modules.pop("cyber_ui", None)
        sys.modules["solaros"] = fake_solaros
        try:
            import cyber_ui
            controller = cyber_ui.Controller(self.FakeClient())
            controller.tabs_active = True
            controller.active_tab = 2
            with mock.patch.object(cyber_ui, "RealtimeStream", self.FakeStream):
                controller.chat("cmail", "c1", "Trinity")
            self.assertEqual(controller.active_tab, 2)
        finally:
            sys.modules.pop("cyber_ui", None)
            if previous_ui is not None:
                sys.modules["cyber_ui"] = previous_ui
            if previous_solaros is None:
                del sys.modules["solaros"]
            else:
                sys.modules["solaros"] = previous_solaros

    def test_duplicate_live_snapshot_does_not_redraw_circ(self):
        class DuplicateStream(self.FakeStream):
            def __init__(self, *_args):
                super().__init__()
                self.sent_duplicate = False

            def read(self, _timeout):
                if self.sent_duplicate:
                    return []
                self.sent_duplicate = True
                return [("put", {"path": "/m11", "data": {
                    "timestamp": 11,
                    "senderUsername": "trinity",
                    "content": "message 11",
                }})]

        fake_tui = self.FakeTUI([self.FakeTUI.KEY_ESCAPE])
        clock = {"now": 0}

        def uptime_ms():
            clock["now"] += 100
            return clock["now"]

        fake_solaros = type("FakeSolaros", (), {
            "tui": fake_tui,
            "should_exit": staticmethod(lambda: False),
            "time": type("FakeTime", (), {"uptime_ms": staticmethod(uptime_ms)}),
        })
        previous_solaros = sys.modules.get("solaros")
        previous_ui = sys.modules.pop("cyber_ui", None)
        sys.modules["solaros"] = fake_solaros
        try:
            import cyber_ui
            controller = cyber_ui.Controller(self.HistoryClient())
            controller.tabs_active = True
            with mock.patch.object(cyber_ui, "RealtimeStream", DuplicateStream):
                controller.chat("circ", "general", "General", {"slug": "general"})
            self.assertEqual(fake_tui.refresh_count, 1)
        finally:
            sys.modules.pop("cyber_ui", None)
            if previous_ui is not None:
                sys.modules["cyber_ui"] = previous_ui
            if previous_solaros is None:
                del sys.modules["solaros"]
            else:
                sys.modules["solaros"] = previous_solaros


class SSETest(unittest.TestCase):
    RECORD = (b": keepalive\r\nevent: put\r\n"
              b"data: {\"path\":\"/m1\",\r\n"
              b"data: \"data\":{\"timestamp\":1}}\r\n\r\n")

    def test_record_split_at_every_byte_boundary(self):
        for split in range(len(self.RECORD) + 1):
            parser = SSEParser()
            events = parser.feed(self.RECORD[:split]) + parser.feed(self.RECORD[split:])
            self.assertEqual(len(events), 1, split)
            self.assertEqual(events[0]["event"], "put")
            self.assertIn(b"\n", events[0]["data"])

    def test_record_one_byte_chunks_comments_and_multiline(self):
        parser = SSEParser()
        events = []
        for value in self.RECORD:
            events.extend(parser.feed(bytes((value,))))
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["data"].startswith(b'{"path"'))

    def test_message_window_orders_large_string_timestamps(self):
        window = MessageWindow()
        window.reconcile([
            {"id": "new", "timestamp": "1755890000000"},
            {"id": "old", "timestamp": "999999999999"},
            {"id": "small", "timestamp": 3},
        ])
        self.assertEqual([record["id"] for record in window.records()],
                         ["small", "old", "new"])

    def test_terminal_and_oversized_events(self):
        parser = SSEParser(max_event_bytes=12)
        with self.assertRaises(SSEError):
            parser.feed(b"data: 1234567890\n\n")
        with self.assertRaisesRegex(SSEError, "auth_revoked"):
            apply_firebase({}, "auth_revoked", {})

    def test_firebase_put_patch_nested_delete(self):
        root = apply_firebase({}, "put", {"path": "/", "data": {"m1": {"content": "a"}}})
        root = apply_firebase(root, "patch", {"path": "/m1", "data": {"content": "b",
                                                                            "meta/x": 1}})
        self.assertEqual(root["m1"]["content"], "b")
        self.assertEqual(root["m1"]["meta"]["x"], 1)
        root = apply_firebase(root, "put", {"path": "/m1/meta/x", "data": None})
        self.assertNotIn("x", root["m1"]["meta"])
        root = apply_firebase(root, "put", {"path": "/m1", "data": None})
        self.assertEqual(root, {})

    def test_queue_reconcile_limit_and_overflow(self):
        window = MessageWindow(limit=2)
        window.queue_live("put", {"path": "/m2", "data": {"timestamp": 2}})
        window.reconcile([{"id": "m1", "timestamp": 1}])
        self.assertEqual([value["id"] for value in window.records()], ["m1", "m2"])
        window.queue_live("put", {"path": "/m3", "data": {"timestamp": 3}})
        self.assertEqual([value["id"] for value in window.records()], ["m2", "m3"])
        overflow = MessageWindow()
        for index in range(17):
            overflow.queue_live("put", {"path": "/m" + str(index), "data": {}})
        self.assertTrue(overflow.overflowed)

    def test_query_root_snapshot_preserves_rest_history(self):
        window = MessageWindow()
        window.start_reconcile()
        window.queue_live("put", {"path": "/", "data": {
            "m3": {"timestamp": 3, "content": "latest"},
        }})
        window.reconcile([
            {"id": "m1", "timestamp": 1, "content": "oldest"},
            {"id": "m2", "timestamp": 2, "content": "middle"},
        ])
        self.assertEqual([record["id"] for record in window.records()],
                         ["m1", "m2", "m3"])
        window.queue_live("put", {"path": "/", "data": {
            "m4": {"timestamp": 4, "content": "new live"},
        }})
        self.assertEqual([record["id"] for record in window.records()],
                         ["m1", "m2", "m3", "m4"])

    def test_repeated_live_value_does_not_request_a_redraw(self):
        window = MessageWindow()
        window.reconcile([{"id": "m1", "timestamp": 1, "content": "same"}])
        event = {"path": "/m1", "data": {
            "timestamp": 1, "content": "same"}}
        self.assertFalse(window.queue_live("put", event))
        changed = {"path": "/m1/content", "data": "different"}
        self.assertTrue(window.queue_live("put", changed))
        self.assertFalse(window.queue_live("put", changed))

    def test_reconnect_schedule_and_bounded_rtdb_url(self):
        stream = RealtimeStream(object(), "https://firebase.example/", "secret token",
                                "chat_messages", "general/room")
        self.assertIn("orderBy=%22timestamp%22", stream.url())
        self.assertIn("limitToLast=1", stream.url())
        self.assertNotIn("general/room", stream.url())
        self.assertEqual([stream.retry_delay() for _ in RECONNECT_DELAYS_MS],
                         list(RECONNECT_DELAYS_MS))
        self.assertIsNone(stream.retry_delay())


class TextEditorScreenTest(unittest.TestCase):
    def test_utf8_editor_limits_and_layout(self):
        model = EditorModel("", 4)
        self.assertTrue(model.insert("☀"))
        self.assertTrue(model.insert("a"))
        self.assertFalse(model.insert("b"))
        self.assertEqual(utf8_len(model.text), 4)
        model.backspace()
        self.assertEqual(model.text, "☀")
        lines, row, col = editor_layout("ab\ncd", 4, 3)
        self.assertEqual(lines, ["ab", "cd"])
        self.assertEqual((row, col), (1, 1))

    def test_sanitizing_wrapping_spoilers_art_and_attachments(self):
        self.assertEqual(sanitize("a\x1bb\n"), "a b\n")
        self.assertEqual(title_text("watched threads"), "Watched Threads")
        self.assertEqual(plain_markdown("# Head\n```\n*x*\n```"), "Head\n*x*")
        self.assertEqual(wrap_text("one two three", 7), ["one two", "three"])
        art = base64.b64encode(b" /\\\n/  \\").decode()
        self.assertIn("/\\", decode_art(art))
        hidden = render_message({"id": "m", "username": "neo", "content": "secret",
                                 "style": "spoiler"})
        self.assertIn("spoiler hidden", hidden)
        shown = render_message({"id": "m", "username": "neo", "content": "secret",
                                "style": "spoiler"}, True)
        self.assertIn("secret", shown)
        links = attachment_urls({"imageUrl": "https://image", "audioAttachment": {
            "src": "https://audio"}})
        self.assertEqual(len(links), 2)

    def test_representative_screen_family_fixtures_and_small_terminal(self):
        post = {"postId": "p", "authorUsername": "neo", "title": "Hello",
                "content": "Body", "topics": ["solar"], "repliesCount": 2}
        profile = {"username": "neo", "displayName": "Neo", "bio": "Hi"}
        guild = {"slug": "solar", "name": "Solar", "memberCount": 2, "bio": "Warm"}
        note = {"id": "n", "revision": 2, "content": "Private"}
        notice = {"id": "x", "type": "reply", "actorUsername": "neo", "read": False}
        conversation = {
            "conversationId": "c1",
            "otherUser": {"username": "trinity", "displayName": "Trinity"},
            "lastMessage": {"senderUsername": "neo", "content": "my own message"},
        }
        self.assertEqual(item_title(post), "Hello")
        self.assertEqual(cmail_title(conversation), "Trinity (@trinity)")
        self.assertEqual(cmail_title({"otherUser": {"username": "trinity"},
                                      "lastMessage": "wrong"}), "@trinity")
        self.assertIn("By @neo", post_lines(post))
        self.assertIn("@neo", profile_lines(profile))
        self.assertIn("2 members, 0 apprentices", guild_lines(guild))
        self.assertIn("Revision 2", note_lines(note))
        self.assertTrue(notification_title(notice).startswith("*"))
        self.assertTrue(chat_lines([{"username": "neo", "content": "hi"}]))
        self.assertEqual(grouped_search({"users": [profile], "posts": [post]} )[0]["_heading"],
                         "Users")
        self.assertEqual(ROOT_MENU, TABS)
        self.assertEqual(SUBMENUS, {})
        self.assertEqual([value for _, value in TABS],
                         ["feed", "notifications", "cmail", "circ", "notes",
                          "bookmarks", "guilds", "topics", "profile", "settings"])
        self.assertTrue(terminal_too_small(11, 80))
        self.assertTrue(terminal_too_small(20, 35))
        self.assertTrue(terminal_too_small(12, 36))
        self.assertFalse(terminal_too_small(13, 36))

    def test_card_models_emphasize_identity_and_required_metadata(self):
        post = {"authorUsername": "neo", "title": "Wake up", "content": "Follow",
                "slug": "wake-up", "topics": ["matrix"]}
        conversation = {"otherUser": {"displayName": "Trinity", "username": "trinity"},
                        "lastMessage": {"content": "hello"}, "unreadCount": 2}
        room = {"name": "General", "slug": "general", "onlineCount": 7,
                "lastActivity": "now"}
        self.assertIn(("@neo", "bold"), post_card(post, 40)[0])
        self.assertEqual(post_card(post, 40)[1], [("Wake up", "bold")])
        self.assertIn(("Trinity", "bold"), conversation_card(conversation, 40)[0])
        self.assertEqual(room_card(room, 40)[0], [("General", "bold")])
        self.assertIn("#general  7 online", room_card(room, 40)[1][0][0])
        self.assertIn(("@neo", "bold"), reply_card(post, 40)[0])
        self.assertIn(("you", "bold"), message_bubble(post, 30, mine=True)[0])
        self.assertEqual(post_permalink(post),
                         "https://cyberspace.online/neo/wake-up")

    def test_human_times_and_compact_irc_rows(self):
        now = {"year": 2025, "month": 8, "day": 22,
               "hour": 19, "minute": 15, "second": 20}
        self.assertEqual(human_activity("1755890000000", now), "2m ago")

        def plus_two(parts):
            result = dict(parts)
            result["hour"] = (result["hour"] + 2) % 24
            return result

        self.assertEqual(format_clock("1755890000000", plus_two), "21:13")
        room = {"name": "General", "slug": "general", "onlineCount": 7,
                "lastMessageAt": "1755890000000"}
        self.assertIn("Last activity 2m ago", room_card(room, 40, now)[2][0][0])
        rows = irc_message_rows({
            "username": "aprilmyroom", "content": "white claw was a joke",
            "timestamp": "1755890000000",
        }, 50, timestamp="21:13")
        rendered = "".join(text for text, _ in rows[0])
        self.assertTrue(rendered.startswith("<aprilmyroom>  white claw"))
        self.assertTrue(rendered.endswith("21:13"))

    def test_logo_is_ascii_and_tab_window_keeps_active_tab_visible(self):
        logo = logo_lines(50)
        self.assertEqual(len(logo), 5)
        self.assertTrue(all(line.isascii() for line in logo))
        self.assertLessEqual(max(len(line) for line in logo), 47)
        self.assertIn("/ __|", logo[1])
        self.assertEqual(logo_lines(46), ["CYBERSPACE"])
        cells = tab_window(8, 50)
        self.assertTrue(any(selected and label == "Profile"
                            for _, _, label, selected in cells))
        self.assertLessEqual(sum(width for _, width, _, _ in cells), 50)


if __name__ == "__main__":
    unittest.main()
