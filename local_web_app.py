#!/usr/bin/env python3
"""
Local web UI for Ollala AI OCR.

Run:
  .venv/bin/python local_web_app.py

Then open:
  http://127.0.0.1:8765
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = BASE_DIR / "ocr_to_md.py"
RUNS_DIR = BASE_DIR / "web_runs"
HOST = "127.0.0.1"
PORT = 8765
WEB_RUN_RETENTION_HOURS = float(os.environ.get("PDF_OCR_WEB_RUN_RETENTION_HOURS", "24"))
CLEANUP_INTERVAL_SECONDS = int(os.environ.get("PDF_OCR_CLEANUP_INTERVAL_SECONDS", "1800"))

SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".tif",
    ".tiff",
    ".bmp",
}

PROFILE_OPTIONS = {
    "safe": {
        "dpi": "120",
        "max_side": "1600",
        "num_ctx": "4096",
        "keep_alive": "0",
        "image_format": "jpeg",
        "jpeg_quality": "82",
        "request_timeout": "300",
        "page_retries": "2",
    },
    "balanced": {
        "dpi": "140",
        "max_side": "1800",
        "num_ctx": "8192",
        "keep_alive": "30s",
        "image_format": "jpeg",
        "jpeg_quality": "85",
        "request_timeout": "420",
        "page_retries": "2",
    },
    "default": {
        "dpi": "160",
        "max_side": "2000",
        "num_ctx": "16384",
        "keep_alive": "30s",
        "image_format": "jpeg",
        "jpeg_quality": "85",
        "request_timeout": "420",
        "page_retries": "2",
    },
    "detail": {
        "dpi": "180",
        "max_side": "2200",
        "num_ctx": "16384",
        "keep_alive": "30s",
        "image_format": "jpeg",
        "jpeg_quality": "88",
        "request_timeout": "600",
        "page_retries": "1",
    },
}


@dataclass
class Job:
    id: str
    status: str = "queued"
    command: list[str] = field(default_factory=list)
    output_dir: Path | None = None
    auto_download: bool = False
    logs: list[str] = field(default_factory=list)
    events: "queue.Queue[str | None]" = field(default_factory=queue.Queue)
    returncode: int | None = None

    def add_log(self, line: str) -> None:
        self.logs.append(line)
        self.events.put(line)


app = Flask(__name__)
jobs: dict[str, Job] = {}
jobs_lock = threading.Lock()


@app.get("/")
def index() -> str:
    return render_template("index.html", profiles=PROFILE_OPTIONS)


@app.post("/api/jobs")
def create_job() -> tuple[Response, int] | Response:
    uploaded_files = request.files.getlist("files")
    relative_paths = request.form.getlist("relative_paths")
    if not uploaded_files:
        return jsonify({"error": "No files were uploaded."}), 400

    job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    job_root = RUNS_DIR / job_id
    input_dir = job_root / "input"
    raw_output_dir = request.form.get("output_dir", "")
    auto_download = not raw_output_dir.strip()
    output_dir = resolve_output_dir(raw_output_dir, job_root)
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    saved_files: list[Path] = []
    for index, uploaded_file in enumerate(uploaded_files):
        raw_relative_path = (
            relative_paths[index]
            if index < len(relative_paths) and relative_paths[index]
            else uploaded_file.filename
        )
        relative_path = safe_relative_path(raw_relative_path, f"upload-{index}")
        if relative_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        destination = input_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        uploaded_file.save(destination)
        saved_files.append(destination)

    if not saved_files:
        return jsonify({"error": "No supported PDF/image files were uploaded."}), 400

    input_target = saved_files[0] if len(saved_files) == 1 else input_dir
    command = build_command(input_target, output_dir, request.form)
    job = Job(
        id=job_id,
        command=command,
        output_dir=output_dir,
        auto_download=auto_download,
    )

    with jobs_lock:
        jobs[job_id] = job

    thread = threading.Thread(target=run_job, args=(job,), daemon=True)
    thread.start()

    return jsonify(
        {
            "job_id": job_id,
            "command": command,
            "output_dir": str(output_dir),
            "auto_download": auto_download,
            "download_url": f"/api/jobs/{job_id}/download",
            "uploaded_files": len(saved_files),
        }
    )


@app.get("/api/jobs/<job_id>")
def get_job(job_id: str) -> tuple[Response, int] | Response:
    job = jobs.get(job_id)
    if job is None:
        return jsonify({"error": "Job not found."}), 404
    return jsonify(job_snapshot(job))


@app.get("/api/jobs/<job_id>/events")
def job_events(job_id: str) -> tuple[Response, int] | Response:
    job = jobs.get(job_id)
    if job is None:
        return jsonify({"error": "Job not found."}), 404

    def stream() -> object:
        for line in job.logs:
            yield sse({"line": line, "status": job.status})
        while True:
            item = job.events.get()
            if item is None:
                yield sse(job_snapshot(job))
                break
            yield sse({"line": item, "status": job.status})

    return Response(stream(), mimetype="text/event-stream")


@app.get("/api/jobs/<job_id>/download")
def download_job(job_id: str) -> tuple[Response, int] | Response:
    job = jobs.get(job_id)
    if job is None:
        return jsonify({"error": "Job not found."}), 404
    if job.status != "completed":
        return jsonify({"error": "Job is not complete yet."}), 409
    if job.output_dir is None or not job.output_dir.exists():
        return jsonify({"error": "Output directory does not exist."}), 404

    markdown_files = sorted(job.output_dir.rglob("*.md"))
    if not markdown_files:
        return jsonify({"error": "No Markdown output files found."}), 404

    if len(markdown_files) == 1:
        return send_file(
            markdown_files[0],
            as_attachment=True,
            download_name=markdown_files[0].name,
            mimetype="text/markdown",
        )

    archive_path = job.output_dir.parent / f"{job.id}-markdown.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for markdown_file in markdown_files:
            archive.write(markdown_file, markdown_file.relative_to(job.output_dir))

    return send_file(
        archive_path,
        as_attachment=True,
        download_name=f"{job.id}-markdown.zip",
        mimetype="application/zip",
    )


@app.get("/api/profiles")
def profiles() -> Response:
    return jsonify(PROFILE_OPTIONS)


@app.post("/api/cleanup")
def cleanup_web_runs() -> Response:
    removed = cleanup_runs(force_completed=True)
    return jsonify({"removed": removed})


@app.post("/api/shutdown")
def shutdown_app() -> tuple[Response, int] | Response:
    if request.remote_addr not in {"127.0.0.1", "::1"}:
        return jsonify({"error": "Shutdown is only available from this Mac."}), 403

    with jobs_lock:
        active_job_ids = [
            job.id for job in jobs.values() if job.status in {"queued", "running"}
        ]

    if active_job_ids:
        return jsonify({"error": "Wait for the current OCR job to finish first."}), 409

    threading.Thread(target=delayed_shutdown, daemon=True).start()
    return jsonify({"message": "Ollala AI OCR is shutting down."})


def resolve_output_dir(raw_output_dir: str, job_root: Path) -> Path:
    cleaned = raw_output_dir.strip()
    if cleaned:
        return Path(cleaned).expanduser().resolve()
    return job_root / "output"


def safe_relative_path(raw_path: str, fallback: str) -> Path:
    raw_path = raw_path.replace("\\", "/").strip()
    parts = []
    for part in raw_path.split("/"):
        if not part or part in {".", ".."}:
            continue
        cleaned = secure_filename(part)
        if cleaned:
            parts.append(cleaned)
    if not parts:
        parts = [secure_filename(fallback) or "upload"]
    return Path(*parts)


def build_command(input_target: Path, output_dir: Path, form: object) -> list[str]:
    profile_name = get_form_value(form, "profile", "safe")
    profile = PROFILE_OPTIONS.get(profile_name, PROFILE_OPTIONS["safe"]).copy()

    for key in (
        "dpi",
        "max_side",
        "num_ctx",
        "keep_alive",
        "image_format",
        "jpeg_quality",
        "request_timeout",
        "page_retries",
    ):
        value = get_form_value(form, key, "")
        if value:
            profile[key] = value

    command = [
        sys.executable,
        str(SCRIPT_PATH),
        str(input_target),
        "-o",
        str(output_dir),
        "--dpi",
        profile["dpi"],
        "--max-side",
        profile["max_side"],
        "--num-ctx",
        profile["num_ctx"],
        "--keep-alive",
        profile["keep_alive"],
        "--image-format",
        profile["image_format"],
        "--jpeg-quality",
        profile["jpeg_quality"],
        "--request-timeout",
        profile["request_timeout"],
        "--page-retries",
        profile["page_retries"],
    ]

    if input_target.is_dir():
        command.append("--recursive")

    return command


def get_form_value(form: object, key: str, default: str) -> str:
    value = form.get(key, default)
    return str(value).strip() if value is not None else default


def run_job(job: Job) -> None:
    job.status = "running"
    job.add_log("Starting OCR job.")
    job.add_log("Command: " + " ".join(job.command))
    job.add_log(f"Output directory: {job.output_dir}")

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    try:
        process = subprocess.Popen(
            job.command,
            cwd=BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        assert process.stdout is not None
        for line in process.stdout:
            job.add_log(line.rstrip())
        job.returncode = process.wait()
        job.status = "completed" if job.returncode == 0 else "failed"
        job.add_log(f"Job finished with exit code {job.returncode}.")
    except Exception as exc:
        job.status = "failed"
        job.add_log(f"Job failed before completion: {exc}")
    finally:
        job.events.put(None)


def cleanup_runs(force_completed: bool = False) -> list[str]:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()
    cutoff = now - (WEB_RUN_RETENTION_HOURS * 3600)
    removed: list[str] = []

    with jobs_lock:
        active_job_ids = {job.id for job in jobs.values() if job.status in {"queued", "running"}}
        finished_job_ids = {
            job.id for job in jobs.values() if job.status in {"completed", "failed"}
        }

    for run_dir in RUNS_DIR.iterdir():
        if not run_dir.is_dir():
            continue
        if run_dir.name in active_job_ids:
            continue

        is_old = run_dir.stat().st_mtime < cutoff
        is_finished = run_dir.name in finished_job_ids
        if force_completed or is_old or is_finished:
            try:
                shutil.rmtree(run_dir)
            except OSError:
                continue
            removed.append(run_dir.name)

    if removed:
        with jobs_lock:
            for job_id in removed:
                jobs.pop(job_id, None)
    return removed


def cleanup_loop() -> None:
    while True:
        time.sleep(CLEANUP_INTERVAL_SECONDS)
        cleanup_runs(force_completed=False)


def delayed_shutdown() -> None:
    time.sleep(0.5)
    os._exit(0)


def job_snapshot(job: Job) -> dict[str, object]:
    return {
        "job_id": job.id,
        "status": job.status,
        "command": job.command,
        "output_dir": str(job.output_dir) if job.output_dir else "",
        "auto_download": job.auto_download,
        "download_url": f"/api/jobs/{job.id}/download",
        "returncode": job.returncode,
        "logs": job.logs,
    }


def sse(payload: dict[str, object]) -> str:
    return "data: " + json.dumps(payload) + "\n\n"


def main() -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    cleanup_runs(force_completed=False)
    cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
    cleanup_thread.start()
    print(f"Starting Ollala AI OCR UI at http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
