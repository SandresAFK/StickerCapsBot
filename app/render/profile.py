from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import List

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from app.i18n import t


@dataclass(frozen=True)
class RenderSticker:
    file_id: str
    path: str
    count: int


C_BG = (18, 18, 20, 255)
C_CARD = (28, 28, 30, 255)
C_MUTED_CARD = (36, 36, 40, 255)
C_TEXT = (245, 245, 245, 255)
C_SUB = (180, 180, 180, 255)
C_BLUE = (64, 123, 255, 255)
CHIP_RING = [
    (220, 55,  55,  255),  # 1 — red
    (55,  110, 225, 255),  # 2 — blue
    (45,  182, 103, 255),  # 3 — green
    (155, 55,  220, 255),  # 4 — purple
    (230, 115, 30,  255),  # 5 — orange
    (30,  195, 215, 255),  # 6 — cyan
    (220, 55,  145, 255),  # 7 — pink
    (130, 205, 35,  255),  # 8 — lime
    (70,  35,  185, 255),  # 9 — indigo
]
CHIP_RING_GOLD = (236, 190, 63, 255)


def _clamp_u8(v: int) -> int:
    return 0 if v < 0 else (255 if v > 255 else v)


def _scale_rgba(c, k: float):
    r, g, b, a = c
    return (
        _clamp_u8(int(round(r * k))),
        _clamp_u8(int(round(g * k))),
        _clamp_u8(int(round(b * k))),
        a,
    )


