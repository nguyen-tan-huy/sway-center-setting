import unittest
from unittest import mock

from swayctl_center.modules import components
from swayctl_center.modules.components import BarModule


class StrayBarTest(unittest.TestCase):
    def test_a_key_binding_copy_is_a_stray_but_the_bar_itself_is_not(self):
        is_stray = BarModule.is_stray
        for argv in (["swayctl-bar", "launcher"], ["/usr/bin/swayctl-bar", "quick"], ["swayctl-bar", "osd", "volume-up"],
                     ["swayctl-bar", "--config-dir", "/x", "launcher", "foot"], ["swayctl-bar", "tray-menu", "2"]):
            self.assertTrue(is_stray(argv), argv)
        for argv in (["swayctl-bar"], ["swayctl-bar", "--config-dir", "/x"], ["swayctl-bar", "--config-dir=/x"],
                     ["waybar", "launcher"], [], ["swayctl-lock", "quick"]):
            self.assertFalse(is_stray(argv), argv)

    def test_strays_are_ended_and_someone_elses_bar_is_left_alone(self):
        cmdlines = {101: b"swayctl-bar\0launcher\0", 102: b"swayctl-bar\0--config-dir\0/mine\0"}
        killed = []

        def read_bytes(self):
            return cmdlines[int(self.parts[2])]

        with mock.patch.object(components.Path, "read_bytes", read_bytes), \
                mock.patch.object(components.os, "kill", lambda pid, sig: killed.append(pid)), \
                mock.patch.object(components.Path, "exists", lambda self: False):
            left = BarModule().adopt_strays([101, 102])
        self.assertEqual(killed, [101])
        self.assertEqual(left, [102])  # a bar someone really started themselves stays theirs

    def test_a_pid_we_cannot_read_is_left_in_the_list(self):
        with mock.patch.object(components.Path, "read_bytes", side_effect=OSError):
            self.assertEqual(BarModule().adopt_strays([5]), [5])

    def test_other_components_keep_every_pid(self):
        self.assertEqual(components.Component().adopt_strays([1, 2]), [1, 2])


if __name__ == "__main__":
    unittest.main()
