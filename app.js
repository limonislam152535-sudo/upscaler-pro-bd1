const $ = (s) => document.querySelector(s);
const EXT = /\.(jpe?g|png|webp)$/i;
const S = { files: [], map: new Map(), batch: null, running: false, next: 0, timer: null };
const bytes = (b) => b >= 1e9 ? (b / 1e9).toFixed(2) + " GB" : b >= 1e6 ? (b / 1e6).toFixed(1) + " MB" : Math.max(1, Math.round(b / 1e3)) + " KB";
const dur = (s) => s == null ? "–" : s >= 3600 ? `${Math.floor(s / 3600)}h ${Math.floor(s % 3600 / 60)}m` : s >= 60 ? `${Math.floor(s / 60)}m ${Math.round(s % 60)}s` : `${Math.round(s)}s`;
const LABEL = { queued: "Ready", uploading: "Uploading", pending: "Queued", processing: "Upscaling", completed: "Done", failed: "Failed" };

function addFiles(list) {
  if (S.batch) return note("Clear all before adding images to a new batch.");
  const max = +$("#maxmb").value * 1048576, skipped = [];
  for (const file of list) {
    if (!EXT.test(file.name)) { skipped.push(`${file.name}: unsupported format`); continue; }
    if (file.size > max) { skipped.push(`${file.name}: larger than ${$("#maxmb").value} MB`); continue; }
    const f = { id: S.next++, file, status: "queued", progress: 0, error: "", uploaded: false, sid: null };
    S.files.push(f); S.map.set(f.id, f); $("#grid").append(card(f));
  }
  note(skipped.length ? `Skipped ${skipped.length}: ` + skipped.slice(0, 4).join("; ") + (skipped.length > 4 ? "…" : "") : "");
  render();
}

function note(t) { const e = $("#skipped"); e.textContent = t; e.hidden = !t; }

function card(f) {
  const el = document.createElement("article"); el.className = "card"; f.el = el;
  el.innerHTML = '<button class="x" title="Remove" aria-label="Remove">×</button><img alt="" loading="lazy" decoding="async"><b></b><small></small><div class="bar"><i></i></div><div class="foot"><span class="badge"></span><a class="dl" hidden>Download</a></div>';
  f.url = URL.createObjectURL(f.file);
  el.querySelector("img").src = f.url;
  el.querySelector("b").textContent = f.file.name; el.querySelector("b").title = f.file.name;
  el.querySelector("small").textContent = bytes(f.file.size);
  el.querySelector(".x").onclick = () => {
    if (S.batch) return;
    URL.revokeObjectURL(f.url); S.files.splice(S.files.indexOf(f), 1); S.map.delete(f.id); el.remove(); render();
  };
  updateCard(f); return el;
}

function updateCard(f) {
  const el = f.el, b = el.querySelector(".badge"), s = el.querySelector("small"), a = el.querySelector(".dl");
  b.className = "badge " + f.status;
  b.textContent = LABEL[f.status] + (f.status === "processing" ? ` ${Math.round(f.progress)}%` : "");
  el.querySelector(".bar i").style.width = (f.status === "completed" ? 100 : f.progress) + "%";
  s.className = f.error ? "err" : ""; s.textContent = f.error || bytes(f.file.size);
  a.hidden = f.status !== "completed";
  if (!a.hidden) a.href = `/api/batches/${S.batch}/images/${f.sid}/download`;
  el.querySelector(".x").hidden = !!S.batch;
}

