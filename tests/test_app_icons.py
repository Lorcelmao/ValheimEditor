"""The desktop and web icons: files exist and are the right shape, and everything
that has to point at them does.

None of this needs a display (the GUI behaviour is in test_gui_smoke.py), so it
also runs on CI, where the Pages deploy would otherwise happily publish a page
whose favicon 404s.
"""
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESKTOP_ICON = ROOT / "src" / "fch_editor" / "gui" / "icon.ico"
WEB = ROOT / "web"


def _ico_sizes(path: Path) -> list[int]:
    data = path.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1), f"{path.name} is not an ICO file"
    return sorted((data[6 + 16 * i] or 256) for i in range(count))  # a stored 0 means 256


def test_desktop_icon_carries_every_size_windows_asks_for():
    # Explorer, the taskbar, Alt-Tab and high-DPI each ask for a different size;
    # a missing one is scaled up from a smaller image and looks soft.
    sizes = _ico_sizes(DESKTOP_ICON)
    assert {16, 32, 48, 256} <= set(sizes)


def test_web_favicon_is_a_real_multi_size_icon():
    assert {16, 32, 48} <= set(_ico_sizes(WEB / "favicon.ico"))


def test_apple_touch_icon_is_a_180px_png():
    data = (WEB / "apple-touch-icon.png").read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", data[16:24]) == (180, 180)


def test_the_web_page_links_icons_that_actually_exist():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    links = re.findall(r'<link\s+rel="(icon|apple-touch-icon)"[^>]*href="([^"]+)"', html)
    assert {rel for rel, _href in links} == {"icon", "apple-touch-icon"}
    for _rel, href in links:
        assert not href.startswith(("/", "http")), "must be relative: Pages serves this under /<repo>/"
        assert (WEB / href).is_file(), f"index.html links {href} but it is not in web/"


def test_the_exe_build_sets_the_icon_and_bundles_it_for_the_window():
    script = (ROOT / "tools" / "build_gui.ps1").read_text(encoding="utf-8")
    assert re.search(r'--icon\s+"[^"]*gui\\icon\.ico"', script), "the .exe's own icon"
    assert re.search(r'--add-data\s+"[^"]*gui\\icon\.ico;fch_editor\\gui"', script), \
        "the copy the running window loads (dest must match ICON_PATH's folder)"


def test_a_pip_install_ships_the_icon_too():
    assert '"fch_editor.gui" = ["icon.ico"]' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
