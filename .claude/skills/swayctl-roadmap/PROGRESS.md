# Tiến độ

## Mốc 1 - design token & theme (XONG)
- [x] Sandbox `tools/sandbox.sh` (bwrap, sway headless)
- [x] B1 design token trong `themes.py` + placeholder mới + CSS libadwaita (`theming.adwaita_css`),
      theme `modern-light/dark`, theme JSON chỉ cần accent; test `tests/test_tokens.py`.
      Token viền tên `outline` (vì `@BORDER@` cũ = accent). `accent_fg` ưu tiên trắng khi tương phản >= 3.5.
      `adwaita_css` chưa được ghi ra đâu: việc của B2 (gtk-4.0/gtk.css là file của người dùng -> cần opt-in).
- [x] B2 token cho waybar (classic giữ nguyên; modern: nổi, bo góc, theo `appearance.style`), swaync,
      Walker, swaylock (sai mật khẩu = error), `client.urgent` = error. `appearance.gtk_css` (mặc định tắt):
      chỉ chèn khối @import có marker vào `~/.config/gtk-4.0/gtk.css`, tắt thì gỡ đúng khối đó.
      Fuzzel: dùng config của người dùng (mục Themed Apps) - không ép.
- [x] B3 `presets.py` + action `preset.modern|classic` + nút trên trang Appearance; đổi `style` kích hoạt áp lại
      mọi thứ có theme (daemon `_apply_changes`).
- [x] `tools/preview.py` (chụp bar trong sway headless), `tools/perf.py` (ngân sách RAM/CPU).
      Mốc so sánh: waybar 26 MB PSS, 0% CPU khi rảnh.
      Sandbox có D-Bus riêng (dbus-run-session), xwayland tắt.

## Mốc 2 - fork SwayFX (XONG)
- [x] Clone `~/Projects/swayctl-fx/{swayfx,scenefx}`, nhánh `swayctl` (mỗi patch = 1 commit trên nhánh này).
      Build: `cd ~/Projects/swayctl-fx/swayfx && uvx --with ninja --from meson meson compile -C build`
      (scenefx là subproject symlink, link tĩnh). Máy không có meson hệ thống -> dùng uvx.
- [x] Patch 1: build được với libinput 1.32 (scroll method CIRCULAR). Patch 2: `get_version` có
      `swayctl_features` (thêm tên vào mảng khi có patch mới). SwayFX đã có sẵn `sway_original_version`.
- [x] IME popup: đã có sẵn từ sway 1.10 (text_input_popup) -> không cần vá.
- [x] An toàn: ĐỔI quyết định `provides=sway` -> cài CẠNH sway: binary `/usr/bin/swayctl-fx` + phiên đăng nhập
      riêng (`packaging/swayctl-fx/`), "Sway" gốc luôn còn để quay lại. `sway -C` không cần: swayctl-center không
      ghi config sway, chỉ gửi lệnh IPC; lệnh riêng SwayFX chỉ gửi khi phát hiện SwayFX.
- [x] Module `effects` (schema `effects.*`, chỉ gửi lệnh khi `sway_original_version` có trong get_version),
      preset modern bật bo góc/bóng/blur/panel. Trang Desktop > Effects có trạng thái; daemon status có `compositor`.
- [x] Sandbox `--fx` (GLES2 trên render node /dev/dri), `tools/desktop_shot.sh` chụp toàn màn hình.
- Lưu ý: SwayFX có `animation_duration_ms`; mặc định gửi 0 (đã chốt không animation compositor).

## Mốc 3 - swayctl-bar (Rust) (XONG)
- [x] Crate `swayctl-bar/` (gtk4 0.11, libadwaita 0.9 v1_6, gtk4-layer-shell 0.8, zbus 5 async-io, không tokio).
      `watch.rs` (giá trị + subscriber, không polling), `services/` (sway IPC thread->async_channel, D-Bus:
      UPower/NM/BlueZ/power-profiles/MPRIS/daemon swayctl; pactl subscribe; brightnessctl; swaync-client),
      `ui/bar.rs` (mỗi monitor 1 bar, workspaces/mode/window/clock+lịch/status), `ui/quick.rs` (Quick Settings:
      tile Wi-Fi/BT/Night Light/DND/Power Mode, slider độ sáng+âm lượng, media, footer settings/lock/power;
      trang con Wi-Fi/Sound Output/Power Mode/Power bằng NavigationView; mở = SpringAnimation fade+slide+scale,
      đóng = TimedAnimation ease-in; Esc/mất focus đóng), `ui/osd.rs` (fade). Lệnh: `swayctl-bar quick`,
      `swayctl-bar osd volume-up|…` gửi tới instance đang chạy (GApplication).
- [x] Python: `bar.program` (waybar|swayctl-bar), `native_config/native_css` (map module waybar -> workspaces/
      mode/window/clock + 1 cụm `status`), phím XF86 -> OSD (gỡ khi về waybar), không restart khi đổi file
      (bar tự theo dõi). PKGBUILD `packaging/swayctl-bar/`, optdepends ở gói chính.
- [x] Đo: renderer mặc định (Vulkan) 39 MB, 0% CPU; ngl 123 MB (driver GL), cairo 27 MB (CPU) -> giữ mặc định.
      Popup/OSD KHÔNG blur của compositor (bóng CSS trong lề trong suốt sẽ thành khối tối).
- [x] Sandbox: D-Bus riêng không có servicedir (`tools/sandbox-bus.conf`) -> không kích hoạt dịch vụ đã cài.
- [x] Tray: `services/tray.rs` - làm StatusNotifierWatcher nếu tên còn trống (không thì theo watcher sẵn có),
      host đọc IconName/IconPixmap (ARGB -> MemoryTexture A8r8g8b8)/ToolTip/Status, theo NewIcon...; click trái
      Activate (qua `clicked` của Button), giữa SecondaryActivate, phải = dbusmenu (GetLayout -> gio::Menu,
      Event "clicked"), không có menu thì ContextMenu. Module `tray` (waybar "tray" map sang). Test:
      `tools/fake_tray_item.py` + `tools/tray_test.sh` (TRAY_X=1830). RAM vẫn 39.4 MB.

## Mốc 4 - cuộn mượt trong nhân (XONG)
- [x] Patch 3 fork: `sway/input/smooth_scroll.c` - móc ở cuối `handle_pointer_axis` (seatop_default), sau
      binding/cuộn thanh tab. Touchpad: low-pass + quán tính sau khi nhấc (giữ axis_stop tới cuối, client
      không coast lần 2; dừng trước khi nhấc >60ms = không coast). Bánh xe: mỗi nấc thành 1 lần trượt tổng
      quãng = nấc x4 px (WHEEL_PIXELS_PER_DELTA), ramp như daemon python. Phát theo tần số màn hình dưới
      con trỏ. Lệnh: `input <id> smooth_scroll enabled|disabled`, `scroll_friction <0-1>`, `scroll_ramp <ms> <pow>`,
      cửa sổ: `scroll_native enable` (cho for_window). Feature `smooth-scroll` trong get_version.
- [x] Test: `tools/vptr/vptr` (wlr virtual pointer, KHÔNG uinput) + `tools/scroll_probe.py` + `tools/scroll_test.sh`
      (`tools/sandbox.sh --fx /home/repo/tools/scroll_test.sh`). Bài học: luôn kết thúc nhóm axis bằng frame
      (thiếu frame làm GTK segfault); con trỏ ảo phải sống tới hết coast.
- [x] swayctl-center: module scrolling phát hiện feature -> gửi lệnh, ghi `enabled:false` cho service python,
      sway giữ cuộn của libinput (không `scroll_method none`); trang Mouse & Touchpad ẩn ô cài service, chỉ hiện
      Glide/Ease-in (tốc độ/chiều = cài đặt cuộn của thiết bị).
- [ ] (tuỳ chọn) blur theo opacity layer: bỏ - popup không dùng blur compositor.

## Mốc 5 - app cài đặt (PHẦN LỚN XONG)
- [x] libadwaita: Adw.Application/ApplicationWindow, NavigationSplitView + breakpoint 640sp (gập 1 cột),
      ToastOverlay (`win.notify()`), app tự theo token theme (adwaita_css từ status) + ép sáng/tối theo theme.
