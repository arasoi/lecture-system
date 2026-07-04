import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from lecture_transcriber import calendar_lookup
from lecture_transcriber.calendar_lookup import find_class_for_timestamp
from lecture_transcriber.config import CalendarRenameConfig


class CalendarLookupTests(unittest.TestCase):
    def test_auto_provider_uses_graph_when_graph_config_present(self):
        config = CalendarRenameConfig(
            enabled=True,
            provider="auto",
            graph_tenant_id="tenant",
            graph_client_id="client",
            graph_client_secret="secret",
            graph_mailbox_user="user@contoso.com",
        )

        with patch("lecture_transcriber.calendar_lookup._find_graph_class_for_timestamp", return_value="bio101") as graph:
            result = find_class_for_timestamp(datetime.now(), config, lookback_minutes=60, lookahead_minutes=60)

        self.assertEqual(result, "bio101")
        graph.assert_called_once()

    def test_auto_provider_falls_back_to_outlook_without_graph_config(self):
        config = CalendarRenameConfig(enabled=True, provider="auto")

        with patch("lecture_transcriber.calendar_lookup._find_outlook_class_for_timestamp", return_value="bio101") as outlook:
            result = find_class_for_timestamp(datetime.now(), config, lookback_minutes=60, lookahead_minutes=60)

        self.assertEqual(result, "bio101")
        outlook.assert_called_once()

    def test_auto_provider_falls_back_to_outlook_with_incomplete_client_credentials(self):
        config = CalendarRenameConfig(
            enabled=True,
            provider="auto",
            graph_auth_mode="client_credentials",
            graph_tenant_id="tenant",
            graph_client_id="client",
            graph_mailbox_user="user@contoso.com",
        )

        with patch("lecture_transcriber.calendar_lookup._find_outlook_class_for_timestamp", return_value="bio101") as outlook:
            result = find_class_for_timestamp(datetime.now(), config, lookback_minutes=60, lookahead_minutes=60)

        self.assertEqual(result, "bio101")
        outlook.assert_called_once()

    def test_graph_provider_requires_graph_fields(self):
        config = CalendarRenameConfig(enabled=True, provider="graph")
        with self.assertRaises(RuntimeError):
            find_class_for_timestamp(datetime.now(), config)

    def test_select_subject_requires_timestamp_within_event(self):
        target = datetime(2026, 7, 4, 14, 44, 47)
        events = [
            ("Bus101", datetime(2026, 7, 4, 13, 30, 0), datetime(2026, 7, 4, 14, 0, 0)),
            ("ENG209", datetime(2026, 7, 4, 14, 30, 0), datetime(2026, 7, 4, 15, 0, 0)),
        ]
        result = calendar_lookup._select_subject_for_timestamp(target, events)
        self.assertEqual(result, "ENG209")

    def test_select_subject_returns_none_when_no_overlapping_event(self):
        target = datetime(2026, 7, 4, 16, 10, 0)
        events = [
            ("ENG209", datetime(2026, 7, 4, 14, 30, 0), datetime(2026, 7, 4, 15, 0, 0)),
        ]
        result = calendar_lookup._select_subject_for_timestamp(target, events)
        self.assertIsNone(result)

    def test_to_local_naive_converts_aware_datetime(self):
        aware_utc = datetime(2026, 7, 4, 14, 30, 0, tzinfo=UTC)
        converted = calendar_lookup._to_local_naive(aware_utc)
        expected = aware_utc.astimezone().replace(tzinfo=None)
        self.assertEqual(converted, expected)

    def test_graph_lookup_requests_events_in_utc(self):
        config = CalendarRenameConfig(enabled=True, provider="graph", graph_auth_mode="device_code", graph_client_id="abc")

        class FakeResponse:
            def __init__(self, body: str):
                self._body = body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return self._body.encode("utf-8")

        seen = {}

        def fake_urlopen(request, timeout=30):
            seen["prefer"] = request.headers.get("Prefer")
            return FakeResponse(
                '{"value":[{"subject":"bio101","start":{"dateTime":"2026-07-04T12:00:00","timeZone":"UTC"},"end":{"dateTime":"2026-07-04T13:00:00","timeZone":"UTC"}}]}'
            )

        with (
            patch("lecture_transcriber.calendar_lookup._acquire_graph_token_device_code", return_value="token"),
            patch("lecture_transcriber.calendar_lookup.urlopen", side_effect=fake_urlopen),
        ):
            subject = calendar_lookup._find_graph_class_for_timestamp(datetime(2026, 7, 4, 12, 30, 0, tzinfo=UTC), 60, 60, config)

        self.assertEqual(subject, "bio101")
        self.assertEqual(seen["prefer"], 'outlook.timezone="UTC"')

    def test_invalid_graph_cache_raises_runtime_error(self):
        with TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "graph_token_cache.json"
            cache_path.write_text("not-json", encoding="utf-8")
            config = CalendarRenameConfig(
                enabled=True,
                provider="graph",
                graph_auth_mode="device_code",
                graph_client_id="abc",
                graph_token_cache_path=str(cache_path),
            )

            class FakeCache:
                has_state_changed = False

                def deserialize(self, payload):
                    raise ValueError("bad cache")

            class FakeMsal:
                SerializableTokenCache = FakeCache

            with patch("lecture_transcriber.calendar_lookup._load_msal", return_value=FakeMsal):
                with self.assertRaises(RuntimeError):
                    calendar_lookup._acquire_graph_token_device_code(config, interactive=False)

    def test_auto_provider_falls_back_to_outlook_when_graph_lookup_fails(self):
        config = CalendarRenameConfig(enabled=True, provider="auto", graph_auth_mode="device_code", graph_client_id="client")

        with (
            patch("lecture_transcriber.calendar_lookup._find_graph_class_for_timestamp", side_effect=RuntimeError("graph fail")),
            patch("lecture_transcriber.calendar_lookup._find_outlook_class_for_timestamp", return_value="bio101") as outlook,
        ):
            result = find_class_for_timestamp(datetime.now(), config, lookback_minutes=60, lookahead_minutes=60)

        self.assertEqual(result, "bio101")
        outlook.assert_called_once()

    def test_auto_provider_treats_placeholder_client_id_as_unconfigured(self):
        config = CalendarRenameConfig(enabled=True, provider="auto", graph_auth_mode="device_code", graph_client_id="YOUR_PUBLIC_CLIENT_ID_HERE")

        with patch("lecture_transcriber.calendar_lookup._find_outlook_class_for_timestamp", return_value="bio101") as outlook:
            result = find_class_for_timestamp(datetime.now(), config, lookback_minutes=60, lookahead_minutes=60)

        self.assertEqual(result, "bio101")
        outlook.assert_called_once()


if __name__ == "__main__":
    unittest.main()