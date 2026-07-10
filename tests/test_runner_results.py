import unittest
import sys
from unittest import mock

from core.runner import RegisterRunner


class RunnerResultsTests(unittest.TestCase):
    def test_record_process_output_extracts_api_key_and_save_path(self):
        runner = RegisterRunner(app=None)

        runner._record_process_output(1, "AI_PLAYGROUNDS_KEY: nvapi-test-key\n")
        runner._record_process_output(1, "   ✅ saved to: C:\\keys\\nvidia_api_key_1.txt\n")

        self.assertEqual(
            runner._run_metadata[1],
            {
                "api_key": "nvapi-test-key",
                "save_path": "C:\\keys\\nvidia_api_key_1.txt",
            },
        )

    def test_run_loop_treats_count_as_runs_per_concurrency_lane(self):
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
            runner._run_loop(count=1, concurrency=3)

        self.assertEqual(len(launched), 3)
        self.assertEqual(
            launched,
            [
                [r"C:\Apps\NvidiaControl\NVIDIARegister.exe", "--register-worker", "--index=1"],
                [r"C:\Apps\NvidiaControl\NVIDIARegister.exe", "--register-worker", "--index=2"],
                [r"C:\Apps\NvidiaControl\NVIDIARegister.exe", "--register-worker", "--index=3"],
            ],
        )


if __name__ == "__main__":
    unittest.main()