function render(s) {
  const n = (st) => S.files.filter((f) => f.status === st).length;
  const total = S.files.length, proc = n("processing"), done = n("completed"), fail = n("failed");
  const up = S.files.filter((f) => f.uploaded).length;
  const sum = S.files.reduce((a, f) => a + (f.status === "completed" || f.status === "failed" ? 100 : f.status === "processing" ? f.progress : 0), 0);
  const pct = total ? Math.round(sum / total) : 0;
  Object.entries({ total, up, proc, done, fail, pend: total - proc - done - fail }).forEach(([k, v]) => $("#s-" + k).textContent = v);
  $("#overall").style.width = pct + "%"; $("#pct").textContent = pct + "%";
  $("#totals").textContent = `${total} images · ${bytes(S.files.reduce((a, f) => a + f.file.size, 0))}`;
  $("#empty").hidden = total > 0;
  if (s) {
    $("#current").textContent = s.current.length ? "Processing: " + s.current[0] + (s.current.length > 1 ? ` (+${s.current.length - 1})` : "") : (S.running ? "Waiting for next image" : "Idle");
    $("#speed").textContent = s.speed_ipm ? `${s.speed_ipm} images/min` : "–";
    $("#eta").textContent = "Time left: " + dur(s.eta_sec);
  }
  $("#start").disabled = S.running || !total || !!S.batch;
  $("#zip").disabled = $("#csv").disabled = !S.batch || !done;
  $("#clear").disabled = S.running || !total;
}

async function start() {
  S.running = true; render();
  const fd = new FormData();
  for (const [k, v] of Object.entries({ scale: $("#scale").value, model: $("#model").value, format: $("#format").value, quality: $("#quality").value, dpi: $("#dpi").value, max_mb: $("#maxmb").value })) fd.append(k, v);
  try {
    const r = await fetch("/api/batches", { method: "POST", body: fd });
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    S.batch = (await r.json()).id;
  } catch (e) { S.running = false; note("Could not start: " + e.message); return render(); }
  S.files.forEach(updateCard);
  poll(); uploadAll();
}

async function uploadAll() {
  const queue = [...S.files];
  const worker = async () => {
    for (let f; (f = queue.shift());) {
      f.status = "uploading"; updateCard(f);
      try {
        const fd = new FormData(); fd.append("file", f.file); fd.append("client_id", f.id);
        const r = await fetch(`/api/batches/${S.batch}/images`, { method: "POST", body: fd });
        if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
        const it = await r.json(); f.sid = it.id; f.status = it.status; f.error = it.error;
      } catch (e) { f.status = "failed"; f.error = "Upload failed: " + e.message; }
      f.uploaded = true; updateCard(f);
    }
  };
  await Promise.all([worker(), worker(), worker()]);
}

async function poll() {
  if (!S.batch) return;
  let s = null;
  try {
    const r = await fetch(`/api/batches/${S.batch}`);
    if (r.ok) {
      s = await r.json();
      for (const it of s.items) {
        const f = S.map.get(it.client_id);
        if (!f || !f.uploaded && f.status !== "uploading") continue;
        if (f.status !== it.status || f.progress !== it.progress) {
          f.sid = it.id; f.status = it.status; f.progress = it.progress; f.error = it.error; updateCard(f);
        }
      }
    } else if (r.status === 404) { S.running = false; note("This batch expired on the server."); }
  } catch (e) { /* transient network error: retry */ }
  if (S.running && S.files.every((f) => f.status === "completed" || f.status === "failed")) S.running = false;
  render(s);
  if (S.running) S.timer = setTimeout(poll, 1000);
}

async function clearAll() {
  clearTimeout(S.timer);
  if (S.batch) fetch(`/api/batches/${S.batch}`, { method: "DELETE" }).catch(() => {});
  S.files.forEach((f) => URL.revokeObjectURL(f.url));
  Object.assign(S, { files: [], map: new Map(), batch: null, running: false });
  $("#grid").replaceChildren(); note(""); render({ current: [], speed_ipm: null, eta_sec: null });
}

const drop = $("#drop");
drop.onclick = () => $("#picker").click();
drop.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("#picker").click(); } };
$("#picker").onchange = (e) => { addFiles([...e.target.files]); e.target.value = ""; };
["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => addFiles([...e.dataTransfer.files]));
$("#start").onclick = start;
$("#clear").onclick = clearAll;
$("#zip").onclick = () => { location.href = `/api/batches/${S.batch}/zip`; };
$("#csv").onclick = () => { location.href = `/api/batches/${S.batch}/csv`; };
$("#quality").oninput = (e) => $("#qv").textContent = e.target.value;
$("#format").onchange = (e) => $("#quality").disabled = e.target.value === "png";
fetch("/api/config").then((r) => r.json()).then((c) => { $("#maxmb").max = c.max_file_mb; $("#maxmb").value = c.max_file_mb; }).catch(() => {});
render();
