# Ollala AI OCR Web Interface

This project includes a local browser interface for running the same OCR script
without typing command-line options each time.

The web app runs only on your Mac at `127.0.0.1`. Files are uploaded from the
browser to the local Flask backend, processed by `ocr_to_md.py`, and
returned as Markdown output.

For the command-line workflow and core OCR details, see [README.md](myProjects/projects/Ollala-AI-OCR/README.md).

## Start The Web App

On macOS, double-click:

```text
launch.command
```

The launcher starts the local Flask app from this folder, waits until it is
ready, then opens `http://127.0.0.1:8765` in your browser. It uses its own file
location, so it still works if you move the whole project folder elsewhere.

You can also start it manually from the project directory:

```bash
cd /path/to/Ollala-AI-OCR
.venv/bin/python local_web_app.py
```

Then open:

```text
http://127.0.0.1:8765
```

Keep the Terminal window open while using the web interface. Stop the server
with the **Shut Down Ollala** button at the bottom of the web interface, or
with `Control-C` in Terminal. After shutdown, the web page tries to close its
browser tab automatically; if your browser blocks that, close the tab manually.

## What The Web Interface Supports

- Drag-and-drop PDFs and images.
- Drag-and-drop folders in browsers that support folder drops.
- File picker and folder picker buttons.
- Quality profiles: Safe, Balanced, Default Detail, and Higher Detail.
- Manual tuning for DPI, max image side, context size, keep-alive, image format,
  and JPEG quality.
- Optional custom output folder.
- Automatic browser download when the output folder is left blank.
- Manual cleanup for inactive `web_runs`.
- Automatic cleanup for old `web_runs`.
- One-click shutdown for the local web app after OCR jobs are finished.
- Live progress logs from the Python OCR process.

Supported input formats:

```text
pdf, png, jpg, jpeg, webp, tif, tiff, bmp
```

## Output Behavior

If the **Output Folder** field is blank, the web app starts a browser download
when OCR completes:

- One Markdown output downloads as `.md`.
- Multiple Markdown outputs download as `.zip`.
- The browser saves the download to its default Downloads folder.

The web app still keeps a local working copy under:

```text
web_runs/<job-id>/output/
```

Those working files are temporary. The app can remove them in two ways:

- Click **Clear Inactive Runs** in the web interface to delete `web_runs`
  folders that are not currently queued or running.
- Leave the app running and it will automatically remove old `web_runs` folders.
  The default retention is 24 hours.

If you fill in **Output Folder**, Markdown files are saved to that folder
instead of relying on browser download.

Example custom output folder:

```text
/Users/you/Desktop/OCR-Markdown
```

## Why Files Are Copied Into `web_runs`

Browsers do not expose real local file paths to web pages for security. Because
of that, drag-and-drop does not let the backend directly process the original
file path.

The web app uses this flow:

1. The browser sends selected files to the local Flask backend.
2. The backend copies them into `web_runs/<job-id>/input/`.
3. The backend runs `ocr_to_md.py` on that local copy.
4. Markdown is written to `web_runs/<job-id>/output/` or your custom output
   folder.
5. If no custom output folder was set, the browser downloads the result.

## Cleanup Settings

By default, old web-run folders are retained for 24 hours. You can change this
when starting the web app:

```bash
PDF_OCR_WEB_RUN_RETENTION_HOURS=6 .venv/bin/python local_web_app.py
```

The cleanup loop runs every 30 minutes by default. To change that interval:

```bash
PDF_OCR_CLEANUP_INTERVAL_SECONDS=600 .venv/bin/python local_web_app.py
```

The cleanup logic skips active queued/running jobs.

## Quality Profiles

Safe:

```text
dpi=120, max_side=1600, num_ctx=4096, keep_alive=0, timeout=120, retries=2
```

Use this for large, scanned, or image-heavy PDFs.

Balanced:

```text
dpi=140, max_side=1800, num_ctx=8192, keep_alive=30s, timeout=180, retries=2
```

Use this after Safe works and you want more detail.

Default Detail:

```text
dpi=160, max_side=2000, num_ctx=16384, keep_alive=30s, timeout=180, retries=2
```

Use this for smaller or cleaner PDFs.

Higher Detail:

```text
dpi=180, max_side=2200, num_ctx=16384, keep_alive=30s, timeout=240, retries=1
```

Use this only when the Mac remains stable and you need more OCR detail.

## Manual Options

```text
DPI
  PDF render resolution. Higher can improve OCR but increases memory use.

Max Side
  Maximum image side length before sending it to Ollama.

Context
  Ollama context window. Lower values reduce memory pressure.

Keep Alive
  How long Ollama keeps the model loaded after each request.
  Use 0 to unload after each page.

Timeout
  Per-page Ollama timeout in seconds.

Retries
  Number of per-page retries with lighter settings when OCR fails.

Image Format
  JPEG is smaller and usually safer for large PDFs.
  PNG is lossless but heavier.

JPEG Quality
  Compression quality for temporary JPEG images sent to Ollama.

Output Folder
  Optional. If blank, the browser downloads the result.
```

## Troubleshooting

If the web page does not open, make sure the server is still running:

```bash
.venv/bin/python local_web_app.py
```

If OCR fails because Ollama is unavailable, open the Ollama app or start the
Ollama service, then check:

```bash
ollama list
```

If `glm-ocr` is missing:

```bash
ollama pull glm-ocr
```

If PDF conversion fails:

```bash
brew install poppler
which pdftoppm
```

If the Mac becomes sluggish during OCR, use the Safe profile or manually lower
`DPI`, `Max Side`, and `Context`, then set `Keep Alive` to `0`.
