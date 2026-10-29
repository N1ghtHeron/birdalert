import contextlib
import datetime as dt
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

import main
from zoopicker_client import (
    AdRequiredError, AuthenticationError, Observation, PlaceResult,
    ZoopickerClient, ZoopickerError, RateLimitError, load_locations, parse_records_jp,
    retry_after_seconds,
)

TARGET = "Calidris melanotos"
DATES = {dt.date(2026, 10, day) for day in (27, 28, 29)}


def response(data=None, status=200, text=None):
    result = requests.Response()
    result.status_code = status
    result.encoding = "utf-8"
    result._content = (text if text is not None else json.dumps(data)).encode()
    return result


def row(day=28, scientific="Ardea cinerea"):
    return {
        "went": {"date": f"2026-10-{day:02d}", "place": {"id": 767, "name": "伊佐沼"}},
        "animal_page": {"id": 1, "title": "アメリカウズラシギ" if scientific == TARGET else "アオサギ",
                        "scientific_name": scientific, "english_name": "Pectoral Sandpiper"},
    }


def page(rows, number=1):
    return response({"watcheds": rows, "meta": {"current_page": number, "last_page": None}})


def login_responses():
    return [response(text='<script>firebaseApiKey:"public-test-key"</script>'),
            response({"idToken": "test-id-token"}), response({}), response({"id": 1})]


def client_with_responses(*responses, authenticated=True, max_pages=99):
    session = Mock(spec=requests.Session)
    session.headers = {}
    session.request.side_effect = responses
    client = ZoopickerClient("test@example.invalid", "test-password", session=session,
                             delay=0, max_pages=max_pages)
    client.authenticated = authenticated
    return client


class AuthenticationTests(unittest.TestCase):
    @patch("zoopicker_client.time.sleep")
    def test_bootstrap_429_waits_then_logs_in(self, sleep):
        client = client_with_responses(response({}, 429), *login_responses())
        with contextlib.redirect_stdout(io.StringIO()):
            client.login()
        self.assertTrue(client.authenticated)
        self.assertIn(unittest.mock.call(30), sleep.call_args_list)
        self.assertEqual(client.session.request.call_count, 5)

    @patch("zoopicker_client.time.sleep")
    def test_persistent_429_is_bounded_and_not_bad_password(self, sleep):
        client = client_with_responses(*[response({}, 429) for _ in range(3)])
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RateLimitError) as caught:
            client.login()
        self.assertTrue(client.rate_limited)
        self.assertEqual(client.session.request.call_count, 3)
        self.assertIn(unittest.mock.call(60), sleep.call_args_list)
        self.assertNotIn("密码", str(caught.exception))

    @patch("zoopicker_client.time.sleep")
    def test_retry_after_is_respected_and_long_cooldown_stops(self, sleep):
        limited = response({}, 429)
        limited.headers["Retry-After"] = "45"
        client = client_with_responses(limited, response({"ok": True}))
        with contextlib.redirect_stdout(io.StringIO()):
            client._request("GET", "https://zoopicker.com/")
        self.assertIn(unittest.mock.call(45), sleep.call_args_list)
        limited.headers["Retry-After"] = "3600"
        client = client_with_responses(limited)
        with self.assertRaises(RateLimitError):
            client._request("GET", "https://zoopicker.com/")
        self.assertEqual(client.session.request.call_count, 1)

    @patch("zoopicker_client.time.sleep")
    def test_post_429_is_never_resubmitted(self, sleep):
        client = client_with_responses(response({}, 429))
        with self.assertRaises(RateLimitError):
            client._request("POST", "https://zoopicker.com/api/v1/accounts/firebase_signin")
        self.assertEqual(client.session.request.call_count, 1)
        sleep.assert_not_called()

    def test_retry_after_formats(self):
        from email.utils import format_datetime
        future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=60)
        seconds = retry_after_seconds(format_datetime(future))
        self.assertTrue(58 <= seconds <= 60)
        for value in (None, "invalid", "NaN", "Infinity"):
            self.assertIsNone(retry_after_seconds(value))

    def test_normal_login_verifies_server_session(self):
        client = client_with_responses(*login_responses(), authenticated=False)
        client.login()
        self.assertTrue(client.authenticated)
        calls = client.session.request.call_args_list
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[1].kwargs["json"]["email"], "test@example.invalid")
        self.assertIn("identitytoolkit.googleapis.com", calls[1].args[1])
        self.assertTrue(calls[2].args[1].endswith("/accounts/firebase_signin"))
        self.assertTrue(calls[3].args[1].endswith("/accounts/me"))

    def test_missing_credentials_does_not_make_requests(self):
        with self.assertRaises(AuthenticationError):
            ZoopickerClient("", "")

    def test_bad_password_is_not_retried_or_echoed(self):
        client = client_with_responses(login_responses()[0],
                                       response({"error": {"message": "test-password"}}, 400))
        with self.assertRaises(AuthenticationError) as caught:
            client.login()
        self.assertNotIn("test-password", str(caught.exception))
        self.assertEqual(client.session.request.call_count, 2)
        self.assertFalse(client.authenticated)

    def test_network_errors_do_not_echo_credentials(self):
        client = client_with_responses(requests.ConnectionError("test-password test-id-token"))
        with self.assertRaises(ZoopickerError) as caught:
            client.login()
        self.assertNotIn("test-password", str(caught.exception))
        self.assertNotIn("test-id-token", str(caught.exception))

    def test_200_login_without_user_is_not_authenticated(self):
        responses = login_responses()
        responses[-1] = response({})
        client = client_with_responses(*responses)
        with self.assertRaises(AuthenticationError):
            client.login()
        self.assertFalse(client.authenticated)

    def test_expired_cookie_reauthenticates_once(self):
        client = client_with_responses(response({}, 401), *login_responses(), page([row(scientific=TARGET)]))
        result = client.fetch_place(767, DATES)
        self.assertFalse(result.warning)
        self.assertEqual(result.records[0].scientific, TARGET)
        self.assertEqual(client.session.request.call_count, 6)

    def test_repeated_401_stops_instead_of_returning_no_birds(self):
        client = client_with_responses(response({}, 401), *login_responses(), response({}, 401))
        result = client.fetch_place(767, DATES)
        self.assertTrue(result.warning)
        self.assertFalse(client.authenticated)
        self.assertEqual(client.session.request.call_count, 6)


