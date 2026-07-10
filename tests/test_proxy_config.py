import os
import sys
import unittest
from unittest import mock


class ProxyConfigTests(unittest.TestCase):
    def test_config_fields_include_user_proxy_settings(self):
        from core.config_manager import ConfigManager

        self.assertIsNotNone(ConfigManager.get_field("HTTP_PROXY"))
        self.assertIsNotNone(ConfigManager.get_field("HTTPS_PROXY"))

    def test_apply_proxy_environment_sets_upper_and_lowercase_keys(self):
        from core.proxy_config import apply_proxy_environment

        env = {}

        apply_proxy_environment(
            {
                "HTTP_PROXY": "http://127.0.0.1:7897",
                "HTTPS_PROXY": "http://127.0.0.1:7897",
            },
            env,
        )

        self.assertEqual(env["HTTP_PROXY"], "http://127.0.0.1:7897")
        self.assertEqual(env["http_proxy"], "http://127.0.0.1:7897")
        self.assertEqual(env["HTTPS_PROXY"], "http://127.0.0.1:7897")
        self.assertEqual(env["https_proxy"], "http://127.0.0.1:7897")

    def test_apply_proxy_environment_removes_blank_proxy_keys(self):
        from core.proxy_config import apply_proxy_environment

        env = {
            "HTTP_PROXY": "http://old.proxy:8080",
            "http_proxy": "http://old.proxy:8080",
            "HTTPS_PROXY": "http://old.proxy:8080",
            "https_proxy": "http://old.proxy:8080",
        }

        apply_proxy_environment({"HTTP_PROXY": "", "HTTPS_PROXY": "   "}, env)

        self.assertNotIn("HTTP_PROXY", env)
        self.assertNotIn("http_proxy", env)
        self.assertNotIn("HTTPS_PROXY", env)
        self.assertNotIn("https_proxy", env)

    def test_build_playwright_proxy_prefers_https_proxy(self):
        from core.proxy_config import build_playwright_proxy

        proxy = build_playwright_proxy(
            {
                "HTTP_PROXY": "http://127.0.0.1:7897",
                "HTTPS_PROXY": "http://127.0.0.1:7898",
            }
        )

        self.assertEqual(proxy, {"server": "http://127.0.0.1:7898"})

    def test_build_playwright_proxy_extracts_credentials_and_bypass(self):
        from core.proxy_config import build_playwright_proxy

        proxy = build_playwright_proxy(
            {
                "HTTPS_PROXY": "http://user:pass@proxy.example.test:7897",
                "NO_PROXY": "localhost,127.0.0.1",
            }
        )

        self.assertEqual(
            proxy,
            {
                "server": "http://proxy.example.test:7897",
                "username": "user",
                "password": "pass",
                "bypass": "localhost,127.0.0.1",
            },
        )

    def test_runner_passes_configured_proxy_to_child_process(self):
        from core.runner import RegisterRunner

        launched_env = []

        class FakeProcess:
            stdout = []
            returncode = 0

            def poll(self):
                return 0

            def kill(self):
                return None

        def fake_popen(args, **kwargs):
            launched_env.append(kwargs["env"])
            return FakeProcess()

        runner = RegisterRunner(app=None)
        runner.apply_config(
            {
                "HTTP_PROXY": "http://127.0.0.1:7897",
                "HTTPS_PROXY": "http://127.0.0.1:7897",
            }
        )

        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "executable", r"C:\Apps\NvidiaControl\NvidiaRegisterControl.exe"), \
                mock.patch("core.runner.subprocess.Popen", side_effect=fake_popen):
            runner._run_loop(count=1, concurrency=1)

        self.assertEqual(launched_env[0]["HTTP_PROXY"], "http://127.0.0.1:7897")
        self.assertEqual(launched_env[0]["HTTPS_PROXY"], "http://127.0.0.1:7897")
        self.assertEqual(launched_env[0]["http_proxy"], "http://127.0.0.1:7897")
        self.assertEqual(launched_env[0]["https_proxy"], "http://127.0.0.1:7897")

    def test_playwright_launch_uses_configured_proxy(self):
        import nvidia_register

        proxy = nvidia_register.build_playwright_proxy_from_env(
            {
                "HTTP_PROXY": "http://127.0.0.1:7897",
                "HTTPS_PROXY": "http://127.0.0.1:7897",
            }
        )

        self.assertEqual(proxy, {"server": "http://127.0.0.1:7897"})

    def test_playwright_browser_install_uses_configured_proxy(self):
        from core.process_manager import ProcessManager

        launched_env = []

        class FakeProcess:
            stdout = []
            returncode = 0

            def wait(self, timeout=None):
                return 0

        def fake_popen(args, **kwargs):
            launched_env.append(kwargs.get("env", {}))
            return FakeProcess()

        manager = ProcessManager()
        manager.set_browser_config(
            {
                "HTTP_PROXY": "http://127.0.0.1:7897",
                "HTTPS_PROXY": "http://127.0.0.1:7897",
            }
        )

        with mock.patch("core.process_manager.is_frozen", return_value=False), \
                mock.patch("core.process_manager.subprocess.Popen", side_effect=fake_popen):
            self.assertTrue(manager.install_browsers())

        self.assertEqual(launched_env[0]["HTTP_PROXY"], "http://127.0.0.1:7897")
        self.assertEqual(launched_env[0]["HTTPS_PROXY"], "http://127.0.0.1:7897")
        self.assertEqual(launched_env[0]["http_proxy"], "http://127.0.0.1:7897")
        self.assertEqual(launched_env[0]["https_proxy"], "http://127.0.0.1:7897")


if __name__ == "__main__":
    unittest.main()
