import argparse
import math
import re
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, ImageDraw
import img2pdf

A4_W_MM = 210
A4_H_MM = 297


def mm_to_px(mm: float, dpi: int) -> int:
    return int(round(mm / 25.4 * dpi))


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def collect_jpegs(folder: Path):
    exts = {".jpg", ".jpeg"}
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in exts]
    files.sort(key=lambda p: natural_key(p.name))
    return files


def transform_back(im: Image.Image, rotate180: bool, mirror: bool) -> Image.Image:
    # rotate/mirror całej grafiki rewersu (na wypadek gdy drukarka robi "do góry nogami")
    if mirror:
        im = ImageOps.mirror(im)
    if rotate180:
        im = im.rotate(180, expand=False)
    return im


def paste_contain(dst: Image.Image, src: Image.Image, x0: int, y0: int, w: int, h: int):
    sw, sh = src.size
    scale = min(w / sw, h / sh)
    nw = max(1, int(round(sw * scale)))
    nh = max(1, int(round(sh * scale)))
    src = src.resize((nw, nh), Image.LANCZOS)
    x = x0 + (w - nw) // 2
    y = y0 + (h - nh) // 2
    dst.paste(src, (x, y))


def draw_cut_lines(page: Image.Image, margin: int, gap: int, cell_w: int, cell_h: int):
    # Rysuje cienkie linie TYLKO w "gapach" i na marginesie (żeby nie wchodziły na karty)
    d = ImageDraw.Draw(page)
    W, H = page.size

    # pionowe (między kolumnami)
    for i in (1, 2):
        x_left = margin + i * cell_w + (i - 1) * gap
        # linia w środku gapa
        x = x_left + gap // 2
        d.line([(x, margin), (x, H - margin)], fill=(0, 0, 0), width=max(1, gap // 20))

    # poziome (między wierszami)
    for i in (1, 2):
        y_top = margin + i * cell_h + (i - 1) * gap
        y = y_top + gap // 2
        d.line([(margin, y), (W - margin, y)], fill=(0, 0, 0), width=max(1, gap // 20))


def main():
    ap = argparse.ArgumentParser(
        description="Duplex PDF A4: 9 awersów na stronie + 9 rewersów na następnej (3x3)."
    )
    ap.add_argument("fronts_dir", help="Folder z awersami (.jpg/.jpeg)")
    ap.add_argument("backs_dir", help="Folder z rewersami (.jpg/.jpeg) — 1 plik (wspólny) lub tyle co awersów")
    ap.add_argument("output_pdf", help="Wyjściowy PDF")
    ap.add_argument("--dpi", type=int, default=300, help="DPI strony A4 (domyślnie 300)")
    ap.add_argument("--quality", type=int, default=85, help="Jakość JPEG stron (domyślnie 85)")
    ap.add_argument("--subsampling", type=int, default=1, choices=[0, 1, 2],
                    help="0 najlepsze krawędzie, 1 kompromis, 2 najmniej waży (domyślnie 1)")
    ap.add_argument("--margin-mm", type=float, default=10.0, help="Margines A4 w mm (domyślnie 10)")
    ap.add_argument("--gap-mm", type=float, default=4.0, help="Odstęp między kartami w mm (domyślnie 4)")
    ap.add_argument("--back-rotate180", action="store_true",
                    help="Obróć rewersy o 180° (jeśli po druku są do góry nogami)")
    ap.add_argument("--back-mirror", action="store_true",
                    help="Odbij rewersy w poziomie (rzadko potrzebne)")
    ap.add_argument("--cut-lines", action="store_true",
                    help="Dodaj linie cięcia w przerwach (gapach)")
    args = ap.parse_args()

    fronts = collect_jpegs(Path(args.fronts_dir))
    backs = collect_jpegs(Path(args.backs_dir))

    if not fronts:
        raise SystemExit("Brak awersów JPG/JPEG.")
    if not backs:
        raise SystemExit("Brak rewersów JPG/JPEG.")

    # rewersy: albo 1 wspólny, albo tyle co awersów
    if len(backs) not in (1, len(fronts)):
        raise SystemExit(f"Rewersy: masz {len(backs)} plików, awersy: {len(fronts)}. "
                         "Daj 1 rewers (wspólny) albo dokładnie tyle co awersów.")

    dpi = args.dpi
    page_w = mm_to_px(A4_W_MM, dpi)
    page_h = mm_to_px(A4_H_MM, dpi)
    margin = mm_to_px(args.margin_mm, dpi)
    gap = mm_to_px(args.gap_mm, dpi)

    cols = rows = 3
    per_page = 9

    usable_w = page_w - 2 * margin - (cols - 1) * gap
    usable_h = page_h - 2 * margin - (rows - 1) * gap
    cell_w = usable_w // cols
    cell_h = usable_h // rows

    def make_sheet(img_paths):
        page = Image.new("RGB", (page_w, page_h), (255, 255, 255))
        for i, path in enumerate(img_paths):
            col = i % cols
            row = i // cols
            x0 = margin + col * (cell_w + gap)
            y0 = margin + row * (cell_h + gap)

            im = Image.open(path).convert("RGB")
            paste_contain(page, im, x0, y0, cell_w, cell_h)

        if args.cut_lines and gap > 0:
            draw_cut_lines(page, margin, gap, cell_w, cell_h)

        bio = BytesIO()
        page.save(
            bio,
            format="JPEG",
            quality=int(args.quality),
            subsampling=int(args.subsampling),
            optimize=True,
            progressive=True,
        )
        bio.seek(0)
        return bio

    page_streams = []

    pages = math.ceil(len(fronts) / per_page)
    for p in range(pages):
        # 9 awersów
        f_chunk = fronts[p * per_page:(p + 1) * per_page]
        page_streams.append(make_sheet(f_chunk))

        # 9 rewersów odpowiadających tym awersom
        if len(backs) == 1:
            b_chunk = [backs[0]] * len(f_chunk)
        else:
            b_chunk = backs[p * per_page:(p + 1) * per_page]

        # transformacje rewersu (gdy drukarka/ustawienie duplex odwraca)
        if args.back_rotate180 or args.back_mirror:
            # robimy tymczasowe JPEG-i w pamięci już po transformacji
            transformed = []
            for bp in b_chunk:
                im = Image.open(bp).convert("RGB")
                im = transform_back(im, rotate180=args.back_rotate180, mirror=args.back_mirror)
                tmp = BytesIO()
                im.save(tmp, format="JPEG", quality=95, subsampling=1, optimize=True)
                tmp.seek(0)
                tmp.name = bp.name
                transformed.append(tmp)
            # teraz składamy z tych “obrazków” jak z plików (Image.open umie BytesIO z .name)
            # prostsze: zapiszmy do pamięci jako obrazy PIL w make_sheet -> tutaj obejście:
            # zrobimy sheet ręcznie:
            page = Image.new("RGB", (page_w, page_h), (255, 255, 255))
            for i, tmp in enumerate(transformed):
                col = i % cols
                row = i // cols
                x0 = margin + col * (cell_w + gap)
                y0 = margin + row * (cell_h + gap)
                im = Image.open(tmp).convert("RGB")
                paste_contain(page, im, x0, y0, cell_w, cell_h)
            if args.cut_lines and gap > 0:
                draw_cut_lines(page, margin, gap, cell_w, cell_h)
            bio = BytesIO()
            page.save(
                bio,
                format="JPEG",
                quality=int(args.quality),
                subsampling=int(args.subsampling),
                optimize=True,
                progressive=True,
            )
            bio.seek(0)
            page_streams.append(bio)
        else:
            page_streams.append(make_sheet(b_chunk))

    a4_pt = (img2pdf.mm_to_pt(A4_W_MM), img2pdf.mm_to_pt(A4_H_MM))
    layout = img2pdf.get_layout_fun(a4_pt)

    pdf_bytes = img2pdf.convert(page_streams, layout_fun=layout)
    Path(args.output_pdf).write_bytes(pdf_bytes)

    print(f"OK: {args.output_pdf} | arkusze: {pages} | strony PDF: {pages*2} | awersy: {len(fronts)} | rewersy: {len(backs)}")


if __name__ == "__main__":
    main()
