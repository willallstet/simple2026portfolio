#!/usr/bin/env python3
"""
Create smaller display versions of portfolio images.

Reads image paths from index.html, resizes for web display, and writes outputs
under photos/display/ (mirroring photos/ paths). Uses Pillow so Display P3 /
EXIF orientation are handled correctly (unlike sips).

Requirements: pip install pillow

Usage:
  python3 scripts/make-display-images.py
  python3 scripts/make-display-images.py --max-width 800
  python3 scripts/make-display-images.py --include-intro --intro-max 120
  python3 scripts/make-display-images.py --dry-run

After running, point <img src="..."> to photos/display/... for the smaller files.
GIFs are skipped — use scripts/reencode-gifs.sh for those.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    from PIL import Image, ImageOps
except ImportError:
    print("Pillow is required. Install with: pip install pillow", file=sys.stderr)
    sys.exit(1)

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
INDEX_HTML = ROOT_DIR / "index.html"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "photos" / "display"

IMAGE_RE = re.compile(
    r'''(?:src|data-src)\s*=\s*["']([^"']+\.(?:jpg|jpeg|png|avif|webp|gif|JPG|JPEG|PNG))["']''',
    re.IGNORECASE,
)

SKIP_NAMES = {"my-classic-thumb.jpg"}
SKIP_SUFFIXES = {".gif"}


def human_size(num_bytes: int) -> str:
    if num_bytes >= 1_048_576:
        return f"{num_bytes / 1_048_576:.1f}M"
    if num_bytes >= 1024:
        return f"{num_bytes / 1024:.1f}K"
    return f"{num_bytes}B"


def parse_image_paths(html_path: Path) -> list[Path]:
    text = html_path.read_text(encoding="utf-8")
    raw_paths: list[str] = []
    for match in IMAGE_RE.finditer(text):
        raw = match.group(1).strip()
        if raw.startswith("./"):
            raw = raw[2:]
        raw_paths.append(raw)

    seen: set[Path] = set()
    ordered: list[Path] = []
    for raw in raw_paths:
        path = (ROOT_DIR / raw).resolve()
        if not path.is_relative_to(ROOT_DIR):
            continue
        if path in seen:
            continue
        seen.add(path)
        ordered.append(path)
    return ordered


def output_path_for(source: Path, output_dir: Path) -> Path:
    if source.is_relative_to(ROOT_DIR / "photos"):
        rel = source.relative_to(ROOT_DIR / "photos")
        return output_dir / rel
    name = source.name
    return output_dir / name


def has_alpha(im: Image.Image) -> bool:
    if im.mode in ("RGBA", "LA"):
        return True
    if im.mode == "P" and "transparency" in im.info:
        return True
    return False


def choose_format(source: Path, im: Image.Image) -> str:
    if has_alpha(im):
        return "PNG"
    if source.suffix.lower() == ".avif":
        return "AVIF"
    return "JPEG"


def adjust_extension(path: Path, fmt: str) -> Path:
    if fmt == "JPEG":
        return path.with_suffix(".jpg")
    if fmt == "PNG":
        return path.with_suffix(".png")
    if fmt == "AVIF":
        return path.with_suffix(".avif")
    return path


def save_image(im: Image.Image, dest: Path, fmt: str, jpeg_quality: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    save_kwargs: dict = {"optimize": True}

    if fmt == "JPEG":
        if im.mode != "RGB":
            im = im.convert("RGB")
        save_kwargs["quality"] = jpeg_quality
        im.save(dest, "JPEG", **save_kwargs)
        return

    if fmt == "PNG":
        if im.mode not in ("RGBA", "RGB", "P"):
            im = im.convert("RGBA" if has_alpha(im) else "RGB")
        im.save(dest, "PNG", **save_kwargs)
        return

    if fmt == "AVIF":
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if has_alpha(im) else "RGB")
        try:
            im.save(dest, "AVIF", quality=jpeg_quality)
        except Exception:
            dest = adjust_extension(dest, "JPEG")
            save_image(im, dest, "JPEG", jpeg_quality)
        return

    raise ValueError(f"Unsupported format: {fmt}")


def process_image(
    source: Path,
    output_dir: Path,
    max_width: int,
    jpeg_quality: int,
    dry_run: bool,
) -> tuple[Path, int, int] | None:
    if not source.exists():
        print(f"  skip missing source: {source.relative_to(ROOT_DIR)}")
        return None

    if source.name in SKIP_NAMES:
        print(f"  skip {source.name} (already optimized)")
        return None

    if source.suffix.lower() in SKIP_SUFFIXES:
        print(f"  skip {source.name} (use scripts/reencode-gifs.sh for GIFs)")
        return None

    im = Image.open(source)
    im = ImageOps.exif_transpose(im)
    orig_size = source.stat().st_size

    if im.width <= max_width and source.suffix.lower() in {".avif", ".jpg", ".jpeg"}:
        w, h = im.size
        if orig_size < 80_000:
            print(f"  skip {source.name} ({human_size(orig_size)}, already small enough)")
            return None

    ratio = min(1.0, max_width / im.width)
    if ratio < 1.0:
        new_size = (max(1, int(im.width * ratio)), max(1, int(im.height * ratio)))
        im = im.resize(new_size, Image.Resampling.LANCZOS)

    fmt = choose_format(source, im)
    dest = adjust_extension(output_path_for(source, output_dir), fmt)

    if dry_run:
        print(
            f"  would write {dest.relative_to(ROOT_DIR)} "
            f"({im.width}x{im.height} {fmt}, from {human_size(orig_size)})"
        )
        return dest, orig_size, 0

    save_image(im, dest, fmt, jpeg_quality)
    out_size = dest.stat().st_size
    return dest, orig_size, out_size


def main() -> int:
    parser = argparse.ArgumentParser(description="Create smaller display images for the portfolio.")
    parser.add_argument("--max-width", type=int, default=800, help="Max width in pixels (default: 800)")
    parser.add_argument(
        "--intro-max",
        type=int,
        default=120,
        help="Max width for photos/line-items when --include-intro is set (default: 120)",
    )
    parser.add_argument(
        "--include-intro",
        action="store_true",
        help="Also rebuild photos/line-items thumbnails",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory (default: photos/display/)",
    )
    parser.add_argument("--jpeg-quality", type=int, default=85, help="JPEG/AVIF quality (default: 85)")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing files")
    args = parser.parse_args()

    if not INDEX_HTML.exists():
        print(f"Could not find {INDEX_HTML}", file=sys.stderr)
        return 1

    sources = parse_image_paths(INDEX_HTML)
    if not args.include_intro:
        sources = [p for p in sources if "line-items" not in p.parts]

    if not sources:
        print("No images found in index.html")
        return 0

    output_dir = args.output_dir.resolve()
    print(f"Output: {output_dir.relative_to(ROOT_DIR)}/")
    print(f"Max width: {args.max_width}px (intro: {args.intro_max}px when included)\n")

    total_before = 0
    total_after = 0
    count = 0

    for source in sources:
        rel = source.relative_to(ROOT_DIR)
        max_width = args.intro_max if "line-items" in source.parts else args.max_width
        print(f"==> {rel}")

        result = process_image(
            source,
            output_dir,
            max_width,
            args.jpeg_quality,
            args.dry_run,
        )
        if not result:
            continue

        dest, before, after = result
        if not args.dry_run:
            total_before += before
            total_after += after
            count += 1
            print(f"  {human_size(before)} -> {human_size(after)}  ({dest.relative_to(ROOT_DIR)})")

    if args.dry_run:
        return 0

    if count:
        saved = total_before - total_after
        pct = (saved / total_before * 100) if total_before else 0
        print(f"\nDone. {count} images written to {output_dir.relative_to(ROOT_DIR)}/")
        print(f"Total: {human_size(total_before)} -> {human_size(total_after)} (~{pct:.0f}% smaller)")
    else:
        print("\nNo images were written.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
