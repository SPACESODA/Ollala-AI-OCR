#!/usr/bin/env python3
"""
Ollala AI OCR: local PDF/Image OCR to Markdown using GLM-OCR on Ollama.

Optimized for macOS Apple Silicon workflows:
  - PDFs are rendered to images via pdf2image + Poppler.
  - Images are normalized with Pillow.
  - OCR is sent to the local Ollama service using the glm-ocr model.

Install:
  pip install ollama pdf2image pillow

For PDF support on macOS:
  brew install poppler

Example:
  python ocr_to_md.py ./input.pdf
  python ocr_to_md.py ./scan-folder --output-dir ./markdown
"""

from __future__ import annotations

import argparse
import gc
import io
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Iterable, Sequence


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

MODEL_NAME = "glm-ocr"
PROMPT = (
    "Identify all text, tables, and formulas. Output in clean Markdown format. "
    "Keep the original structure."
)

SUPPORTED_IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".tif",
    ".tiff",
    ".bmp",
}
SUPPORTED_PDF_EXTENSIONS = {".pdf"}


def require_python_dependencies() -> tuple[object, object, object, object]:
    missing: list[str] = []

    try:
        import ollama  # type: ignore
    except ImportError:
        ollama = None
        missing.append("ollama")

    try:
        from pdf2image import convert_from_path, pdfinfo_from_path  # type: ignore
    except ImportError:
        convert_from_path = None
        pdfinfo_from_path = None
        missing.append("pdf2image")

    try:
        from PIL import Image, ImageOps  # type: ignore
    except ImportError:
        Image = None
        ImageOps = None
        missing.append("pillow")

    if missing:
        print("Missing Python dependencies:", ", ".join(missing), file=sys.stderr)
        print("Install them with:", file=sys.stderr)
        print("  pip install ollama pdf2image pillow", file=sys.stderr)
        raise SystemExit(1)

    return ollama, convert_from_path, pdfinfo_from_path, (Image, ImageOps)


def ensure_ollama_available(ollama: object, model_name: str) -> None:
    try:
        response = ollama.list()
    except Exception as exc:
        print("Could not connect to Ollama.", file=sys.stderr)
        print("Make sure the Ollama app/service is running, then try again.", file=sys.stderr)
        print(f"Details: {exc}", file=sys.stderr)
        raise SystemExit(1)

    installed_models = extract_model_names(response)
    if model_name not in installed_models:
        print(f"Ollama is running, but model '{model_name}' was not found.", file=sys.stderr)
        print(f"Install it with: ollama pull {model_name}", file=sys.stderr)
        raise SystemExit(1)


def extract_model_names(ollama_list_response: object) -> set[str]:
    models = getattr(ollama_list_response, "models", None)
    if models is None and isinstance(ollama_list_response, dict):
        models = ollama_list_response.get("models", [])

    names: set[str] = set()
    for model in models or []:
        name = getattr(model, "model", None) or getattr(model, "name", None)
        if name is None and isinstance(model, dict):
            name = model.get("model") or model.get("name")
        if name:
            names.add(str(name))
            names.add(str(name).split(":")[0])
    return names


def ensure_poppler_available_if_needed(paths: Sequence[Path]) -> None:
    needs_pdf = any(path.suffix.lower() in SUPPORTED_PDF_EXTENSIONS for path in paths)
    if not needs_pdf:
        return

    if shutil.which("pdftoppm") and shutil.which("pdfinfo"):
        return

    print("Poppler is required for PDF conversion, but it was not found.")
    if platform.system() == "Darwin" and shutil.which("brew"):
        answer = input("Install it now with 'brew install poppler'? [y/N]: ").strip().lower()
        if answer in {"y", "yes"}:
            try:
                subprocess.run(["brew", "install", "poppler"], check=True)
            except subprocess.CalledProcessError as exc:
                print(f"Failed to install Poppler: {exc}", file=sys.stderr)
                raise SystemExit(1)
            return

    print("Please install Poppler and retry:", file=sys.stderr)
    print("  brew install poppler", file=sys.stderr)
    raise SystemExit(1)


def collect_input_files(input_path: Path, recursive: bool) -> list[Path]:
    if not input_path.exists():
        print(f"Input path does not exist: {input_path}", file=sys.stderr)
        raise SystemExit(1)

    if input_path.is_file():
        if is_supported_file(input_path):
            return [input_path]
        print(f"Unsupported file type: {input_path}", file=sys.stderr)
        raise SystemExit(1)

    pattern = "**/*" if recursive else "*"
    files = [
        path
        for path in input_path.glob(pattern)
        if path.is_file() and is_supported_file(path)
    ]
    return sorted(files, key=lambda path: str(path).lower())


