"""Defaults of the old stack (waybar, classic look, swaylock). The app no
longer offers these, but the code paths remain; tests for them start here."""
from swayctl_center import schema


def legacy_defaults():
    v = schema.defaults()
    v["bar"]["program"] = "waybar"
    v["appearance"]["style"] = "classic"
    v["auth"]["lock_screen"] = "swaylock"
    return v
