import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageChops, ImageStat


class FrozenPackagingTests(unittest.TestCase):
    def test_pyinstaller_does_not_extract_onefile_to_current_directory(self):
        spec_text = Path("nvidia_register_ui.spec").read_text(encoding="utf-8")

        self.assertNotIn('runtime_tmpdir="."', spec_text)

    def test_pyinstaller_embeds_supplied_icon(self):
        spec_text = Path("nvidia_register_ui.spec").read_text(encoding="utf-8")

        self.assertIn('name="NVIDIARegister"', spec_text)
        self.assertIn('icon=str(project_dir / "icon" / "app.ico")', spec_text)
        self.assertIn('(str(project_dir / "icon" / "app.ico"), "icon")', spec_text)
        self.assertTrue(Path("icon/app.ico").is_file())

    def test_gui_builds_do_not_open_a_console_window(self):
        for spec_name in ("nvidia_register_ui.spec", "nvidia_register_fast.spec"):
            spec_text = Path(spec_name).read_text(encoding="utf-8")
            self.assertIn("console=False", spec_text)
            self.assertNotIn("console=True", spec_text)

    def test_builds_do_not_bundle_source_icon_or_tk_demos(self):
        for spec_name in ("nvidia_register_ui.spec", "nvidia_register_fast.spec"):
            spec_text = Path(spec_name).read_text(encoding="utf-8")
            self.assertNotIn('(str(project_dir / "icon" / "image-2.png"), "icon")', spec_text)
            self.assertIn('"demos" in path.relative_to(source_root).parts', spec_text)

    def test_build_script_reports_nvidiaregister_exe(self):
        script = Path("build_exe.bat").read_text(encoding="utf-8")

        self.assertIn(r"dist\NVIDIARegister.exe", script)
        self.assertNotIn("NVIDIARegisterControl.exe", script)

    def test_fast_spec_builds_onedir_package(self):
        spec_text = Path("nvidia_register_fast.spec").read_text(encoding="utf-8")

        self.assertIn('name="NVIDIARegister"', spec_text)
        self.assertIn("exclude_binaries=True", spec_text)
        self.assertIn("COLLECT(", spec_text)
        self.assertIn('name="NVIDIARegister-Fast"', spec_text)

    def test_app_icon_is_full_supplied_image_not_a_crop(self):
        source = Image.open("icon/image-2.png").convert("RGB").resize(
            (512, 512), Image.Resampling.LANCZOS
        )
        generated = Image.open("icon/app-icon.png").convert("RGB")

        self.assertEqual(generated.size, (512, 512))

        diff = ImageChops.difference(source, generated)
        rms = sum(value * value for value in ImageStat.Stat(diff).rms) ** 0.5
        self.assertLess(rms, 15)

    def test_app_base_dir_uses_executable_directory_when_frozen(self):
        from core import runtime_paths

        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "executable", r"C:\Apps\NvidiaControl\NVIDIARegister.exe"):
            self.assertEqual(
                runtime_paths.app_base_dir(),
                r"C:\Apps\NvidiaControl",
            )

    def test_configure_playwright_ignores_bundled_browser_directory(self):
        from core import runtime_paths

        with tempfile.TemporaryDirectory() as bundle_dir:
            browser_dir = os.path.join(bundle_dir, "ms-playwright")
            os.makedirs(browser_dir)
            with mock.patch.object(sys, "frozen", True, create=True), \
                    mock.patch.object(sys, "_MEIPASS", bundle_dir, create=True), \
                    mock.patch.dict(os.environ, {}, clear=True):
                runtime_paths.configure_playwright_browsers()
                self.assertNotIn("PLAYWRIGHT_BROWSERS_PATH", os.environ)

    def test_resource_path_uses_pyinstaller_bundle_when_frozen(self):
        from core import runtime_paths

        with tempfile.TemporaryDirectory() as bundle_dir, \
                mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "_MEIPASS", bundle_dir, create=True), \
                mock.patch.object(sys, "executable", r"C:\Apps\NvidiaControl\NvidiaRegisterControl.exe"):
            self.assertEqual(
                runtime_paths.resource_path("icon/app.ico"),
                os.path.join(bundle_dir, "icon", "app.ico"),
            )

    def test_configure_playwright_uses_user_browser_directory(self):
        from core import runtime_paths

        with tempfile.TemporaryDirectory() as browser_dir, \
                mock.patch.dict(os.environ, {"NV_PLAYWRIGHT_BROWSERS_PATH": browser_dir}, clear=True):
            runtime_paths.configure_playwright_browsers()
            self.assertEqual(os.environ["PLAYWRIGHT_BROWSERS_PATH"], browser_dir)

    def test_configure_stdio_utf8_reconfigures_console_streams_for_realtime_logs(self):
        from core import runtime_paths

        stdout = mock.Mock()
        stderr = mock.Mock()

        with mock.patch.object(sys, "stdout", stdout), \
                mock.patch.object(sys, "stderr", stderr):
            runtime_paths.configure_stdio_utf8()

        stdout.reconfigure.assert_called_once_with(
            encoding="utf-8",
            errors="replace",
            line_buffering=True,
            write_through=True,
        )
        stderr.reconfigure.assert_called_once_with(
            encoding="utf-8",
            errors="replace",
            line_buffering=True,
            write_through=True,
        )

    def test_find_chromium_executable_uses_user_executable_path(self):
        from core import runtime_paths

        with tempfile.TemporaryDirectory() as temp_dir:
            chrome_path = os.path.join(temp_dir, "chrome.exe")
            with open(chrome_path, "w", encoding="utf-8") as f:
                f.write("")

            found = runtime_paths.find_chromium_executable(
                {"CHROMIUM_EXECUTABLE_PATH": chrome_path}
            )

        self.assertIsNotNone(found)
        self.assertEqual(found["path"], chrome_path)
        self.assertEqual(found["source"], "CHROMIUM_EXECUTABLE_PATH")

    def test_frozen_runner_launches_same_exe_worker(self):
        from core.runner import RegisterRunner

        launched = []

        class FakeProcess:
            stdout = []
            returncode = 0

            def poll(self):
                return 0

            def kill(self):
                return None

        def fake_popen(args, **kwargs):
            launched.append(args)
            return FakeProcess()

        runner = RegisterRunner(app=None)
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "executable", r"C:\Apps\NvidiaControl\NVIDIARegister.exe"), \
                mock.patch("core.runner.subprocess.Popen", side_effect=fake_popen):
            runner._run_loop(count=1, concurrency=1)

        self.assertEqual(
            launched[0],
            [r"C:\Apps\NvidiaControl\NVIDIARegister.exe", "--register-worker", "--index=1"],
        )

    def test_runner_requests_realtime_utf8_child_runtime(self):
        from core.runner import RegisterRunner

        launched_env = []
        launched_kwargs = []

        class FakeProcess:
            stdout = []
            returncode = 0

            def poll(self):
                return 0

            def kill(self):
                return None

        def fake_popen(args, **kwargs):
            launched_env.append(kwargs["env"])
            launched_kwargs.append(kwargs)
            return FakeProcess()

        runner = RegisterRunner(app=None)
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "executable", r"C:\Apps\NvidiaControl\NVIDIARegister.exe"), \
                mock.patch("core.runner.subprocess.Popen", side_effect=fake_popen):
            runner._run_loop(count=1, concurrency=1)

        self.assertEqual(launched_env[0]["PYTHONIOENCODING"], "utf-8:replace")
        self.assertEqual(launched_env[0]["PYTHONUTF8"], "1")
        self.assertEqual(launched_env[0]["PYTHONUNBUFFERED"], "1")
        self.assertEqual(launched_kwargs[0]["bufsize"], 1)

    def test_importing_runner_does_not_import_registration_automation(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import core.runner; print('nvidia_register' in sys.modules)",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        self.assertEqual(result.stdout.strip(), "False")


if __name__ == "__main__":
    unittest.main()
