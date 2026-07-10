import unittest
import tempfile
from unittest import mock

import requests

from core.config_manager import ConfigManager
from mail_providers import DuckMailProvider, normalize_mail_domain


class DuckMailProviderTests(unittest.TestCase):
    def test_normalize_mail_domain_accepts_leading_at(self):
        self.assertEqual(normalize_mail_domain("@duckmail.sbs"), "duckmail.sbs")
        self.assertEqual(normalize_mail_domain(" https://duckmail.sbs/ "), "duckmail.sbs")

    def test_create_mailbox_uses_single_at_and_custom_api_base(self):
        provider = DuckMailProvider(
            api_key="dk_test",
            domain="@duckmail.sbs",
            api_base="https://mail-api.example.test/",
        )
        calls = []

        def fake_request(method, path, **kwargs):
            calls.append((method, path, kwargs))
            return {"token": "token-1", "id": "account-1"}

        provider._request = fake_request

        mailbox = provider.create_mailbox(username="abc")

        self.assertEqual(provider.domain, "duckmail.sbs")
        self.assertEqual(provider.base_url, "https://mail-api.example.test")
        self.assertEqual(mailbox["address"], "abc@duckmail.sbs")
        self.assertEqual(calls[0][2]["payload"]["address"], "abc@duckmail.sbs")
        self.assertEqual(calls[1][2]["payload"]["address"], "abc@duckmail.sbs")

    def test_network_errors_include_dns_and_actionable_hint(self):
        provider = DuckMailProvider(api_key="dk_test", domain="duckmail.sbs")

        with mock.patch(
            "mail_providers.requests.request",
            side_effect=requests.exceptions.SSLError(
                "UNEXPECTED_EOF_WHILE_READING"
            ),
        ), mock.patch(
            "mail_providers.socket.getaddrinfo",
            return_value=[(None, None, None, "", ("198.18.0.155", 443))],
        ):
            with self.assertRaisesRegex(RuntimeError, "DUCKMAIL_API_BASE"):
                provider._request("POST", "/accounts", use_api_key=True, payload={})

    def test_config_includes_duckmail_api_base(self):
        self.assertIsNotNone(ConfigManager.get_field("DUCKMAIL_API_BASE"))

    def test_config_defaults_are_field_specific(self):
        self.assertEqual(ConfigManager.default_value("MAIL_TYPE"), "api")
        self.assertEqual(ConfigManager.default_value("CAPTCHA_AI_ENABLED"), "false")

    def test_config_write_normalizes_duckmail_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ConfigManager(f"{temp_dir}/.env")
            manager.write({
                "MAIL_TYPE": "duckmail",
                "DUCKMAIL_DOMAIN": "@duckmail.sbs",
                "DUCKMAIL_API_BASE": "api.duckmail.sbs/",
            })

            values = manager.read()

        self.assertEqual(values["DUCKMAIL_DOMAIN"], "duckmail.sbs")
        self.assertEqual(values["DUCKMAIL_API_BASE"], "https://api.duckmail.sbs")


if __name__ == "__main__":
    unittest.main()
