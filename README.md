# swayctl-center

Một app cài đặt cho sway: cài lại OS → `pacman -S sway` → cài swayctl-center → cấu hình mọi thứ
bằng giao diện, không cần biết file config nằm ở đâu.

## Kiến trúc

- **Daemon** (`swayctl-center daemon`): giữ kho cài đặt, áp dụng vào sway qua IPC — không sửa
  `~/.config/sway/config` của người dùng. Tự áp dụng lại khi sway `reload`.
- **Kho lưu**: `~/.config/swayctl-center/settings.json` (dùng chung) và `settings.local.json`
  (riêng máy). Chỉ lưu giá trị khác mặc định của schema. Lần chạy đầu đọc cấu hình sway hiện tại
  để không làm thay đổi gì.
- **D-Bus** `io.github.huyhappy.SwayctlCenter`: `GetSchema`, `GetAll`, `Get`, `Set`, `Reset`,
  `ApplyAll`, signal `Changed`. Giá trị truyền dạng JSON.
- **Khởi động**: gói cài `/etc/sway/config.d/50-swayctl-center.conf` → chạy systemd user unit
  một lần mỗi phiên đăng nhập.

## Các mảng đang quản lý

| Mảng | Áp dụng | Ghi chú |
|---|---|---|
| `layout` | `default_border`, `gaps`, `smart_gaps`… | Viền cửa sổ đang mở chỉ đổi khi người dùng đổi giá trị |
| `input.touchpad`, `input.pointer` | `input type:… …` | |
| `outputs` (riêng máy) | `output "<make model serial>" …` | Chỉ gửi lệnh khi khác thực tế (tránh nháy); màn hình mới tự được ghi nhớ |
| `background` | `output * bg …` | Ảnh được sao chép vào `~/.config/swayctl-center/wallpapers/` |
| `font` | `font pango:…` + gsettings `font-name`, `monospace-font-name` | |
| `keybindings` | `bindsym --no-warn …` / `unbindsym` | `$mod` thay theo `modifier`; chỉ quản lý mode mặc định |
| `autostart` | `exec …` một lần mỗi phiên | Không nhập `exec` từ config cũ (tránh chạy hai lần) |
| `appearance` | `client.*` của sway + gsettings `color-scheme` (portal) | `auto`: theo giờ mặt trời hoặc giờ tự đặt; theme riêng: `~/.config/swayctl-center/themes/<tên>.json` |
| `location` (riêng máy) | — | Mặc định suy từ múi giờ (`zone1970.tab`) |
| `night_light` | wlsunset trong unit `swayctl-center-night-light.service` | Chỉ khởi động lại khi tham số đổi |

| `bar`, `notifications`, `idle`, `clipboard`, `input_method`, `polkit_agent` | unit `swayctl-center-<tên>.service`, config sinh ra trong `generated/<tên>/` | Chỉ chạy khi "managed"; không bao giờ chạy trùng với tiến trình cùng loại mà config của bạn đã bật (lần đầu tự đặt managed = false cho các thành phần đó); dừng khi sway thoát. Khi bar "managed", các `bar { }` của sway (swaybar trong config mặc định) bị ẩn bằng `bar <id> mode invisible` |

Thao tác cho phím tắt: `swayctl-center action theme.toggle | night_light.toggle | night_light.warmer | night_light.cooler | lock | notifications.panel | notifications.dnd`.
Trạng thái lúc chạy: `swayctl-center status`.

## Phát triển

```sh
python3 -m unittest discover -s tests -t .          # test
XDG_CONFIG_HOME=/tmp/scc python3 -m swayctl_center daemon -v   # chạy daemon với kho riêng
python3 -m swayctl_center ui                        # mở giao diện (--page keybindings để mở thẳng một trang)
python3 -m swayctl_center get layout
python3 -m swayctl_center set layout.gaps_inner 8
python3 -m swayctl_center reset layout.gaps_inner
cd packaging && makepkg -f                           # build gói Arch
```

## Theme cho app khác (template)

Trang **Themed Apps** (`theming.templates`): mỗi mục là `{template, output, reload}`. Khi theme/font đổi, template
được chép sang output với `@BG@ @FG@ @ACCENT@ @MUTED@` (hex không `#`; tự thêm alpha như `@BG@f2`),
`@BG_HEX@`…, `@BORDER@`/`@MATCH@` (tương thích template "paper" cũ), `@FONT@ @FONT_SIZE@ @FONT_SIZE_PX@
@MONO_FONT@ @VARIANT@`, rồi chạy lệnh `reload`. Bar và thông báo còn có `config_file` (dùng config waybar/swaync
của bạn) và `style_template` (style từ template); bar có `theme` riêng.

