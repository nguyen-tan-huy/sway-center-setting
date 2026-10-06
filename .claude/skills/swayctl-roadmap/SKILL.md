---
name: swayctl-roadmap
description: Lộ trình hiện đại hoá swayctl-center theo từng mốc - design token/theme (B1-B3), fork SwayFX (cuộn mượt trong nhân, popup IME, chế độ an toàn), swayctl-bar viết bằng Rust + libadwaita (bar, Quick Settings kiểu macOS có animation, OSD), libadwaita cho app cài đặt. Dùng skill này khi người dùng nhắc tới "mốc"/"giai đoạn"/"làm tiếp", design token, theme hiện đại, SwayFX/fork, swayctl-bar, Quick Settings, OSD, cuộn mượt trong compositor, IME popup, hoặc hỏi tiến độ lộ trình.
---

# Lộ trình swayctl-center

Đọc `PROGRESS.md` (cùng thư mục) trước tiên để biết đang ở mốc nào; cập nhật nó khi xong một hạng mục.

## Quy tắc bắt buộc: chỉ làm và test trong sandbox

Người dùng chạy sway thật trên máy này. **Không bao giờ** làm điều gì chạm vào phiên thật:
- Không chạy `swaymsg`, `sway`, daemon, UI, `systemctl --user`, `gsettings`, `pkexec`, `pacman -S`
  ngoài sandbox. Không ghi vào `~/.config`, `/etc`.
- Mọi test/chạy thử: `tools/sandbox.sh <lệnh>` (bwrap: HOME + XDG_RUNTIME_DIR tạm, không có socket
  sway/D-Bus/systemd thật, repo chỉ đọc). Cần sway: `tools/sandbox.sh --sway <lệnh>` (sway headless,
  pixman, `SWAYSOCK` trỏ vào sway trong sandbox). Ghi kết quả (ảnh grim, log) vào `/tmp/out`
  = `tools/out/` trên máy.
- Test: `tools/sandbox.sh python3 -m unittest discover -s tests -t .`
- Build Rust/C (cargo, meson) được chạy trực tiếp vì chỉ ghi vào thư mục build trong repo; nhưng
  chạy binary kết quả thì qua sandbox.
- Không commit trừ khi người dùng yêu cầu; working tree có thể chứa thay đổi dở của người dùng.

## Quyết định đã chốt
- Fork **SwayFX + SceneFX** (không fork sway gốc) ở `~/Projects/swayctl-fx`, nhánh `swayctl`. Patch nhỏ,
  mỗi patch một commit để rebase. Cài **cạnh** sway (binary `swayctl-fx` + phiên đăng nhập riêng),
  không thay thế sway. Chạy thử: `tools/sandbox.sh --fx …`.
- **Không** làm animation trong compositor. Animation chỉ ở popup shell (Quick Settings, OSD)
  phía client bằng libadwaita (`SpringAnimation`/`TimedAnimation`, `NavigationView`).
- Shell viết bằng **Rust + gtk4-rs + gtk4-layer-shell + libadwaita**, ưu tiên nhẹ (mục tiêu
  swayctl-bar < 40 MB RAM, ~0% CPU khi rảnh, popup mở < 50 ms). Hướng sự kiện, không polling;
  chạy trên GLib main loop (zbus không cần tokio).
- Cài đặt swayctl đi qua D-Bus của daemon Python (`Get/Set/Action`, signal `Changed`);
  dịch vụ hệ thống (NM, BlueZ, UPower, MPRIS, power-profiles) gọi thẳng bằng zbus.
- Theme: design token sinh từ theme (4 màu cũ vẫn hợp lệ), ánh xạ sang biến CSS libadwaita.

## Các mốc

| Mốc | Nội dung |
|---|---|
| 1 | **B1** design token (`themes.py`: OKLab, surface/text/accent-fg/border/trạng thái, radius…), theme kiểu "chỉ cần accent", placeholder mới trong `theming.py`, CSS libadwaita. **B2** áp token cho sway/waybar/swaync/fuzzel/GTK. **B3** preset "Modern". Kèm: script đo hiệu năng, test ảnh chụp sway headless |
| 2 | **A0** fork SwayFX/SceneFX + PKGBUILD (cài cạnh sway), `swayctl_features` trong `get_version`; vá **popup input-method-v2** (fcitx5 tiếng Việt); **chế độ an toàn** (`sway -C` trước khi áp dụng, phiên "Sway gốc" dự phòng, UI ẩn tuỳ chọn không áp dụng được) |
| 3 | **B4** crate `swayctl-bar/`: bar layer-shell mỗi output, workspaces/clock/pin/mạng/âm lượng; Quick Settings (Wi-Fi, BT, âm lượng+đầu ra, độ sáng, night light, power profile, DND, media MPRIS, menu nguồn), lịch ở đồng hồ, OSD; lựa chọn "swayctl-bar / waybar" trong `components.py`; tray (StatusNotifierItem) sau cùng |
| 4 | **A1** cuộn mượt trong nhân SwayFX (port `ScrollSmoother`, phát theo frame, lệnh `input … smooth_scroll/scroll_friction/scroll_ramp`, `for_window … smooth_scroll native`), module `scrolling` gửi lệnh IPC khi phát hiện fork, giữ daemon Python cho sway gốc; tuỳ chọn blur theo opacity của layer |
| 5 | **B5** app cài đặt chuyển sang libadwaita; polkit agent + khoá màn hình theo theme; i18n vi/en; chuyển đổi dữ liệu cũ (theme 4 màu, waybar); cập nhật wizard |
| sau | Hồ sơ màn hình (kiểu kanshi), portal chia sẻ màn hình, chụp/quay màn hình, Alt-Tab, hiệu ứng kính (khúc xạ) |

## Cách làm một mốc
1. Đọc `PROGRESS.md`, chọn hạng mục chưa xong tiếp theo.
2. Đọc mã liên quan, viết theo phong cách sẵn có (module trong `swayctl_center/modules/`,
   schema trong `schema.py`, test `tests/test_*.py` dùng `unittest`).
3. Viết test, chạy trong sandbox, sửa tới khi xanh.
4. Cập nhật `PROGRESS.md` (đã xong / còn lại / ghi chú quyết định) và README nếu hành vi đổi.
