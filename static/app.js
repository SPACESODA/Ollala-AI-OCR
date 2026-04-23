const profiles = window.OCR_PROFILES || {};
const selectedFiles = [];

const dropZone = document.querySelector("#dropZone");
const fileInput = document.querySelector("#fileInput");
const folderInput = document.querySelector("#folderInput");
const chooseFiles = document.querySelector("#chooseFiles");
const chooseFolder = document.querySelector("#chooseFolder");
const clearFiles = document.querySelector("#clearFiles");
const clearRuns = document.querySelector("#clearRuns");
const fileList = document.querySelector("#fileList");
const form = document.querySelector("#ocrForm");
const logs = document.querySelector("#logs");
const appStatus = document.querySelector("#appStatus");
const outputPath = document.querySelector("#outputPath");
const runButton = document.querySelector("#runButton");

const profile = document.querySelector("#profile");
const dpi = document.querySelector("#dpi");
const maxSide = document.querySelector("#maxSide");
const numCtx = document.querySelector("#numCtx");
const keepAlive = document.querySelector("#keepAlive");
const requestTimeout = document.querySelector("#requestTimeout");
const pageRetries = document.querySelector("#pageRetries");
const imageFormat = document.querySelector("#imageFormat");
const jpegQuality = document.querySelector("#jpegQuality");
const outputDir = document.querySelector("#outputDir");

chooseFiles.addEventListener("click", () => fileInput.click());
chooseFolder.addEventListener("click", () => folderInput.click());
clearFiles.addEventListener("click", clearSelection);
clearRuns.addEventListener("click", cleanupRuns);

fileInput.addEventListener("change", () => {
  addFiles(Array.from(fileInput.files).map((file) => ({ file, path: file.name })));
  fileInput.value = "";
});

folderInput.addEventListener("change", () => {
  addFiles(
    Array.from(folderInput.files).map((file) => ({
      file,
      path: file.webkitRelativePath || file.name,
    })),
  );
  folderInput.value = "";
});

profile.addEventListener("change", () => applyProfile(profile.value));

dropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  dropZone.classList.add("is-dragging");
});

dropZone.addEventListener("dragleave", () => {
  dropZone.classList.remove("is-dragging");
});

dropZone.addEventListener("drop", async (event) => {
  event.preventDefault();
  dropZone.classList.remove("is-dragging");
  const dropped = await collectDroppedFiles(event.dataTransfer);
  addFiles(dropped);
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (selectedFiles.length === 0) {
    setLog("Choose or drop at least one supported file first.");
    return;
  }

  runButton.disabled = true;
  appStatus.textContent = "Running";
  outputPath.textContent = "";
  setLog("Uploading files...");

  const data = new FormData();
  for (const item of selectedFiles) {
    data.append("files", item.file, item.file.name);
    data.append("relative_paths", item.path);
  }
  data.append("profile", profile.value);
  data.append("dpi", dpi.value);
  data.append("max_side", maxSide.value);
  data.append("num_ctx", numCtx.value);
  data.append("keep_alive", keepAlive.value);
  data.append("request_timeout", requestTimeout.value);
  data.append("page_retries", pageRetries.value);
  data.append("image_format", imageFormat.value);
  data.append("jpeg_quality", jpegQuality.value);
  data.append("output_dir", outputDir.value);

  try {
    const response = await fetch("/api/jobs", { method: "POST", body: data });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Could not start OCR job.");
    }
    outputPath.textContent = payload.output_dir;
    setLog(`Started job ${payload.job_id}\nOutput: ${payload.output_dir}\n`);
    listenToJob(payload.job_id, payload.auto_download, payload.download_url);
  } catch (error) {
    appStatus.textContent = "Error";
    appendLog(error.message);
    runButton.disabled = false;
  }
});

function applyProfile(name) {
  const next = profiles[name];
  if (!next) return;
  dpi.value = next.dpi;
  maxSide.value = next.max_side;
  numCtx.value = next.num_ctx;
  keepAlive.value = next.keep_alive;
  requestTimeout.value = next.request_timeout;
  pageRetries.value = next.page_retries;
  imageFormat.value = next.image_format;
  jpegQuality.value = next.jpeg_quality;
}

