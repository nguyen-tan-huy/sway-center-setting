// Scroll test input for tools/sandbox.sh: a wlr virtual pointer (exists only
// inside the sandboxed sway; no kernel device is created).
//   vptr finger <steps> <delta> <ms>   two-finger swipe, then lift (axis_stop)
//   vptr wheel <notches> <ms>          wheel notches (15 px, v120 = 120 each)
//   vptr click <x> <y> <button>        click (272 left, 273 right, 274 middle)
//   vptr move <x> <y>                  just move the pointer there
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <wayland-client.h>
#include "wlr-virtual-pointer-unstable-v1-client-protocol.h"

static struct zwlr_virtual_pointer_manager_v1 *mgr;
static struct wl_seat *seat;

static void global(void *d, struct wl_registry *r, uint32_t name, const char *iface, uint32_t v) {
	if (!strcmp(iface, zwlr_virtual_pointer_manager_v1_interface.name)) {
		mgr = wl_registry_bind(r, name, &zwlr_virtual_pointer_manager_v1_interface, 2);
	} else if (!strcmp(iface, wl_seat_interface.name)) {
		seat = wl_registry_bind(r, name, &wl_seat_interface, 1);
	}
}
static void global_remove(void *d, struct wl_registry *r, uint32_t name) {}
static const struct wl_registry_listener reg = { global, global_remove };

static uint32_t ms(void) {
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}
static void sleep_ms(int n) {
	struct timespec ts = { n / 1000, (n % 1000) * 1000000L };
	nanosleep(&ts, NULL);
}

int main(int argc, char **argv) {
	if (argc < 3) {
		fprintf(stderr, "usage: vptr finger <steps> <delta> <ms> | wheel <notches> <ms>\n");
		return 2;
	}
	struct wl_display *dpy = wl_display_connect(NULL);
	if (!dpy) { perror("wl_display_connect"); return 1; }
	struct wl_registry *r = wl_display_get_registry(dpy);
	wl_registry_add_listener(r, &reg, NULL);
	wl_display_roundtrip(dpy);
	if (!mgr) { fprintf(stderr, "no virtual pointer manager\n"); return 1; }
	struct zwlr_virtual_pointer_v1 *p = zwlr_virtual_pointer_manager_v1_create_virtual_pointer(mgr, seat);
	int x = 960, y = 540;
	// wheel / finger at a given spot: VPTR_X / VPTR_Y (default: the middle)
	if (getenv("VPTR_X")) x = atoi(getenv("VPTR_X"));
	if (getenv("VPTR_Y")) y = atoi(getenv("VPTR_Y"));
	if ((!strcmp(argv[1], "click") || !strcmp(argv[1], "move")) && argc > 3) {
		x = atoi(argv[2]);
		y = atoi(argv[3]);
	}
	zwlr_virtual_pointer_v1_motion_absolute(p, ms(), x, y, 1920, 1080);
	zwlr_virtual_pointer_v1_frame(p);
	wl_display_flush(dpy);
	sleep_ms(100);
	if (!strcmp(argv[1], "move")) {
		// nothing more: the motion above was the point
	} else if (!strcmp(argv[1], "click")) {
		int button = argc > 4 ? atoi(argv[4]) : 272;
		zwlr_virtual_pointer_v1_button(p, ms(), button, WL_POINTER_BUTTON_STATE_PRESSED);
		zwlr_virtual_pointer_v1_frame(p);
		wl_display_flush(dpy);
		sleep_ms(40);
		zwlr_virtual_pointer_v1_button(p, ms(), button, WL_POINTER_BUTTON_STATE_RELEASED);
		zwlr_virtual_pointer_v1_frame(p);
	} else if (!strcmp(argv[1], "finger")) {
		int steps = atoi(argv[2]), interval = argc > 4 ? atoi(argv[4]) : 10;
		double delta = argc > 3 ? atof(argv[3]) : 10;
		for (int i = 0; i < steps; i++) {
			zwlr_virtual_pointer_v1_axis_source(p, WL_POINTER_AXIS_SOURCE_FINGER);
			zwlr_virtual_pointer_v1_axis(p, ms(), WL_POINTER_AXIS_VERTICAL_SCROLL, wl_fixed_from_double(delta));
			zwlr_virtual_pointer_v1_frame(p);
			wl_display_flush(dpy);
			sleep_ms(interval);
		}
		zwlr_virtual_pointer_v1_axis_source(p, WL_POINTER_AXIS_SOURCE_FINGER);
		zwlr_virtual_pointer_v1_axis_stop(p, ms(), WL_POINTER_AXIS_VERTICAL_SCROLL);
		zwlr_virtual_pointer_v1_frame(p);
	} else {
		int notches = atoi(argv[2]), interval = argc > 3 ? atoi(argv[3]) : 80;
		for (int i = 0; i < notches; i++) {
			zwlr_virtual_pointer_v1_axis_source(p, WL_POINTER_AXIS_SOURCE_WHEEL);
			zwlr_virtual_pointer_v1_axis_discrete(p, ms(), WL_POINTER_AXIS_VERTICAL_SCROLL, wl_fixed_from_double(15), 1);
			zwlr_virtual_pointer_v1_frame(p);
			wl_display_flush(dpy);
			sleep_ms(interval);
		}
	}
	wl_display_flush(dpy);
	// stay: removing the last pointer clears pointer focus, cutting a coast short
	sleep_ms(1800);
	zwlr_virtual_pointer_v1_destroy(p);
	wl_display_roundtrip(dpy);
	return 0;
}