def is_supported_file(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS | SUPPORTED_PDF_EXTENSIONS


def get_pdf_page_count(pdf_path: Path, pdfinfo_from_path: object) -> int:
    try:
        info = pdfinfo_from_path(str(pdf_path))
        return int(info["Pages"])
    except Exception as exc:
        raise RuntimeError(f"Failed to inspect PDF {pdf_path} (it may be broken or password protected): {exc}")


def load_image(path: Path, Image: object) -> object:
    try:
        image = Image.open(path)
        image.load()
        return image
    except Exception as exc:
        raise RuntimeError(f"Failed to open image {path} (it may be broken or an unsupported format): {exc}")


def render_pdf_page(pdf_path: Path, convert_from_path: object, dpi: int, page_num: int) -> object:
    try:
        pages = convert_from_path(
            str(pdf_path),
            dpi=dpi,
            fmt="png",
            first_page=page_num,
            last_page=page_num,
            thread_count=1,
        )
        if not pages:
            raise RuntimeError(f"Poppler returned no image for page {page_num}.")
        return pages[0]
    except Exception as exc:
        raise RuntimeError(f"Failed to convert page {page_num} of PDF {pdf_path}: {exc}")


def prepare_image_bytes(
    image: object,
    ImageOps: object,
    max_side: int,
    image_format: str,
    jpeg_quality: int,
) -> tuple[bytes, str]:
    image = ImageOps.exif_transpose(image)

    if image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")
    elif image.mode == "L":
        image = image.convert("RGB")

    width, height = image.size
    longest_side = max(width, height)
    if longest_side > max_side:
        scale = max_side / longest_side
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        image = image.resize(new_size)

    buffer = io.BytesIO()
    normalized_format = image_format.lower()
    if normalized_format == "jpeg":
        image.save(buffer, format="JPEG", quality=jpeg_quality, optimize=True)
        suffix = ".jpg"
    else:
        image.save(buffer, format="PNG", optimize=True)
        suffix = ".png"
    return buffer.getvalue(), suffix


def ocr_image(
    ollama: object,
    image_bytes: bytes,
    image_suffix: str,
    model_name: str,
    prompt: str,
    num_ctx: int,
    keep_alive: str | None,
) -> str:
    with tempfile.NamedTemporaryFile(suffix=image_suffix, delete=False) as tmp:
        tmp.write(image_bytes)
        tmp_path = tmp.name

    try:
        chat_kwargs = {
            "model": model_name,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [tmp_path],
                }
            ],
            "options": {"num_ctx": num_ctx},
        }
        if keep_alive is not None:
            chat_kwargs["keep_alive"] = keep_alive
        response = ollama.chat(**chat_kwargs)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    message = getattr(response, "message", None)
    if message is None and isinstance(response, dict):
        message = response.get("message", {})

    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")

    if not content:
        raise RuntimeError("Ollama returned an empty OCR response.")
    return str(content).strip()


def ocr_image_with_retries(
    ollama: object,
    page_image: object,
    ImageOps: object,
    model_name: str,
    max_side: int,
    image_format: str,
    jpeg_quality: int,
    num_ctx: int,
    keep_alive: str | None,
    page_retries: int,
) -> str:
    attempts = max(1, page_retries + 1)
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        retry_scale = 0.75 ** (attempt - 1)
        attempt_max_side = max(768, int(max_side * retry_scale))
        attempt_num_ctx = max(2048, int(num_ctx * retry_scale))
        attempt_quality = max(70, int(jpeg_quality - ((attempt - 1) * 5)))

        if attempt > 1:
            print(
                "Retrying image with lighter settings "
                f"(attempt {attempt}/{attempts}, "
                f"max_side={attempt_max_side}, num_ctx={attempt_num_ctx})..."
            )

        try:
            image_bytes, image_suffix = prepare_image_bytes(
                page_image,
                ImageOps,
                attempt_max_side,
                image_format,
                attempt_quality,
            )
            try:
                return ocr_image(
                    ollama,
                    image_bytes,
                    image_suffix,
                    model_name,
                    PROMPT,
                    attempt_num_ctx,
                    keep_alive,
                )
            finally:
                del image_bytes
        except Exception as exc:
            last_error = exc
            print(f"OCR attempt {attempt}/{attempts} failed: {exc}", file=sys.stderr)
            gc.collect()
            if attempt < attempts:
                time.sleep(3)

    raise RuntimeError(last_error or "OCR failed after all retry attempts.")


