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
    exts = {".jpg", ".jpeg", ".png"}
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in exts]
    files.sort(key=lambda p: natural_key(p.name))
    return files


def parse_grid(grid: str):
    m = re.fullmatch(r"\s*(\d+)\s*x\s*(\d+)\s*", grid.lower())
    if not m:
        raise argparse.ArgumentTypeError("Grid musi mieć format np. 10x8, 3x3, 1x10")

    cols = int(m.group(1))
    rows = int(m.group(2))

    if cols <= 0 or rows <= 0:
        raise argparse.ArgumentTypeError("Liczba kolumn i wierszy musi być większa od 0")

    return cols, rows


def get_grid(per_page: int):
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


def load_image_on_white_background(img_path: Path) -> Image.Image:
    with Image.open(img_path) as opened:
        opened = opened.convert("RGBA")
        background = Image.new("RGBA", opened.size, (255, 255, 255, 255))
        background.alpha_composite(opened)
        return background.convert("RGB")


def main():
    ap = argparse.ArgumentParser(
        description="Folder PNG/JPG/JPEG -> PDF A4 z wybranym układem obrazków na stronie."
    )

    ap.add_argument("input_dir", help="Folder z .png/.jpg/.jpeg")
    ap.add_argument("output_pdf", help="Wyjściowy PDF")

    ap.add_argument(
        "--grid",
        type=parse_grid,
        default=None,
        help="Układ obrazków na stronie, np. 10x8, 3x3, 1x10.",
    )

    ap.add_argument(
        "--cards-per-page",
        type=int,
        default=None,
        help="STARE: liczba obrazków na stronę. Dla kompatybilności wstecznej.",
    )

    ap.add_argument(
        "--copies",
        type=int,
        default=1,
        help="Ile kopii każdego obrazka wstawić, domyślnie 1.",
    )

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
        help="Odstęp między obrazkami w mm, domyślnie 4.",
    )

    args = ap.parse_args()

    in_dir = Path(args.input_dir)
    out_pdf = Path(args.output_pdf)

    files = collect_images(in_dir)
    if not files:
        raise SystemExit(f"Brak PNG/JPG/JPEG w folderze: {in_dir}")

    if args.copies < 1:
        raise SystemExit("--copies musi być >= 1")

    files = [p for p in files for _ in range(args.copies)]

    dpi = args.dpi
    page_w = mm_to_px(A4_W_MM, dpi)
    page_h = mm_to_px(A4_H_MM, dpi)

    margin = mm_to_px(args.margin_mm, dpi)
    gap = mm_to_px(args.gap_mm, dpi)

    if args.grid is not None:
        cols, rows = args.grid
        per_page = cols * rows
    elif args.cards_per_page is not None:
        per_page = max(1, int(args.cards_per_page))
        cols, rows = get_grid(per_page)
    else:
        cols, rows = parse_grid("3x3")
        per_page = cols * rows

    usable_w = page_w - 2 * margin - (cols - 1) * gap
    usable_h = page_h - 2 * margin - (rows - 1) * gap

    cell_w = usable_w // cols
    cell_h = usable_h // rows

    if cell_w <= 0 or cell_h <= 0:
        raise SystemExit("Za duży margines/odstęp albo za dużo obrazków na stronie.")

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

            im = load_image_on_white_background(img_path)

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
        f"OK: {out_pdf} | obrazy po kopiach: {len(files)} | strony: {pages} | "
        f"układ: {cols}x{rows} | obrazków/strona: {per_page} | "
        f"copies={args.copies} | dpi={dpi} quality={args.quality} "
        f"subsampling={args.subsampling}"
    )


if __name__ == "__main__":
    main()
