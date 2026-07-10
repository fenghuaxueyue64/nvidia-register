import unittest
from pathlib import Path


class RunTabLayoutTests(unittest.TestCase):
    def test_duckmail_selector_is_kept_with_run_inputs(self):
        source = Path("ui/tabs/run_tab.py").read_text(encoding="utf-8")

        self.assertIn("before=self._show_config_cb", source)

    def test_run_count_label_matches_concurrency_round_semantics(self):
        source = Path("ui/tabs/run_tab.py").read_text(encoding="utf-8")

        self.assertIn('text="运行轮数"', source)
        self.assertNotIn('text="运行次数"', source)

    def test_key_directory_actions_are_not_duplicated_in_control_card(self):
        source = Path("ui/tabs/run_tab.py").read_text(encoding="utf-8")

        self.assertEqual(source.count('"最新 Key"'), 1)
        self.assertNotIn('text="📂 Keys 目录"', source)

    def test_run_tab_has_compact_top_right_actions(self):
        source = Path("ui/tabs/run_tab.py").read_text(encoding="utf-8")

        self.assertIn("_build_top_actions", source)
        self.assertIn("side=\"right\"", source)
        self.assertIn("height=30", source)

    def test_ai_connection_uses_entries_instead_of_only_api_txt(self):
        source = Path("ui/tabs/run_tab.py").read_text(encoding="utf-8")

        self.assertIn("test_connection(api_key=api_key, base_url=api_base, model=model_name)", source)
        self.assertNotIn("result = test_connection()", source)

    def test_ai_connection_button_sits_with_primary_run_actions(self):
        source = Path("ui/tabs/run_tab.py").read_text(encoding="utf-8")

        primary_start = source.index("# ---- 主操作行")
        ai_status_start = source.index("# 检测状态行")
        test_button = source.index("测试连接")

        self.assertGreater(test_button, primary_start)
        self.assertLess(test_button, ai_status_start)

    def test_stats_strip_is_compact_single_row(self):
        source = Path("ui/tabs/run_tab.py").read_text(encoding="utf-8")
        stats_start = source.index("def _build_stats_card")
        terminal_start = source.index("def _build_terminal_card")
        stats_source = source[stats_start:terminal_start]

        self.assertIn("_build_stat_metric", source)
        self.assertIn('font=_mk_font(24, "bold")', stats_source)
        self.assertNotIn('text="数据库概览"', stats_source)
        self.assertNotIn('pady=(SPACING_MD, 0)', stats_source)

    def test_terminal_gets_more_default_vertical_space(self):
        source = Path("ui/tabs/run_tab.py").read_text(encoding="utf-8")

        self.assertIn("height=320", source)
        self.assertNotIn("height=240", source)

    def test_run_tab_uses_model_menu_for_ai_backend(self):
        source = Path("ui/tabs/run_tab.py").read_text(encoding="utf-8")

        self.assertIn("self._ai_model_selector = ctk.CTkOptionMenu", source)
        self.assertNotIn("self._ai_model_entry = ctk.CTkEntry", source)

    def test_model_test_tab_reads_env_config_before_api_txt(self):
        app_source = Path("ui/app_window.py").read_text(encoding="utf-8")
        tab_source = Path("ui/tabs/model_test_tab.py").read_text(encoding="utf-8")

        self.assertIn("config_manager=self._config_manager", app_source)
        self.assertIn("AI_VISION_API_KEY", tab_source)
        self.assertIn("AI_VISION_API_BASE", tab_source)
        self.assertIn("LLMClient.discover_api_txt()", tab_source)


if __name__ == "__main__":
    unittest.main()
