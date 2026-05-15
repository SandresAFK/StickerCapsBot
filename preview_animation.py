"""Standalone preview script — generates a sample VS-screen GIF animation.
Run: python preview_animation.py
Output: preview_vs.gif  (open with any image viewer / browser)
"""
from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw, ImageFont

W, H = 700, 320
FRAMES = 24
DURATION_MS = 70

C_BG   = (22, 22, 35)
C_CARD = (38, 40, 60)
C_TEXT = (220, 222, 240)
C_SUB  = (120, 122, 150)
C_GOLD = (255, 205, 50)
C_RED  = (220, 60, 60)
C_BLUE = (60, 120, 220)
C_BOLT = (255, 225, 70)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for p in [
        os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "segoeui.ttf"),
        os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "arial.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        if os.path.exists(p):
            return ImageFont.truetype(p, size=size)
    return ImageFont.load_default()


def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0], bb[3] - bb[1]


def _rounded_rect(draw: ImageDraw.ImageDraw, xy, radius: int, fill):
    draw.rounded_rectangle(xy, radius=radius, fill=fill)


def _bolt(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, fill):
    s = size
    pts = [
        (cx - s * 0.22, cy - s * 0.50),
        (cx + s * 0.08, cy - s * 0.04),
        (cx - s * 0.04, cy - s * 0.04),
        (cx + s * 0.22, cy + s * 0.50),
        (cx - s * 0.08, cy + s * 0.04),
        (cx + s * 0.04, cy + s * 0.04),
    ]
    draw.polygon(pts, fill=fill)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _ease_out(t: float) -> float:
    return 1 - (1 - t) ** 3


def make_frame(f: int) -> Image.Image:
    t = f / FRAMES           # 0..1 linear
    pulse = abs(math.sin(t * math.pi * 4))    # fast pulse 0..1
    slow_pulse = abs(math.sin(t * math.pi * 2))

    img = Image.new("RGB", (W, H), C_BG)
    draw = ImageDraw.Draw(img)

    # ── outer card ────────────────────────────────────────────────────────────
    _rounded_rect(draw, (20, 20, W - 20, H - 20), 28, C_CARD)

    # ── fonts ─────────────────────────────────────────────────────────────────
    ft_name = _font(32)
    ft_vs   = _font(int(54 + 6 * pulse))
    ft_sub  = _font(20)
    ft_chip = _font(18)

    # ── player names slide in ─────────────────────────────────────────────────
    slide_t = _ease_out(min(1.0, t * 2.5))

    # left player (slides from far left)
    p1 = "@AleXXXSandres"
    p1w, p1h = _text_size(draw, p1, ft_name)
    p1_target_x = W // 4 - p1w // 2
    p1_x = int(_lerp(-p1w - 40, p1_target_x, slide_t))
    p1_y = H // 2 - p1h - 10
    draw.text((p1_x, p1_y), p1, font=ft_name, fill=C_TEXT)

    # right player (slides from far right)
    p2 = "@CrowleyKek"
    p2w, p2h = _text_size(draw, p2, ft_name)
    p2_target_x = 3 * W // 4 - p2w // 2
    p2_x = int(_lerp(W + 40, p2_target_x, slide_t))
    p2_y = H // 2 - p2h - 10
    draw.text((p2_x, p2_y), p2, font=ft_name, fill=C_TEXT)

    # ── chips row under each player ───────────────────────────────────────────
    chip_r = 10
    chip_colors_l = [C_RED, (180, 50, 50), C_RED]
    chip_colors_r = [C_BLUE, (50, 80, 200), C_BLUE]
    for i, col in enumerate(chip_colors_l):
        cx = p1_target_x + i * (chip_r * 2 + 6) + (p1_x - p1_target_x)
        cy = H // 2 + 14
        draw.ellipse((cx, cy, cx + chip_r * 2, cy + chip_r * 2), fill=col)
    for i, col in enumerate(chip_colors_r):
        cx = p2_target_x + i * (chip_r * 2 + 6) + (p2_x - p2_target_x)
        cy = H // 2 + 14
        draw.ellipse((cx, cy, cx + chip_r * 2, cy + chip_r * 2), fill=col)

    # ── VS text ───────────────────────────────────────────────────────────────
    vs_appear = _ease_out(min(1.0, max(0.0, t * 3.5 - 0.5)))
    vsw, vsh = _text_size(draw, "VS", ft_vs)
    vs_x = W // 2 - vsw // 2
    vs_y = H // 2 - vsh // 2 - 10
    gold_r = int(_lerp(100, 255, vs_appear))
    gold_g = int(_lerp(80, 205, vs_appear))
    gold_b = int(_lerp(20, 50,  vs_appear))
    draw.text((vs_x, vs_y), "VS", font=ft_vs, fill=(gold_r, gold_g, gold_b))

    # ── lightning bolt below VS ───────────────────────────────────────────────
    bolt_appear = _ease_out(min(1.0, max(0.0, t * 4 - 1.0)))
    bolt_size = (18 + 8 * pulse) * bolt_appear
    bolt_alpha_col = (
        int(C_BOLT[0]),
        int(C_BOLT[1] * (0.7 + 0.3 * pulse)),
        int(C_BOLT[2] * (0.5 + 0.5 * slow_pulse)),
    )
    _bolt(draw, W // 2, H // 2 + 42, bolt_size, bolt_alpha_col)

    # ── horizontal flash lines ────────────────────────────────────────────────
    if t > 0.4:
        line_alpha = int(30 * pulse)
        lc = (200, 210, 255)
        cy_line = H // 2 + 2
        draw.line((50, cy_line, W // 2 - 45, cy_line), fill=lc, width=1)
        draw.line((W // 2 + 45, cy_line, W - 50, cy_line), fill=lc, width=1)

    # ── subtitle ──────────────────────────────────────────────────────────────
    sub = "Дуэль начинается..."
    subw, _ = _text_size(draw, sub, ft_sub)
    sub_appear = _ease_out(min(1.0, max(0.0, t * 4 - 1.5)))
    sub_col = (int(C_SUB[0] * sub_appear), int(C_SUB[1] * sub_appear), int(C_SUB[2] * sub_appear))
    draw.text((W // 2 - subw // 2, H - 55), sub, font=ft_sub, fill=sub_col)

    return img


if __name__ == "__main__":
    frames = [make_frame(f) for f in range(FRAMES)]

    out = "preview_vs.gif"
    frames[0].save(
        out,
        save_all=True,
        append_images=frames[1:],
        duration=DURATION_MS,
        loop=0,
        optimize=False,
    )
    print(f"✅ Saved: {os.path.abspath(out)}")
    print("   Open preview_vs.gif in browser or image viewer.")
