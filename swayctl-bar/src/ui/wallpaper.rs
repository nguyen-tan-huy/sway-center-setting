//! A video as the wallpaper: a layer surface on the background layer of one output that plays the
//! file muted and in a loop, scaled to cover (GTK's own GStreamer media backend: no extra process).
//! It sits under the frame's glass and the bar, so what the glass bends is the moving picture.

use gtk::prelude::*;
use gtk::{gdk, gio};
use gtk4_layer_shell::{Edge, KeyboardMode, Layer, LayerShell};

pub const NAMESPACE: &str = "swayctl-wallpaper";

pub fn build(app: &adw::Application, monitor: &gdk::Monitor, video: &str) -> gtk::Window {
    let win = gtk::Window::builder().application(app).css_classes(["wallpaper-window"]).build();
    win.init_layer_shell();
    win.set_namespace(Some(NAMESPACE));
    win.set_monitor(Some(monitor));
    win.set_layer(Layer::Background);
    for e in [Edge::Top, Edge::Bottom, Edge::Left, Edge::Right] {
        win.set_anchor(e, true);
    }
    // the whole output, whatever the bar or anything else reserves
    win.set_exclusive_zone(-1);
    win.set_keyboard_mode(KeyboardMode::None);

    let media = gtk::MediaFile::for_file(&gio::File::for_path(video));
    media.set_loop(true);
    media.set_muted(true);
    let picture = gtk::Picture::builder().content_fit(gtk::ContentFit::Cover).can_shrink(true)
        .hexpand(true).vexpand(true).build();
    picture.set_paintable(Some(&media));
    win.set_child(Some(&picture));
    // clicks go straight through to the desktop
    win.connect_realize(|w| {
        if let Some(s) = w.surface() {
            s.set_input_region(Some(&gtk::cairo::Region::create()));
        }
    });
    // starts once the surface is mapped; an unreadable video shows nothing (the output colour stays)
    media.play();
    win.connect_destroy({
        let media = media.clone();
        move |_| media.pause()
    });
    win
}
