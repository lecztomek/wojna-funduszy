import csv
import json
import re
from pathlib import Path
from typing import Dict, Tuple, List, Any, Optional

from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageChops


# =========================
# Utils
# =========================
def sanitize_filename(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"[^\w\-ąćęłńóśźżĄĆĘŁŃÓŚŹŻ ]+", "", s)
    s = re.sub(r"\s+", "_", s)
    return s[:80] if s else "karta"


def clamp_int(v, default=0) -> int:
    if v is None:
        return default
    s = str(v).strip()
    if s == "" or s == "—":
        return default
    try:
        return int(float(s))
    except Exception:
        return default


def should_show_icon(raw_value, mode="positive") -> bool:
    """
    Wspiera:
      - positive: pokaż tylko gdy > 0
      - nonzero: pokaż gdy != 0
      - negative: pokaż tylko gdy < 0
      - always: zawsze pokaż
    """
    mode = (mode or "positive").lower()

    if mode == "always":
        return True

    s = "" if raw_value is None else str(raw_value).strip()
    if s == "" or s == "—":
        return False

    v = clamp_int(raw_value, 0)

    if mode == "positive":
        return v > 0
    if mode == "nonzero":
        return v != 0
    if mode == "negative":
        return v < 0

    return v > 0


def hex_to_rgb(s: str) -> Tuple[int, int, int]:
    s = (s or "").strip().lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def load_font(font_name: str, size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        font_name,
        f"./{font_name}",
        f"./assets/{font_name}",
        "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def wrap_lines(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> List[str]:
    words = (text or "").split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def resolve_theme(row: Dict[str, str], layout: Dict[str, Any]) -> str:
    """
    Ustala motyw karty: 'jasny' albo 'ciemny'.

    Kolejność:
    1) jeśli layout ma theme_key i wiersz ma taką kolumnę -> użyj jej
    2) jeśli layout ma type_key i wartość kończy się na _jasne / _ciemne -> wyciągnij z niej
    3) fallback -> layout.theme_default albo 'jasny'
    """
    theme_key = (layout.get("theme_key") or "").strip()
    if theme_key:
        raw = (row.get(theme_key) or "").strip().lower()
        if raw in ("jasny", "ciemny"):
            return raw

    type_key = (layout.get("type_key") or "").strip()
    if type_key:
        raw = (row.get(type_key) or "").strip().lower()
        if raw.endswith("_jasne"):
            return "jasny"
        if raw.endswith("_ciemne"):
            return "ciemny"

    return (layout.get("theme_default") or "jasny").strip().lower()


def resolve_theme_value(value, theme: str, default=None):
    """
    Jeśli value jest zwykłą wartością -> zwraca ją bez zmian.
    Jeśli value jest dict-em, np. {"jasny": "#000", "ciemny": "#FFF"},
    to zwraca value[theme] albo fallback.
    """
    if isinstance(value, dict):
        if theme in value:
            return value[theme]
        if "default" in value:
            return value["default"]
        if default is not None:
            return default
        return next(iter(value.values()), None)
    return value if value is not None else default


def draw_text(draw: ImageDraw.ImageDraw, spec: Dict[str, Any], value: str, theme: str = "jasny"):
    x, y = spec["xy"]
    max_width = int(spec.get("max_width", 99999))
    max_height = int(spec.get("max_height", 0))
    valign = (spec.get("valign") or "top").lower()

    font = load_font(spec.get("font", "DejaVuSans.ttf"), int(spec.get("size", 28)))

    color_raw = resolve_theme_value(spec.get("color", "#FFFFFF"), theme, "#FFFFFF")
    stroke = int(spec.get("stroke", 0))
    stroke_color_raw = resolve_theme_value(spec.get("stroke_color", "#000000"), theme, "#000000")

    color = hex_to_rgb(color_raw)
    stroke_color = hex_to_rgb(stroke_color_raw)
    align = spec.get("align", "left")

    txt = "" if value is None else str(value)

    max_lines = spec.get("max_lines")
    if max_lines:
        max_lines = int(max_lines)
        lines = wrap_lines(draw, txt, font, max_width)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1].rstrip() + "…"

        line_h = int(spec.get("line_height", int(int(spec.get("size", 28)) * 1.25)))
        block_h = len(lines) * line_h

        y_start = y
        if max_height > 0:
            if valign in ("middle", "center"):
                y_start = y + max(0, (max_height - block_h) // 2)
            elif valign in ("bottom", "end"):
                y_start = y + max(0, max_height - block_h)

        for i, line in enumerate(lines):
            lx = x
            if align == "center":
                lw = draw.textlength(line, font=font)
                lx = x + (max_width - lw) / 2
            elif align == "right":
                lw = draw.textlength(line, font=font)
                lx = x + (max_width - lw)

            draw.text(
                (lx, y_start + i * line_h),
                line,
                font=font,
                fill=color,
                stroke_width=stroke,
                stroke_fill=stroke_color,
            )
        return

    # single-line
    bbox = draw.textbbox((0, 0), txt, font=font, stroke_width=stroke)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    if align == "center":
        x = x + (max_width - tw) / 2
    elif align == "right":
        x = x + (max_width - tw)

    if max_height > 0:
        if valign in ("middle", "center"):
            y = y + (max_height - th) / 2 - bbox[1]
        elif valign in ("bottom", "end"):
            y = y + (max_height - th) - bbox[1]
        else:
            y = y - bbox[1]

    draw.text(
        (x, y),
        txt,
        font=font,
        fill=color,
        stroke_width=stroke,
        stroke_fill=stroke_color,
    )


def draw_value_badge(
    img: Image.Image,
    xy: Tuple[int, int],
    size: Tuple[int, int],
    value: int,
    cfg: Optional[Dict[str, Any]]
):
    """
    Rysuje badge z liczbą na ikoncie.
    Jeśli cfg nie istnieje, nic nie robi.
    Dzięki temu zachowujemy kompatybilność wsteczną.
    """
    if not cfg:
        return

    if isinstance(cfg, bool):
        cfg = {}

    show_when = (cfg.get("show_when") or "always").lower()

    if show_when == "not_one" and abs(value) == 1:
        return
    if show_when == "nonzero" and value == 0:
        return
    if show_when == "only_negative" and value >= 0:
        return
    if show_when == "only_multi" and abs(value) <= 1:
        return

    text = str(value)

    font = load_font(cfg.get("font", "DejaVuSans-Bold.ttf"), int(cfg.get("size", 28)))
    color = hex_to_rgb(cfg.get("color", "#FFFFFF"))
    stroke = int(cfg.get("stroke", 2))
    stroke_color = hex_to_rgb(cfg.get("stroke_color", "#000000"))

    badge_fill = hex_to_rgb(cfg.get("badge_fill", "#111111"))
    badge_outline = hex_to_rgb(cfg.get("badge_outline", "#FFFFFF"))
    outline_width = int(cfg.get("outline_width", 2))
    radius = int(cfg.get("radius", 14))

    pad_x = int(cfg.get("padding_x", 10))
    pad_y = int(cfg.get("padding_y", 4))

    off_x = int(cfg.get("offset_x", size[0] - 6))
    off_y = int(cfg.get("offset_y", size[1] - 6))

    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    bw = tw + pad_x * 2
    bh = th + pad_y * 2

    x = int(xy[0] + off_x - bw)
    y = int(xy[1] + off_y - bh)

    draw.rounded_rectangle(
        (x, y, x + bw, y + bh),
        radius=radius,
        fill=badge_fill,
        outline=badge_outline,
        width=outline_width
    )

    tx = x + pad_x
    ty = y + pad_y - bbox[1]

    draw.text(
        (tx, ty),
        text,
        font=font,
        fill=color,
        stroke_width=stroke,
        stroke_fill=stroke_color
    )


def paste_scaled(dst: Image.Image, src: Image.Image, xy: Tuple[int, int], size: Tuple[int, int], alpha=255):
    src = src.convert("RGBA")
    if size:
        src = src.resize((int(size[0]), int(size[1])), Image.LANCZOS)
    if alpha != 255:
        a = src.split()[-1]
        a = ImageEnhance.Brightness(a).enhance(alpha / 255.0)
        src.putalpha(a)
    dst.paste(src, (int(xy[0]), int(xy[1])), src)


# =========================
# Icon cache
# =========================
ICON_CACHE: Dict[str, Image.Image] = {}


def load_icon_cached(path: Path) -> Optional[Image.Image]:
    p = str(path)
    if p in ICON_CACHE:
        return ICON_CACHE[p]
    if not path.exists():
        return None
    img = Image.open(path).convert("RGBA")
    ICON_CACHE[p] = img
    return img


# =========================
# Photo helpers
# =========================
def fit_cover(img: Image.Image, w: int, h: int) -> Image.Image:
    """Skaluje i kadruje do w×h (cover)."""
    img = img.convert("RGBA")
    sw, sh = img.size
    if sw <= 0 or sh <= 0:
        return Image.new("RGBA", (w, h), (0, 0, 0, 0))

    scale = max(w / sw, h / sh)
    nw, nh = int(sw * scale + 0.5), int(sh * scale + 0.5)
    img = img.resize((nw, nh), Image.LANCZOS)

    x0 = (nw - w) // 2
    y0 = (nh - h) // 2
    return img.crop((x0, y0, x0 + w, y0 + h))


def rounded_mask(w: int, h: int, r: int) -> Image.Image:
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle((0, 0, w, h), radius=r, fill=255)
    return m


def normalize_key_name(s: str) -> str:
    """
    Normalizuje nazwę kolumny:
    - zamienia niełamiące spacje na zwykłe,
    - ścina spacje z początku/końca,
    - redukuje wielokrotne spacje do jednej.
    """
    if s is None:
        return ""
    s = str(s).replace("\u00a0", " ")
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    return s


# =========================
# PLACE: foto
# =========================
def place_photo(img: Image.Image, row: Dict[str, str], layout: Dict[str, Any], assets_dir: Path):
    place_cfg = layout.get("place") or {}
    cfg = place_cfg.get("photo")
    if not cfg:
        print("INFO: place.photo not configured in layout")
        return

    declared_key = cfg.get("key", "Foto")
    norm_target = normalize_key_name(declared_key)

    photo_col = None
    for k in row.keys():
        if normalize_key_name(k) == norm_target:
            photo_col = k
            break

    if photo_col is None:
        print(
            "INFO: could not match photo column for",
            repr(declared_key),
            "normalized as",
            repr(norm_target),
            "available keys:",
            [repr(k) for k in row.keys()],
        )
        return

    raw_val = row.get(photo_col)
    if raw_val is None:
        print(f"INFO: value for photo column '{photo_col}' is None")
        return

    rel = str(raw_val).strip()
    if not rel:
        print(f"INFO: empty value for photo column '{photo_col}'")
        return

    full_path = assets_dir / rel
    src = load_icon_cached(full_path)
    if not src:
        print("WARN: photo not found:", full_path)
        return

    at = cfg.get("at", {"x": 0, "y": 0})
    size = cfg.get("size", {"w": src.width, "h": src.height})
    w, h = int(size.get("w", src.width)), int(size.get("h", src.height))

    mode = (cfg.get("mode") or "cover").lower()
    if mode == "contain":
        tmp = src.copy()
        tmp.thumbnail((w, h), Image.LANCZOS)
        out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ox = (w - tmp.width) // 2
        oy = (h - tmp.height) // 2
        out.paste(tmp, (ox, oy), tmp)
    else:
        out = fit_cover(src, w, h)

    r = int(cfg.get("radius", 0) or 0)
    if r > 0:
        m = rounded_mask(w, h, r)
        a = out.split()[-1]
        out.putalpha(ImageChops.multiply(a, m))

    x = int(at.get("x", 0))
    y = int(at.get("y", 0))
    print(
        f"INFO: drawing photo from column {repr(photo_col)} "
        f"('{rel}') at ({x},{y}) size ({w}x{h})"
    )
    img.paste(out, (x, y), out)


# =========================
# PLACE: generyczne wiersze ikonek
# =========================
def place_icon_rows(
    img: Image.Image,
    row: Dict[str, str],
    layout: Dict[str, Any],
    assets_dir: Path
):
    """
    Generyczne rysowanie wierszy ikonek na podstawie liczb w CSV.

    Kompatybilność wsteczna:
      - stare layouty działają bez zmian,
      - jeśli nie podasz show_when / repeat_mode / value_label,
        zachowanie pozostaje jak wcześniej.

    Layout (przykład):

      "assets": {
        "karty": {
          "Karta(Uni)": "icons/karta_uni.png",
          "Karta(Kon)": "icons/karta_kon.png"
        }
      },

      "place": {
        "icon_rows": [
          {
            "assets_group": "karty",
            "keys": ["Karta(Uni)", "Karta(Kon)"],
            "at": { "x": 100, "y": 950 },
            "draw_icon": { "w": 80, "h": 80 },
            "gap_x": 8,
            "row_gap": 10,
            "max_cols": 10,
            "flow": "rows",

            "show_when": "positive",
            "repeat_mode": "abs",
            "value_label": {
              "show_when": "nonzero",
              "font": "DejaVuSans-Bold.ttf",
              "size": 28
            }
          }
        ]
      }

    flow:
      - "rows": każdy key = osobny wiersz, ikonki w poziomie
      - "down": jedna kolumna, wszystkie typy po kolei w pionie
      - "flat": wszystkie ikonki z różnych key w jednym ciągu

    show_when:
      - "positive" | "nonzero" | "negative" | "always"

    repeat_mode:
      - "abs"  -> powtarzaj ikonę |value| razy
      - "once" -> pokaż jedną ikonę i opcjonalny badge z wartością
    """
    place_cfg = layout.get("place") or {}
    icon_rows = place_cfg.get("icon_rows")
    if not icon_rows:
        return

    if isinstance(icon_rows, dict):
        icon_rows = [icon_rows]

    assets_all = layout.get("assets") or {}

    for cfg in icon_rows:
        if not cfg:
            continue

        assets_group = cfg.get("assets_group")
        if not assets_group:
            continue

        assets_map = assets_all.get(assets_group, {})
        if not assets_map:
            continue

        keys: List[str] = cfg.get("keys") or list(assets_map.keys())

        at = cfg.get("at", {"x": 0, "y": 0})
        start_x = int(at.get("x", 0))
        start_y = int(at.get("y", 0))

        draw_icon = cfg.get("draw_icon", {"w": 60, "h": 60})
        iw = int(draw_icon.get("w", 60))
        ih = int(draw_icon.get("h", 60))

        gap_x = int(cfg.get("gap_x", 8))
        gap_y = int(cfg.get("gap_y", 8))
        row_gap = int(cfg.get("row_gap", 10))

        max_cols = cfg.get("max_cols")
        max_cols = int(max_cols) if max_cols not in (None, "", 0) else None

        flow = (cfg.get("flow") or "rows").lower()

        # NOWE, ale opcjonalne -> wstecznie kompatybilne
        show_when = (cfg.get("show_when") or "positive").lower()
        repeat_mode = (cfg.get("repeat_mode") or "abs").lower()
        value_label = cfg.get("value_label")

        def repeats_for(value: int) -> int:
            if repeat_mode == "once":
                return 1
            return max(1, abs(value))

        # -----------------------------
        # flow == "down": jedna kolumna, wszystkie typy po kolei
        # -----------------------------
        if flow == "down":
            cursor_y = start_y
            for key in keys:
                raw_value = row.get(key, 0)
                value = clamp_int(raw_value, 0)

                if not should_show_icon(raw_value, show_when):
                    continue

                rel = assets_map.get(key)
                if not rel:
                    continue

                icon = load_icon_cached(assets_dir / rel)
                if not icon:
                    continue

                repeats = repeats_for(value)

                for n in range(repeats):
                    x = start_x
                    y = cursor_y

                    paste_scaled(img, icon, (x, y), (iw, ih))

                    if n == 0:
                        draw_value_badge(img, (x, y), (iw, ih), value, value_label)

                    cursor_y += ih + gap_y
            continue

        # -----------------------------
        # flow == "flat":
        # wszystkie ikonki z różnych key w jednym ciągu
        # -----------------------------
        if flow == "flat":
            anchor = (cfg.get("anchor") or "topleft").lower()

            planned = []

            for key in keys:
                raw_value = row.get(key, 0)
                value = clamp_int(raw_value, 0)

                if not should_show_icon(raw_value, show_when):
                    continue

                rel = assets_map.get(key)
                if not rel:
                    continue

                icon = load_icon_cached(assets_dir / rel)
                if not icon:
                    continue

                repeats = repeats_for(value)

                for _ in range(repeats):
                    planned.append({
                        "icon": icon,
                        "iw": iw,
                        "ih": ih
                    })

            if not planned:
                continue

            if anchor == "center" and not max_cols:
                total_w = sum(p["iw"] for p in planned) + gap_x * (len(planned) - 1)
                cursor_x = start_x - total_w // 2

                for p in planned:
                    x = cursor_x
                    y = start_y
                    paste_scaled(img, p["icon"], (x, y), (p["iw"], p["ih"]))
                    cursor_x += p["iw"] + gap_x
                continue

            idx = 0
            for p in planned:
                if max_cols and max_cols > 0:
                    col = idx % max_cols
                    wrap_row = idx // max_cols
                else:
                    col = idx
                    wrap_row = 0

                x = start_x + col * (p["iw"] + gap_x)
                y = start_y + wrap_row * (p["ih"] + row_gap)

                paste_scaled(img, p["icon"], (x, y), (p["iw"], p["ih"]))
                idx += 1
            continue

        # -----------------------------
        # flow == "rows": każdy key ma własny wiersz
        # -----------------------------
        current_row = 0
        for key in keys:
            raw_value = row.get(key, 0)
            value = clamp_int(raw_value, 0)

            if not should_show_icon(raw_value, show_when):
                continue

            rel = assets_map.get(key)
            if not rel:
                continue

            icon = load_icon_cached(assets_dir / rel)
            if not icon:
                continue

            repeats = repeats_for(value)
            y = start_y + current_row * (ih + row_gap)

            for n in range(repeats):
                if max_cols and max_cols > 0:
                    col = n % max_cols
                    wrap_row = n // max_cols
                    x = start_x + col * (iw + gap_x)
                    yy = y + wrap_row * (ih + row_gap)
                else:
                    x = start_x + n * (iw + gap_x)
                    yy = y

                paste_scaled(img, icon, (x, yy), (iw, ih))

                if n == 0:
                    draw_value_badge(img, (x, yy), (iw, ih), value, value_label)

            current_row += 1


def place_value_icons(
    img: Image.Image,
    row: Dict[str, str],
    layout: Dict[str, Any],
    assets_dir: Path
):
    """
    Rysuje ikonki wybierane na podstawie wartości w CSV.

    Layout:
      "assets": {
        "nagroda_value": {
          "0": "votes/neu/0.png",
          "1": "votes/neu/1.png",
          "2": "votes/neu/2.png",
          "3": "votes/neu/3.png"
        }
      },

      "place": {
        "value_icons": [
          {
            "key": "Nagroda",
            "assets_group": "nagroda_value",
            "at": { "x": 512, "y": 1310 },
            "draw_icon": { "w": 180, "h": 180 },
            "anchor": "center"
          }
        ]
      }

    Dla danego wpisu:
      - czyta row["Nagroda"],
      - szuka ikony o kluczu "1", "2", "3" (albo "0" fallback),
      - rysuje JEDNĄ ikonkę.
    """
    place_cfg = layout.get("place") or {}
    cfg_list = place_cfg.get("value_icons")
    if not cfg_list:
        return

    if isinstance(cfg_list, dict):
        cfg_list = [cfg_list]

    assets_all = layout.get("assets") or {}

    for cfg in cfg_list:
        if not cfg:
            continue

        key = cfg.get("key")
        group = cfg.get("assets_group")
        if not key or not group:
            continue

        assets_map = assets_all.get(group, {})
        if not assets_map:
            continue

        val = clamp_int(row.get(key, 0), 0)
        rel = assets_map.get(str(val)) or assets_map.get("0")
        if not rel:
            continue

        icon = load_icon_cached(assets_dir / rel)
        if not icon:
            continue

        at = cfg.get("at", {"x": 0, "y": 0})
        x = int(at.get("x", 0))
        y = int(at.get("y", 0))

        draw_icon = cfg.get("draw_icon", {"w": icon.width, "h": icon.height})
        iw = int(draw_icon.get("w", icon.width))
        ih = int(draw_icon.get("h", icon.height))

        anchor = (cfg.get("anchor") or "topleft").lower()
        if anchor == "center":
            x = x - iw // 2
            y = y - ih // 2

        paste_scaled(img, icon, (x, y), (iw, ih))


# =========================
# Rendering
# =========================
def render_card(row: Dict[str, str], layout: Dict[str, Any], assets_dir: Path) -> Image.Image:
    cw, ch = layout.get("canvas", [1024, 1536])
    cw, ch = int(cw), int(ch)

    def resolve_code_by_map(value: str, token_map: Dict[str, List[str]], default: str) -> str:
        v = (value or "").strip()
        v_low = v.lower()
        for code, tokens in (token_map or {}).items():
            for t in (tokens or []):
                if not t:
                    continue
                if t == v or t.lower() == v_low:
                    return code
                if t in v or t.lower() in v_low:
                    return code
        return default

    # -------------------------
    # wybór tła:
    # 1) type_map + backgrounds
    # 2) background
    # -------------------------
    bg_path: Optional[Path] = None

    if layout.get("type_map") and layout.get("backgrounds"):
        type_key = (layout.get("type_key") or "Typ")
        type_value = row.get(type_key, "")
        type_code = resolve_code_by_map(type_value, layout.get("type_map", {}), default="std")
        bg_file = (layout.get("backgrounds") or {}).get(type_code, "")
        bg_file = (bg_file or "").strip()
        if bg_file:
            bg_path = assets_dir / bg_file

    if bg_path is None:
        bg_single = (layout.get("background") or "").strip()
        if bg_single:
            bg_path = assets_dir / bg_single

    if bg_path and bg_path.exists():
        img = Image.open(bg_path).convert("RGBA")
        if img.size != (cw, ch):
            img = img.resize((cw, ch), Image.LANCZOS)
    else:
        img = Image.new("RGBA", (cw, ch), (0, 0, 0, 255))

    # -------------------------
    # warstwy
    # -------------------------
    place_photo(img, row, layout, assets_dir)
    place_icon_rows(img, row, layout, assets_dir)
    place_value_icons(img, row, layout, assets_dir)

    theme = resolve_theme(row, layout)

    draw = ImageDraw.Draw(img)
    for t in (layout.get("texts") or []):
        if "value" in t:
            value = t.get("value", "")
        else:
            key = t.get("key", "")
            value = row.get(key, "")
        draw_text(draw, t, value, theme=theme)

    return img


# =========================
# CLI
# =========================
def main():
    import argparse

    def clamp_quality(v: int) -> int:
        return max(1, min(100, int(v)))

    def resolve_jpeg_subsampling(v: str):
        """
        Pillow:
          0 = 4:4:4
          1 = 4:2:2
          2 = 4:2:0
        """
        mapping = {
            "4:4:4": 0,
            "4:2:2": 1,
            "4:2:0": 2,
        }
        return mapping[v]

    ap = argparse.ArgumentParser()
    ap.add_argument("--layout", required=True, help="ścieżka do layout.json")
    ap.add_argument("--csv", required=True, help="CSV (separator ;)")
    ap.add_argument("--out", required=True, help="folder wyjściowy")
    ap.add_argument("--assets", required=True, help="folder z assetami")
    ap.add_argument(
        "--prefix",
        default="",
        help="prefiks nazwy plików, np. 'kampania1'"
    )

    ap.add_argument(
        "--format",
        default="png",
        choices=["png", "jpeg", "jpg"],
        help="format wyjściowy plików"
    )
    ap.add_argument(
        "--jpeg-quality",
        type=int,
        default=95,
        help="jakość JPEG w zakresie 1-100"
    )
    ap.add_argument(
        "--jpeg-subsampling",
        default="4:4:4",
        choices=["4:4:4", "4:2:2", "4:2:0"],
        help="sampling chromy dla JPEG"
    )

    args = ap.parse_args()

    layout = json.loads(Path(args.layout).read_text(encoding="utf-8"))
    assets_dir = Path(args.assets)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    file_prefix = sanitize_filename(args.prefix)
    if file_prefix:
        file_prefix += "_"

    out_format = "jpeg" if args.format in ("jpeg", "jpg") else "png"
    file_ext = "jpg" if out_format == "jpeg" else "png"
    jpeg_quality = clamp_quality(args.jpeg_quality)
    jpeg_subsampling = resolve_jpeg_subsampling(args.jpeg_subsampling)

    with open(args.csv, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for i, row in enumerate(reader, start=1):
            nazwisko = (row.get("Nazwa") or row.get("Nazwisko") or "").strip()
            img = render_card(row, layout, assets_dir)

            out_path = out_dir / f"{file_prefix}{i:04d}_{sanitize_filename(nazwisko)}.{file_ext}"

            if out_format == "jpeg":
                # JPEG nie wspiera przezroczystości, więc spłaszczamy do białego tła
                rgba = img.convert("RGBA")
                jpg_img = Image.new("RGB", rgba.size, (255, 255, 255))
                jpg_img.paste(rgba, mask=rgba.getchannel("A"))

                jpg_img.save(
                    out_path,
                    format="JPEG",
                    quality=jpeg_quality,
                    subsampling=jpeg_subsampling,
                    optimize=True,
                )
            else:
                img.save(out_path, format="PNG")

            print("OK:", out_path)


if __name__ == "__main__":
    main()