r"""KVLR branding, applied at build time to copies of upstream's files, so upstream's own files never change and
SmoovPlay's updates keep merging cleanly.

What it changes (kvlr/build_kvlr.py calls it):
- The launcher (installer/launcher): every *.cs and Ui.xaml is copied to installer/build/kvlr-brand/launcher and
  compiled from there.
  - The product name inside C# string literals and XAML text becomes NAME (the rail's big title: RAIL_NAME).
    Names Windows or the disk use are left alone: the install folder (lines with Path.Combine or .Equals), files
    (SmoovPlay.exe, SmoovPlay.lnk, SmoovPlay-Setup...), the registry key, and UpdateSignature.cs as a whole (its
    header line is part of every signature).
  - Colours: COLOURS maps SmoovPlay's amber palette to KVLR's (cyan accent, gold warnings, KVLR red and green,
    KVLR's darker greys); an #AARRGGBB colour keeps its alpha.
  - The rail logo (the one 1024x1024 Canvas in Ui.xaml) becomes the KVLR mark, traced from kvlr/brand/kvlr-mark.png.
- The app icon (.ico and icon-256.png): the KVLR mark on a dark tile with a cyan edge (icon_rgba).
- The app's Python (the staged app\framegen): the product name inside string tokens (window title, messages, clip
  names). The replay folder (Videos\SmoovPlay) and settings folders stay as they are.

Kept as is on purpose: install folder, Start-menu shortcut file names, %APPDATA%\framegen, environment variables
(SMOOVPLAY_*), and the credit to SmoovPlay in the licence files.
"""
from __future__ import annotations

import io
import re
import shutil
import tokenize
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
MARK = HERE / "brand" / "kvlr-mark.png"

NAME = "KVLR PS5 Frame Gen"
RAIL_NAME = "KVLR PS5"

# The product name as a word: not part of an identifier, a file name, a path or a key.
NAME_RX = re.compile(r"(?<![\w\\/.\-])SmoovPlay(?![\w\-/\\])(?!\.\w)")  # "SmoovPlay." ends a sentence; ".exe" doesn't
CS_KEEP_LINE = re.compile(r"Path\.Combine|\.Equals\(|Uninstall\\\\|GetFolderPath")
CS_SKIP_FILES = {"UpdateSignature.cs"}
CS_STRING = re.compile(r'@?\$?"(?:[^"\\\n]|\\.)*"')

# SmoovPlay -> KVLR (kvlrtv.com tokens: cyan #2fe4f2, orange #ff8a1e, gold #ffc94a, red #ff3b3b, green #2fe45a,
# background #0a0d0e).
COLOURS = {
    # accent (amber -> cyan), its lighter tint, the ink drawn on it
    "FFB02E": "2FE4F2", "FFCB5C": "7CF0F8", "1A1206": "03181A", "FFBD24": "7CF0F8", "FC930B": "2FE4F2",
    "FC5F03": "17A9B4",
    # the accent gradient's far end and the rail's glow: deep cyan / cyan (KVLR's accent is cyan throughout)
    "FF8A1F": "17A9B4", "FF9F2E": "2FE4F2",
    # states
    "FFC24B": "FFC94A", "FF6464": "FF3B3B", "E5484D": "E53535", "3DDC8E": "2FE45A",
    # backgrounds and lines
    "0E1014": "0A0D0E", "0F1217": "0C1011", "161A21": "121718", "171B22": "131A1B", "1B2029": "182022",
    "1C2129": "161D1F", "1E222B": "192123", "1E232C": "192123", "20252E": "1B2426", "222833": "1E2729",
    "262C36": "212B2D", "2A2F38": "242E30", "2A303B": "253033", "2D3440": "2A3538", "2E3542": "283436",
    "323A47": "2C393C", "3A4250": "334245", "4A5363": "3F5155",
    # text
    "F3F5F9": "F4F7F8", "C9CED8": "C8D2D4", "A9B1BF": "A9B5B8", "8E97A6": "8B999C", "8D96A5": "8B999C",
    "6F788A": "6E7C80",
}
HEX_RX = re.compile(r"#([0-9A-Fa-f]{8}|[0-9A-Fa-f]{6})\b")

TILE_TOP, TILE_BOTTOM, EDGE, MARK_FILL = "#14201F", "#0A0D0E", "#2FE4F2", "#F4F7F8"