function addFiles(items) {
  const supported = items.filter((item) => isSupported(item.path || item.file.name));
  for (const item of supported) {
    const key = `${item.path}:${item.file.size}`;
    if (!selectedFiles.some((existing) => `${existing.path}:${existing.file.size}` === key)) {
      selectedFiles.push(item);
    }
  }
  renderFileList();
}

function clearSelection() {
  selectedFiles.length = 0;
  renderFileList();
}

function renderFileList() {
  fileList.innerHTML = "";
  if (selectedFiles.length === 0) {
    fileList.innerHTML = "<li>No files selected.</li>";
    return;
  }

  for (const item of selectedFiles) {
    const li = document.createElement("li");
    const name = document.createElement("span");
    const size = document.createElement("span");
    name.textContent = item.path;
    size.textContent = formatBytes(item.file.size);
    li.append(name, size);
    fileList.append(li);
  }
}

function isSupported(path) {
  return /\.(pdf|png|jpe?g|webp|tiff?|bmp)$/i.test(path);
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}

async function collectDroppedFiles(dataTransfer) {
  const items = Array.from(dataTransfer.items || []);
  if (items.length === 0) {
    return Array.from(dataTransfer.files || []).map((file) => ({ file, path: file.name }));
  }

  const collected = [];
  for (const item of items) {
    const entry = item.webkitGetAsEntry ? item.webkitGetAsEntry() : null;
    if (entry) {
      collected.push(...(await readEntry(entry, "")));
    } else {
      const file = item.getAsFile();
      if (file) collected.push({ file, path: file.name });
    }
  }
  return collected;
}

function readEntry(entry, prefix) {
  return new Promise((resolve) => {
    if (entry.isFile) {
      entry.file((file) => resolve([{ file, path: `${prefix}${file.name}` }]));
      return;
    }

    if (entry.isDirectory) {
      const reader = entry.createReader();
      const all = [];
      const readBatch = () => {
        reader.readEntries(async (entries) => {
          if (entries.length === 0) {
            resolve(all);
            return;
          }
          for (const child of entries) {
            all.push(...(await readEntry(child, `${prefix}${entry.name}/`)));
          }
          readBatch();
        });
      };
      readBatch();
      return;
    }

    resolve([]);
  });
}

function listenToJob(jobId, autoDownload, downloadUrl) {
  const source = new EventSource(`/api/jobs/${jobId}/events`);
  let downloaded = false;
  source.onmessage = (event) => {
    const payload = JSON.parse(event.data);
    if (payload.line) {
      appendLog(payload.line);
    }
    if (payload.status) {
      appStatus.textContent = payload.status;
    }
    if (payload.status === "completed" || payload.status === "failed") {
      if (payload.status === "completed" && autoDownload && !downloaded) {
        downloaded = true;
        appendLog("Starting browser download...");
        startDownload(downloadUrl || payload.download_url);
      }
      source.close();
      runButton.disabled = false;
    }
  };

  source.onerror = () => {
    appendLog("Lost connection to progress stream.");
    source.close();
    runButton.disabled = false;
  };
}

function startDownload(url) {
  if (!url) return;
  const link = document.createElement("a");
  link.href = url;
  link.download = "";
  link.style.display = "none";
  document.body.append(link);
  link.click();
  link.remove();
}

async function cleanupRuns() {
  clearRuns.disabled = true;
  try {
    const response = await fetch("/api/cleanup", { method: "POST" });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Cleanup failed.");
    }
    appendLog(`Cleared ${payload.removed.length} inactive web run(s).`);
  } catch (error) {
    appendLog(error.message);
  } finally {
    clearRuns.disabled = false;
  }
}

function setLog(text) {
  logs.textContent = text;
}

function appendLog(text) {
  logs.textContent += `${text}\n`;
  logs.scrollTop = logs.scrollHeight;
}

applyProfile("safe");