class PaginationTests(unittest.TestCase):
    def test_isanuma_regression_and_independent_same_species_rows(self):
        first = [row(28) for _ in range(60)] + [row(27) for _ in range(40)]
        first[22] = row(28, TARGET)
        first[86] = row(27, TARGET)
        second = [row(27) for _ in range(65)] + [row(25) for _ in range(35)]
        for index in (5, 58, 59, 64):
            second[index] = row(27, TARGET)
        client = client_with_responses(page(first), page(second, 2))
        result = client.fetch_place(767, DATES)
        self.assertFalse(result.warning)
        self.assertEqual((result.pages, result.fetched_count, len(result.records)), (2, 200, 165))
        targets = [rec for rec in result.records if rec.scientific == TARGET]
        self.assertEqual(sum(rec.date.day == 28 for rec in targets), 1)
        self.assertEqual(sum(rec.date.day == 27 for rec in targets), 5)
        self.assertEqual(client.session.request.call_count, 2)

    def test_empty_authenticated_list_is_valid(self):
        result = client_with_responses(page([])).fetch_place(767, DATES)
        self.assertFalse(result.warning)
        self.assertEqual(result.pages, 1)

    def test_full_page_on_cutoff_date_requires_next_page(self):
        client = client_with_responses(page([row(27)] * 100), page([row(27, TARGET)], 2))
        result = client.fetch_place(767, DATES)
        self.assertFalse(result.warning)
        self.assertEqual(len(result.records), 101)

    def test_partial_results_survive_ad_gate_on_next_page(self):
        client = client_with_responses(page([row(28, TARGET)] * 100),
                                       response(text="さらに野鳥の場所情報を見る 短い広告を見る"))
        result = client.fetch_place(767, DATES)
        self.assertEqual(len(result.records), 100)
        self.assertIn("广告", result.warning)

    def test_repeated_page_is_incomplete_and_not_double_counted(self):
        rows = [row(28)] * 100
        client = client_with_responses(page(rows), page(rows, 2))
        result = client.fetch_place(767, DATES)
        self.assertIn("重复", result.warning)
        self.assertEqual(len(result.records), 100)

    def test_wrong_page_number_is_incomplete(self):
        client = client_with_responses(page([row(28)] * 100), page([row(27)], 1))
        result = client.fetch_place(767, DATES)
        self.assertIn("分页", result.warning)
        self.assertEqual(result.pages, 1)

    def test_page_limit_is_not_a_success(self):
        client = client_with_responses(page([row(28)] * 100), max_pages=1)
        result = client.fetch_place(767, DATES)
        self.assertIn("上限", result.warning)

    def test_unsorted_page_does_not_stop_at_old_date(self):
        first = [row(25)] + [row(28)] * 98 + [row(25)]
        client = client_with_responses(page(first), page([row(27, TARGET)], 2))
        result = client.fetch_place(767, DATES)
        self.assertFalse(result.warning)
        self.assertEqual(result.pages, 2)
        self.assertEqual(result.records[-1].scientific, TARGET)

    def test_anonymous_preview_is_rejected(self):
        preview = row()
        del preview["went"]["place"]
        result = client_with_responses(page([preview] * 8)).fetch_place(767, DATES)
        self.assertTrue(result.warning)
        self.assertFalse(result.records)

    def test_schema_or_html_changes_are_not_empty_successes(self):
        malformed = row()
        malformed["went"]["date"] = "unknown"
        for bad_response in [page([malformed]), response(text="<html>Sign in</html>"),
                             response({"different": []}), response({}, 403)]:
            with self.subTest(response=bad_response.status_code):
                result = client_with_responses(bad_response).fetch_place(767, DATES)
                self.assertTrue(result.warning)
                self.assertFalse(result.records)