## Launcher (Walker)

Trang **Launcher**: Walker (giao diện) + elephant (dịch vụ kết quả, mỗi loại một plugin từ AUR). App chạy cả hai
như unit, config sinh trong `generated/launcher/` (`elephant --config …`, Walker qua `XDG_CONFIG_HOME`), plugin ở
`/etc/xdg/elephant/providers` được symlink vào đó. Chưa cài thì trang gợi ý và có nút cài (mở terminal chạy
pacman + paru/yay); `Super+D` (`action launcher.open`) và lịch sử clipboard dùng fuzzel cho tới khi Walker chạy.
Menu "Settings" trong Walker: gõ "wifi", "dark", "night light"… để mở trang cài đặt hoặc chạy thao tác.

## Cuộn mượt (Mouse & Touchpad)

`swayctl_center/smoothscroll.py` là dịch vụ root (đọc touchpad/chuột qua evdev) làm cuộn mượt + trôi quán tính.
Nút *Set up smooth scrolling* cài nó bằng pkexec (một lần) thành `swayctl-center-smoothscroll.service`, thay
`touchpad-inertia.service` cũ. Thông số nằm trong kho cài đặt (`scrolling.*`), app ghi `generated/smoothscroll.json`,
dịch vụ tự đọc lại trong ~1 giây — không cần mật khẩu khi chỉnh. Khi cuộn mượt chạy, app đặt `scroll_method none`
cho touchpad và bỏ chiều/tốc độ cuộn của sway cho chuột (tránh cuộn hai lần / đảo chiều hai lần).

## Sway mới cài

Với config mặc định của sway (chưa có `~/.config/sway/config`), lần chạy đầu: swaybar được ẩn và thay bằng waybar,
`$mod+d` (`wmenu-run`) đổi thành `action launcher.open` (fuzzel, hoặc Walker nếu đã cài), thêm `$mod+Shift+v` cho lịch
sử clipboard nếu phím còn trống, và chạy polkit-gnome để các nút cần mật khẩu (pkexec) hoạt động. Gói kéo theo `foot`
(terminal của `$mod+Return` mặc định) và `fuzzel`.

## Sao lưu và máy mới

- `swayctl-center export backup.zip` / `import backup.zip` (hoặc trang **System** trong app). Gồm cài đặt dùng
  chung, ảnh hình nền, theme tự tạo; không gồm màn hình và vị trí (riêng từng máy). Nhập = thay toàn bộ cài
  đặt dùng chung.
- `swayctl-center doctor`: kiểm tra chương trình, dịch vụ hệ thống, portal, tự khởi động; trang **System** có nút
  *Fix* (bật dịch vụ qua polkit, thêm `include /etc/sway/config.d/*` vào config sway nếu thiếu).
- Lần đầu mở app: trình hướng dẫn (kiểm tra → nhập bản sao lưu → chọn thành phần app quản lý).

## Kiểm thử với sway headless

Chạy một phiên sway riêng để thử các thành phần mà không đụng phiên đang dùng:

```sh
WLR_BACKENDS=headless WLR_RENDERER=pixman sway -c test.conf &   # test.conf ghi env ra file
export SWAYSOCK=… WAYLAND_DISPLAY=…                               # của phiên headless
export XDG_CONFIG_HOME=/tmp/scc XDG_STATE_HOME=/tmp/scc-state GSETTINGS_BACKEND=memory \
       SWAYCTL_CENTER_BUS_NAME=io.github.huyhappy.SwayctlCenterTest SWAYCTL_CENTER_UNIT_PREFIX=swayctl-center-test-
python3 -m swayctl_center daemon -v
```

## Lộ trình

- [x] P5: template theme cho app khác, config/template riêng cho bar và swaync, DND khi đăng nhập, trang Scroll (nếu có touchpad-inertia)

- [x] P0: khung daemon, schema, kho, D-Bus, CLI, module layout + input
- [x] P1: màn hình (hotplug), hình nền, font (sway + GTK), phím tắt, tự khởi động
- [x] P2: theme sáng/tối (lịch mặt trời/giờ tự đặt, toggle, portal), vị trí từ múi giờ, night light
- [x] P3: thành phần shell (waybar, swaync, swayidle/swaylock, cliphist, fcitx5) chạy bằng systemd unit, theo theme + font
- [x] P4: giao diện GTK4 đầy đủ: trang Mạng/Bluetooth/Âm thanh/Nguồn (loại A), xuất/nhập (.zip), `doctor` + trình hướng dẫn lần đầu
