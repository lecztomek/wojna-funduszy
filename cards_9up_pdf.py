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


def main():
    ap = argparse.ArgumentParser(description="Folder JPG -> PDF A4: 9 kart na stronę (3x3) z realnym downscalem.")
    ap.add_argument("input_dir", help="Folder z .jpg/.jpeg")
    ap.add_argument("output_pdf", help="Wyjściowy PDF")
    ap.add_argument("--dpi", type=int, default=300, help="DPI strony A4 (domyślnie 300). Na ekran można dać 240/200.")
    ap.add_argument("--quality", type=int, default=85, help="Jakość JPEG dla stron (domyślnie 85).")
    ap.add_argument("--subsampling", type=int, default=1, choices=[0, 1, 2],
                    help="0 najlepsze krawędzie, 1 kompromis, 2 najmniej waży (domyślnie 1).")
    ap.add_argument("--margin-mm", type=float, default=10.0, help="Margines A4 w mm (domyślnie 10).")
    ap.add_argument("--gap-mm", type=float, default=4.0, help="Odstęp między kartami w mm (domyślnie 4).")
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

    cols, rows = 3, 3
    per_page = cols * rows

    usable_w = page_w - 2 * margin - (cols - 1) * gap
    usable_h = page_h - 2 * margin - (rows - 1) * gap

    cell_w = usable_w // cols
    cell_h = usable_h // rows

    # przygotuj JPEG strony w pamięci
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

            im = Image.open(img_path).convert("RGB")
            iw, ih = im.size

            # contain (bez kadrowania) + REALNY downscale do komórki
            scale = min(cell_w / iw, cell_h / ih)
            nw = max(1, int(round(iw * scale)))
            nh = max(1, int(round(ih * scale)))
            im = im.resize((nw, nh), Image.LANCZOS)

            x = x0 + (cell_w - nw) // 2
            y = y0 + (cell_h - nh) // 2
            page.paste(im, (x, y))

        bio = BytesIO()
        # zapisuj stronę jako JPEG (to jest główna kompresja)
        page.save(
            bio,
            format="JPEG",
            quality=int(args.quality),
            subsampling=int(args.subsampling),
            optimize=True,
            progressive=True,
        )
        bio.seek(0)
        # (opcjonalnie) nazwa pomaga w debug, img2pdf i tak czyta po nagłówku
        bio.name = f"page_{p+1:04d}.jpg"
        page_streams.append(bio)

    # PDF A4 w punktach (1 in = 72 pt)
    a4_pt = (img2pdf.mm_to_pt(A4_W_MM), img2pdf.mm_to_pt(A4_H_MM))
    layout = img2pdf.get_layout_fun(a4_pt)

    pdf_bytes = img2pdf.convert(page_streams, layout_fun=layout)
    out_pdf.write_bytes(pdf_bytes)

    print(f"OK: {out_pdf} | obrazy: {len(files)} | strony: {pages} | dpi={dpi} quality={args.quality} subsampling={args.subsampling}")


if __name__ == "__main__":
    main()
