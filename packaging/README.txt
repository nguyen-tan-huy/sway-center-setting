swayctl setup
=============

What this folder contains
-------------------------
  swayctl-center-*.pkg.tar.zst    the settings app (also starts the daemon)
  swayctl-bar-*.pkg.tar.zst       the bar, Quick Settings, notifications, OSD, lock screen
  swayctl-fx-*.pkg.tar.zst        SwayFX fork (liquid glass, smooth scrolling) as swayctl-fx
  install.sh                      interactive installer (pacman -U, optional extras)
  README.txt                      this file

Install
-------
  On a new machine with SwayFX (sudo pacman -S swayfx), copy this folder (or the
  swayctl-setup-*.tar.gz it came in: tar xf swayctl-setup-*.tar.gz) and run:

  ./install.sh            asks before anything optional
  ./install.sh --yes      takes every recommended extra

Then log out and pick "Sway (swayctl-fx)" on the login screen. Plain "Sway" stays
as the fallback if you ever need it (no liquid glass / smooth scrolling).

Building this folder
--------------------
  packaging/make-bundle.sh in the swayctl-center repo builds the three packages
  and writes packaging/dist/swayctl-setup-<date>.tar.gz.

Uninstall
---------
  sudo pacman -Rns swayctl-center swayctl-bar swayctl-fx

Notes
-----
  * Dependencies (sway, gtk4, python-gobject, ...) come from the normal repos.
  * The first start of Settings opens a short setup wizard; later open Settings
    from the launcher or the gear in Quick Settings.
  * Liquid glass and smooth scrolling only work on "Sway (swayctl-fx)".
