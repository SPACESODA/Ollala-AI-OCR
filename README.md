# Ollala AI OCR

A local macOS AI-based OCR utility for converting PDFs and images into Markdown
with `glm-ocr` running through Ollama.

The workflow stays local: PDFs are rendered into page images with Poppler,
images are normalized with Pillow, each page/image is sent to the local Ollama
model, and the result is saved as `.md`.

To use Ollala locally with a clean, user-friendly web interface, check out the [Web Interface Guide](README-web.md).

If you want ultra-fast, non-AI-based PDF to text conversion, check out my other open-source project: [pdf2txt](https://spacesoda.github.io/pdf2txt/).

## Why Not Use Ollama Directly?

Ollama does not natively support reading or parsing PDF files currently. It handles multimodal inputs by accepting images. Because of this, the PDF must first be rendered into page-by-page images (which we do using Poppler), and then each image is passed to the `glm-ocr` model on your local Ollama for text extraction. This script seamlessly automates that entire process for you.

## What It Does

- Converts one PDF or image into a Markdown file.
- Converts a folder of PDFs/images in batch.
- Optionally scans folders recursively.
- Preserves multi-page PDFs as one Markdown file.
- Separates PDF pages with `---` in the final Markdown.
- Asks `glm-ocr` to extract text, tables, and formulas in clean Markdown.
- Prints progress while processing files and pages.
- Processes PDF pages one at a time instead of loading the whole PDF into RAM.
- Writes PDF output incrementally after each page, so partial progress is kept
  if a later page fails.
- Checks for common setup problems before running OCR.

Supported image formats:

```text
png, jpg, jpeg, webp, tif, tiff, bmp
```

## Requirements

This project is built for macOS, especially Apple Silicon Macs.

You need:

- Python 3
- Ollama running in the background
- The latest `glm-ocr` model installed in Ollama
- Poppler for PDF conversion
- Python packages from `requirements.txt`

Poppler is required for PDFs. Install it once from Terminal:

```bash
brew install poppler
```

Make sure Ollama is running before starting OCR. Also make sure `glm-ocr` is
installed:

```bash
ollama pull glm-ocr
ollama list
```

`ollama list` should show `glm-ocr` or `glm-ocr:latest`.

## Setup

Clone the repository and install dependencies:

```bash
git clone https://github.com/realanthonyc/ollala-ai-ocr.git
cd ollala-ai-ocr
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

If Poppler or `glm-ocr` are not installed yet, run:

```bash
brew install poppler
ollama pull glm-ocr
```

## Command Line Usage

Run commands from the project directory:

```bash
cd ollala-ai-ocr
```

Convert one PDF:

```bash
.venv/bin/python ocr_to_md.py /path/to/file.pdf
```

Convert one image:

```bash
.venv/bin/python ocr_to_md.py /path/to/image.png
```

Convert all supported files in a folder:

```bash
.venv/bin/python ocr_to_md.py /path/to/input-folder
```

Convert a folder and its subfolders:

```bash
.venv/bin/python ocr_to_md.py /path/to/input-folder --recursive
```

Choose where Markdown files are saved:

```bash
.venv/bin/python ocr_to_md.py /path/to/input-folder -o /path/to/output-folder
```

Use a lighter setting for large or scanned PDFs:

```bash
.venv/bin/python ocr_to_md.py /path/to/file.pdf --dpi 100 --max-side 1400 --num-ctx 4096 --keep-alive 0 --request-timeout 120
```

## Tuning Quality vs Stability

Start with the safe profile if the PDF is large, scanned, image-heavy, or if
the Mac becomes sluggish during OCR:

```bash
.venv/bin/python ocr_to_md.py /path/to/file.pdf --dpi 100 --max-side 1400 --num-ctx 4096 --keep-alive 0 --request-timeout 120
```

If that works, try a balanced profile:

```bash
.venv/bin/python ocr_to_md.py /path/to/file.pdf --dpi 140 --max-side 1800 --num-ctx 8192 --keep-alive 30s
```

For cleaner or smaller PDFs, the default profile may give better OCR detail:

```bash
.venv/bin/python ocr_to_md.py /path/to/file.pdf
```

If you need more OCR detail and the Mac remains stable, increase quality
gradually:

```bash
.venv/bin/python ocr_to_md.py /path/to/file.pdf --dpi 180 --max-side 2200 --num-ctx 16384
```

Avoid jumping straight to very high DPI on large scanned PDFs. Higher DPI and
larger `--max-side` values create larger images for Ollama and can sharply
increase memory pressure.

## Command Options

```text
input
  Required. A PDF, image, or directory containing supported files.

-o, --output-dir
  Output folder for Markdown files.
  Default: markdown_output inside the input folder.

--model
  Ollama model name.
  Default: glm-ocr

--dpi
  PDF render resolution.
  Higher values can improve OCR quality but increase memory use and latency.
  Default: 160

--max-side
  Maximum image side length before sending an image to Ollama.
  Lower this if OCR is too slow or memory pressure is high.
  Default: 2000

--image-format
  Temporary image format sent to Ollama.
  JPEG is smaller and usually safer for large PDFs. PNG is lossless but heavier.
  Default: jpeg

--jpeg-quality
  JPEG quality when --image-format jpeg is used.
  Default: 85

--num-ctx
  Ollama context window.
  The default follows the high-resolution OCR setting, but lowering it can
  reduce memory pressure.
  Default: 16384

--keep-alive
  How long Ollama keeps the model loaded after each request.
  Use 0 to unload after each page if memory pressure is a problem.
  Default: 30s

--page-retries
  Retry failed PDF pages with lighter image/context settings.
  Default: 2

--stop-on-page-error
  Stop the PDF if a page fails. By default, failed pages get a Markdown error
  marker and the script continues.

--request-timeout
  Per-page Ollama request timeout in seconds.
  Default: 180

--start-page
  First PDF page to process. Useful for testing or splitting a large PDF.
  Default: 1

--end-page
  Last PDF page to process. Useful for testing or splitting a large PDF.
  Default: end of PDF

--recursive
  Scan input directories recursively.
```

## Output

For a single file:

```text
file.pdf -> markdown_output/file.md
image.png -> markdown_output/image.md
```

For a folder, the script keeps the relative folder structure in the output
directory.

For multi-page PDFs, all pages are combined into one Markdown file:

```markdown
Page 1 content

---

Page 2 content
```

## Troubleshooting

If PDF conversion fails, check Poppler:

```bash
which pdftoppm
brew install poppler
```

If the script cannot connect to Ollama, open the Ollama app or start the Ollama
service, then check:

```bash
ollama list
```

If `glm-ocr` is missing:

```bash
ollama pull glm-ocr
```

If large PDFs are slow, memory-heavy, or make Ollama unstable, use the safer
profile:

```bash
.venv/bin/python ocr_to_md.py /path/to/file.pdf --dpi 100 --max-side 1400 --num-ctx 4096 --keep-alive 0 --request-timeout 120
```

If only one page fails because Ollama returns a model/server error, the script
now retries that page with lighter settings. If it still fails, the default
behavior is to write a clear error marker for that page and continue with the
remaining pages. Add `--stop-on-page-error` if you prefer the old fail-fast
behavior.

To test a single difficult page before running the whole PDF:

```bash
.venv/bin/python ocr_to_md.py /path/to/file.pdf --start-page 6 --end-page 6 --dpi 90 --max-side 1100 --num-ctx 2048 --keep-alive 0 --request-timeout 90
```

OCR quality depends on the source document, scan clarity, PDF render DPI, image
resolution, and the current `glm-ocr` model behavior. For clean digital PDFs,
lower DPI may be enough. For scanned or dense documents, higher DPI may improve
accuracy at the cost of speed.

If the Mac becomes sluggish during OCR, stop the run and restart with lower
`--dpi`, lower `--max-side`, lower `--num-ctx`, and `--keep-alive 0`.
