import unittest


class DesignTokenTests(unittest.TestCase):
    def test_light_theme_uses_soft_surfaces_not_pure_white_cards(self):
        import core.design as design

        self.assertNotEqual(design.COLOR_BG[0].lower(), "#ffffff")
        self.assertNotEqual(design.COLOR_SURFACE[0].lower(), "#ffffff")
        self.assertNotEqual(design.COLOR_TERMINAL_BG[0].lower(), "#ffffff")
        self.assertEqual(design.RADIUS_LG, 8)


if __name__ == "__main__":
    unittest.main()