def output_path_for(input_file: Path, input_root: Path, output_dir: Path) -> Path:
    if input_root.is_dir():
        relative = input_file.relative_to(input_root)
        return output_dir / relative.with_suffix(".md")
    return output_dir / input_file.with_suffix(".md").name


def write_markdown(path: Path, markdown: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown.strip() + "\n", encoding="utf-8")


def append_markdown(path: Path, markdown: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(markdown.strip() + "\n")


def process_file(
    input_file: Path,
    input_root: Path,
    output_dir: Path,
    ollama: object,
    convert_from_path: object,
    pdfinfo_from_path: object,
    Image: object,
    ImageOps: object,
    dpi: int,
    max_side: int,
    image_format: str,
    jpeg_quality: int,
    model_name: str,
    num_ctx: int,
    keep_alive: str | None,
    page_retries: int,
    stop_on_page_error: bool,
    start_page: int,
    end_page: int | None,
) -> Path:
    print(f"\nProcessing file: {input_file}")
    suffix = input_file.suffix.lower()
    output_file = output_path_for(input_file, input_root, output_dir)

    if suffix == ".pdf":
        total_pages = get_pdf_page_count(input_file, pdfinfo_from_path)
        first_page = max(1, start_page)
        last_page = min(total_pages, end_page) if end_page is not None else total_pages
        if first_page > total_pages:
            raise RuntimeError(f"--start-page {first_page} is beyond PDF length {total_pages}.")
        if last_page < first_page:
            raise RuntimeError(f"--end-page {last_page} is before --start-page {first_page}.")

        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text("", encoding="utf-8")

        failed_pages: list[int] = []

        if first_page != 1 or last_page != total_pages:
            append_markdown(
                output_file,
                f"<!-- OCR page range: {first_page}-{last_page} of {total_pages} -->",
            )

        for page_num in range(first_page, last_page + 1):
            print(f"Processing page {page_num}/{total_pages}...")
            page_image = None
            try:
                page_image = render_pdf_page(input_file, convert_from_path, dpi, page_num)
                page_text = ocr_image_with_retries(
                    ollama,
                    page_image,
                    ImageOps,
                    model_name,
                    max_side,
                    image_format,
                    jpeg_quality,
                    num_ctx,
                    keep_alive,
                    page_retries,
                )
            except Exception as exc:
                failed_pages.append(page_num)
                error_text = (
                    f"<!-- OCR failed on page {page_num}/{total_pages}: {exc} -->\n\n"
                    f"> OCR failed on this page after {page_retries + 1} attempt(s)."
                )
                print(f"Page {page_num}/{total_pages} failed: {exc}", file=sys.stderr)
                if stop_on_page_error:
                    raise
                page_text = error_text
            finally:
                if page_image is not None and hasattr(page_image, "close"):
                    page_image.close()

            if page_num > 1:
                append_markdown(output_file, "\n---\n")
            append_markdown(output_file, page_text)

            del page_text
            gc.collect()

        if failed_pages:
            failed_list = ", ".join(str(page) for page in failed_pages)
            print(f"Saved with OCR failures on page(s): {failed_list}", file=sys.stderr)
    else:
        print("Processing image 1/1...")
        image = load_image(input_file, Image)
        try:
            markdown = ocr_image_with_retries(
                ollama=ollama,
                page_image=image,
                ImageOps=ImageOps,
                model_name=model_name,
                max_side=max_side,
                image_format=image_format,
                jpeg_quality=jpeg_quality,
                num_ctx=num_ctx,
                keep_alive=keep_alive,
                page_retries=page_retries,
            )
        finally:
            if hasattr(image, "close"):
                image.close()
        write_markdown(output_file, markdown)

    print(f"Saved: {output_file}")
    return output_file


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert PDFs and images to Markdown using GLM-OCR on local Ollama."
    )
    parser.add_argument(
        "input",
        type=Path,
        help="A PDF/image file or a directory containing PDFs/images.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for .md output. Defaults to '<input-dir>/markdown_output'.",
    )
    parser.add_argument(
        "--model",
        default=MODEL_NAME,
        help=f"Ollama model name. Default: {MODEL_NAME}",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=160,
        help="PDF render DPI. Higher improves OCR but uses more memory. Default: 160.",
    )
    parser.add_argument(
        "--max-side",
        type=int,
        default=2000,
        help="Maximum image side length before sending to Ollama. Default: 2000.",
    )
    parser.add_argument(
        "--image-format",
        choices=("jpeg", "png"),
        default="jpeg",
        help="Temporary image format sent to Ollama. JPEG is smaller; PNG is lossless. Default: jpeg.",
    )
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        default=85,
        help="JPEG quality when --image-format jpeg is used. Default: 85.",
    )
    parser.add_argument(
        "--num-ctx",
        type=int,
        default=16384,
        help="Ollama context window. Lower this if Ollama causes memory pressure. Default: 16384.",
    )
    parser.add_argument(
        "--keep-alive",
        default="30s",
        help="How long Ollama keeps the model loaded after a request. Use 0 to unload after each page. Default: 30s.",
    )
    parser.add_argument(
        "--page-retries",
        type=int,
        default=2,
        help="Retry failed PDF pages with lighter settings. Default: 2.",
    )
    parser.add_argument(
        "--stop-on-page-error",
        action="store_true",
        help="Stop the whole PDF when a page fails instead of writing an error marker and continuing.",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=300.0,
        help="Per-request Ollama timeout in seconds. Default: 300.",
    )
    parser.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="First PDF page to process. Default: 1.",
    )
    parser.add_argument(
        "--end-page",
        type=int,
        default=None,
        help="Last PDF page to process. Default: end of PDF.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recursively scan directories.",
    )
    return parser.parse_args(list(argv))


