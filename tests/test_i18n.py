import importlib
import os
import unittest
from unittest import mock

from swayctl_center import i18n, schema


class I18nTest(unittest.TestCase):
    def load(self, **env):
        with mock.patch.dict(os.environ, env, clear=True):
            return importlib.reload(i18n)

    def tearDown(self):
        importlib.reload(i18n)

    def lang(self, **env):
        with mock.patch.dict(os.environ, env, clear=True):
            return i18n.language()

    def test_language_from_env(self):
        self.assertEqual(self.lang(LANG="vi_VN.UTF-8"), "vi")
        self.assertEqual(self.lang(LANGUAGE="vi:en", LANG="en_US.UTF-8"), "vi")
        self.assertEqual(self.lang(LANG="C"), "c")
        self.assertEqual(self.lang(LANG="vi_VN.UTF-8", SWAYCTL_LANG="en"), "en")

    def test_vietnamese(self):
        m = self.load(LANG="vi_VN.UTF-8")
        self.assertEqual(m._("Smooth scrolling"), "Cuộn mượt")
        self.assertEqual(m._("not translated"), "not translated")

    def test_english_passthrough(self):
        self.assertEqual(self.load(LANG="en_US.UTF-8")._("Smooth scrolling"), "Smooth scrolling")

    def test_every_explanation_has_vietnamese(self):
        missing = sorted(set(schema.HELP.values()) - i18n.VI.keys())
        self.assertEqual(missing, [])

    def test_every_setting_label_has_vietnamese(self):
        missing = sorted({k.label for k in schema.KEYS if not k.hidden} - i18n.VI.keys())
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
