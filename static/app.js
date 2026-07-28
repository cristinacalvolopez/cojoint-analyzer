(() => {
  "use strict";

  const state = {
    sessionId: null,
    filename: null,
    nRows: 0,
    columns: [],           // [{name,label}]
    unmatchedColumns: [],
    draft: null,           // config de mapeo en edición (forma de ConjointMappingConfig + auxiliares)
    reshapeSummary: null,
    reshapePreview: null,
    amceResult: null,
    amceMethod: "ols",
  };

  const el = (id) => document.getElementById(id);
  const fmt = (n, d = 3) => (n === null || n === undefined || Number.isNaN(n) ? "—" : Number(n).toLocaleString("es-ES", { maximumFractionDigits: d, minimumFractionDigits: 0 }));
  const fmtP = (p) => (p === null || p === undefined ? "—" : p < 0.001 ? "< 0.001" : fmt(p, 3));
  const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  async function postJson(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Ha ocurrido un error.");
    return data;
  }
  async function getJson(url) {
    const res = await fetch(url);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Ha ocurrido un error.");
    return data;
  }

  // ---------- Theme ----------
  function initTheme() {
    const saved = localStorage.getItem("cojoint-theme");
    if (saved) document.documentElement.setAttribute("data-theme", saved);
    updateThemeIcon();
  }
  function updateThemeIcon() {
    const current = document.documentElement.getAttribute("data-theme");
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const isDark = current ? current === "dark" : prefersDark;
    el("themeIcon").innerHTML = isDark ? "&#9788;" : "&#9789;";
  }
  el("themeToggle").addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme");
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const isDark = current ? current === "dark" : prefersDark;
    const next = isDark ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("cojoint-theme", next);
    updateThemeIcon();
  });
  initTheme();

  // ---------- Modal ----------
  const modalOverlay = el("modalOverlay");
  const modalBody = el("modalBody");
  function openModal(html) {
    modalBody.innerHTML = html;
    modalOverlay.hidden = false;
    modalBody.querySelectorAll(".modal-close").forEach((b) => b.addEventListener("click", closeModal));
  }
  function closeModal() {
    modalOverlay.hidden = true;
    modalBody.innerHTML = "";
  }
  modalOverlay.addEventListener("click", (e) => { if (e.target === modalOverlay) closeModal(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modalOverlay.hidden) closeModal(); });

  // ---------- Upload ----------
  const dropzone = el("dropzone");
  const fileInput = el("fileInput");
  const uploadStatus = el("uploadStatus");

  ["dragenter", "dragover"].forEach((evtName) =>
    dropzone.addEventListener(evtName, (e) => { e.preventDefault(); dropzone.classList.add("is-dragover"); })
  );
  ["dragleave", "drop"].forEach((evtName) =>
    dropzone.addEventListener(evtName, (e) => { e.preventDefault(); dropzone.classList.remove("is-dragover"); })
  );
  dropzone.addEventListener("drop", (e) => {
    const file = e.dataTransfer.files[0];
    if (file) handleUpload(file);
  });
  fileInput.addEventListener("change", () => {
    if (fileInput.files[0]) handleUpload(fileInput.files[0]);
  });

  function setUploadStatus(message, type) {
    uploadStatus.hidden = !message;
    uploadStatus.textContent = message || "";
    uploadStatus.className = "upload-status" + (type ? ` is-${type}` : "");
  }

  async function handleUpload(file) {
    const validExt = /\.(xlsx|xls|csv|dta|sav)$/i.test(file.name);
    if (!validExt) {
      setUploadStatus("Formato no soportado. Usa .xlsx, .xls, .csv, .dta o .sav.", "error");
      return;
    }
    setUploadStatus("Procesando archivo…", "loading");
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await fetch("/api/upload", { method: "POST", body: formData });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Error al procesar el archivo.");
      setUploadStatus("", null);
      onDatasetLoaded(data);
    } catch (err) {
      setUploadStatus(err.message, "error");
    }
  }

  function onDatasetLoaded(data) {
    state.sessionId = data.session_id;
    state.filename = data.filename;
    state.nRows = data.n_rows;
    state.columns = data.columns;
    state.reshapeSummary = null;
    state.reshapePreview = null;
    state.amceResult = null;

    const suggestion = data.suggested_mapping;
    state.unmatchedColumns = suggestion.unmatched_columns || [];
    state.draft = {
      respondent_id: suggestion.respondent_id,
      tasks: suggestion.tasks.length ? suggestion.tasks : ["cj1"],
      profiles: suggestion.profiles.length ? suggestion.profiles : ["A", "B"],
      attributes: suggestion.attributes.length
        ? suggestion.attributes
        : [{ name: "atributo1", label: "atributo1", columns: {} }],
      choice_columns: suggestion.choice_columns || {},
      choice_value_map: suggestion.choice_value_map || {},
    };

    el("fileMeta").textContent = `${data.filename} · ${data.n_rows.toLocaleString("es-ES")} filas · ${data.n_cols} variables`;
    el("resetBtn").hidden = false;
    el("uploadScreen").hidden = true;
    el("appScreen").hidden = false;

    goToStep("mapping");
    renderMappingStep();
  }

  el("resetBtn").addEventListener("click", async () => {
    if (state.sessionId) {
      try { await fetch(`/api/session/${state.sessionId}`, { method: "DELETE" }); } catch (_e) { /* noop */ }
    }
    location.reload();
  });

  // ---------- Navegación por pasos ----------
  const STEPS = ["mapping", "reshape", "amce"];
  let currentStep = "mapping";

  function goToStep(step) {
    currentStep = step;
    document.querySelectorAll(".stepper__step").forEach((s) => s.classList.toggle("is-active", s.dataset.step === step));
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("is-active", t.dataset.tab === step));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("is-active"));
    el(`tab${step[0].toUpperCase()}${step.slice(1)}`).classList.add("is-active");
  }

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => goToStep(tab.dataset.tab));
  });
  document.querySelectorAll(".stepper__step").forEach((s) => {
    s.addEventListener("click", () => goToStep(s.dataset.step));
  });

  function markStepDone(step) {
    const stepEl = document.querySelector(`.stepper__step[data-step="${step}"]`);
    if (stepEl) stepEl.classList.add("is-done");
  }

  // =====================================================================
  // Paso 1 · Mapeo de variables
  // =====================================================================

  function columnOptionsHtml(selected) {
    const opts = ['<option value="">—</option>'];
    for (const c of state.columns) {
      const sel = c.name === selected ? "selected" : "";
      const label = c.label && c.label !== c.name ? `${c.label} (${c.name})` : c.name;
      opts.push(`<option value="${escapeHtml(c.name)}" ${sel}>${escapeHtml(label)}</option>`);
    }
    return opts.join("");
  }

  function renderMappingStep() {
    const d = state.draft;

    el("respondentIdSelect").innerHTML = '<option value="">(usar número de fila)</option>' + columnOptionsHtml(d.respondent_id).replace('<option value="">—</option>', "");
    el("respondentIdSelect").value = d.respondent_id || "";
    el("tasksInput").value = d.tasks.join(", ");
    el("profilesInput").value = d.profiles.join(", ");

    renderAttributeGrid();
    renderChoiceGrid();
    renderUnmatchedColumns();
  }

  el("respondentIdSelect").addEventListener("change", (e) => {
    state.draft.respondent_id = e.target.value || null;
  });

  el("rebuildGridBtn").addEventListener("click", () => {
    const tasks = el("tasksInput").value.split(",").map((s) => s.trim()).filter(Boolean);
    const profiles = el("profilesInput").value.split(",").map((s) => s.trim()).filter(Boolean);
    if (tasks.length === 0 || profiles.length < 2) {
      alert("Indica al menos una tarea y dos perfiles.");
      return;
    }
    state.draft.tasks = tasks;
    state.draft.profiles = profiles;
    // Conserva mapeos de elección existentes para tareas que se mantienen.
    const newChoice = {};
    for (const t of tasks) if (state.draft.choice_columns[t]) newChoice[t] = state.draft.choice_columns[t];
    state.draft.choice_columns = newChoice;
    const newChoiceMap = {};
    for (const p of profiles) {
      const existingRaw = Object.entries(state.draft.choice_value_map).find(([, v]) => v === p);
      newChoiceMap[existingRaw ? existingRaw[0] : p] = p;
    }
    state.draft.choice_value_map = newChoiceMap;
    renderAttributeGrid();
    renderChoiceGrid();
  });

  el("addAttributeBtn").addEventListener("click", () => {
    openModal(`
      <div class="modal-header"><h3>Añadir atributo</h3><button class="modal-close" aria-label="Cerrar">&times;</button></div>
      <div class="modal-body">
        <label class="field"><span>Nombre técnico (sin espacios)</span><input id="newAttrName" type="text" placeholder="rol"></label>
        <label class="field" style="margin-top:10px"><span>Etiqueta descriptiva</span><input id="newAttrLabel" type="text" placeholder="Rol profesional"></label>
        <div id="newAttrError" class="modal-error" hidden></div>
      </div>
      <div class="modal-footer">
        <button class="btn btn--ghost modal-close">Cancelar</button>
        <button id="newAttrSave" class="btn btn--primary">Añadir</button>
      </div>
    `);
    el("newAttrSave").addEventListener("click", () => {
      const name = el("newAttrName").value.trim();
      const label = el("newAttrLabel").value.trim() || name;
      if (!name) {
        el("newAttrError").hidden = false;
        el("newAttrError").textContent = "Indica un nombre.";
        return;
      }
      if (state.draft.attributes.some((a) => a.name === name)) {
        el("newAttrError").hidden = false;
        el("newAttrError").textContent = "Ya existe un atributo con ese nombre.";
        return;
      }
      state.draft.attributes.push({ name, label, columns: {} });
      closeModal();
      renderAttributeGrid();
    });
  });

  function renderAttributeGrid() {
    const d = state.draft;
    const wrap = el("mappingGridWrap");
    let html = '<table class="mapping-grid"><thead><tr><th>Tarea</th>';
    for (const attr of d.attributes) {
      html += `<th colspan="${d.profiles.length}">${escapeHtml(attr.label || attr.name)} <button class="btn btn--icon btn--sm remove-attr-btn" data-attr="${escapeHtml(attr.name)}" title="Quitar atributo">&times;</button></th>`;
    }
    html += "</tr><tr><th></th>";
    for (const attr of d.attributes) {
      for (const p of d.profiles) html += `<th>${escapeHtml(p)}</th>`;
    }
    html += "</tr></thead><tbody>";
    for (const task of d.tasks) {
      html += `<tr><th>${escapeHtml(task)}</th>`;
      for (const attr of d.attributes) {
        for (const p of d.profiles) {
          const current = (attr.columns[task] || {})[p] || "";
          const cls = current ? "is-matched" : "is-unmatched";
          html += `<td><select class="${cls}" data-kind="attr" data-attr="${escapeHtml(attr.name)}" data-task="${escapeHtml(task)}" data-profile="${escapeHtml(p)}">${columnOptionsHtml(current)}</select></td>`;
        }
      }
      html += "</tr>";
    }
    html += "</tbody></table>";
    wrap.innerHTML = html;

    wrap.querySelectorAll('select[data-kind="attr"]').forEach((sel) => {
      sel.addEventListener("change", (e) => {
        const { attr, task, profile } = e.target.dataset;
        const attrObj = state.draft.attributes.find((a) => a.name === attr);
        if (!attrObj.columns[task]) attrObj.columns[task] = {};
        attrObj.columns[task][profile] = e.target.value || undefined;
        if (!e.target.value) delete attrObj.columns[task][profile];
        e.target.className = e.target.value ? "is-matched" : "is-unmatched";
      });
    });
    wrap.querySelectorAll(".remove-attr-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.draft.attributes = state.draft.attributes.filter((a) => a.name !== btn.dataset.attr);
        renderAttributeGrid();
      });
    });
  }

  function renderChoiceGrid() {
    const d = state.draft;
    const wrap = el("choiceGridWrap");
    let html = '<table class="mapping-grid"><thead><tr><th>Tarea</th><th>Columna de elección</th></tr></thead><tbody>';
    for (const task of d.tasks) {
      const current = d.choice_columns[task] || "";
      const cls = current ? "is-matched" : "is-unmatched";
      html += `<tr><th>${escapeHtml(task)}</th><td><select class="${cls}" data-task="${escapeHtml(task)}">${columnOptionsHtml(current)}</select></td></tr>`;
    }
    html += "</tbody></table>";
    html += '<div style="padding:14px"><p class="text-secondary" style="font-size:12.5px;margin-bottom:10px">¿Con qué valor se codifica cada perfil en la columna de elección?</p>';
    for (const p of d.profiles) {
      const raw = Object.entries(d.choice_value_map).find(([, v]) => v === p);
      html += `<label class="field" style="display:inline-flex;margin-right:16px"><span>Perfil ${escapeHtml(p)} = valor</span><input type="text" data-profile-value="${escapeHtml(p)}" value="${escapeHtml(raw ? raw[0] : "")}" style="width:90px"></label>`;
    }
    html += "</div>";
    wrap.innerHTML = html;

    wrap.querySelectorAll("select[data-task]").forEach((sel) => {
      sel.addEventListener("change", (e) => {
        state.draft.choice_columns[e.target.dataset.task] = e.target.value || undefined;
        if (!e.target.value) delete state.draft.choice_columns[e.target.dataset.task];
        e.target.className = e.target.value ? "is-matched" : "is-unmatched";
      });
    });
    wrap.querySelectorAll("input[data-profile-value]").forEach((input) => {
      input.addEventListener("change", (e) => {
        const profile = e.target.dataset.profileValue;
        for (const k of Object.keys(state.draft.choice_value_map)) {
          if (state.draft.choice_value_map[k] === profile) delete state.draft.choice_value_map[k];
        }
        if (e.target.value.trim()) state.draft.choice_value_map[e.target.value.trim()] = profile;
      });
    });
  }

  function renderUnmatchedColumns() {
    const card = el("unmatchedCard");
    const wrap = el("unmatchedColumns");
    if (!state.unmatchedColumns.length) { card.hidden = true; return; }
    card.hidden = false;
    wrap.innerHTML = state.unmatchedColumns.map((c) => `<span class="chip">${escapeHtml(c)}</span>`).join("");
  }

  el("applyMappingBtn").addEventListener("click", applyMapping);

  async function applyMapping() {
    const d = state.draft;
    const payload = {
      respondent_id: d.respondent_id || null,
      tasks: d.tasks,
      profiles: d.profiles,
      attributes: d.attributes.map((a) => ({ name: a.name, label: a.label || a.name, columns: a.columns })),
      choice_columns: d.choice_columns,
      choice_value_map: d.choice_value_map,
    };
    const issuesEl = el("mappingIssues");
    issuesEl.innerHTML = "";
    try {
      const result = await postJson(`/api/mapping/${state.sessionId}/apply`, payload);
      issuesEl.innerHTML = result.issues.map((i) => `<div class="issue-list__item">${escapeHtml(i)}</div>`).join("");
      state.reshapeSummary = result.summary;
      markStepDone("mapping");
      updateSidebarSummary();
      await loadReshapePreview();
      renderReshapeStep();
      resetAmceStep();
      goToStep("reshape");
    } catch (err) {
      issuesEl.innerHTML = `<div class="issue-list__item">${escapeHtml(err.message)}</div>`;
    }
  }

  function updateSidebarSummary() {
    const s = state.reshapeSummary;
    el("sumRows").textContent = state.nRows.toLocaleString("es-ES");
    el("sumTasks").textContent = s ? s.n_tasks : "–";
    el("sumProfiles").textContent = s ? s.n_profiles : "–";
    el("sumAttrs").textContent = state.draft ? state.draft.attributes.length : "–";
  }

  // =====================================================================
  // Paso 2 · Reestructuración
  // =====================================================================

  async function loadReshapePreview() {
    state.reshapePreview = await getJson(`/api/reshape/${state.sessionId}/preview?limit=50`);
  }

  function renderReshapeStep() {
    const s = state.reshapeSummary;
    el("reshapeEmpty").hidden = true;
    el("reshapeContent").hidden = false;

    el("reshapeStats").innerHTML = [
      ["Entrevistados", s.n_respondents],
      ["Tareas", s.n_tasks],
      ["Perfiles por tarea", s.n_profiles],
      ["Conjuntos de elección", s.n_choice_sets],
      ["Filas (formato largo)", s.n_rows],
    ].map(([label, value]) => `
      <div class="stat-tile"><span class="stat-tile__label">${escapeHtml(label)}</span><span class="stat-tile__value">${fmt(value, 0)}</span></div>
    `).join("");

    const warnings = [];
    if (s.choice_sets_without_selection > 0) warnings.push(`${s.choice_sets_without_selection} conjunto(s) de elección sin perfil elegido (revisa la columna de elección o el mapeo de valores).`);
    if (s.choice_sets_with_multiple_selections > 0) warnings.push(`${s.choice_sets_with_multiple_selections} conjunto(s) de elección con más de un perfil marcado como elegido.`);
    if (s.missing_choice_rows > 0) warnings.push(`${s.missing_choice_rows} filas sin valor de elección.`);
    for (const [attr, cov] of Object.entries(s.attribute_coverage)) {
      if (cov.n_missing > 0) warnings.push(`El atributo "${attr}" tiene ${cov.n_missing} valores perdidos.`);
    }
    el("reshapeWarnings").hidden = warnings.length === 0;
    el("reshapeWarningsList").innerHTML = warnings.map((w) => `<div class="issue-list__item">${escapeHtml(w)}</div>`).join("");

    const preview = state.reshapePreview;
    const cols = preview.rows.length ? Object.keys(preview.rows[0]) : [];
    const thead = el("reshapePreviewTable").querySelector("thead");
    const tbody = el("reshapePreviewTable").querySelector("tbody");
    thead.innerHTML = `<tr>${cols.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr>`;
    tbody.innerHTML = preview.rows.map((row) => `<tr>${cols.map((c) => `<td>${row[c] === null || row[c] === undefined ? "" : escapeHtml(row[c])}</td>`).join("")}</tr>`).join("");
  }

  // =====================================================================
  // Paso 3 · Estimación del AMCE
  // =====================================================================

  function resetAmceStep() {
    state.amceResult = null;
    el("amceEmpty").hidden = false;
    el("amceContent").hidden = true;
    renderAmceControls();
  }

  function renderAmceControls() {
    const attrs = state.draft.attributes;
    if (!attrs.length) return;
    el("amceEmpty").hidden = true;
    el("amceContent").hidden = false;

    el("amceAttributes").innerHTML = attrs.map((a) => `
      <label class="checklist-item">
        <input type="checkbox" class="amce-attr-check" value="${escapeHtml(a.name)}" checked>
        <span>${escapeHtml(a.label || a.name)}</span>
      </label>
    `).join("");

    renderBaselineSelectors();
    el("amceAttributes").querySelectorAll(".amce-attr-check").forEach((cb) => {
      cb.addEventListener("change", renderBaselineSelectors);
    });
  }

  function renderBaselineSelectors() {
    const checked = Array.from(el("amceAttributes").querySelectorAll(".amce-attr-check:checked")).map((c) => c.value);
    const coverage = (state.reshapeSummary && state.reshapeSummary.attribute_coverage) || {};
    el("amceBaselines").innerHTML = checked.map((attr) => {
      const levels = (coverage[attr] && coverage[attr].levels) || [];
      return `
        <label class="field" style="margin-top:8px">
          <span>Referencia: ${escapeHtml(attr)}</span>
          <select data-baseline-attr="${escapeHtml(attr)}">
            ${levels.map((l) => `<option value="${escapeHtml(l)}">${escapeHtml(l)}</option>`).join("")}
          </select>
        </label>`;
    }).join("");
  }

  document.querySelectorAll("#amceMethodToggle .segmented__btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#amceMethodToggle .segmented__btn").forEach((b) => b.classList.remove("is-active"));
      btn.classList.add("is-active");
      state.amceMethod = btn.dataset.method;
    });
  });

  el("runAmceBtn").addEventListener("click", runAmce);

  async function runAmce() {
    const attributes = Array.from(el("amceAttributes").querySelectorAll(".amce-attr-check:checked")).map((c) => c.value);
    if (!attributes.length) { alert("Elige al menos un atributo."); return; }
    const baselines = {};
    el("amceBaselines").querySelectorAll("select[data-baseline-attr]").forEach((sel) => {
      baselines[sel.dataset.baselineAttr] = sel.value;
    });

    el("runAmceBtn").disabled = true;
    el("runAmceBtn").textContent = "Estimando…";
    try {
      const result = await postJson(`/api/amce/${state.sessionId}`, { method: state.amceMethod, attributes, baselines });
      state.amceResult = result;
      renderAmceResult(result);
      markStepDone("amce");
    } catch (err) {
      el("amceResultEmpty").hidden = false;
      el("amceResultEmpty").textContent = err.message;
      el("amceResult").hidden = true;
    } finally {
      el("runAmceBtn").disabled = false;
      el("runAmceBtn").textContent = "Estimar AMCE";
    }
  }

  function renderAmceResult(result) {
    el("amceResultEmpty").hidden = true;
    el("amceResult").hidden = false;

    const fitStats = [["N (perfiles)", result.n], ["Entrevistados", result.n_respondents], ["Conjuntos de elección", result.n_choice_sets]];
    if (result.method === "ols") fitStats.push(["R²", fmt(result.r_squared, 3)]);
    if (result.method === "clogit") {
      fitStats.push(["Log-verosimilitud", fmt(result.log_likelihood, 1)]);
      if (result.choice_sets_dropped) fitStats.push(["Conjuntos descartados", result.choice_sets_dropped]);
    }
    el("amceFitStats").innerHTML = fitStats.map(([label, value]) => `
      <div class="stat-tile"><span class="stat-tile__label">${escapeHtml(label)}</span><span class="stat-tile__value">${value}</span></div>
    `).join("");

    renderDotplot(result.plot_rows);

    const tbody = el("amceCoefTable").querySelector("tbody");
    tbody.innerHTML = result.plot_rows.map((row) => {
      if (row.is_baseline) {
        return `<tr><td>${escapeHtml(row.attribute)}</td><td>${escapeHtml(row.level)}</td><td>referencia</td><td>0</td><td>—</td><td>—</td><td>—</td></tr>`;
      }
      const sig = row.significant_at_05 ? "text-significant" : "";
      return `<tr>
        <td>${escapeHtml(row.attribute)}</td>
        <td>${escapeHtml(row.level)}</td>
        <td class="text-muted">–</td>
        <td class="${sig}">${fmt(row.estimate)}</td>
        <td>${fmt((row.ci_high - row.ci_low) / (2 * 1.959964))}</td>
        <td>[${fmt(row.ci_low)}, ${fmt(row.ci_high)}]</td>
        <td class="${sig}">${fmtP(row.p_value)}</td>
      </tr>`;
    }).join("");
  }

  // ---------- Dot plot (SVG) ----------
  function renderDotplot(plotRows) {
    const rowHeight = 28;
    const headerHeight = 22;
    const marginTop = 20;
    const marginBottom = 40;
    const marginLeft = 190;
    const marginRight = 30;
    const plotWidth = 480;

    const items = [];
    let lastAttr = null;
    for (const row of plotRows) {
      if (row.attribute !== lastAttr) {
        items.push({ type: "header", attribute: row.attribute });
        lastAttr = row.attribute;
      }
      items.push({ type: "data", ...row });
    }

    const values = plotRows.flatMap((r) => (r.ci_low === null ? [0] : [r.ci_low, r.ci_high]));
    let xMin = Math.min(0, ...values);
    let xMax = Math.max(0, ...values);
    const pad = (xMax - xMin) * 0.15 || 0.1;
    xMin -= pad; xMax += pad;

    let y = marginTop;
    const rows = [];
    for (const item of items) {
      if (item.type === "header") {
        rows.push({ ...item, y });
        y += headerHeight;
      } else {
        rows.push({ ...item, y: y + rowHeight / 2 });
        y += rowHeight;
      }
    }
    const height = y + marginBottom;
    const width = marginLeft + plotWidth + marginRight;

    const xScale = (v) => marginLeft + ((v - xMin) / (xMax - xMin)) * plotWidth;

    let svg = `<svg class="dotplot" viewBox="0 0 ${width} ${height}" width="100%" height="${height}" xmlns="http://www.w3.org/2000/svg">`;

    // Eje X: ticks
    const nTicks = 5;
    for (let i = 0; i <= nTicks; i++) {
      const v = xMin + ((xMax - xMin) * i) / nTicks;
      const x = xScale(v);
      svg += `<line class="dotplot__gridline" x1="${x}" y1="${marginTop - 8}" x2="${x}" y2="${y - 4}"></line>`;
      svg += `<text class="dotplot__axis-label" x="${x}" y="${y + 14}" text-anchor="middle">${v.toFixed(2)}</text>`;
    }
    // línea de referencia en 0
    const zeroX = xScale(0);
    svg += `<line class="dotplot__zeroline" x1="${zeroX}" y1="${marginTop - 8}" x2="${zeroX}" y2="${y - 4}"></line>`;

    for (const row of rows) {
      if (row.type === "header") {
        svg += `<text class="dotplot__attr-label" x="0" y="${row.y + 12}">${escapeHtml(row.attribute)}</text>`;
        continue;
      }
      const labelText = row.is_baseline ? `${row.level} (ref.)` : row.level;
      svg += `<text class="dotplot__level-label" x="14" y="${row.y + 4}">${escapeHtml(labelText)}</text>`;
      const cx = xScale(row.estimate);
      if (!row.is_baseline && row.ci_low !== null) {
        const x1 = xScale(row.ci_low);
        const x2 = xScale(row.ci_high);
        svg += `<line class="dotplot__ci" x1="${x1}" y1="${row.y}" x2="${x2}" y2="${row.y}"></line>`;
      }
      const pointCls = row.is_baseline ? "dotplot__point is-baseline" : `dotplot__point${row.significant_at_05 ? "" : " is-nonsig"}`;
      svg += `<circle class="${pointCls}" cx="${cx}" cy="${row.y}" r="4.5"></circle>`;
    }

    svg += "</svg>";
    el("dotplotWrap").innerHTML = svg;
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  }

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  // El SVG en pantalla usa clases CSS con var(--series-1) etc. para seguir
  // el tema en vivo, pero un SVG exportado (descargado o rasterizado a PNG)
  // se abre fuera de este documento y pierde esa hoja de estilos: sin
  // colores resueltos explícitamente, el archivo exportado sale en negro
  // y sin las barras de error. Por eso, para exportar, clonamos el SVG y
  // fijamos los valores de color ya resueltos como atributos de presentación.
  function buildExportableSvg() {
    const original = el("dotplotWrap").querySelector("svg");
    if (!original) return null;
    const clone = original.cloneNode(true);
    const palette = {
      gridline: cssVar("--gridline"),
      baseline: cssVar("--baseline"),
      series1: cssVar("--series-1"),
      textPrimary: cssVar("--text-primary"),
      textSecondary: cssVar("--text-secondary"),
      textMuted: cssVar("--text-muted"),
      surfaceRaised: cssVar("--surface-raised"),
    };
    clone.setAttribute("font-family", "system-ui, -apple-system, 'Segoe UI', sans-serif");
    clone.querySelectorAll(".dotplot__gridline").forEach((n) => n.setAttribute("stroke", palette.gridline));
    clone.querySelectorAll(".dotplot__zeroline").forEach((n) => {
      n.setAttribute("stroke", palette.baseline);
      n.setAttribute("stroke-width", "1.5");
    });
    clone.querySelectorAll(".dotplot__ci").forEach((n) => {
      n.setAttribute("stroke", palette.series1);
      n.setAttribute("stroke-width", "1.6");
    });
    clone.querySelectorAll(".dotplot__point").forEach((n) => {
      n.setAttribute("fill", n.classList.contains("is-baseline") ? palette.textMuted : palette.series1);
      if (n.classList.contains("is-nonsig")) n.setAttribute("fill-opacity", "0.55");
    });
    clone.querySelectorAll(".dotplot__attr-label").forEach((n) => {
      n.setAttribute("fill", palette.textSecondary);
      n.setAttribute("font-weight", "600");
      n.setAttribute("font-size", "11.5");
    });
    clone.querySelectorAll(".dotplot__level-label").forEach((n) => {
      n.setAttribute("fill", palette.textPrimary);
      n.setAttribute("font-size", "12.5");
    });
    clone.querySelectorAll(".dotplot__axis-label").forEach((n) => {
      n.setAttribute("fill", palette.textMuted);
      n.setAttribute("font-size", "11");
    });

    const [, , vbWidth, vbHeight] = clone.getAttribute("viewBox").split(" ").map(Number);
    clone.setAttribute("width", String(vbWidth));
    clone.setAttribute("height", String(vbHeight));

    const bg = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    bg.setAttribute("x", "0"); bg.setAttribute("y", "0");
    bg.setAttribute("width", String(vbWidth)); bg.setAttribute("height", String(vbHeight));
    bg.setAttribute("fill", palette.surfaceRaised);
    clone.insertBefore(bg, clone.firstChild);

    return clone;
  }

  el("exportSvgBtn").addEventListener("click", () => {
    const svgEl = buildExportableSvg();
    if (!svgEl) return;
    const serialized = new XMLSerializer().serializeToString(svgEl);
    const blob = new Blob([serialized], { type: "image/svg+xml" });
    downloadBlob(blob, "amce_dotplot.svg");
  });

  el("exportPngBtn").addEventListener("click", () => {
    const svgEl = buildExportableSvg();
    if (!svgEl) return;
    const serialized = new XMLSerializer().serializeToString(svgEl);
    const svgBlob = new Blob([serialized], { type: "image/svg+xml" });
    const url = URL.createObjectURL(svgBlob);
    const img = new Image();
    img.onload = () => {
      const scale = 2;
      const canvas = document.createElement("canvas");
      canvas.width = img.width * scale;
      canvas.height = img.height * scale;
      const ctx = canvas.getContext("2d");
      ctx.scale(scale, scale);
      const bg = getComputedStyle(document.documentElement).getPropertyValue("--surface-raised").trim() || "#fff";
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, img.width, img.height);
      ctx.drawImage(img, 0, 0);
      URL.revokeObjectURL(url);
      canvas.toBlob((blob) => downloadBlob(blob, "amce_dotplot.png"));
    };
    img.src = url;
  });

  el("exportCsvBtn").addEventListener("click", () => {
    if (!state.amceResult) return;
    const rows = state.amceResult.coefficients;
    const header = ["attribute", "level", "baseline", "estimate", "std_err", "ci_low", "ci_high", "p_value", "significant_at_05"];
    const lines = [header.join(",")];
    for (const r of rows) {
      lines.push(header.map((h) => JSON.stringify(r[h] === undefined ? "" : r[h])).join(","));
    }
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    downloadBlob(blob, "amce_coeficientes.csv");
  });
})();
