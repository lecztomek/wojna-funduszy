import argparse
import math
import re
from io import BytesIO
from pathlib import Path

from PIL import Image
import img2pdf


A4_W_MM = 210
A4_H_MM = 297


def mm_to_px(mm: float, dpi: int) -> int:
    return int(round(mm / 25.4 * dpi))


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def collect_images(folder: Path):
    exts = {".jpg", ".jpeg"}
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in exts]
    files.sort(key=lambda p: natural_key(p.name))
    return files


def get_grid(per_page: int):
    """
    Zwraca układ: kolumny, wiersze.
    Preferuje pionowy układ dla małej liczby kart.
    """
    layouts = {
        1: (1, 1),
        2: (1, 2),
        3: (1, 3),
        4: (2, 2),
        5: (2, 3),
        6: (2, 3),
        7: (2, 4),
        8: (2, 4),
        9: (3, 3),
        10: (2, 5),
        11: (3, 4),
        12: (3, 4),
    }

    if per_page in layouts:
        return layouts[per_page]

    cols = math.ceil(math.sqrt(per_page))
    rows = math.ceil(per_page / cols)
    return cols, rows


def main():
    ap = argparse.ArgumentParser(
        description="Folder JPG -> PDF A4 z dowolną liczbą kart na stronę."
    )
    ap.add_argument("input_dir", help="Folder z .jpg/.jpeg")
    ap.add_argument("output_pdf", help="Wyjściowy PDF")
    ap.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="DPI strony A4, domyślnie 300.",
    )
    ap.add_argument(
        "--quality",
        type=int,
        default=85,
        help="Jakość JPEG dla stron, domyślnie 85.",
    )
    ap.add_argument(
        "--subsampling",
        type=int,
        default=1,
        choices=[0, 1, 2],
        help="0 najlepsze krawędzie, 1 kompromis, 2 najmniej waży.",
    )
    ap.add_argument(
        "--margin-mm",
        type=float,
        default=10.0,
        help="Margines A4 w mm, domyślnie 10.",
    )
    ap.add_argument(
        "--gap-mm",
        type=float,
        default=4.0,
        help="Odstęp między kartami w mm, domyślnie 4.",
    )
    ap.add_argument(
        "--cards-per-page",
        type=int,
        default=9,
        help="Liczba kart na stronę, domyślnie 9.",
    )

    args = ap.parse_args()

    in_dir = Path(args.input_dir)
    out_pdf = Path(args.output_pdf)

    files = collect_images(in_dir)
    if not files:
        raise SystemExit(f"Brak JPG/JPEG w folderze: {in_dir}")

    dpi = args.dpi
    page_w = mm_to_px(A4_W_MM, dpi)
    page_h = mm_to_px(A4_H_MM, dpi)

    margin = mm_to_px(args.margin_mm, dpi)
    gap = mm_to_px(args.gap_mm, dpi)

    per_page = max(1, int(args.cards_per_page))

    cols, rows = get_grid(per_page)

    usable_w = page_w - 2 * margin - (cols - 1) * gap
    usable_h = page_h - 2 * margin - (rows - 1) * gap

    cell_w = usable_w // cols
    cell_h = usable_h // rows

    if cell_w <= 0 or cell_h <= 0:
        raise SystemExit(
            "Za duży margines/odstęp albo za dużo kart na stronę."
        )

    page_streams = []
    pages = math.ceil(len(files) / per_page)

    for p in range(pages):
        page = Image.new("RGB", (page_w, page_h), (255, 255, 255))

        chunk = files[p * per_page:(p + 1) * per_page]

        for i, img_path in enumerate(chunk):
            col = i % cols
            row = i // cols

            x0 = margin + col * (cell_w + gap)
            y0 = margin + row * (cell_h + gap)

            with Image.open(img_path) as opened:
                im = opened.convert("RGB")

            iw, ih = im.size

            scale = min(cell_w / iw, cell_h / ih)
            nw = max(1, int(round(iw * scale)))
            nh = max(1, int(round(ih * scale)))

            im = im.resize((nw, nh), Image.LANCZOS)

            x = x0 + (cell_w - nw) // 2
            y = y0 + (cell_h - nh) // 2

            page.paste(im, (x, y))

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
        bio.name = f"page_{p + 1:04d}.jpg"
        page_streams.append(bio)

    a4_pt = (img2pdf.mm_to_pt(A4_W_MM), img2pdf.mm_to_pt(A4_H_MM))
    layout = img2pdf.get_layout_fun(a4_pt)

    pdf_bytes = img2pdf.convert(page_streams, layout_fun=layout)
    out_pdf.write_bytes(pdf_bytes)

    print(
        f"OK: {out_pdf} | obrazy: {len(files)} | strony: {pages} | "
        f"kart/strona: {per_page} | układ: {cols}x{rows} | "
        f"dpi={dpi} quality={args.quality} subsampling={args.subsampling}"
    )


if __name__ == "__main__":
    main()