# ------------------------------------------------------------------------------------------------- text
def recolour(text: str) -> str:
    def sub(m):
        h = m.group(1)
        alpha, rgb = (h[:2], h[2:]) if len(h) == 8 else ("", h)
        new = COLOURS.get(rgb.upper())
        return m.group(0) if new is None else "#" + alpha + new
    return HEX_RX.sub(sub, text)


def brand_cs(text: str) -> str:
    out = []
    for line in text.splitlines(keepends=True):
        if not CS_KEEP_LINE.search(line):
            line = CS_STRING.sub(lambda m: NAME_RX.sub(NAME, m.group(0)), line)
        line = CS_STRING.sub(lambda m: recolour(m.group(0)), line)
        out.append(line)
    return "".join(out)


def brand_xaml(text: str) -> str:
    text = text.replace('<TextBlock Text="SmoovPlay" FontFamily="{StaticResource Display}" FontSize="18"',
                        f'<TextBlock Text="{RAIL_NAME}" FontFamily="{{StaticResource Display}}" FontSize="18"', 1)
    # attribute values only (Text, Title, ToolTip, ...), never names or comments
    text = re.sub(r'="([^"]*)"', lambda m: '="' + NAME_RX.sub(NAME, m.group(1)) + '"', text)
    text = recolour(text)
    # the rail's footer credits the app this is built on (MIT), after the name pass so it keeps its own name
    footer = 'x:Name="RailFooterTitle" Text="Free and open source"'
    if footer not in text:
        raise SystemExit("[kvlr] Ui.xaml's rail footer changed upstream; update kvlr/branding.py brand_xaml()")
    text = text.replace(footer, 'x:Name="RailFooterTitle" Text="Built on SmoovPlay (MIT)"', 1)
    return replace_logo(text)


def brand_python(text: str) -> str:
    """The name inside string tokens only (window title, messages, clip names), never code or comments; a line
    that builds a path keeps it."""
    toks = tokenize.generate_tokens(io.StringIO(text).readline)
    kinds = {tokenize.STRING} | ({tokenize.FSTRING_MIDDLE} if hasattr(tokenize, "FSTRING_MIDDLE") else set())
    lines = text.splitlines(keepends=True)
    starts = [0]
    for ln in lines:
        starts.append(starts[-1] + len(ln))
    edits = []
    for t in toks:
        if t.type in kinds and "SmoovPlay" in t.string:
            line = lines[t.start[0] - 1]
            if re.search(r'/\s*["\']SmoovPlay["\']', line):
                continue  # a folder (Videos\SmoovPlay)
            a = starts[t.start[0] - 1] + t.start[1]
            b = starts[t.end[0] - 1] + t.end[1]
            edits.append((a, b))
    for a, b in reversed(edits):
        text = text[:a] + NAME_RX.sub(NAME, text[a:b]) + text[b:]
    return text


# ------------------------------------------------------------------------------------------------- logo
def mark_mask() -> np.ndarray:
    img = cv2.imread(str(MARK), cv2.IMREAD_UNCHANGED)
    if img is None or img.ndim != 3 or img.shape[2] != 4:
        raise SystemExit(f"[kvlr] {MARK} is missing or has no alpha")
    return img[:, :, 3]


