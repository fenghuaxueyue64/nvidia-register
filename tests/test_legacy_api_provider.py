import tempfile
import unittest
from unittest import mock

from nvidia_register import LegacyApiProvider


class _JsonResponse:
    status_code = 200
    text = ""

    def __init__(self, data=None, error=None):
        self._data = data or {}
        self._error = error

    def json(self):
        if self._error:
            raise self._error
        return self._data


class LegacyApiProviderTests(unittest.TestCase):
    def test_default_usernames_are_unique_within_same_second(self):
        requested_names = []

        def fake_post(_url, **kwargs):
            requested_names.append(kwargs["json"]["name"])
            name = kwargs["json"]["name"]
            return _JsonResponse({
                "jwt": f"jwt-{name}",
                "address": f"{name}@example.test",
            })

        provider = LegacyApiProvider(
            "https://mail.example.test",
            "secret",
            "example.test",
        )

        with mock.patch.dict("nvidia_register.os.environ", {"EMAIL_CREATE_INTERVAL_SECONDS": "0"}), \
                mock.patch("nvidia_register.time.time", return_value=1783428198), \
                mock.patch("nvidia_register.requests.post", side_effect=fake_post):
            first = provider.create_mailbox()
            second = provider.create_mailbox()

        self.assertNotEqual(requested_names[0], requested_names[1])
        self.assertNotEqual(first["address"], second["address"])

    def test_create_mailbox_retries_transient_non_json_response(self):
        responses = [
            _JsonResponse(error=ValueError("Expecting value: line 1 column 1 (char 0)")),
            _JsonResponse({"jwt": "jwt-ok", "address": "nv1@example.test"}),
        ]

        provider = LegacyApiProvider(
            "https://mail.example.test",
            "secret",
            "example.test",
        )

        with mock.patch.dict("nvidia_register.os.environ", {
            "EMAIL_CREATE_RETRIES": "1",
            "EMAIL_CREATE_RETRY_DELAY_SECONDS": "0",
            "EMAIL_CREATE_INTERVAL_SECONDS": "0",
        }), mock.patch("nvidia_register.requests.post", side_effect=responses) as post:
            mailbox = provider.create_mailbox(username="nv1")

        self.assertEqual(post.call_count, 2)
        self.assertEqual(mailbox, {"address": "nv1@example.test", "jwt": "jwt-ok"})

    def test_create_mailbox_buffers_requests_across_short_interval(self):
        current_time = {"value": 100.0}
        sleeps = []

        def fake_time():
            return current_time["value"]

        def fake_sleep(seconds):
            sleeps.append(seconds)
            current_time["value"] += seconds

        def fake_post(_url, **kwargs):
            name = kwargs["json"]["name"]
            return _JsonResponse({
                "jwt": f"jwt-{name}",
                "address": f"{name}@example.test",
            })

        provider = LegacyApiProvider(
            "https://mail.example.test",
            "secret",
            "example.test",
        )

        with tempfile.TemporaryDirectory() as temp_dir, \
                mock.patch.dict("nvidia_register.os.environ", {
                    "EMAIL_CREATE_INTERVAL_SECONDS": "2",
                    "EMAIL_CREATE_RETRIES": "0",
                    "NV_EMAIL_BUFFER_DIR": temp_dir,
                }), mock.patch("nvidia_register.time.time", side_effect=fake_time), \
                mock.patch("nvidia_register.time.sleep", side_effect=fake_sleep), \
                mock.patch("nvidia_register.requests.post", side_effect=fake_post):
            provider.create_mailbox(username="nv1")
            current_time["value"] += 0.5
            provider.create_mailbox(username="nv2")

        self.assertTrue(
            any(delay >= 1.4 for delay in sleeps),
            f"expected buffered wait, got sleeps={sleeps}",
        )


if __name__ == "__main__":
    unittest.main()