- [x] i18n: `swayctl_center/i18n.py` (dict, không cần .mo), áp ở 1 chỗ cho mọi nhãn schema + menu + tiêu đề +
      lựa chọn; test bắt buộc mọi nhãn schema có bản tiếng Việt. Còn tiếng Anh: chuỗi viết thẳng trong ui.py
      (dòng trạng thái, "Advanced", vài nút) và trang pages/*.
- [x] Chuyển đổi dữ liệu: theme 4 màu dùng nguyên (token tự sinh); module waybar -> swayctl-bar map tự động.
- [x] Khoá màn hình: swaylock theo token (ring/sai mật khẩu/xác minh).
- [ ] Polkit agent riêng: CHƯA - code bảo mật, sandbox không có polkitd để test; giữ polkit-gnome.
- [ ] Wizard: chưa thêm bước "giao diện hiện đại" - wizard.py đang có thay đổi dở của người dùng, tránh đụng.

## Còn lại / làm sau
- Polkit agent riêng (cần môi trường có polkitd để test), bước "giao diện hiện đại" trong wizard,
  dịch nốt chuỗi viết thẳng trong ui.py/pages, các mục "sau" của lộ trình (kanshi, portal, chụp màn hình,
  Alt-Tab, hiệu ứng kính).
- Chưa thử trên phiên thật: cài `packaging/swayctl-fx` + `packaging/swayctl-bar` rồi đăng nhập
  "Sway (swayctl-fx)"; "Sway" gốc luôn còn để quay lại.

## Mở khoá bằng vân tay (chỉ vân tay + mật khẩu; khuôn mặt đã BỎ theo yêu cầu)
- [x] `swayctl_center/auth.py`: khối PAM có marker (`auth sufficient pam_fprintd.so`) chèn TRƯỚC dòng auth đầu
      tiên của sudo / polkit-1 (chép từ /usr/lib/pam.d) / ly; kiểm tra mọi dòng cũ còn nguyên; backup
      `*.swayctl-backup` một lần; `restore_script` gỡ sạch. Dịch vụ màn hình khoá: `swayctl-lock-{password,fingerprint}`.
      Schema `auth.fingerprint_{lock,sudo,polkit,login}` + `auth.lock_screen`; trang Nguồn & khoá > Vân tay
      (cài fprintd / `fprintd-enroll` trong terminal, Áp dụng/Hoàn tác qua pkexec - không bao giờ tự ghi).
- [x] `swayctl-lock`: ext-session-lock (FFI gtk4-session-lock), PAM song song (mật khẩu theo Enter, vân tay lặp),
      `--fingerprint`, `--daemonize`. Test: `SANDBOX_PAM=tools/pam-test tools/sandbox.sh --fx /home/repo/tools/lock_test.sh`.
- [ ] Chưa test: sai mật khẩu (cần bàn phím ảo), fprintd thật.
- Máy này KHÔNG có cảm biến vân tay (lsusb) -> bước cài đặt thật chỉ làm được khi có đầu đọc (USB).

## Liquid Glass (XONG cả 2 mức)
- [x] Mức 1: popup/OSD không còn tự vẽ bóng trong lề (compositor vẽ bóng/blur/bo góc theo đúng surface);
      `freeze_size` = đúng kích thước card (hết dải thừa). CSS kính khi `effects.glass`: nền trong 30-42%,
      viền trắng 22%, highlight inset trên. Bar phụ thuộc section `effects`.
- [x] Mức 2: SceneFX `glass.frag` (SDF hình bo tròn -> khúc xạ vào trong ở viền, tách màu, rim light),
      `wlr_scene_blur_set_glass` + `fx_glass_options` (header `scenefx/types/fx/glass.h`), vẽ thay cho texture
      blur trong `fx_render_pass_add_blur`. SwayFX: `layer_effects <ns> "glass enable"`, `glass_refraction <px>`,
      `glass_highlight <0-1>`; edge = corner_radius*1.4. Feature `glass`. Commit: scenefx 0eb5295, swayfx 8a157edc.
- [x] swayctl-center: `effects.glass`, `effects.glass_refraction` (22); khi glass: blur nhẹ (2 lượt, r=3),
      saturation 1.35. Preset modern bật glass. `tools/glass_shot.sh` so sánh plain/glass.

## Cài đặt chỉ còn phần mới + thông báo của swayctl-bar (2026-10-03, XONG)
- [x] swayctl-bar là server `org.freedesktop.Notifications` (`services/notify.rs`: zbus interface trên luồng zbus
      -> async_channel -> main loop; lịch sử 50, DND, resident/transient, image-data/image-path/app_icon, replaces_id,
      ActionInvoked/NotificationClosed). Popup `ui/notify.rs`: 1 layer surface ns `swayctl-notifications` (Overlay),
      card trượt (Revealer) + co surface theo card, rê chuột dừng đếm giờ, tối đa `max_visible`. Quick Settings:
      tile DND (của bar, swaync-client chỉ khi server khác giữ tên) + 5 thông báo mới nhất + "Clear"; mở Quick
      Settings dọn popup. Lệnh `swayctl-bar dnd on|off|toggle`. Không lấy được tên (swaync đang chạy) -> chỉ log.
- [x] Python: `notifications.program` (ẩn, swayctl-bar|swaync); native -> không unit swaync (dừng unit cũ, vẫn mask
      swaync.service), cài đặt đi vào `config.json` của bar (`notifications`), bar depends_on notifications.
      Kính: ns mới trong PANEL_NAMESPACES + SHAPED, CSS `.notification-card` trong native_css.
- [x] Ẩn khỏi UI (giữ trong store): bar layer/spacing/margin/exclusive/clock_format_alt; effects shadows/blur*/panels/
      animations; notifications các key riêng swaync. Cuộn: chỉ hiện khi compositor là swayctl-fx (không còn tuỳ
      chọn cho service Python), bỏ mouse_ramp_floor.
- Test: `tests/test_native_notifications.py`; `tools/sandbox.sh --fx /home/repo/tools/notify_shot.sh` (popup, -r,
  hết hạn, Quick Settings, DND); `tools/settings_shot.sh <page>...` chụp trang cài đặt với daemon thật.
- Còn: chưa test bấm nút action/click card bằng con trỏ ảo; chưa có chấm báo trên bar khi có thông báo mới.
- [x] Quick Settings mở vẫn cuộn được cửa sổ: catcher giữ để bắt click ngoài; sự kiện cuộn đầu tiên làm input region
      của catcher rỗng (+ `seat - cursor move 0 0` để sway chọn lại surface dưới con trỏ), 1.5 s sau bắt lại.
      Mất 1 sự kiện ở đầu (và khi bắt lại giữa lúc đang cuộn). Thử OnDemand + đóng khi mất focus: KHÔNG được -
      sway bỏ focus layer khi đổi Exclusive->OnDemand, GTK không báo is-active cho layer. Test: `tools/quick_scroll_test.sh`.
- [x] Walker kính lỏng kiểu Quick Settings: panel trong suốt, ô nhập/mỗi mục/mỗi gợi ý phím (cả khối .keybind) là 1 mảnh kính; mục chọn = kính màu accent. ns `walker` trong SHAPED. `tools/launcher_shot.sh`.
- [x] Lịch ở đồng hồ: layer surface riêng `swayctl-calendar` (ui/calendar.rs, popover GTK không thành kính được),
      catcher dùng chung `ui/catcher.rs` (cả Quick Settings), ns trong SHAPED. `tools/calendar_shot.sh`.