def mark_path_data(box: tuple[float, float, float, float]) -> str:
    """The mark as XAML path data (EvenOdd), fitted into box = (x, y, w, h) of a 1024 canvas."""
    a = mark_mask()
    _, bw = cv2.threshold(a, 127, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(bw, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    h, w = a.shape
    x0, y0, bw_, bh_ = box
    s = min(bw_ / w, bh_ / h)
    ox, oy = x0 + (bw_ - w * s) / 2, y0 + (bh_ - h * s) / 2
    parts = []
    for c in contours:
        c = cv2.approxPolyDP(c, 0.6, True).reshape(-1, 2)
        if len(c) < 3:
            continue
        pts = [f"{ox + x * s:.1f},{oy + y * s:.1f}" for x, y in c]
        parts.append("M" + pts[0] + " L" + " ".join(pts[1:]) + " Z")
    return "F0 " + " ".join(parts)


def replace_logo(xaml: str) -> str:
    start = xaml.find('<Canvas Width="1024" Height="1024">')
    end = xaml.find("</Canvas>", start)
    if start < 0 or end < 0 or xaml.find('<Canvas Width="1024" Height="1024">', end) >= 0:
        raise SystemExit("[kvlr] Ui.xaml's logo Canvas changed upstream; update kvlr/branding.py replace_logo()")
    indent = " " * (xaml.rfind("\n", 0, start) and start - xaml.rfind("\n", 0, start) - 1)
    data = mark_path_data((150, 210, 724, 604))
    new = (f'<Canvas Width="1024" Height="1024">\n'
           f'{indent}  <!-- KVLR: the KVLR mark (kvlr/brand/kvlr-mark.png, traced by kvlr/branding.py) -->\n'
           f'{indent}  <Rectangle Width="1024" Height="1024" RadiusX="228" RadiusY="228" Stroke="{EDGE}" '
           f'StrokeThickness="36">\n'
           f'{indent}    <Rectangle.Fill><LinearGradientBrush StartPoint="0,0" EndPoint="1,1">'
           f'<GradientStop Offset="0" Color="{TILE_TOP}"/><GradientStop Offset="1" Color="{TILE_BOTTOM}"/>'
           f'</LinearGradientBrush></Rectangle.Fill>\n'
           f'{indent}  </Rectangle>\n'
           f'{indent}  <Path Fill="{MARK_FILL}" Data="{data}"/>\n'
           f'{indent}')
    return xaml[:start] + new + xaml[end:]


def _hex_bgr(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)


def icon_rgba(size: int) -> np.ndarray:
    """The app icon at one size, BGRA: the KVLR mark on a dark rounded tile with a cyan edge (drawn at 1024 and
    scaled down, so every size matches the rail logo)."""
    n = 1024
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    t = (xx + yy) / (2 * n - 2)
    top, bot = np.array(_hex_bgr(TILE_TOP), np.float32), np.array(_hex_bgr(TILE_BOTTOM), np.float32)
    img = np.zeros((n, n, 4), np.float32)
    img[..., :3] = top * (1 - t[..., None]) + bot * t[..., None]
    r = 228
    tile = np.zeros((n, n), np.uint8)
    cv2.rectangle(tile, (r, 0), (n - 1 - r, n - 1), 255, -1)
    cv2.rectangle(tile, (0, r), (n - 1, n - 1 - r), 255, -1)
    for cx, cy in ((r, r), (n - 1 - r, r), (r, n - 1 - r), (n - 1 - r, n - 1 - r)):
        cv2.circle(tile, (cx, cy), r, 255, -1, cv2.LINE_AA)
    # 36 px edge, as the rail logo's StrokeThickness; outside the image counts as empty, so the sides erode too
    inner = cv2.erode(tile, np.ones((3, 3), np.uint8), iterations=36, borderType=cv2.BORDER_CONSTANT, borderValue=0)
    edge = cv2.subtract(tile, inner)
    img[..., :3][edge > 0] = _hex_bgr(EDGE)
    img[..., 3] = tile
    a = mark_mask()
    h, w = a.shape
    box = (150, 210, 724, 604)
    s = min(box[2] / w, box[3] / h)
    mw, mh = round(w * s), round(h * s)
    m = cv2.resize(a, (mw, mh), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    ox, oy = round(box[0] + (box[2] - mw) / 2), round(box[1] + (box[3] - mh) / 2)
    region = img[oy:oy + mh, ox:ox + mw, :3]
    region[:] = region * (1 - m[..., None]) + np.array(_hex_bgr(MARK_FILL), np.float32) * m[..., None]
    out = cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)
    return np.clip(out, 0, 255).astype(np.uint8)


# ------------------------------------------------------------------------------------------------- staging
def brand_launcher(launcher: Path, out_root: Path) -> Path:
    """Branded copies of upstream's launcher folder; returns the folder that stands in for installer/."""
    dst = out_root / "launcher"
    if out_root.exists():
        shutil.rmtree(out_root)
    dst.mkdir(parents=True)
    for f in launcher.iterdir():
        if not f.is_file():
            continue
        if f.suffix == ".cs" and f.name not in CS_SKIP_FILES:
            (dst / f.name).write_text(brand_cs(f.read_text(encoding="utf-8")), encoding="utf-8")
        elif f.name == "Ui.xaml":
            (dst / f.name).write_text(brand_xaml(f.read_text(encoding="utf-8")), encoding="utf-8")
        else:
            shutil.copy2(f, dst / f.name)
    return out_root


def brand_app(stage: Path) -> int:
    """Brands the staged app's Python in place; returns how many files changed."""
    n = 0
    for f in sorted((stage / "app").rglob("*.py")):
        src = f.read_text(encoding="utf-8")
        new = brand_python(src)
        if new != src:
            compile(new, str(f), "exec")  # a branding slip fails the build, not the player
            f.write_text(new, encoding="utf-8")
            n += 1
    return n
