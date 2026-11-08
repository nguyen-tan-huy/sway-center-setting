import tempfile
import unittest
from pathlib import Path

from swayctl_center import presets, schema, themes
from swayctl_center.daemon import Daemon
from swayctl_center.modules import Context, by_section
from swayctl_center.modules.components import BarModule
from swayctl_center.store import Store

KINDS = ("anim_open_close", "anim_workspace", "anim_move", "anim_quick")


def migrated(values: str):
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "settings.json").write_text('{"version": 1, "values": ' + values + "}")
        daemon = Daemon.__new__(Daemon)
        daemon.store = Store(d)
        daemon.modules = by_section()
        daemon.store.load()
        daemon._retire_old_choices()
        return daemon.store.effective()["effects"], daemon.store.is_set("effects", "animations")


class AnimationSwitchesTest(unittest.TestCase):
    def test_off_by_default_and_every_switch_is_visible(self):
        for name in KINDS:
            key = schema.lookup("effects", name)
            self.assertFalse(key.default, name)
            self.assertFalse(key.hidden, name)
        self.assertTrue(schema.lookup("effects", "animations").hidden)  # the retired master

    def test_styles_turn_all_of_them_on_or_off_together(self):
        for style, expect in (("flat", False), ("rounded", True), ("liquid", True), ("frame", True)):
            fx = presets.ui_style_values(style)["effects"]
            self.assertEqual({n: fx[n] for n in KINDS}, {n: expect for n in KINDS}, style)

    def test_the_old_master_switch_is_carried_over_once(self):
        fx, still_set = migrated('{"effects": {"animations": true}}')
        self.assertTrue(all(fx[n] for n in KINDS))
        self.assertFalse(still_set)
        fx, _ = migrated('{"effects": {"animations": false}}')
        self.assertFalse(any(fx[n] for n in KINDS))

    def test_a_kind_you_already_chose_is_kept(self):
        fx, _ = migrated('{"effects": {"animations": true, "anim_workspace": false}}')
        self.assertFalse(fx["anim_workspace"])
        self.assertTrue(fx["anim_move"] and fx["anim_quick"])

    def test_the_compositor_is_told_about_popups_on_their_own(self):
        from swayctl_center.modules.effects import EffectsModule
        live = {"sway_original_version": "1.10", "swayctl_features": ["animation-kinds", "animation-popups"]}
        for on in (False, True):
            v = schema.defaults()["effects"] | {"anim_quick": on, "anim_move": True}
            ctx = Context(data_dir=Path("/tmp"), values={"effects": v}, theme=themes.BUILTIN["dark"], live=live)
            cmds = EffectsModule().commands("effects", v, None, ctx)
            self.assertIn(f"animations popups {'enable' if on else 'disable'}", cmds)
            # the length is only on while some kind is: popups alone must switch it on
            v2 = v | {"anim_open_close": False, "anim_workspace": False, "anim_move": False}
            ctx2 = Context(data_dir=Path("/tmp"), values={"effects": v2}, theme=themes.BUILTIN["dark"], live=live)
            dur = [c for c in EffectsModule().commands("effects", v2, None, ctx2) if c.startswith("animation_duration_ms")]
            self.assertEqual(dur[0] != "animation_duration_ms 0", on)
        # a compositor without the kind is not sent a command it would refuse
        ctx = Context(data_dir=Path("/tmp"), values={"effects": v}, theme=themes.BUILTIN["dark"],
                      live={"sway_original_version": "1.10", "swayctl_features": ["animation-kinds"]})
        self.assertFalse([c for c in EffectsModule().commands("effects", v, None, ctx) if "popups" in c])

    def test_the_bar_is_not_told_to_animate_anything_itself(self):
        values = {"appearance": {"style": "modern"}, "effects": {"anim_quick": True}}
        ctx = Context(data_dir=Path("/tmp"), values=values, theme=themes.BUILTIN["dark"])
        self.assertNotIn("animate_quick", BarModule().native_config(schema.defaults()["bar"], ctx))

    def test_the_settings_page_shows_only_the_animation_rows(self):
        from swayctl_center import ui
        shown = [n for _t, names in ui.EFFECT_GROUPS for n in names]
        for n in KINDS + ("anim_slide", "anim_curve", "anim_response", "anim_bounce", "anim_duration"):
            self.assertIn(n, shown)
        for n in ("shadows", "shadow_blur_radius"):
            self.assertIn(n, shown)
        for n in ("glass", "glass_refraction", "glass_blur", "glass_highlight"):
            self.assertIn(n, shown)  # liquid glass is tunable here
        self.assertIn("corner_radius", shown)  # tunable: starts from the interface style
        self.assertIn(("effects", "Effects"), ui.PAGES["desktop"])
        # the rows that only matter for one choice follow it
        v = {"anim_workspace": False, "anim_curve": "ease"}
        vw = ui.EffectsPage.visible_when
        self.assertFalse(vw["shadow_blur_radius"]({"shadows": False}))
        self.assertTrue(vw["shadow_blur_radius"]({"shadows": True}))
        self.assertFalse(vw["anim_slide"](v))
        self.assertFalse(vw["anim_bounce"](v))
        self.assertTrue(vw["anim_duration"](v))
        self.assertTrue(vw["anim_slide"](v | {"anim_workspace": True}))
        self.assertTrue(vw["anim_bounce"](v | {"anim_curve": "spring"}))


if __name__ == "__main__":
    unittest.main()
