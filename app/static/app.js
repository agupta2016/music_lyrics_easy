const $ = (id) => document.getElementById(id);

const STATUS_TEXT = {
  queued: "Waiting in line…",
  downloading: "Fetching the audio…",
  transcribing: "Listening and writing down the lyrics… (this can take a few minutes)",
  translating: "Translating…",
};

const SUBMIT_TEXT = { link: "Get lyrics", file: "Get lyrics", video: "Download video" };

let mode = "link";
let currentJob = null;
let pollTimer = null;

async function loadLanguages() {
  const res = await fetch("/api/languages");
  const languages = await res.json();
  const select = $("language");
  const sung = $("sung-language");
  for (const [code, name] of Object.entries(languages)) {
    const opt = document.createElement("option");
    opt.value = code;
    opt.textContent = name;
    select.appendChild(opt);
    if (code !== "original") sung.appendChild(opt.cloneNode(true));
  }
  try {
    const saved = localStorage.getItem("mle-language");
    if (saved && languages[saved]) select.value = saved;
    const savedSung = localStorage.getItem("mle-sung-language");
    if (savedSung && (savedSung === "auto" || languages[savedSung])) sung.value = savedSung;
  } catch (_) { /* storage unavailable */ }
}

function setMode(next) {
  mode = next;
  document.querySelectorAll(".tab").forEach((tab) => {
    const active = tab.dataset.mode === next;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  $("link-field").hidden = next === "file";
  $("file-field").hidden = next !== "file";
  $("quality-field").hidden = next !== "video";
  document.querySelectorAll(".lyrics-field").forEach((el) => (el.hidden = next === "video"));
  $("submit").textContent = SUBMIT_TEXT[next];
}

function showError(message) {
  $("error").textContent = message;
  $("error").hidden = false;
  $("status").hidden = true;
  $("submit").disabled = false;
}

function showStatus(status, text) {
  $("status-text").textContent = text || STATUS_TEXT[status] || status;
  $("status").hidden = false;
}

function formatTime(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

function hasTranslation(job) {
  return job.lines.some((l) => l.translation);
}

function describeDiagnostics(d) {
  if (!d || !d.model) return "";
  const parts = [`Model ${d.model} on ${d.device}`];
  if (d.vocals_isolated !== undefined) {
    parts.push(d.vocals_isolated ? "vocals separated" : "vocals NOT separated (music mixed in)");
  } else {
    parts.push("vocals NOT separated (Demucs not running)");
  }
  if (d.audio_seconds) {
    parts.push(`heard ${formatTime(d.heard_seconds)} of ${formatTime(d.audio_seconds)}`);
    parts.push(`last line at ${formatTime(d.last_line_ends)}`);
  }
  if (d.dropped_lines) parts.push(`${d.dropped_lines} garbled line(s) removed`);
  if (d.hint) parts.push(`title hint: "${d.hint}"`);
  return parts.join(" · ");
}

function renderResult(job) {
  currentJob = job;
  $("result-title").textContent = job.title || "Lyrics";
  const detected = job.detected_language ? `Detected language: ${job.detected_language}` : "";
  $("result-meta").textContent = [detected, describeDiagnostics(job.diagnostics)]
    .filter(Boolean)
    .join(" · ");
  $("show-original").parentElement.hidden = !hasTranslation(job);

  const list = $("lines");
  list.innerHTML = "";
  if (job.lines.length === 0) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "No words were detected in this audio.";
    list.appendChild(li);
  }
  const showOriginal = $("show-original").checked;
  const showTimes = $("show-times").checked;
  for (const line of job.lines) {
    const li = document.createElement("li");
    if (showTimes) {
      const t = document.createElement("span");
      t.className = "time";
      t.textContent = formatTime(line.start);
      li.appendChild(t);
    }
    const main = document.createElement("span");
    main.className = "text";
    main.textContent = line.translation || line.text;
    li.appendChild(main);
    if (showOriginal && line.translation) {
      const orig = document.createElement("span");
      orig.className = "original";
      orig.textContent = line.text;
      li.appendChild(orig);
    }
    list.appendChild(li);
  }
  $("result").hidden = false;
}

async function poll(jobId) {
  try {
    const res = await fetch(`/api/jobs/${jobId}`);
    const job = await res.json();
    if (!res.ok) return showError(job.detail || "Something went wrong.");
    if (job.status === "done") {
      $("status").hidden = true;
      $("submit").disabled = false;
      renderResult(job);
    } else if (job.status === "error") {
      showError(job.error || "Something went wrong.");
    } else {
      showStatus(job.status);
      pollTimer = setTimeout(() => poll(jobId), 1500);
    }
  } catch (err) {
    showError(`Lost contact with the server: ${err.message}`);
  }
}

function formatSize(bytes) {
  if (!bytes) return "";
  const mb = bytes / (1024 * 1024);
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb.toFixed(1)} MB`;
}

function renderVideo(item) {
  $("video-title").textContent = item.title || "Video";
  $("video-meta").textContent = [item.filename, formatSize(item.size_bytes)].filter(Boolean).join(" · ");
  $("video-save").href = `/api/videos/${item.id}/file`;
  $("video-result").hidden = false;
}

async function pollVideo(id) {
  try {
    const res = await fetch(`/api/videos/${id}`);
    const item = await res.json();
    if (!res.ok) return showError(item.detail || "Something went wrong.");
    if (item.status === "done") {
      $("status").hidden = true;
      $("submit").disabled = false;
      renderVideo(item);
    } else if (item.status === "error") {
      showError(item.error || "Something went wrong.");
    } else {
      const pct = item.progress == null ? "" : ` ${Math.floor(item.progress)}%`;
      showStatus(item.status, item.status === "queued" ? null : `Downloading the video…${pct}`);
      pollTimer = setTimeout(() => pollVideo(id), 1000);
    }
  } catch (err) {
    showError(`Lost contact with the server: ${err.message}`);
  }
}

async function submitVideo() {
  const url = $("url").value.trim();
  if (!url) return showError("Paste a link first.");
  const res = await fetch("/api/videos", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, quality: $("quality").value }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) return showError(body.detail || `Request failed (${res.status}).`);
  $("submit").disabled = true;
  showStatus(body.status);
  pollVideo(body.id);
}

async function submit(event) {
  event.preventDefault();
  clearTimeout(pollTimer);
  $("error").hidden = true;
  $("result").hidden = true;
  $("video-result").hidden = true;
  if (mode === "video") return submitVideo();

  const language = $("language").value;
  const sungLanguage = $("sung-language").value;
  try {
    localStorage.setItem("mle-language", language);
    localStorage.setItem("mle-sung-language", sungLanguage);
  } catch (_) { /* ignore */ }

  let res;
  if (mode === "link") {
    const url = $("url").value.trim();
    if (!url) return showError("Paste a link first.");
    res = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, target_language: language, source_language: sungLanguage }),
    });
  } else {
    const file = $("file").files[0];
    if (!file) return showError("Choose a file first.");
    const form = new FormData();
    form.append("file", file);
    form.append("target_language", language);
    form.append("source_language", sungLanguage);
    res = await fetch("/api/jobs/upload", { method: "POST", body: form });
  }

  const body = await res.json().catch(() => ({}));
  if (!res.ok) return showError(body.detail || `Request failed (${res.status}).`);
  $("submit").disabled = true;
  showStatus(body.status);
  poll(body.id);
}

function copyLyrics() {
  if (!currentJob) return;
  const text = currentJob.lines.map((l) => l.translation || l.text).join("\n");
  navigator.clipboard.writeText(text).then(() => {
    $("copy").textContent = "Copied";
    setTimeout(() => ($("copy").textContent = "Copy"), 1500);
  });
}

document.querySelectorAll(".tab").forEach((tab) =>
  tab.addEventListener("click", () => setMode(tab.dataset.mode))
);
$("job-form").addEventListener("submit", submit);
$("copy").addEventListener("click", copyLyrics);
$("show-original").addEventListener("change", () => currentJob && renderResult(currentJob));
$("show-times").addEventListener("change", () => currentJob && renderResult(currentJob));
loadLanguages();