- [x] Chỉ còn 2 theme: `light` (#f5f5f7 / chữ #1d1d1f) và `dark` (#1c1c1e / chữ #f5f5f7), accent #0a84ff.
      `themes.LEGACY` đổi tên cũ (gruvbox/nord/dracula/solarized/modern-*) -> light/dark, không báo "missing".
      light_theme/dark_theme/bar.theme ẩn. Kính: tint tối thiểu 38% (dark, kính khói) / 16% (light, kính sữa),
      bóng chữ theo màu chữ (`_text_shadow`). File theme người dùng vẫn đọc được nhưng UI không chọn được nữa.
- [x] Đọc được trên nền nhiều chữ (máy thật): kính dày hơn - tint tối thiểu 55% (dark) / 50% (light), blur kính
      3 lượt r=5 (trước 1/2: chữ phía sau còn sắc và lẫn với chữ của mình), khúc xạ mặc định 18 (trước 40),
      viền đen `GLASS_EDGE` (1px alpha(black,.55)) quanh mọi tấm kính. Walker kiểu Spotlight: ô tìm 1 viên kính
      (chữ to), kết quả 1 tấm kính chung (mục chọn = accent), dải gợi ý phím riêng. Nền thử: tools/launcher_shot.sh (trang chữ).
- [x] Quick Settings theme Light: thanh trượt/icon theo màu chữ (đen trên kính sáng), dòng "Notifications/Clear" trên kính.
- [x] App đổi theo light/dark (`swayctl_center/appthemes.py`, key `appearance.apps_follow`): GTK3 gtk-theme adw-gtk3(-dark)
      nếu có adw-gtk-theme, không thì Adwaita(-dark) + settings.ini prefer-dark (trình duyệt/Electron đoán theo GTK3);
      Qt: QT_QPA_PLATFORMTHEME=xdgdesktopportal vào môi trường systemd/D-Bus (không đụng nếu user đã đặt); foot
      [colors-dark]/[colors-light] + SIGUSR1/2, kitty *.auto.conf, alacritty import (chỉ tạo alacritty.toml nếu chưa có).
      Giới hạn: app mở bằng phím tắt sway không có biến Qt (env của sway); wezterm chưa làm.
- [x] Trang con Quick Settings (Wi-Fi/Sound Output/Power Mode/Power): không panel; header, từng dòng, nút "Wi-Fi Settings…" là kính riêng có viền. `THEME=light tools/sandbox.sh --fx …/quick_subpage_test.sh`.
- [x] Kính theo đúng cài đặt: bỏ sàn tint (chỉ giữ 1% cho shaped glass), Glass frost quyết định blur (0 = 0 lượt, 100 = 3 lượt r5); mặc định tint 50 (max 90), frost 100.
- [x] Dark = kính khói trong: tint = 45% + 55% x setting (không bao giờ trong suốt); light = đúng setting. Mờ chỉ do frost.
- [x] Danh sách thông báo trong Quick Settings cuộn được: chiều cao = tự nhiên, tối đa phần màn hình còn trống (tự đo, ScrolledWindow không báo natural height). tools/quick_long_list_test.sh; vptr wheel/finger nhận VPTR_X/VPTR_Y.
- [x] Kính cho cửa sổ thường: fork commit d4f0ed97 `glass enable|refraction|blur` (for_window), mask = buffer của cửa sổ, feature glass-windows. effects gửi for_window (quoted, sway tách lệnh ở dấu phẩy) cho app cài đặt; app nạp `app_glass_css` (nền trong, sidebar/list/header/nút/ô nhập/tiêu đề trên kính). tools/settings_shot.sh GLASS=1 THEME=…
- [x] App: không viền focus (border none trong rule kính), sidebar = viên kính mỗi mục + chip tên nhóm, list không khung = viên kính mỗi dòng, mọi nhãn ngoài list/nút lên kính (box > label; loại trừ dùng :not(.glass-chip) để thắng specificity). Bar: không panel, mỗi module một viên kính (swayctl-bar chuyển sang SHAPED).
- [x] App không đổ bóng: rule kính thêm `shadows disable` (gửi sau lệnh shadows toàn cục nên thắng).
- [x] Kính tự nhiên hơn: scenefx 74ee83b - mép kính làm nhoè ảnh phía sau (12 mẫu hình elip lớn dần về mép), tách màu x0.6, viền sáng mềm. swayctl-fx pkgrel=2.
- [x] Kính app lệch khỏi khung: scenefx 782d579 - mask theo source box của buffer (cửa sổ CSD có lề resize vô hình).
      Bar/popup không đổi (source box = cả texture). swayctl-fx pkgrel=3.
- [x] swayctl-lock không nhận mật khẩu đúng: bỏ pam_acct_mgmt (dịch vụ dự phòng /etc/pam.d/swaylock không có
      "account" -> luôn PERM_DENIED). Test: tools/pam-test/swayctl-authonly-fingerprint +
      `SANDBOX_PAM=tools/pam-test tools/sandbox.sh --fx env PREFIX=swayctl-authonly- /home/repo/tools/lock_test.sh`
      (bản cũ: "still locked: FAIL").
- [x] B1 chữ luôn đọc được trên kính: shader text_mode (scenefx bffb67a) làm tối/sáng nền sau kính vừa đủ 4.5:1 so với
      màu chữ; sway 09aaaf53 `layer_effects <ns> "glass_text light|dark|none"`, `glass text …` cho cửa sổ, feature
      glass-text. effects gửi theo theme (bar = none). Nhoè sâu hơn: bevel tới 40% nửa cạnh ngắn (box), kính theo hình
      đo độ dày tại chỗ (reach = max(edge*2.5, 48)), smear = refraction*0.6*rim^1.5 + 4*rim.
- [x] B2 bar chữ theo hình nền: config.json `backdrop` (image/mode/color/tint_dark/tint_light, chỉ khi glass);
      swayctl-bar ui/backdrop.rs lưới độ sáng 96x54 theo kiểu căn của sway, mỗi module class on-light/on-dark
      (so tương phản chữ sáng trên kính khói vs chữ tối trên kính sữa), gắn lại khi map + đổi workspace.
      tools/adaptive_shot.sh (THEME, TINT, INVERT).
- Còn: B3 (compositor đo nền thật qua IPC) chưa làm.
- [x] Chữ sáng/tối theo nền cho popup và app: popup (Quick Settings, lịch, thông báo) chụp nhanh màn hình bằng `grim -s 0.2`
      ngay trước khi hiện -> lưới độ sáng, gắn on-light/on-dark cho từng tấm kính (tag_panes); app: swayctl_center/backdrop.py
      (hình nền theo vị trí cửa sổ từ get_tree, cửa sổ xếp ô không chồng nhau), gắn lại khi đổi trang/kích thước/focus.
      Mỗi tấm kính thêm tint-0..10 = độ dày tối thiểu để đạt 4.5:1 ở chỗ nền khó nhất phía sau (min/max, không chỉ trung bình).
      Các surface/cửa sổ này gửi glass_text none (tự lo). Walker (app ngoài) vẫn dùng glass_text theo theme.
      Giới hạn: app thả nổi (floating) đè lên cửa sổ khác vẫn tính theo hình nền.
- [x] Nhoè toàn tấm kính (smear = refraction*(0.35+0.6*rim^1.5)+4*rim) + damage padding 112px cho kính (scenefx). fx pkgrel=2.
- [x] Nhoè mịn: 24 mẫu gaussian xoay theo nhiễu từng điểm ảnh, đo mép 24 bước có nội suy (scenefx). fx pkgrel=3.
- [x] Kính trong: smear = refraction*0.7*rim^3 + 3*rim^2 (giữa sắc), bỏ nhiễu xoay; damage cả tấm kính khi một phần bị vẽ lại (hết dải). fx pkgrel=4.
- [x] Bỏ nhoè; ánh sáng qua kính: mép dẫn sáng (sáng + đậm màu), dải caustic phía đối diện nguồn sáng, vệt sáng chéo. fx pkgrel=5.
- [x] Kính kiểu macOS: mép thấu kính (shift x(1+1.2u^2)), viền phản chiếu 2 góc chéo, vibrancy, tối nhẹ mép dưới; refraction mặc định 28. fx pkgrel=6.
- [x] Kính theo hình: trường độ phủ mượt (3 vòng x 16 hướng) cho độ sâu + pháp tuyến (hết răng cưa, mọi tấm cùng mép); bỏ qua khi c>0.999; thấu kính 1+0.4u^2, tách màu x0.3. fx pkgrel=7.
- [x] Tắt tự đổi màu theo nền (adaptive=false, glass_text none, app không gắn on-light/on-dark; code còn giữ). Kính kiểu chất lỏng: viền sáng sắc, dải tối bên trong, vệt phản chiếu mềm; kính theo hình: hướng từ độ dốc trường (bước rộng), khoảng cách bằng chia đôi trên mép mask (hết sọc). fx pkgrel=8.
- [x] Viền bóng (dải sáng trong mép trên, bỏ dải tối); shader nhẹ hơn: kiểm 8 điểm cho phần giữa, trường 25 mẫu. fx pkgrel=9.
- [x] Mép trên lúc có lúc không: trường độ phủ đếm xuyên khe sang tấm kính bên cạnh (nút cách ~10px) -> mỗi hướng dừng ở bước đầu ngoài kính; mask nhận mọi alpha>0; tint sáng tối thiểu 2%. fx pkgrel=10.
- [x] Nhẹ hơn: bỏ vẽ lại cả tấm kính (không còn nhoè), padding 64px, kiểm phần giữa 24 mẫu (8px, nửa, cả bevel). fx pkgrel=11.
- [x] Cuộn mượt hơn: mép kính theo hình = 8 hướng dò + chia đôi (min mềm, pháp tuyến trung bình trọng số), bỏ trường độ phủ: điểm mép ~64 lần đọc (trước ~300). fx pkgrel=12.
- [x] Răng cưa: viên kính mỏng hơn 2 lần bevel bị xé ở đường giữa -> bevel <= nửa độ dày tại chỗ (cặp hướng đối nhau). 12 hướng, chia đôi 7 bước, đọc nền bilinear tự làm, 2 mẫu dọc chỗ ép. fx pkgrel=13.
- [x] Bar nhân bản chữ khi đổi workspace: tấm kính nhỏ (<15% màn hình) vẽ lại cả tấm. fx pkgrel=14.
- [x] Hiệu ứng từ khung đầu: daemon ghi generated/swayctl-fx.conf (layer_effects + for_window app), swayctl-fx (88d91660) đọc kèm config khi khởi động/reload; app nạp CSS kính trước khi present. tools/startup_fx_test.sh.
- [x] Bóng bẩy kính: giữ nguyên ánh sáng (rimline, gloss trong mép, Fresnel, sheen trên); thêm lớp polish cùng `highlight` — core trắng ~0.3px trên mép, vệt sáng dưới bevel (đèn phía trên), phản chiếu đèn elip góc trên-trái + streak theo hướng sáng trên mặt kính (chỉ rounded-box; shaped panes không có p theo mặt). glass.frag cả fork lẫn packaging/src. fx pkgrel=2.
- [x] OSD âm lượng/độ sáng kiểu macOS: pill kính sữa, icon + % màu tối, thanh xanh accent bo tròn; radius compositor 999; Quick Settings slider cùng style. osd.rs + default.css + glass_css; tools/osd_shot.sh. bar/center pkgrel=2.
- [x] Toàn bộ shell theo look OSD (user: OSD là chuẩn cho mọi UI, không chỉ OSD): bar/Quick/thông báo/app/launcher/native_css/default.css — milk_fill trắng, MILK_RIM viền trắng 0.48, MILK_TEXT #1d1d1f, scale trough đen 0.14 + highlight accent; bỏ GLASS_EDGE dark; milk_opacity() dùng glass_opacity thô (không smoke floor dark). Khi glass bật: panel trong suốt (native_css panel_bg=none, glass_css !important clear .quick-panel/navigation-view); khi glass tắt: fallback milk từ native_css. default.css chỉ giữ shape, paint bởi style.css. bar/center pkgrel=3. 196 test xanh.
- [x] Kính Tahoe (theo ảnh macOS thick glass): shader glass.frag (fork 901e1c1 + packaging/src) — refraction curve 1+0.95u², spread 0.18, chroma 0.45, Beer-Lambert absorption mép (0.62/0.70/0.68), Fresnel 0.42, rimline/core/gloss/bounce mạnh hơn; schema defaults glass_refraction=48, glass_blur=40 (trong, không frosting 100); milk_opacity() ×0.55 khi compositor glass bật để lộ khúc xạ (ui.py settings app cũng vậy); i18n help mới; glass_shot/osd_shot defaults khớp. Gói: center-0.1.0-4, bar-0.1.0-4, fx-0.6.r18.88d91660-3 → dist/swayctl-setup + tar.gz. 196 test xanh.
- [x] Tự chỉnh liquid glass trong center (theo https://winaviation.github.io/liquid-glass-demo/): fork swayfx `bbb6a563` — `glass_highlight` (specular 0-1), `glass_edge` (bezel px, 0 = auto theo bo góc), `glass_chroma` (dispersion theo bội refraction; **-1 = auto 0.12, 0 = không tách màu**); plumbing layer_criteria/layers/container/output.c (layer + window path), `glass highlight|edge|chroma` cho for_window, IPC feature `glass-tune`. Center: schema 3 key mới + nhóm "Liquid glass" trong Effects + slider labels + i18n vi; `layer_effects`/`app_glass` gửi highlight luôn, edge/chroma sau feature `glass-tune`. Bỏ qua Surface Type (convex/concave) — shader chỉ có profile ¼ tròn. 196 test xanh. Cài: `tar xf dist/swayctl-setup.tar.gz && cd swayctl-setup && ./install.sh` → đăng xuất chọn "Sway (swayctl-fx)".
- [x] Sửa slider int: `SliderRow` gửi float từ Gtk.Scale → `effects.glass_opacity: expected an integer, got 48.113`. `slider_out()` cast int cho key int + step 1; schema nhận float nguyên (48.0 → 48), vẫn từ chối 48.113. Gói: center-0.1.0-6, fx-0.6.r19.bbb6a563-1 (bar giữ 0.1.0-4) → dist. 197 test xanh.
- [x] Body refraction toàn panel (demo Bezel 70 / Thickness 200 / Refraction 3x): fork scenefx `14b6b95` — glass.frag thêm body dome toàn pane (Snell lệch ra ngoài, Beer-Lambert body_tint theo thickness/200), `thickness` uniform (glass.h, shaders.h/c, fx_pass.c, wlr_scene.c, scale theo surface). swayfx `279ed546` — `glass_thickness <0-300>` (0 = chỉ rim như cũ), plumbing layer_criteria/layers/container/output.c cả layer + window path. Center: defaults mới refraction=60 (max 120), edge=70 (max 120), thickness=200 (max 300); schema HELP + i18n vi; ui.py GROUPS/SLIDERS/visible_when; effects.py gửi thickness sau glass-tune. Gói: center-0.1.0-7, fx-0.6.r20.279ed546-1, bar-0.1.0-4 → dist/swayctl-setup + tar.gz. 198 test xanh.
- [x] Kính dày hơn 5 lần: max glass_thickness 300 → **1500** (user: độ dày chưa đủ). swayfx `279ed546`→ mới (layer_criteria + glass cmd 0-1500); scenefx damage margin = refraction + chroma + thickness*0.07*refr_scale (trước chỉ refraction+chroma → pane dày sample ngoài vùng copy). Center schema max=1500. Gói: center-0.1.0-8, fx-0.6.r21.*-1. 198 test xanh.
- [x] Viền thể hiện độ dày kính: scenefx `46ad79b` — `pane = thickness/200`, `rim_wide = 1+0.5*min(pane,3.5)` mở rộng bevel (mask + rounded-box) và mọi dải sáng/tối ở mép (rimline/gloss/inner/core/bounce), `rim_bend` kéo mạnh hơn, spread rộng hơn, hấp thụ Beer-Lambert mép sâu hơn, Fresnel + self-shadow nhẹ hơn. Trước đó thickness chỉ nuôi body dome, mép vẫn là hairline. PKGBUILD fx: pkgver() ghép cả hash scenefx (scenefx-only change cũng bump version). Gói center-0.1.0-9, fx-0.6.r21.d603c79b46ad79b-1, bar-0.1.0-4. 198 test xanh.
- [x] Shader kính theo đúng demo https://winaviation.github.io/liquid-glass-demo/ (kube.io): user nói look đang khác hẳn và **viền phải khúc xạ màu từ phía sau**. scenefx `b80f0a9` — viết lại `glass.frag`: port model demo (convex squircle `h(x)=(1-(1-x)^4)^{1/4}`, Snell `remaining=h(x)*bezel+thickness`, specular dải mỏng, bỏ body dome/Beer-Lambert caustic invent). Thickness chỉ nuôi path length ở mép → trung tâm trong, mép bẻ mạnh; chroma (px = refraction×fraction) tách R/B fringe (IOR 1.475/1.50/1.53). Damage margin = refraction + 0.20×refraction + 6. swayfx `ccdfe99a` — refraction/edge max 140, auto chroma 0.12→0.40, auto highlight 0.55→0.50. Center defaults demo-like: refraction=80 (max 140), blur=20 (gần trong), highlight=0.50, chroma=0.40; schema HELP + i18n vi mới. Gói: center-0.1.0-10, fx-0.6.r22.ccdfe99ab80f0a9-1, bar-0.1.0-4 → dist/swayctl-setup + tar.gz. 198 test xanh. Cài: `tar xf dist/swayctl-setup.tar.gz && cd swayctl-setup && ./install.sh`.
- [x] Đưa lại hiệu ứng ánh sáng (user: mất phần light): scenefx `f115f7c` — giữ model demo (squircle+Snell+chroma), lắp lại stack light cũ: Fresnel theo tilt squircle, rimline + gloss + inner reflection (độ rộng theo `rim_wide=thickness`), core trắng, bounce, lamp spot + streak (chỉ rounded-box), self-shadow mép dưới, top sheen, Beer-Lambert mép nhẹ; mọi lớp theo `highlight`. Gói mới fx-0.6.r22.ccdfe99af115f7c-1 → dist + tar.gz.
- [x] Bar + Quick Settings = đúng demo Precision Lens (user: "tạo đúng phần liquid glass lên bar và quicksetting như đúng demo"): `DEMO_LENS` trong effects.py — bar edge=12/thick=70/refr=40/hl=0.95, quick edge=18/thick=90/refr=50/hl=0.95, osd edge=0/thick=70/hl=1.0 (blur=0, chroma≈0.3). glass_css: bỏ milk Tahoe → capsule trong `alpha(white,0.035)` + viền trắng specular `1.5px solid alpha(white,0.88)` + inset/bloom như demo. milk_opacity khi glass on ×0.20 (gần trong). Defaults center: refraction=50, opacity=10, blur=0, highlight=0.90, edge=20, thickness=90, chroma=0.35. glass_shot.sh khớp DEMO_LENS. 198 test xanh. Gói center-0.1.0-11 → dist + tar.gz (fx giữ 0.6.r22.ccdfe99af115f7c-1).
- [x] Kính liquid = mock đã duyệt, sửa đúng hình + kiểm chứng bằng số: (1) **Hình sai = bóng ngoài CSS** — `LENS_SHADOW 0 2px 10px` làm mờ `mask_at` (chia 0.003) nên mask = hộp panel, trong khi mock không có bóng ngoài (CSS backdrop-filter bỏ alpha); bỏ shadow ở 12 capsule trong `glass_css` (giữ `.osd` — path box, vô hại), body tint 0.06 giữ nguyên. (2) **596 px phản hồi** — `d = -clamp(-log(wsum/12)/soft_k)` bị 11 hướng còn lại kẹt ở `bevel` (wsum sàn ~0.55) làm loãng → cả mép đọc x≈0.7 → field≈0; sửa `d = -min(dmin, bevel)` (khoảng cách viền gần nhất) + `thick` chỉ tính cặp hướng **cả hai** tới viền (`reached[12]`), không thì `thick=1e4`. (3) `PANE_RADIUS` gửi radius thật (bar theo `modern`: radius_lg / quick radius_lg+6) vì glass mode blur radius=0; `CARD_SURFACE` (thông báo/lịch/walker/swaync) giữ `shadows disable`, bar/quick `shadows enable`. (4) bỏ debug shader, dựng lại xanh. **Đo A/B** (`tools/out/probe.sh`): glass-off vs r0 = 0 px; r0 vs r87 = 22.903 px (mật độ: giữa capsule ≈0, đổi chỉ ở dải bevel mọi viên, ngoài panel 0, khe OFF→glass lệch +3/255); 0 lỗi GLSL (trừ warning corner_radius pre-existing). Note: bóng từng ô trong mock không giữ được trên capsule (đầu độc mask) → thay bằng bóng panel compositor (khớp `default.css` ghi chú); ảnh Read tool hay trả cache lệch → tin số liệu density. packaging/src sync 4 file (glass.frag, fx_pass.c, wlr_scene.c, blur_data.c). 198 test xanh. Gói: scenefx commit `cac4d2c`, center-0.1.0-12, fx-0.6.r22.ccdfe99acac4d2c-1, bar giữ 0.1.0-4 (source không đổi) → dist/swayctl-setup + tar.gz; makepkg fx cần shim arch-meson/meson (uvx --with ninja --from meson — hệ thống không có meson/ninja). Center repo chưa commit.
- [x] Panel Quick Settings đục trắng (user) — **CSS glass viết `!important` bị GTK4 từ chối**: test parse trực tiếp (`Gtk.CssProvider` + `parsing-error`) chứng minh `background: none !important` → "Expected a valid color", `background: #ff00ff !important` / `box-shadow … !important` → "Junk at end of value", `border-color: none` → "none is not a valid color" (chỉ `background: none` / `border: none` là hợp lệ). Hệ quả: mọi rule clear của `glass_css` (`window.quick-window`, `.quick-panel navigation-view`) bị drop → nền Adwaita trắng thò ra (sandbox không có theme nên không tái hiện được milky, chỉ thấy lỗi log). Sửa `components.py`: bỏ hết ` !important` (4 chỗ — provider APPLICATION+1 vẫn thắng Adwaita/DEFAULT_CSS), `panel_border` glass = `transparent`. Hot-reload GIO monitor của bar **hoạt động đúng** (append `.quick-panel{background:#ff00ff}` không important → 62.634 px magenta khi panel đang mở); trước đó test reload fail là do harness (panel không mở / `effects.sh` rỗng vì gọi `EffectsModule.commands` không qua instance → iterable rỗng → mất hết `layer_effects`, kể cả quick — không phải lỗi app). Bar log giờ **0 Theme parser error**. 198 test xanh. Gói center-0.1.0-13 → dist/swayctl-setup + tar.gz (fx/bar giữ nguyên). Center repo vẫn chưa commit.
- [x] Đo ảnh thật `/tmp/qs-now.png` (3072x1920, panel mở trên terminal trắng): interior 243.8–247.9 vs nền cùng cửa sổ 245.0 → chênh +1.6/255 (~0.6%) = **panel trong suốt, không wash GTK**; dip bóng 196 ở rìa = bóng compositor. User: "nó là phần shadow của panel đó, ẩn shadow đi" → `effects.py` thêm `NO_SHADOW = CARD_SURFACE + ("swayctl-quick",)` (bỏ `shadows enable` cho quick; bar giữ nguyên), test line 114 đổi theo. 198 test xanh. Gói center-0.1.0-14 → dist/swayctl-setup + tar.gz. Apply ngay: `swaymsg 'layer_effects "swayctl-quick" "shadows disable"'`. Center repo vẫn chưa commit.
- [x] Ẩn shadow cả bar (user gửi ảnh: bóng dưới các viên pill): `NO_SHADOW = CARD_SURFACE + ("swayctl-quick", "swayctl-bar")` trong effects.py, test đổi theo (bar/quick `shadows disable`; OSD + cửa sổ giữ bóng). 198 test xanh. Gói center-0.1.0-15 → dist/swayctl-setup + tar.gz. Apply ngay: `swaymsg 'layer_effects "swayctl-bar" "shadows disable"'`. Center repo vẫn chưa commit.
- [x] Bar/Quick Settings/OSD đi theo setting Liquid glass (user: "bar và quicksetting không đi theo setting liquid glass của center setting") — 2 chỗ bị ghim: (1) `DEMO_LENS` trong effects.py pin cứng refraction/highlight/blur/edge/thickness/chroma của bar/quick/osd theo preset demo (test còn assert osd refraction 87 vs setting 50, bar edge 13, thickness 200, chroma 0) → bỏ hẳn DEMO_LENS, mọi surface đọc `v["glass_*"]` như cửa sổ (mẫu số verify: quick nhận 50/0.9/0/20/90/0.35); (2) `BarModule.glass_css` body = hằng `LENS_BODY 0.06` bỏ qua `glass_opacity` (launcher/notifications đã dùng milk_opacity) → `body = alpha(white, {opacity:.3f})`, mặc định 10% → 0.040 (floor), slider 50 → 0.100. Cập nhật tooltip schema (bớt câu "demo-capsule values") + i18n EN/VI, comment schema; test: test_effects assert theo setting + thêm test "they move with the sliders", test_native_bar tint theo slider; harness: glass_shot.sh đọc schema.defaults thay DEMO_LENS + shadows khớp NO_SHADOW (bar/quick disable, osd enable), liquid_wall.sh tự build demo_lens từ settings (giữ shape cho liquid-demo.html). 198 test xanh. Gói center-0.1.0-16 → dist/swayctl-setup + tar.gz. Center repo vẫn chưa commit.
- [x] Tối ưu khi nhiều kính (user: "hiệu năng UI hiển thị nhiều liquid glass bị chậm, tối ưu"):
      **SEGV có sẵn** — scenefx `wlr_scene.c` `wlr_scene_blur_set_transparency_mask_source` deref `source==NULL`
      khi `glass disable` cho cửa sổ (tái hiện 3/3, coredump: linked_node_destroy ← … ← output_configure_scene)
      → guard NULL (chỉ `linked_node_destroy(&source->blur)` khi source != NULL); test enable→disable→alive ✓.
      **Shader nhẹ hơn** `glass.frag`, xuất ảnh **đ pixel-identical** (glass_shot: glass-glass.png IDENTICAL,
      bar chỉ lệch giây đồng hồ 58px): nội bộ phẳng `x>=1` bỏ Snell + 3×demo_disp và backdrop 16 mẫu → 1 mẫu
      (giữ smear ±0.175px, mask n≠0 giữ nguyên); `chroma<=0` → r_amt==b_amt (0×hữu hạn=0) bỏ 2 demo_disp + 1 đọc.
      **Đã thử & BỎ**: bisection sớm 0.5px → Δ159, 0.125px → Δ35 (nóng lại đúng viền, dựng lại y nguyên cả 2 mức)
      → giữ chia đôi cố định 7 bước để giữ parity. **Đo**: mới `tools/fps_probe.sh` — foot damage + cửa sổ 24 viên
      kính + bar + quick, pha A idle / C damage / B damage+không kính, gpu_busy% + CPU ms/iter + grim + ảnh scene.
      Host yên: kính = **+19-20pp GPU busy, +4-5ms CPU**; phần opt nằm dưới độ phân giải counter GPU dùng chung
      (≤1-2pp; phiên thật của user gõ phím kẹt ~70% mọi pha → phải chạy lúc máy nghỉ) → bằng chứng chính là
      parity bit-identical + ít lệnh hơn, không phải delta fps. Sửa harness: glass_shot chờ 3s (1.1s chụp trúng
      lúc panel còn trượt → lệch layout ~80px), PILLS=0 cần 1 DrawingArea trống (GTK bỏ surface 0×0 → không map).
      packaging/src sync 2 file (glass.frag, wlr_scene.c). 198 test xanh. Chưa commit (fx 2 file + center tools;
      PKGBUILD fx theo hash git → chưa đóng gói).
- [x] B3 — **đo nền qua IPC**: bar đọc nền thật từ compositor thay cho grim (user chọn B3 thay i18n/commit/notification dot). Thao tác: RUN_COMMAND không truyền được data (`cmd_results_to_json` chỉ có success/error) → type mới `IPC_GET_BACKDROP=102` (ipc.h, sau GET_INPUTS/SEATS); payload `{output, cols/rows (mặc định 96×54, clamp ≤512), x/y/w/h logical tùy chọn (mặc định cả output)}` → reply `{success, output, x/y/w/h, scale, cols, rows, format:"rgb", cells:[rgb phẳng, row0-trên]}` (RGB thuần — client tự tính luma). Feature `backdrop-sample` trong `swayctl_features[]` (ipc-json.c); `swaymsg -t get_backdrop` (type table, reply in qua default pretty-print). Đọc pixels: scenefx `fx_renderer_read_buffer_pixels(renderer, buffer, x,y,w,h, rgb_out)` (fx_renderer.c/h) — make current → `fx_framebuffer_get_or_create` → glReadPixels RGBA → lật hàng (GL bottom-up) → khôi phục PACK_ALIGNMENT + FBO binding + EGL ctx; sway giữ `last_frame` = buffer commit cuối qua listener `wlr_output->events.commit` (`sway_output.commit/last_frame`, `wlr_buffer_lock`; unlock ở begin_destroy; bỏ khi MODE/ENABLED đổi). Synchronous, không forced frame; v1: chỉ transform=normal, chưa có frame → error. Bar `Grid::capture` (backdrop.rs) đổi thành IPC-first qua `services::sway::request(GET_BACKDROP=102)` rồi **fallback grim** (stock sway verify: buộc readback fail → vẫn tag được). Test `tools/backdrop_probe.sh`: wallpaper đặc RGB(30,100,200) → 4×4 grid/defaults 96×54/rect 1×1/error paths, chạy `sandbox.sh --fx` → PASS; adaptive_shot EXIT=0 với IPC path; get_version liệt kê backdrop-sample. **Nhiệm vụ điều tra noise RGB** trên kính panes phía nền tối: pre-existing (có sẵn trong zoom-quick.png 3/10, tắt readback vẫn còn) — không phải B3, để riêng. Python `backdrop.py` giữ nguyên (math theo wallpaper; đọc màn hình sẽ thấy cả cửa sổ settings). **Demo trước khi áp dụng** `tools/backdrop_demo.sh` (chạy qua sandbox --fx): wallpaper sáng/tối, so lưới IPC 96×54 với grim trung bình box — **tìm & sửa lỗi lật dọc** (glReadPixels rows đã top-down sẵn, code flip thừa → lưới úp; probe wallpaper đặc màu không bắt được → probe đổi wallpaper đỏ/trên-xanh/dưới + assert orientation + wallpaper 1920×1080 tránh scaler); composite script lỗi 2× `set_source_surface` (lớp lưới mất, paint lớp cuối) → paint từng lớp. Sau sửa: **mean|diff|=0.00/255, max=0.0 cả 5184 ô** (đ khớp grim từng ô, kể cả mép); probe PASS; adaptive_shot EXIT=0. 198 test xanh. Chưa commit (sway/ipc + scenefx readback + bar backdrop.rs/sway.rs + tools/{backdrop_probe,backdrop_demo}.sh).
- [x] Demo **panel liquid glass đổi chữ theo nền** `tools/glass_text_demo.sh` (user muốn xem trước khi áp dụng): 1 phiên sandbox — wallpaper sáng/trái-tối/phải → mở Quick Settings chụp (`gtd-quick-darkbg.png`), đổi wallpaper tối/trái-sáng/phải → mở lại chụp (`gtd-quick-lightbg.png`), ghép `gtd-side.png`. **Phát hiện 2 lỗi khiến adaptive "tắt ngầm":** (1) `components.py backdrop_config` hardcode `"adaptive": False` (tắt từ khi fx pkgrel=8, code giữ) → `Grid::capture` trả None ngay; (2) `adaptive_css()` (rule `.on-dark.on-dark.on-dark`/`.tint-N`) **không bao giờ được nối vào `native_css`** → class gắn vô ích. Demo patch cả 2 trong script (config `cfg["backdrop"]["adaptive"]=True` + nối `BarModule.adaptive_css(ctx)` vào style.css) — **sản phẩm chưa đổi, chờ user duyệt**; `adaptive_shot.sh` cũng patch tương tự (trước đây chụp "adaptive" nhưng thực ra default). Instrument retag/tag_panes xác nhận chạy (origin 1544,49; tints 0.50/0.10 @ glass_opacity=10) → gỡ debug. Kết quả đo pixel: state A DND title max=245 trên tile 22 (chữ sáng), right module p90=206 (chữ/ảnh sáng), clock min=34 trên pill 248 (chữ tối); state B đảo đúng chiều (title min=29/p10=88 trên 248, clock sáng trên pill tối 36); 198 test xanh. Ảnh: `tools/out/gtd-{quick-darkbg,quick-lightbg,side}.png`. Chưa commit.
- [x] Demo 3 trạng thái + **đảm bảo chữ đọc rõ trên mọi nền màu** (user: "background nhiều màu hơn trắng/đen, làm sao luôn đọc rõ"):
      **(1) Envelope guarantee** — compositor `sway/ipc-server.c`: box-downsample giờ track `lmin`/`lmax` (Y linear per cell, LUT srgb→linear) → reply thêm 2 mảng; bar `Grid` 3-torrent (lum,lmin,lmax), `capture_ipc` parse fallback `lum`, `capture_grim` full-res pool, `Grid::new` sample 2×2 subpoint/cell, `stats` dùng envelope, `choose()` chia needed alpha cho **0.9** (gradient tint-N bottom = alpha×0.9). Mirror `backdrop.py` (grid 3-tuple, /0.9). Tests: rust `mod tests` trong backdrop.rs (2), python `test_readable_over_every_color_and_detail` → **199 xanh**; `backdrop_probe.sh` phase 5 PASS (`mixed cell avg=63 lmin=0 lmax=255`).
      **(2) Bar retag live** — trước đây tag 1 lần lúc startup từ config wallpaper; `bar.rs` giờ `Grid::capture` (fallback `Grid::new`) + retag on map + `svc.sway.state.subscribe` + timer 2s (wallpaper đổi không sinh sway event); demo sleep 2.6s sau đổi nền.
      **(3) State C màu** — wallpaper 27 dải màu ngang 40px (palette `BANDS` 10 màu) → `gtd-quick-colorbg.png`, ghép `gtd-side.png` 3 cột.
      **(4) Debug sâu → tìm bug cascade thật**: instrument `tag()` (sau gỡ) + copy style.css ra `gtd-style.css` → CSS đúng hết; **`window.bar label` (glass_css, spec 0,1,2) thắng `.on-dark label` (0,1,1)** → mọi label trong bar bị ghim `#1d1d1f` → **clock ẩn chữ trên fill tối** (colorbg: interior toàn #1c1c1e, không pixel chữ). Icon (`image`) không có rule bar cạnh tranh → vẫn đúng. Sửa: bỏ rule thừa `label` ở glass_css (`label{}` line ~154 đã phủ) — **đổi product trong components.py** (199 test vẫn xanh). Test cascade tối giản `tools/gtk_cascade_probe.sh` (GTK4 + grim trong sandbox) chứng minh adaptive thắng `.quick-footer button` khi cô lập → lỗi không nằm ở specificity rule phụ.
      **(5) Gate demo viết lại** — gate cũ gamma + tọa độ sai (đo ngoài vòng nút/đứng nhầm chữ wallpaper) + luôn assume chữ sáng → FAIL ảo. Mới: Y tuyến tính WCAG (srgb→linear), chữ = percentile cực trị **p1/p99** của đuôi xa median (median = nền), rect thật: DND title/Off, slider icon, interior 3 nút (loại rim), clock, right module; ngưỡng **4.5 chữ / 3.0 icon** → **24/24 PASS** cả 3 state (thấp nhất: colorbg DND Off 4.88 — dim-label 0.75). Trước fix: colorbg clock 1.98→14.84.
      Ảnh: `gtd-quick-{darkbg,lightbg,colorbg}.png`, `gtd-side.png`, `gtd-z-*`. Sync `packaging/swayctl-fx/src/swayfx/sway/ipc-server.c` (lmin/lmax). 199 py + 2 rust xanh. **Pending user duyệt**: (a) `backdrop_config` adaptive=False, (b) nối `adaptive_css()` vào `native_css` — demo vẫn patch tay. Chưa commit.
- [x] **Áp adaptive vào sản phẩm + build gói cài đặt chính thức** (user: "áp luôn + build", "commit fx 2 repo"):
      (1) `components.py backdrop_config` → `"adaptive": True`; (2) `BarModule.files()` nối `+ self.adaptive_css(ctx)` vào `style.css` (kể cả khi có `style_template` — class.on-dark/.tint-N nếu không có rule sẽ vô nghĩa) — `native_css()` giữ nguyên nên test `assertNotIn(".on-light", native_css)` vẫn đúng; test `test_bar_backdrop` đổi `assertTrue` + assert 2 selector có trong `files() style.css`. Demo/adaptive_shot bỏ patch tay, giờ sinh config+style qua `BarModule().files()` (đường sản phẩm, end-to-end) → demo 24/24 PASS. `window.bar label` bỏ trước đó (spec 0,1,2 thắng `.on-dark label` → clock ẩn chữ).
      (2) Commit fx (bắt buộc — PKGBUILD `git+file://…#branch=swayctl`): swayfx `676960a3` "ipc: get_backdrop (B3) with per-cell lmin/lmax envelope"; scenefx `ff8ec86` readback + `b69f2f4` NULL guard + `f4dff2d` glass flat-interior opt.
      (3) Gói: center **pkgrel 16→17**, bar **pkgrel 4→5**, fx pkgver auto **0.6.r23.676960a3f4dff2d-1** (rev-count 22→23). Host không có meson/ninja → shim `/tmp/opencode/bin/{arch-meson,meson}` qua `uvx --with ninja --from meson`; makepkg bar/fx cần `-d` (cargo/meson không pacman-resolve được). Sanity: pkg center chứa `"adaptive": True` + `style + self.adaptive_css`; bin fx có string `lmin`/`lmax`; 199 py + 2 rust xanh. Ghép `dist/swayctl-setup/` (3 pkg + install.sh + README.txt) → `dist/swayctl-setup.tar.gz` (2.3MB). Cài: `tar xf dist/swayctl-setup.tar.gz && cd swayctl-setup && ./install.sh`. Chưa commit repo center.

## Phiên 2026-10-06 — chữ theo nền kiểu liquid-demo, probe nền, chiều cao bar, ChoSua (XONG, chưa commit center)
- [x] `tools/liquid-demo.html`: chữ thuần đen/trắng (ngưỡng 0.32/0.255 có hysteresis), halo theo độ rối + gần ngưỡng,
      chuyển màu mượt (@property), nút kính kéo thả; `liquid_wall.sh` xuất lưới `luma` mỗi nền (file:// không đọc được pixel).
- [x] Bar/Quick/OSD theo demo: `backdrop.rs` `ink_dark`/`halo`/`choose_ink` (+ `through_glass` theo glass_opacity, frost
      giảm halo), class `halo-0..4`; `components.adaptive_css(lens=True)` khi glass: kính trong, chữ #fff/#111114, transition.
      `config.json backdrop` thêm `lens/lens_tint/frost`.
- [x] Fork: **probe nền** (scenefx `fx_backdrop_probe` trên blur node, đọc bản sao kính sắp khúc xạ → không lẫn nội dung
      của chính surface; cộng dồn vùng vẽ lại, đủ khi 1 frame không thêm pixel mới; chỉ ép vẽ lại khi chưa đủ — ép mỗi lần
      gây bóng ma). IPC `GET_BACKDROP` + `"namespace"` (layer) / `"app_id"` (cửa sổ). Commit scenefx 734272b, d416320,
      fdc169f; swayfx 4dab6ed3, 17f019dc, 25b8d070. Quick 250 ms, OSD 150 ms, bar 1 s.
- [x] Lỗi cũ tìm ra: OSD chưa từng có kính compositor — `corner_radius 999` bị từ chối và `layer_criteria_add` xoá luật cũ
      trước khi parse (mất `blur enable`). Fork parse trước rồi mới thay; OSD radius 22 (radius cũng cắt nội dung surface).
- [x] `bar.height` hai chiều: `components.bar_size_css` (pill = h − 2·gap − viền kính, nút workspace vừa pill, chữ thu
      nhỏ khi thấp hơn dòng chữ). Trước: chỉ là kích thước tối thiểu (không thấp hơn ~34, cao thì kéo dài pill).
- [x] ChoSua (`~/Downloads/Element`, nhánh `liquid-glass-ink`, chưa commit, patch riêng `.git/chosua-liquid-glass-ink.patch`):
      `effects.GLASS_APPS` gồm `chosua`; `sway_glass.rs` watch → `GlassConfig`/`GlassBackdrop`; app.js `retagInk()`.
- Harness: `tools/liquid_shot.sh` dùng `BarModule().files()`; script thử trong `tools/out/{live,osd,chosua,height}_shot.sh`.
- Gói đã build: center -23, bar -9, fx r26, chosua -15 (chưa cài/chưa thử trên phiên thật).

## Launcher Spotlight trên elephant (2026-10-06, XONG — chưa thử phiên thật)
- [x] Duyệt UI bằng `tools/spotlight-demo.html` (engine kính + ink của liquid-demo; `?q=` để chụp).
- [x] `swayctl-bar/src/services/elephant.rs`: client socket `$XDG_RUNTIME_DIR/elephant/elephant.sock`, khung
      `[type][format=1 JSON][len BE][payload]` (không cần protobuf); trả `[type][len][payload]`: 0/1 item, 254 không có, 255 xong.
      Một kết nối = một truy vấn (truy vấn mới huỷ cũ). Activate trên kết nối riêng. CLI `elephant query` panic khi 0 kết quả → không dùng.
- [x] `ui/launcher.rs` (ns `swayctl-launcher`, Overlay, Exclusive, 18% từ trên): ô tìm + tấm kết quả (Top Hit, nhóm theo
      provider, tô đậm ký tự khớp từ fuzzyinfo) + dải phím; máy tính / lưới emoji; gợi ý = app đã pin (không có thì ẩn);
      ↑↓/Tab, Enter = action đầu, Ctrl+Enter = action thứ 2, Esc xoá rồi đóng; spring mở / fade đóng; catcher; probe 250 ms.
      Lệnh: `swayctl-bar launcher` (bật/tắt), `swayctl-bar launcher <chữ>` (mở sẵn chữ: "." emoji, "=" máy tính).
      Gộp truy vấn trong 1 nhịp main loop (set_text = xoá + chèn), đổi loại kết quả thì xoá kết quả cũ ngay.
- [x] Center: `launcher.program` (swayctl-bar|walker, mặc định swayctl-bar, chỉ có tác dụng khi bar là swayctl-bar) →
      chỉ unit elephant; `config.json.launcher` (providers mặc định + prefixes từ cài đặt); bar depends_on launcher;
      `launcher.open` → `swayctl-bar launcher` khi bar chạy và Walker không; ns trong PANEL/SHAPED/NO_SHADOW/ADAPTIVE;
      kính launcher đục tối thiểu 16%. Test: `tests/test_p7.py` NativeLauncherTest. Sandbox: `tools/out/spot_shot.sh`.
- Còn: chưa test phím thật (không có bàn phím ảo trong sandbox — chỉ test qua `launcher <chữ>`), menu con của provider
  `menus`, pin/bỏ pin trong launcher. Gói: center -24, bar -10.
- [x] Clipboard trong launcher: tiền tố `:` (khi `clipboard.managed`), đọc thẳng cliphist (`services/clipboard.rs`: list/decode/
      delete qua stdin như picker cũ; copy = decode | wl-copy trong thread), không dùng provider clipboard của elephant (trùng
      cliphist). Mới nhất trước, lọc theo từ (mọi thứ tự), ảnh = thumbnail (Texture từ decode, cache theo dòng). Enter copy +
      đóng, Shift/Ctrl+Delete xoá và ở lại. `action clipboard.history|delete` → `swayctl-bar launcher :` khi bar chạy và không
      có Walker. Bar depends_on clipboard. Sandbox: `tools/out/clip_shot.sh`. Gói: center -25, bar -11.
- [x] Nhiều kết quả: danh sách trong ScrolledWindow trong tấm kính, cao = min(tự nhiên, 55% màn hình) — tự đo và đặt
      min/max_content_height (ScrolledWindow không báo natural height, như danh sách thông báo của Quick Settings).
      ↑↓/hover chỉ đổi class `selected` + gợi ý phím (không dựng lại danh sách, giữ vị trí cuộn), tự cuộn tới mục chọn. bar -12.
- [x] Rò bộ nhớ swayctl-bar (máy thật: ~28 GB heap sau 11 giờ): `Watch` không bao giờ bỏ subscriber, mà Quick
      Settings dựng panel mới mỗi lần mở và bar dựng lại mỗi lần đổi config/màn hình -> closure giữ sống mọi panel/bar
      cũ, và mỗi thông báo dựng lại 30 thẻ trong MỌI panel cũ, mỗi sự kiện sway dựng lại nút workspace của MỌI bar cũ.
      Sửa: `Watch::subscribe` trả id + `unsubscribe`, `watch::Subs` (kết thúc cả nhóm); Quick Settings `subs.clear()` khi
      đóng, `State.bar_subs` clear khi rebuild; timer 10 s của bar và đồng hồ dừng khi bar cũ mất (đồng hồ giữ weak).
      Test: `tools/sandbox.sh --fx /home/repo/tools/bar_leak_test.sh [binary]` - bản cũ +70 MB sau 90 lần mở + 40 thông
      báo, bản mới +0,4 MB. Quy tắc: widget dựng theo lần mở/rebuild phải `Subs::follow`, không `subscribe` thẳng. bar -20.
- [x] Bar: workspace "giọt nước" (`WsDrop` trong `ui/bar.rs`). Một viên màu (`.workspace.focused.ws-blob`, trong `Fixed` nằm DƯỚI
      hàng nút bằng `Overlay` + `set_measure_overlay`) trượt tới nút mới: hai mép là hai `adw::SpringAnimation`, mép dẫn
      (phía đang đi tới) cứng+nảy nhẹ (ζ 0.7, k 380), mép đuôi mềm (ζ 0.95, k 130) nên viên màu giãn ra rồi co lại, dẹt
      tối đa 8% khi giãn; bị ngắt giữa chừng thì mang vận tốc sang lần sau. Nút chỉ đổi class tại chỗ khi chỉ đổi focus
      (chỉ dựng lại khi workspace thêm/bớt), class `current` = đang focus (tìm viên đích), `.under-drop` = viên màu đang
      phủ giữa nút -> chữ accent (components.py: các selector `.workspace.focused` có thêm `.workspace.under-drop`;
      MOTION_CSS ở main.rs, provider APPLICATION+2). Tắt animation hệ thống thì adw tự nhảy tới đích. Test ảnh:
      `tools/sandbox.sh --fx /home/repo/tools/ws_drop_shot.sh` (khung 0-900 ms, 2 chiều); rò rỉ: bar_leak_test (200 lần
      đổi workspace +50 kB). bar -21.
- [x] Sửa hồi quy của drop: nút workspace đổi class `focused` -> `current`, nên theme sinh ra CŨ (chưa cài center mới) không còn
      tô chữ accent cho nó -> chữ khoá #FF00FE hiện nguyên trên viên màu đặc (compositor không ink được chữ trên nền đặc).
      MOTION_CSS (APPLICATION+2) giờ tự đặt `.workspace.under-drop` = accent_fg, không phụ thuộc theme sinh ra; ws_drop_shot
      chạy với theme "cũ" cố ý (chữ khoá). Luôn cài bar và center cùng lúc. bar -22, center -38.
- [x] Lỗi "mở app cài đặt lên: chữ khoá #FF00FE lộ ra, `swaymsg reload` mới hết" (10/10). Tái hiện được:
      `tools/sandbox.sh --fx /home/repo/tools/ink_stale_rules.sh` - sway đang giữ một rule for_window mới hơn (`glass text none`)
      -> cửa sổ mở ra không được ink (5802 điểm ảnh khoá) tới khi reload chạy lại rule. Lý do rule sai trong phiên thật chưa rõ
      (sway giữ mọi rule for_window, cái mới nhất thắng), nên sửa ở chỗ chắc chắn: daemon đăng ký sự kiện `window`
      (swayipc.EVENT_NAMES +window), khi cửa sổ của app kính mở (`change: new`) thì gửi thẳng rule của nó
      `[con_id=N] glass enable, ... glass text auto ...` (`EffectsModule.window_rules` / `window_opened`). Sau sửa: 0 điểm ảnh khoá.
      Test: tests/test_effects.py; công cụ chẩn đoán còn lại: tools/ink_repro.sh (8 tình huống, đều 0). center -39.
- [x] Cấu hình từ khung đầu: daemon ghi generated/startup.conf (gaps, viền, màu client, font, input, output, bindsym... — bỏ lệnh "all set"/[criteria]/exec), swayctl-fx.conf `include` nó; fork đọc sẵn nên không cần build lại swayctl-fx. tools/startup_config_test.sh (không lỗi config, include chạy được).
- [x] Cài đặt dạng số chọn theo bậc thay vì kéo/nhập: ui.LEVELS + LevelRow (nút liền nhau: Thin/Normal/Thick...) cho kính, góc bo, gaps, viền, cuộn, con trỏ, phím, font, bar, thông báo...; giá trị ngoài bậc hiện không chọn gì (tooltip có số). Test: mọi bậc hợp lệ + mặc định là một bậc.