class HtmlAndReportTests(unittest.TestCase):
    def test_card_scoping_ignores_sidebar_text_and_inserted_labels(self):
        date = "2026年10月28日(水)に観察"
        html = f'''<aside>広告内容<br>{date}<br>Unrelated / example</aside>
        <div class="list-item"><span>アメリカウズラシギ</span>
        <div class="font-size-xs">Pectoral Sandpiper / {TARGET}</div>
        <button>追加のボタン</button><div class="watched-date">{date}</div></div>'''
        records = parse_records_jp(html, {date: "unused"})
        self.assertEqual(records[date], [{"observed_jp": "アメリカウズラシギ", "scientific": TARGET}])

    def test_ad_gate_and_login_preview_fail_explicitly(self):
        with self.assertRaises(AdRequiredError):
            parse_records_jp("<h1>さらに野鳥の場所情報を見る</h1><button>短い広告を見る</button>", {})
        with self.assertRaises(AuthenticationError):
            parse_records_jp("未ログインのため観察記録の表示が制限されています", {})

    def test_bom_does_not_drop_first_location(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "locations.csv"
            path.write_text("\ufeff109,葛西臨海公園\n767,伊佐沼\n", encoding="utf8")
            locations = load_locations(path)
        self.assertEqual([loc["id"] for loc in locations], [109, 767])
        self.assertTrue(locations[0]["url"].endswith("/observations"))

    def test_report_preserves_partial_records_and_warns(self):
        client = Mock()
        client.authenticated = True
        client.fetch_place.return_value = PlaceResult(
            [Observation(dt.date(2026, 10, 28), "アメリカウズラシギ", TARGET)],
            pages=1, fetched_count=100, warning="需要观看广告")
        with patch.object(main, "load_library", return_value=set()), \
                patch.object(main.ZoopickerClient, "from_env") as factory, \
                contextlib.redirect_stdout(io.StringIO()):
            factory.return_value.__enter__.return_value = client
            report = main.generate_markdown(zoopicker_only=True, place_ids=[767], today=dt.date(2026, 10, 29))
        self.assertIn(TARGET, report)
        self.assertIn("数据不完整", report)
        self.assertIn("0/1", report)

    def test_auth_failure_is_not_no_new_birds(self):
        with patch.object(main.ZoopickerClient, "from_env", side_effect=AuthenticationError("登录失败")), \
                patch.object(main, "fetch_ebird_data", return_value={}) as ebird:
            report = main.generate_markdown(zoopicker_only=True, place_ids=[767])
        ebird.assert_not_called()
        self.assertIn("不能据此判断", report)
        self.assertNotIn("无新增鸟种记录。", report)

    def test_ebird_failure_keeps_zoopicker_results(self):
        client = Mock()
        client.authenticated = True
        client.fetch_place.return_value = PlaceResult(
            [Observation(dt.date(2026, 10, 28), "アメリカウズラシギ", TARGET)], pages=1)
        with patch.object(main, "load_library", return_value=set()), \
                patch.object(main.ZoopickerClient, "from_env") as factory, \
                patch.object(main, "fetch_ebird_data", side_effect=ValueError("eBird 请求失败")), \
                contextlib.redirect_stdout(io.StringIO()):
            factory.return_value.__enter__.return_value = client
            report = main.generate_markdown(place_ids=[767], today=dt.date(2026, 10, 29))
        self.assertIn(TARGET, report)
        self.assertIn("eBird 请求失败", report)

    def test_zoopicker_only_does_not_require_coordinates(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(main.ZoopickerClient, "from_env", side_effect=AuthenticationError("未配置账号")):
            report = main.generate_markdown(zoopicker_only=True, place_ids=[767])
        self.assertIn("未配置账号", report)

    def test_date_window_uses_calendar_days_including_today(self):
        self.assertEqual(main.get_target_dates(3, dt.date(2026, 10, 29)), DATES)


if __name__ == "__main__":
    unittest.main()