def validate_args(args: argparse.Namespace) -> None:
    if args.dpi < 72:
        print("--dpi must be at least 72.", file=sys.stderr)
        raise SystemExit(1)
    if args.max_side < 512:
        print("--max-side must be at least 512.", file=sys.stderr)
        raise SystemExit(1)
    if not 1 <= args.jpeg_quality <= 95:
        print("--jpeg-quality must be between 1 and 95.", file=sys.stderr)
        raise SystemExit(1)
    if args.num_ctx < 2048:
        print("--num-ctx must be at least 2048.", file=sys.stderr)
        raise SystemExit(1)
    if args.page_retries < 0:
        print("--page-retries must be 0 or greater.", file=sys.stderr)
        raise SystemExit(1)
    if args.request_timeout <= 0:
        print("--request-timeout must be greater than 0.", file=sys.stderr)
        raise SystemExit(1)
    if args.start_page < 1:
        print("--start-page must be at least 1.", file=sys.stderr)
        raise SystemExit(1)
    if args.end_page is not None and args.end_page < 1:
        print("--end-page must be at least 1.", file=sys.stderr)
        raise SystemExit(1)


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    validate_args(args)
    input_path = args.input.expanduser().resolve()
    input_root = input_path if input_path.is_dir() else input_path.parent
    output_dir = (
        args.output_dir.expanduser().resolve()
        if args.output_dir
        else (input_root / "markdown_output")
    )

    ollama, convert_from_path, pdfinfo_from_path, pillow = require_python_dependencies()
    ollama_client = ollama.Client(timeout=args.request_timeout)
    Image, ImageOps = pillow

    input_files = collect_input_files(input_path, args.recursive)
    if not input_files:
        print(f"No supported PDFs/images found in: {input_path}", file=sys.stderr)
        return 1

    ensure_poppler_available_if_needed(input_files)
    ensure_ollama_available(ollama, args.model)

    print(f"Found {len(input_files)} supported file(s).")
    print(f"Output directory: {output_dir}")
    print(
        "Settings: "
        f"dpi={args.dpi}, max_side={args.max_side}, "
        f"image_format={args.image_format}, num_ctx={args.num_ctx}, "
        f"keep_alive={args.keep_alive}, page_retries={args.page_retries}, "
        f"request_timeout={args.request_timeout}"
    )

    saved_files: list[Path] = []
    for index, input_file in enumerate(input_files, start=1):
        print(f"\nFile {index}/{len(input_files)}")
        try:
            saved_files.append(
                process_file(
                    input_file=input_file,
                    input_root=input_root,
                    output_dir=output_dir,
                    ollama=ollama_client,
                    convert_from_path=convert_from_path,
                    pdfinfo_from_path=pdfinfo_from_path,
                    Image=Image,
                    ImageOps=ImageOps,
                    dpi=args.dpi,
                    max_side=args.max_side,
                    image_format=args.image_format,
                    jpeg_quality=args.jpeg_quality,
                    model_name=args.model,
                    num_ctx=args.num_ctx,
                    keep_alive=args.keep_alive,
                    page_retries=args.page_retries,
                    stop_on_page_error=args.stop_on_page_error,
                    start_page=args.start_page,
                    end_page=args.end_page,
                )
            )
        except Exception as exc:
            print(f"Error processing {input_file}: {exc}", file=sys.stderr)

    print(f"\nDone. Saved {len(saved_files)}/{len(input_files)} Markdown file(s).")
    return 0 if saved_files else 1


if __name__ == "__main__":
    raise SystemExit(main())
