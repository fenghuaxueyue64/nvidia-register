import unittest
from unittest import mock


class AiConfigAndSolverTests(unittest.TestCase):
    def test_llm_client_normalizes_compatible_mode_base_url(self):
        from core.llm_client import LLMClient

        client = LLMClient(
            api_key="test-key",
            base_url="https://dashscope.aliyuncs.com/compatible-mode",
        )

        self.assertEqual(
            client.base_url,
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

    def test_invalid_ai_model_placeholder_uses_default_model(self):
        from core.llm_client import LLMClient

        client = LLMClient(
            api_key="test-key",
            base_url="https://vision.example.com/v1",
            model="api",
        )

        self.assertEqual(client.model, "qwen3.6-flash")

    def test_config_normalizes_invalid_ai_model_placeholder(self):
        from core.config_manager import ConfigManager

        normalized = ConfigManager.normalize_values(
            {
                "AI_VISION_API_BASE": "https://dashscope.aliyuncs.com/compatible-mode",
                "AI_VISION_MODEL": "api",
            }
        )

        self.assertEqual(
            normalized["AI_VISION_API_BASE"],
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self.assertEqual(normalized["AI_VISION_MODEL"], "qwen3.6-flash")

    def test_captcha_connection_uses_explicit_ui_credentials(self):
        from core import captcha_solver

        with mock.patch.object(captcha_solver.LLMClient, "discover_api_txt", return_value=None), \
                mock.patch.object(captcha_solver.LLMClient, "test_connectivity",
                                  return_value={"ok": True, "message": "ok", "latency_ms": 1}) as test_conn, \
                mock.patch.object(captcha_solver, "LLMClient", wraps=captcha_solver.LLMClient) as client_cls:
            result = captcha_solver.test_connection(
                api_key="ui-key",
                base_url="https://vision.example.com/v1",
                model="ui-model",
            )

        self.assertTrue(result["ok"])
        client_cls.assert_called_with(
            api_key="ui-key",
            base_url="https://vision.example.com/v1",
            model="ui-model",
        )
        test_conn.assert_called_once()

    def test_agent_prompt_enforces_high_precision_multi_round_protocol(self):
        from core.captcha_solver import AGENT_SYSTEM_PROMPT

        prompt = AGENT_SYSTEM_PROMPT.lower()
        for required in (
            "do not guess",
            "confidence",
            "target instruction",
            "multi-round",
            "never call report_done",
            "verify after every action",
        ):
            self.assertIn(required, prompt)

    def test_agent_coordinate_contract_uses_left_full_page_coordinates(self):
        from core.captcha_solver import AGENT_SYSTEM_PROMPT, CAPTCHA_TOOLS

        prompt = AGENT_SYSTEM_PROMPT.lower()
        tool_text = "\n".join(tool["description"] for tool in CAPTCHA_TOOLS).lower()

        self.assertIn("left full-page absolute", prompt)
        self.assertIn("right zoom", prompt)
        self.assertIn("detail only", prompt)
        self.assertIn("full-page viewport", tool_text)
        self.assertNotIn("within the captcha challenge area screenshot", tool_text)
        self.assertNotIn("within the captcha area", tool_text)

    def test_out_of_viewport_action_coordinates_are_rejected(self):
        from core.captcha_solver import AgentCaptchaSolver

        area = {"vw": 1000, "vh": 800}

        ok, message = AgentCaptchaSolver._validate_viewport_point(1001, 400, area, "click")

        self.assertFalse(ok)
        self.assertIn("outside viewport", message)

    def test_parse_unknown_response_waits_instead_of_reporting_done(self):
        from core.captcha_solver import AgentCaptchaSolver

        solver = AgentCaptchaSolver(vision_client=object(), verbose=False)

        parsed = solver._parse_tool_call("I cannot determine the answer from this screenshot.")

        self.assertEqual(parsed["tool"], "wait")

    def test_grid_cell_center_uses_inner_image_grid_not_entire_challenge(self):
        from core.captcha_solver import AgentCaptchaSolver

        solver = AgentCaptchaSolver(vision_client=object(), verbose=False)
        area = {"ox": 100, "oy": 50, "cw": 420, "ch": 620}

        _x, y = solver._grid_cell_center(area, rows=3, cols=3, row=0, col=0)

        self.assertGreater(y, area["oy"] + area["ch"] * 0.22)
        self.assertLess(y, area["oy"] + area["ch"] * 0.45)


if __name__ == "__main__":
    unittest.main()