@lru_cache(maxsize=64)
def _rim_texture(size: int) -> Image.Image:
    base = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(base)
    for i in range(size // 2):
        t = i / max(1, (size // 2) - 1)
        a = int(55 * (1 - t))
        d.ellipse((i, i, size - 1 - i, size - 1 - i), outline=(255, 255, 255, a))
    try:
        n = Image.effect_noise((size, size), 22).filter(ImageFilter.GaussianBlur(radius=0.6))
        n = n.point(lambda p: _clamp_u8(int((p - 128) * 0.30 + 128)))
        n_rgba = Image.merge("RGBA", (n, n, n, Image.new("L", (size, size), 22)))
        base = Image.alpha_composite(base, n_rgba)
    except Exception:
        pass
    try:
        scratches = Image.new("L", (size, size), 0)
        sd = ImageDraw.Draw(scratches)
        step = max(10, size // 14)
        for y in range(0, size, step):
            sd.line((0, y, size, y + size // 18), fill=18, width=1)
        scratches = scratches.filter(ImageFilter.GaussianBlur(radius=1.2))
        s_rgba = Image.merge("RGBA", (
            Image.new("L", (size, size), 255),
            Image.new("L", (size, size), 255),
            Image.new("L", (size, size), 255),
            scratches,
        ))
        base = Image.alpha_composite(base, s_rgba)
    except Exception:
        pass
    return base


@lru_cache(maxsize=64)
def _gloss_overlay(size: int) -> Image.Image:
    o = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(o)
    d.ellipse((int(size * 0.08), int(size * 0.04), int(size * 0.86), int(size * 0.55)), fill=(255, 255, 255, 32))
    d.ellipse((int(size * 0.18), int(size * 0.10), int(size * 0.78), int(size * 0.48)), fill=(255, 255, 255, 18))
    try:
        s = Image.effect_noise((size, size), 34)
        s = s.point(lambda p: 0 if p < 160 else int((p - 160) * 1.2))
        s = s.filter(ImageFilter.GaussianBlur(radius=0.8))
        s_rgba = Image.merge("RGBA", (
            Image.new("L", (size, size), 255),
            Image.new("L", (size, size), 255),
            Image.new("L", (size, size), 255),
            s,
        ))
        o = Image.alpha_composite(o, s_rgba)
    except Exception:
        pass
    return o


def _load_font(size: int):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "segoeui.ttf"),
        os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "arial.ttf"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return ImageFont.truetype(p, size=size)
    return ImageFont.load_default()


def _rounded_rect(draw: ImageDraw.ImageDraw, xy, radius: int, fill):
    draw.rounded_rectangle(xy, radius=radius, fill=fill)


@lru_cache(maxsize=256)
def _circle_mask(size: int) -> Image.Image:
    ss = 4
    big = Image.new("L", (size * ss, size * ss), 0)
    ImageDraw.Draw(big).ellipse((0, 0, size * ss - 1, size * ss - 1), fill=255)
    return big.resize((size, size), Image.Resampling.LANCZOS)


def _paste_circle(img: Image.Image, path: str, x: int, y: int, size: int):
    st = Image.open(path).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
    img.paste(st, (x, y), _circle_mask(size))


def _cover_resize(im: Image.Image, size: int) -> Image.Image:
    w, h = im.size
    if w <= 0 or h <= 0:
        return im.resize((size, size), Image.Resampling.LANCZOS)
    scale = max(size / w, size / h)
    nw, nh = int(round(w * scale)), int(round(h * scale))
    im2 = im.resize((nw, nh), Image.Resampling.LANCZOS)
    left = max(0, (nw - size) // 2)
    top = max(0, (nh - size) // 2)
    return im2.crop((left, top, left + size, top + size))


def _draw_chip(*, img: Image.Image, draw: ImageDraw.ImageDraw, sticker_path: str, x: int, y: int, size: int, nominal: int, number: int, font_badge, font_num, show_number: bool = True):
    # soft shadow (blurred)
    try:
        sp = max(10, size // 18)
        shadow = Image.new("RGBA", (size + sp * 4, size + sp * 4), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.ellipse((sp * 2, sp * 2, sp * 2 + size, sp * 2 + size), fill=(0, 0, 0, 95))
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=sp))
        img.alpha_composite(shadow, (x - sp * 2 + 2, y - sp * 2 + 6))
    except Exception:
        draw.ellipse((x + 6, y + 10, x + size + 8, y + size + 12), fill=(0, 0, 0, 70))

    ring_color = CHIP_RING[min(max(1, nominal), 9) - 1] if nominal < 10 else CHIP_RING_GOLD
    draw.ellipse((x, y, x + size, y + size), fill=ring_color)

    rim = int(round(max(6, size // 28) * 1.5))
    tex = _rim_texture(size)

    rim_mask = _circle_mask(size)
    inner_mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(inner_mask).ellipse((rim, rim, size - 1 - rim, size - 1 - rim), fill=255)
    rim_only = ImageChops.subtract(rim_mask, inner_mask)
    tmp_rim = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    tmp_rim.paste(tex, (0, 0), rim_only)
    try:
        dark = Image.new("RGBA", (size, size), _scale_rgba(ring_color, 0.72))
        light = Image.new("RGBA", (size, size), _scale_rgba(ring_color, 1.12))
        grad = Image.new("L", (size, size), 0)
        gd = ImageDraw.Draw(grad)
        gd.ellipse((int(size * 0.00), int(size * 0.10), int(size * 0.95), int(size * 1.02)), fill=120)
        gd.ellipse((int(size * 0.05), int(size * 0.00), int(size * 0.90), int(size * 0.62)), fill=200)
        grad = grad.filter(ImageFilter.GaussianBlur(radius=max(2, size // 18)))
        color_rim = Image.composite(light, dark, grad).convert("RGBA")
        rim_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        rim_layer.paste(color_rim, (0, 0), rim_only)
        # add fine texture details on top of the colored rim
        rim_layer = Image.alpha_composite(rim_layer, tmp_rim)
        tmp_rim = rim_layer
    except Exception:
        pass
    img.alpha_composite(tmp_rim, (x, y))

    inner = size - 2 * rim
    inner_x, inner_y = x + rim, y + rim
    draw.ellipse((inner_x, inner_y, inner_x + inner, inner_y + inner), fill=(25, 25, 28, 255))

    try:
        st = Image.open(sticker_path).convert("RGBA")
        st = _cover_resize(st, inner)
        tmp = Image.new("RGBA", (inner, inner), (0, 0, 0, 0))
        tmp.paste(st, (0, 0), _circle_mask(inner))
        img.alpha_composite(tmp, (inner_x, inner_y))
    except Exception:
        pass

    # subtle highlight (gloss) - only on rim (avoid noise over sticker)
    gloss = _gloss_overlay(size).copy()
    try:
        r, g, b, a = gloss.split()
        a = a.point(lambda p: int(p * 0.55))
        gloss = Image.merge("RGBA", (r, g, b, a))
    except Exception:
        pass
    tmp_gloss = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    tmp_gloss.paste(gloss, (0, 0), rim_only)
    img.alpha_composite(tmp_gloss, (x, y))

    ss = 4

    if show_number:
        n = f"№{number}"
        nb = draw.textbbox((0, 0), n, font=font_num)
        ntw, nth = nb[2] - nb[0], nb[3] - nb[1]
        pad = 10
        bw = max(34, ntw + pad * 2)
        bh = max(34, nth + pad * 2)
        nx = x + 10
        ny = y + 10
        badge = Image.new("RGBA", (bw * ss, bh * ss), (0, 0, 0, 0))
        bd = ImageDraw.Draw(badge)
        bd.rounded_rectangle((0, 0, bw * ss - 1, bh * ss - 1), radius=14 * ss, fill=(80, 80, 86, 235))
        badge = badge.resize((bw, bh), Image.Resampling.LANCZOS)
        img.alpha_composite(badge, (nx, ny))
        draw.text((nx + (bw - ntw) / 2 - nb[0], ny + (bh - nth) / 2 - nb[1]), n, font=font_num, fill=(245, 245, 245, 255))

    energy = str(nominal)
    try:
        font_energy = _load_font(getattr(font_badge, "size", 24) + 10)
    except Exception:
        font_energy = font_badge
    eb = draw.textbbox((0, 0), energy, font=font_energy)
    etw, eth = eb[2] - eb[0], eb[3] - eb[1]
    icon = max(20, int(round(eth * 1.10)))
    pad_x, pad_y = 14, 12
    bw = pad_x * 2 + icon + 8 + etw
    bh = pad_y * 2 + max(icon, eth)
    bx2, by2 = x + size - 12, y + size - 12
    bx1, by1 = bx2 - bw, by2 - bh
    badge2 = Image.new("RGBA", (bw * ss, bh * ss), (0, 0, 0, 0))
    bd2 = ImageDraw.Draw(badge2)
    bd2.rounded_rectangle((0, 0, bw * ss - 1, bh * ss - 1), radius=16 * ss, fill=C_BLUE, outline=(236, 190, 63, 255), width=max(2, ss * 2))
    badge2 = badge2.resize((bw, bh), Image.Resampling.LANCZOS)
    img.alpha_composite(badge2, (bx1, by1))

    lx = bx1 + pad_x
    ly = by1 + (bh - icon) / 2
    s = float(icon)
    bolt = [
        (lx + s * 0.55, ly + s * 0.02),
        (lx + s * 0.20, ly + s * 0.58),
        (lx + s * 0.50, ly + s * 0.58),
        (lx + s * 0.30, ly + s * 0.98),
        (lx + s * 0.84, ly + s * 0.36),
        (lx + s * 0.52, ly + s * 0.36),
    ]
    draw.polygon(bolt, fill=(255, 255, 255, 255))
    try:
        draw.line(bolt + [bolt[0]], fill=(236, 190, 63, 255), width=2)
    except Exception:
        pass
    tx = lx + icon + 8
    ty = by1 + (bh - eth) / 2
    draw.text((tx - eb[0], ty - eb[1]), energy, font=font_energy, fill=(255, 255, 255, 255))


def _draw_bowling_ball(draw: ImageDraw.ImageDraw, cx: int, cy: int, radius: int) -> None:
    r = radius
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(40, 40, 50, 255))
    hr = max(2, r // 5)
    draw.ellipse((cx - r // 3 - hr, cy - r // 3 - hr, cx - r // 3 + hr, cy - r // 3 + hr), fill=(80, 80, 90, 255))
    draw.ellipse((cx + r // 6 - hr, cy - r // 2 - hr, cx + r // 6 + hr, cy - r // 2 + hr), fill=(80, 80, 90, 255))
    draw.ellipse((cx + r // 2 - hr, cy - r // 5 - hr, cx + r // 2 + hr, cy - r // 5 + hr), fill=(80, 80, 90, 255))


def _draw_bolt(draw: ImageDraw.ImageDraw, x: int, y: int, size: int, *, fill=(255, 255, 255, 255), outline=(236, 190, 63, 255)) -> None:
    s = float(size)
    bolt = [
        (x + s * 0.55, y + s * 0.02),
        (x + s * 0.20, y + s * 0.58),
        (x + s * 0.50, y + s * 0.58),
        (x + s * 0.36, y + s * 0.98),
        (x + s * 0.84, y + s * 0.36),
        (x + s * 0.52, y + s * 0.36),
    ]
    draw.polygon(bolt, fill=fill)
    try:
        draw.line(bolt + [bolt[0]], fill=outline, width=2)
    except Exception:
        pass


def render_profile(*, user_title: str, avatar_path: str | None, stickers: List[RenderSticker], out_path: str, empty_lines: List[str] | None = None, duels_count: int = 0, lang: str = "ru") -> str:
    w = 900
    cols, chip = 3, 220
    gap_x, gap_y = 35, 55
    header_bottom = 220
    start_y = 360
    bottom_pad = 80
    if stickers:
        rows = (len(stickers) + cols - 1) // cols
        chips_h = rows * chip + max(0, (rows - 1)) * gap_y
        h = max(720, start_y + chips_h + bottom_pad)
    else:
        h = 720
    bg = Image.new("RGBA", (w, h), C_BG)
    draw = ImageDraw.Draw(bg)
    ft = _load_font(40)
    fs = _load_font(26)
    fb = _load_font(24)
    fn = _load_font(24)

    _rounded_rect(draw, (40, 40, w - 40, 220), radius=30, fill=C_CARD)

    header_top, header_bottom = 40, header_bottom
    header_h = header_bottom - header_top
    left_x = 70

    title_bb = draw.textbbox((0, 0), user_title, font=ft)
    title_h = title_bb[3] - title_bb[1]

    total_chips = len(stickers)
    total_energy = sum(int(s.count) for s in stickers)
    totals_text = t(lang, "profile_totals", chips=total_chips)
    totals_bb = draw.textbbox((0, 0), totals_text, font=fs)
    totals_h = totals_bb[3] - totals_bb[1]

    gap1 = 10
    block_h = title_h + gap1 + totals_h
    y0 = header_top + max(0, int((header_h - block_h) / 2))

    y_title = y0
    y_totals = y_title + title_h + gap1

    draw.text((left_x, y_title - title_bb[1]), user_title, font=ft, fill=C_TEXT)

    draw.text((left_x, y_totals - totals_bb[1]), totals_text, font=fs, fill=C_SUB)
    bolt_x = left_x + (totals_bb[2] - totals_bb[0])
    bolt_size = 20
    bolt_y = int(y_totals + (totals_h - bolt_size) / 2)
    _draw_bolt(draw, int(bolt_x), bolt_y, bolt_size)
    energy_duels_text = t(lang, "profile_energy_duels", energy=total_energy, duels=duels_count)
    draw.text((int(bolt_x) + bolt_size + 6, y_totals - totals_bb[1]), energy_duels_text, font=fs, fill=C_SUB)

    _rounded_rect(draw, (40, 260, w - 40, h - 40), radius=30, fill=C_CARD)

    if not stickers:
        lines = [t(lang, "no_chips")]
        if empty_lines:
            lines.extend([str(x) for x in empty_lines if str(x).strip()])
        y = 380
        for ln in lines:
            draw.text((70, y), ln, font=fs, fill=C_SUB)
            y += 40
    else:
        inner_left, inner_right = 40, w - 40
        inner_w = inner_right - inner_left
        grid_w = cols * chip + (cols - 1) * gap_x
        start_x = inner_left + max(0, (inner_w - grid_w) // 2)
        for i, s in enumerate(stickers):
            r, c = i // cols, i % cols
            x = start_x + c * (chip + gap_x)
            y = start_y + r * (chip + gap_y)
            _draw_chip(img=bg, draw=draw, sticker_path=s.path, x=x, y=y, size=chip, nominal=int(s.count), number=i + 1, font_badge=fb, font_num=fn)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    bg.convert("RGB").save(out_path, "PNG")
    return out_path


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    tmp_img = Image.new("RGBA", (1, 1))
    tmp_draw = ImageDraw.Draw(tmp_img)
    for word in words:
        test = (cur + " " + word).strip()
        bb = tmp_draw.textbbox((0, 0), test, font=font)
        if bb[2] - bb[0] > max_width and cur:
            lines.append(cur)
            cur = word
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines or [text]


def render_duel_result(
    *,
    title: str,
    user_title: str,
    avatar_path: str | None,
    attacker_label: str,
    defender_label: str,
    attacker_delta: int,
    defender_delta: int,
    attacker_gained: List[RenderSticker],
    defender_gained: List[RenderSticker],
    out_path: str,
    lang: str = "ru",
) -> str:
    w = 900
    chip_sz, cols, chip_gap = 220, 3, 35
    PAD_L = 70

    def _grid_h(items: List[RenderSticker]) -> int:
        if not items:
            return 40
        rows = (len(items) + cols - 1) // cols
        return rows * chip_sz + (rows - 1) * chip_gap

    ft = _load_font(40)
    fs = _load_font(28)
    fb = _load_font(24)
    fn = _load_font(24)

    BALL_R = 14
    title_lines = _wrap_text(user_title, ft, w - PAD_L - 40)
    line_h = ft.size + 6
    header_text_h = len(title_lines) * line_h + 10 + (fs.size + 4)
    header_h = max(180, header_text_h + 60)

    ag_h = _grid_h(attacker_gained)
    dg_h = _grid_h(defender_gained)

    LABEL_H = 50
    DELTA_H = 60
    TROPHIES_LABEL_H = 44
    SECTION_GAP = 50
    PAD_TOP = 30
    PAD_BOTTOM = 50

    main_content_h = (PAD_TOP + LABEL_H + DELTA_H + TROPHIES_LABEL_H + ag_h +
                      SECTION_GAP + LABEL_H + DELTA_H + TROPHIES_LABEL_H + dg_h + PAD_BOTTOM)

    header_top = 40
    header_bottom = header_top + header_h
    main_top = header_bottom + 30
    h = main_top + main_content_h + 40

    bg = Image.new("RGBA", (w, h), C_BG)
    draw = ImageDraw.Draw(bg)

    _rounded_rect(draw, (40, header_top, w - 40, header_bottom), radius=30, fill=C_CARD)
    ty = header_top + 30
    for ln in title_lines:
        draw.text((PAD_L, ty), ln, font=ft, fill=C_TEXT)
        ty += line_h
    score_y = ty + 4
    ball_cx = PAD_L + BALL_R
    ball_cy = score_y + fs.size // 2
    _draw_bowling_ball(draw, ball_cx, ball_cy, BALL_R)
    draw.text((PAD_L + BALL_R * 2 + 8, score_y), title, font=fs, fill=C_SUB)

    _rounded_rect(draw, (40, main_top, w - 40, h - 40), radius=30, fill=C_CARD)

    def _draw_delta_line(v: int, y: int) -> None:
        sign = "+" if v >= 0 else "\u2212"
        sign_bb = draw.textbbox((0, 0), sign, font=ft)
        sign_w = sign_bb[2] - sign_bb[0]
        draw.text((PAD_L, y), sign, font=ft, fill=C_TEXT)
        bolt_x = PAD_L + sign_w + 12
        _draw_bolt(draw, bolt_x, y + 10, 26)
        draw.text((bolt_x + 34, y), str(abs(v)), font=ft, fill=C_TEXT)

    def render_grid(items: List[RenderSticker], top_y: int) -> None:
        for i, s in enumerate(items):
            r, c = i // cols, i % cols
            x = PAD_L + c * (chip_sz + chip_gap)
            y = top_y + r * (chip_sz + chip_gap)
            _draw_chip(img=bg, draw=draw, sticker_path=s.path, x=x, y=y, size=chip_sz,
                       nominal=int(s.count), number=i + 1, font_badge=fb, font_num=fn, show_number=False)
        if not items:
            draw.text((PAD_L, top_y + 8), t(lang, "no_chips"), font=fs, fill=C_SUB)

    y = main_top + PAD_TOP
    draw.text((PAD_L, y), str(attacker_label), font=ft, fill=C_TEXT)
    y += LABEL_H
    _draw_delta_line(attacker_delta, y)
    y += DELTA_H
    draw.text((PAD_L, y), t(lang, "trophies"), font=fs, fill=C_SUB)
    y += TROPHIES_LABEL_H
    render_grid(attacker_gained, y)
    y += ag_h + SECTION_GAP

    draw.text((PAD_L, y), str(defender_label), font=ft, fill=C_TEXT)
    y += LABEL_H
    _draw_delta_line(defender_delta, y)
    y += DELTA_H
    draw.text((PAD_L, y), t(lang, "trophies"), font=fs, fill=C_SUB)
    y += TROPHIES_LABEL_H
    render_grid(defender_gained, y)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    bg.convert("RGB").save(out_path, "PNG")
    return out_path


def render_battle_result(
    *,
    title: str,
    user_title: str,
    avatar_path: str | None,
    lost: List[RenderSticker],
    won: List[RenderSticker],
    out_path: str,
    top_label: str = "Выиграно",
    bottom_label: str = "Соперник:",
    show_bottom: bool = True,
    header_energy: int | None = None,
    lang: str = "ru",
) -> str:
    w, h = 900, 1200
    bg = Image.new("RGBA", (w, h), C_BG)
    draw = ImageDraw.Draw(bg)
    ft = _load_font(40)
    fs = _load_font(28)
    fb = _load_font(24)
    fn = _load_font(24)

    _rounded_rect(draw, (40, 40, w - 40, 220), radius=30, fill=C_CARD)
    has_avatar = False
    if avatar_path and os.path.exists(avatar_path):
        try:
            _paste_circle(bg, avatar_path, 70, 80, 90)
            has_avatar = True
        except Exception:
            pass
    text_x = 180 if has_avatar else 70
    draw.text((text_x, 80), user_title, font=ft, fill=C_TEXT)
    draw.text((text_x, 140), title, font=fs, fill=C_SUB)

    _rounded_rect(draw, (40, 250, w - 40, h - 40), radius=30, fill=C_CARD)
    won_energy = sum(int(s.count) for s in won)
    lost_energy = sum(int(s.count) for s in lost)
    if str(top_label).strip() in (t(lang, "attacker"), t(lang, "attacker_dash")):
        label_text = t(lang, "attacker")
        sep_text = " "
    else:
        label_text = str(top_label)
        sep_text = ""

    x0, y0 = 70, 280
    draw.text((x0, y0), label_text, font=ft, fill=C_TEXT)
    lb = draw.textbbox((0, 0), label_text, font=ft)
    lw = lb[2] - lb[0]
    sb = draw.textbbox((0, 0), sep_text, font=ft)
    sw = sb[2] - sb[0]
    x_sep = x0 + lw
    if sep_text:
        draw.text((x_sep, y0), sep_text, font=ft, fill=C_TEXT)

    bolt_size = 26
    x_bolt = x_sep + sw
    _draw_bolt(draw, int(x_bolt), 292, bolt_size)
    draw.text((int(x_bolt + bolt_size + 6), y0), str(won_energy), font=ft, fill=C_TEXT)
    if show_bottom:
        draw.text((70, 760), str(bottom_label), font=ft, fill=C_TEXT)
        _draw_bolt(draw, 330, 772, 26)
        draw.text((362, 760), str(lost_energy), font=ft, fill=C_TEXT)

    def render_grid(items: List[RenderSticker], top_y: int):
        chip, cols, gap = 220, 3, 35
        for i, s in enumerate(items[:9]):
            r, c = i // cols, i % cols
            x = 70 + c * (chip + gap)
            y = top_y + r * (chip + gap)
            _draw_chip(img=bg, draw=draw, sticker_path=s.path, x=x, y=y, size=chip, nominal=int(s.count), number=i + 1, font_badge=fb, font_num=fn)
        if not items:
            draw.text((70, top_y + 20), "-", font=fs, fill=C_SUB)

    render_grid(won, 350)
    if show_bottom:
        render_grid(lost, 830)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    bg.convert("RGB").save(out_path, "PNG")
    return out_path

