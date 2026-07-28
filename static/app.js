(() => {
  "use strict";

  const state = {
    sessionId: null,
    filename: null,
    nRows: 0,
    columns: [],              // [{name,label}] de todo el fichero
    experiments: {},          // id -> {id,name,kind,sample_filter,is_mapped}
    experimentOrder: [],      // ids en orden de creación
    activeExperimentId: null,
    conjoint: {},             // id -> {draft, unmatchedColumns, candidateTasks, candidateProfiles,
                               //        reshapeSummary, reshapePreview, amceResult, amceMethod, choiceValueOptions}
    vignette: {},             // id -> {draft, candidateOutcomes, candidateAttributes, summary, preview, amceResult}
    filterValueCache: {},     // "column" -> [{value,n}]
  };

  const el = (id) => document.getElementById(id);
  const fmt = (n, d = 3) => (n === null || n === undefined || Number.isNaN(n) ? "—" : Number(n).toLocaleString("es-ES", { maximumFractionDigits: d, minimumFractionDigits: 0 }));
  const fmtP = (p) => (p === null || p === undefined ? "—" : p < 0.001 ? "< 0.001" : fmt(p, 3));
  const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  async function request(method, url, body) {
    const opts = { method };
    if (body !== undefined) {
      opts.headers = { "Content-Type": "application/json" };
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(url, opts);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Ha ocurrido un error.");
    return data;
  }
  const getJson = (url) => request("GET", url);
  const postJson = (url, body) => request("POST", url, body ?? {});
  const patchJson = (url, body) => request("PATCH", url, body ?? {});
  const deleteJson = (url) => request("DELETE", url);

  function activeExperiment() {
    return state.experiments[state.activeExperimentId] || null;
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
      await onDatasetLoaded(data);
    } catch (err) {
      setUploadStatus(err.message, "error");
    }
  }

  async function onDatasetLoaded(data) {
    state.sessionId = data.session_id;
    state.filename = data.filename;
    state.nRows = data.n_rows;
    state.columns = data.columns;
    state.experiments = {};
    state.experimentOrder = [];
    state.conjoint = {};
    state.vignette = {};
    state.filterValueCache = {};

    for (const e of data.experiments) {
      state.experiments[e.id] = e;
      state.experimentOrder.push(e.id);
    }

    // La sugerencia del conjunto por defecto ya viene en la respuesta de subida:
    // nos ahorramos un round-trip para el caso más común (un solo experimento).
    const defaultId = data.default_experiment_id;
    state.conjoint[defaultId] = buildConjointStateFromSuggestion(data.suggested_mapping);

    el("fileMeta").textContent = `${data.filename} · ${data.n_rows.toLocaleString("es-ES")} filas · ${data.n_cols} variables`;
    el("resetBtn").hidden = false;
    el("uploadScreen").hidden = true;
    el("appScreen").hidden = false;

    await selectExperiment(defaultId);
  }

  el("resetBtn").addEventListener("click", async () => {
    if (state.sessionId) {
      try { await fetch(`/api/session/${state.sessionId}`, { method: "DELETE" }); } catch (_e) { /* noop */ }
    }
    location.reload();
  });

  // =====================================================================
  // Conjuntos (experimentos): panel lateral, crear / renombrar / duplicar / eliminar
  // =====================================================================

  function renderExperimentsList() {
    const wrap = el("experimentsList");
    wrap.innerHTML = state.experimentOrder.map((id) => {
      const e = state.experiments[id];
      const isActive = id === state.activeExperimentId;
      const kindLabel = e.kind === "vignette" ? "Viñeta" : "Elección";
      return `
        <div class="experiment-item ${isActive ? "is-active" : ""}" data-id="${escapeHtml(id)}">
          <span class="experiment-item__kind is-${e.kind}">${kindLabel}</span>
          <span class="experiment-item__name" title="${escapeHtml(e.name)}">${escapeHtml(e.name)}</span>
          <div class="experiment-item__actions">
            <button data-action="rename" title="Renombrar">&#9998;</button>
            <button data-action="duplicate" title="Duplicar como plantilla">&#10697;</button>
            <button data-action="delete" title="Eliminar">&times;</button>
          </div>
        </div>`;
    }).join("");

    wrap.querySelectorAll(".experiment-item").forEach((row) => {
      const id = row.dataset.id;
      row.addEventListener("click", (e) => {
        if (e.target.closest("[data-action]")) return;
        selectExperiment(id);
      });
      row.querySelector('[data-action="rename"]').addEventListener("click", () => renameExperimentFlow(id));
      row.querySelector('[data-action="duplicate"]').addEventListener("click", () => duplicateExperimentFlow(id));
      row.querySelector('[data-action="delete"]').addEventListener("click", () => deleteExperimentFlow(id));
    });
  }

  el("addExperimentBtn").addEventListener("click", () => {
    openModal(`
      <div class="modal-header"><h3>Nuevo conjunto</h3><button class="modal-close" aria-label="Cerrar">&times;</button></div>
      <div class="modal-body">
        <label class="field"><span>Nombre</span><input id="newExpName" type="text" placeholder="Experimento 2"></label>
        <label class="field" style="margin-top:10px">
          <span>Tipo</span>
          <select id="newExpKind">
            <option value="conjoint">Elección (perfiles enfrentados → AMCE)</option>
            <option value="vignette">Viñeta (perfil único → variable de resultado)</option>
          </select>
        </label>
        <div id="newExpError" class="modal-error" hidden></div>
      </div>
      <div class="modal-footer">
        <button class="btn btn--ghost modal-close">Cancelar</button>
        <button id="newExpSave" class="btn btn--primary">Crear</button>
      </div>
    `);
    el("newExpSave").addEventListener("click", async () => {
      const name = el("newExpName").value.trim();
      if (!name) {
        el("newExpError").hidden = false;
        el("newExpError").textContent = "Indica un nombre.";
        return;
      }
      const kind = el("newExpKind").value;
      try {
        const exp = await postJson(`/api/experiments/${state.sessionId}`, { name, kind });
        state.experiments[exp.id] = exp;
        state.experimentOrder.push(exp.id);
        closeModal();
        renderExperimentsList();
        await selectExperiment(exp.id);
      } catch (err) {
        el("newExpError").hidden = false;
        el("newExpError").textContent = err.message;
      }
    });
  });

  function renameExperimentFlow(id) {
    const exp = state.experiments[id];
    openModal(`
      <div class="modal-header"><h3>Renombrar conjunto</h3><button class="modal-close" aria-label="Cerrar">&times;</button></div>
      <div class="modal-body">
        <label class="field"><span>Nombre</span><input id="renameExpName" type="text" value="${escapeHtml(exp.name)}"></label>
      </div>
      <div class="modal-footer">
        <button class="btn btn--ghost modal-close">Cancelar</button>
        <button id="renameExpSave" class="btn btn--primary">Guardar</button>
      </div>
    `);
    el("renameExpName").focus();
    el("renameExpSave").addEventListener("click", async () => {
      const name = el("renameExpName").value.trim();
      if (!name) return;
      const updated = await patchJson(`/api/experiments/${state.sessionId}/${id}`, { name });
      state.experiments[id] = updated;
      closeModal();
      renderExperimentsList();
    });
  }

  function duplicateExperimentFlow(id) {
    const exp = state.experiments[id];
    openModal(`
      <div class="modal-header"><h3>Duplicar conjunto</h3><button class="modal-close" aria-label="Cerrar">&times;</button></div>
      <div class="modal-body">
        <p class="text-secondary" style="font-size:13px;margin-bottom:12px">
          Se copia el mapeo ya aplicado de "${escapeHtml(exp.name)}" como punto de partida para el nuevo conjunto.
        </p>
        <label class="field"><span>Nombre del nuevo conjunto</span><input id="dupExpName" type="text" value="${escapeHtml(exp.name)} (copia)"></label>
      </div>
      <div class="modal-footer">
        <button class="btn btn--ghost modal-close">Cancelar</button>
        <button id="dupExpSave" class="btn btn--primary">Duplicar</button>
      </div>
    `);
    el("dupExpSave").addEventListener("click", async () => {
      const name = el("dupExpName").value.trim();
      if (!name) return;
      const created = await postJson(`/api/experiments/${state.sessionId}/${id}/duplicate`, { name });
      state.experiments[created.id] = created;
      state.experimentOrder.push(created.id);
      // El estado local (borrador de mapeo) también se copia, para que el usuario
      // vea de inmediato la misma tabla ya rellenada en vez de una sugerencia en blanco.
      if (exp.kind === "conjoint" && state.conjoint[id]) {
        state.conjoint[created.id] = JSON.parse(JSON.stringify(state.conjoint[id]));
      } else if (exp.kind === "vignette" && state.vignette[id]) {
        state.vignette[created.id] = JSON.parse(JSON.stringify(state.vignette[id]));
      }
      closeModal();
      renderExperimentsList();
      await selectExperiment(created.id);
    });
  }

  function deleteExperimentFlow(id) {
    const exp = state.experiments[id];
    if (state.experimentOrder.length <= 1) {
      alert("No puedes eliminar el único conjunto de la sesión.");
      return;
    }
    openModal(`
      <div class="modal-header"><h3>Eliminar conjunto</h3><button class="modal-close" aria-label="Cerrar">&times;</button></div>
      <div class="modal-body">
        <p style="font-size:13.5px">¿Seguro que quieres eliminar "${escapeHtml(exp.name)}"? Se perderá su mapeo y sus resultados.</p>
      </div>
      <div class="modal-footer">
        <button class="btn btn--ghost modal-close">Cancelar</button>
        <button id="deleteExpConfirm" class="btn btn--primary" style="background:var(--critical);border-color:var(--critical)">Eliminar</button>
      </div>
    `);
    el("deleteExpConfirm").addEventListener("click", async () => {
      await deleteJson(`/api/experiments/${state.sessionId}/${id}`);
      delete state.experiments[id];
      delete state.conjoint[id];
      delete state.vignette[id];
      state.experimentOrder = state.experimentOrder.filter((x) => x !== id);
      closeModal();
      if (state.activeExperimentId === id) {
        await selectExperiment(state.experimentOrder[0]);
      } else {
        renderExperimentsList();
      }
    });
  }

  // =====================================================================
  // Cambio de conjunto activo: pasos y contenido dependen de su tipo
  // =====================================================================

  async function selectExperiment(id) {
    state.activeExperimentId = id;
    renderExperimentsList();
    const exp = activeExperiment();

    renderStepperAndTabs(exp.kind);
    renderSampleFilterCard();

    el("conjointMappingPanel").hidden = exp.kind !== "conjoint";
    el("vignetteMappingPanel").hidden = exp.kind !== "vignette";
    el("amceMethodField").hidden = exp.kind !== "conjoint";

    if (exp.kind === "conjoint") {
      await ensureConjointState(id);
      renderMappingStep();
      renderReshapeStepForActive();
      renderAmceStepForActive();
    } else {
      await ensureVignetteState(id);
      renderVignetteMappingStep();
      renderVignetteReshapeStepForActive();
      renderAmceStepForActive();
    }
    goToStep("mapping");
  }

  // =====================================================================
  // Filtro de submuestra (común a ambos tipos de conjunto)
  // =====================================================================

  function renderSampleFilterCard() {
    const exp = activeExperiment();
    const select = el("filterColumnSelect");
    select.innerHTML = '<option value="">(sin filtro · todo el fichero)</option>' +
      state.columns.map((c) => {
        const label = c.label && c.label !== c.name ? `${c.label} (${c.name})` : c.name;
        return `<option value="${escapeHtml(c.name)}">${escapeHtml(label)}</option>`;
      }).join("");
    select.value = exp.sample_filter ? exp.sample_filter.column : "";

    if (exp.sample_filter) {
      loadFilterValues(exp.sample_filter.column, exp.sample_filter.values);
    } else {
      el("filterValuesChecklist").innerHTML = "";
    }
  }

  el("filterColumnSelect").addEventListener("change", (e) => {
    if (!e.target.value) {
      el("filterValuesChecklist").innerHTML = "";
      return;
    }
    loadFilterValues(e.target.value, []);
  });

  async function loadFilterValues(column, preselected) {
    const wrap = el("filterValuesChecklist");
    wrap.innerHTML = '<span class="text-muted" style="font-size:12.5px">Cargando valores…</span>';
    if (!state.filterValueCache[column]) {
      const data = await getJson(`/api/columns/${state.sessionId}/values?column=${encodeURIComponent(column)}&limit=60`);
      state.filterValueCache[column] = data.values;
    }
    const values = state.filterValueCache[column];
    const preselectedSet = new Set(preselected);
    wrap.innerHTML = values.map((v) => `
      <label class="checklist-item">
        <input type="checkbox" class="filter-value-check" value="${escapeHtml(v.value)}" ${preselectedSet.has(v.value) ? "checked" : ""}>
        <span>${escapeHtml(v.value)}</span>
        <span class="text-muted" style="font-size:11.5px">${v.n}</span>
      </label>
    `).join("");
  }

  el("applyFilterBtn").addEventListener("click", async () => {
    const id = state.activeExperimentId;
    const column = el("filterColumnSelect").value;
    const checked = Array.from(el("filterValuesChecklist").querySelectorAll(".filter-value-check:checked")).map((c) => c.value);

    let updated;
    if (!column) {
      updated = await patchJson(`/api/experiments/${state.sessionId}/${id}`, { clear_sample_filter: true });
    } else {
      if (checked.length === 0) {
        alert("Marca al menos un valor, o deja la columna vacía para no filtrar.");
        return;
      }
      updated = await patchJson(`/api/experiments/${state.sessionId}/${id}`, {
        sample_filter: { column, values: checked },
      });
    }
    state.experiments[id] = updated;
    // Cambiar el filtro invalida el mapeo aplicado (lo hace el propio backend);
    // descartamos también el borrador local para recalcular la sugerencia sobre la nueva submuestra.
    delete state.conjoint[id];
    delete state.vignette[id];
    renderExperimentsList();
    await selectExperiment(id);
  });

  // =====================================================================
  // Stepper / tabs dinámicos según el tipo de conjunto
  // =====================================================================

  const STEP_LABELS = {
    conjoint: ["Mapeo de variables", "Reestructuración", "Estimación AMCE"],
    vignette: ["Mapeo de variables", "Vista previa", "Estimación"],
  };
  const STEPS = ["mapping", "reshape", "amce"];
  let currentStep = "mapping";

  function renderStepperAndTabs(kind) {
    const labels = STEP_LABELS[kind];
    el("stepper").innerHTML = STEPS.map((step, i) => `
      <div class="stepper__step" data-step="${step}">
        <span class="stepper__num">${i + 1}</span><span>${escapeHtml(labels[i])}</span>
      </div>
    `).join("");
    el("tabs").innerHTML = STEPS.map((step, i) => `
      <button class="tab" data-tab="${step}">${i + 1} · ${escapeHtml(labels[i])}</button>
    `).join("");

    document.querySelectorAll(".stepper__step").forEach((s) => s.addEventListener("click", () => goToStep(s.dataset.step)));
    document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => goToStep(tab.dataset.tab)));

    const exp = activeExperiment();
    if (exp.kind === "conjoint" && state.conjoint[exp.id]) {
      if (state.conjoint[exp.id].reshapeSummary) markStepDone("mapping");
      if (state.conjoint[exp.id].amceResult) markStepDone("reshape");
    }
    if (exp.kind === "vignette" && state.vignette[exp.id]) {
      if (state.vignette[exp.id].summary) markStepDone("mapping");
      if (state.vignette[exp.id].amceResult) markStepDone("reshape");
    }
    goToStep("mapping");
  }

  function goToStep(step) {
    currentStep = step;
    document.querySelectorAll(".stepper__step").forEach((s) => s.classList.toggle("is-active", s.dataset.step === step));
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("is-active", t.dataset.tab === step));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("is-active"));
    el(`tab${step[0].toUpperCase()}${step.slice(1)}`).classList.add("is-active");
  }

  function markStepDone(step) {
    const stepEl = document.querySelector(`.stepper__step[data-step="${step}"]`);
    if (stepEl) stepEl.classList.add("is-done");
  }

  // =====================================================================
  // Conjunto de tipo "elección" (conjoint) · Paso 1 · Mapeo
  // =====================================================================

  function buildConjointStateFromSuggestion(suggestion) {
    return {
      draft: {
        respondent_id: suggestion.respondent_id,
        tasks: suggestion.tasks.length ? [...suggestion.tasks] : [],
        profiles: suggestion.profiles.length ? [...suggestion.profiles] : ["A", "B"],
        attributes: suggestion.attributes.length
          ? suggestion.attributes
          : [{ name: "atributo1", label: "atributo1", columns: {} }],
        choice_columns: suggestion.choice_columns || {},
        choice_value_map: suggestion.choice_value_map || {},
      },
      unmatchedColumns: suggestion.unmatched_columns || [],
      unmatchedChoiceValues: suggestion.unmatched_choice_values || [],
      candidateTasks: suggestion.candidate_tasks || [],
      candidateProfiles: suggestion.candidate_profiles || [],
      reshapeSummary: null,
      reshapePreview: null,
      amceResult: null,
      amceMethod: "ols",
      choiceValueOptions: {},
    };
  }

  async function ensureConjointState(id) {
    if (state.conjoint[id]) return;
    const suggestion = await getJson(`/api/mapping/${state.sessionId}/${id}/suggest`);
    state.conjoint[id] = buildConjointStateFromSuggestion(suggestion);
  }

  // Las candidatas de viñeta (outcome/atributo) son un heurístico sobre los
  // datos (nº de niveles, nombre...) y puede fallar en casos reales (p. ej.
  // una escala 0-10 con techo, donde casi todos contestan "10" y apenas
  // aparecen 4 valores distintos en la submuestra). Por eso nunca se usan
  // para restringir el selector, solo para ordenar: todas las columnas del
  // fichero siguen siendo elegibles.
  function columnOptionsWithSuggestionsHtml(suggested, selected) {
    const suggestedSet = new Set(suggested);
    const rest = state.columns.filter((c) => !suggestedSet.has(c.name));
    const optionHtml = (c) => {
      const label = c.label && c.label !== c.name ? `${c.label} (${c.name})` : c.name;
      return `<option value="${escapeHtml(c.name)}" ${c.name === selected ? "selected" : ""}>${escapeHtml(label)}</option>`;
    };
    let html = "";
    if (suggested.length) {
      const suggestedCols = suggested.map((name) => state.columns.find((c) => c.name === name)).filter(Boolean);
      html += `<optgroup label="Sugeridas">${suggestedCols.map(optionHtml).join("")}</optgroup>`;
      html += `<optgroup label="Todas las demás columnas">${rest.map(optionHtml).join("")}</optgroup>`;
    } else {
      html += state.columns.map(optionHtml).join("");
    }
    return html;
  }

  function columnOptionsHtml(selected) {
    const opts = ['<option value="">—</option>'];
    for (const c of state.columns) {
      const sel = c.name === selected ? "selected" : "";
      const label = c.label && c.label !== c.name ? `${c.label} (${c.name})` : c.name;
      opts.push(`<option value="${escapeHtml(c.name)}" ${sel}>${escapeHtml(label)}</option>`);
    }
    return opts.join("");
  }

  function currentConjointState() {
    return state.conjoint[state.activeExperimentId];
  }

  function renderMappingStep() {
    const cs = currentConjointState();
    const d = cs.draft;

    el("respondentIdSelect").innerHTML = '<option value="">(usar número de fila)</option>' + columnOptionsHtml(d.respondent_id).replace('<option value="">—</option>', "");
    el("respondentIdSelect").value = d.respondent_id || "";

    renderTaskChips();
    renderProfileChips();
    renderAttributeGrid();
    renderChoiceGrid();
    renderUnmatchedColumns();
    updateSidebarSummary();
  }

  el("respondentIdSelect").addEventListener("change", (e) => {
    currentConjointState().draft.respondent_id = e.target.value || null;
  });

  function renderTaskChips() {
    const cs = currentConjointState();
    const wrap = el("tasksChips");
    wrap.innerHTML = cs.draft.tasks.map((t) => `
      <span class="chip">${escapeHtml(t)}<button data-task="${escapeHtml(t)}" title="Quitar tarea">&times;</button></span>
    `).join("");
    wrap.querySelectorAll("button").forEach((btn) => {
      btn.addEventListener("click", () => {
        cs.draft.tasks = cs.draft.tasks.filter((t) => t !== btn.dataset.task);
        delete cs.draft.choice_columns[btn.dataset.task];
        renderTaskChips();
        renderAttributeGrid();
        renderChoiceGrid();
      });
    });

    const select = el("addTaskSelect");
    const remaining = cs.candidateTasks.filter((t) => !cs.draft.tasks.includes(t));
    select.innerHTML = '<option value="">+ añadir tarea…</option>' + remaining.map((t) => `<option value="${escapeHtml(t)}">${escapeHtml(t)}</option>`).join("");
  }

  el("addTaskSelect").addEventListener("change", (e) => {
    if (!e.target.value) return;
    const cs = currentConjointState();
    cs.draft.tasks.push(e.target.value);
    e.target.value = "";
    renderTaskChips();
    renderAttributeGrid();
    renderChoiceGrid();
  });

  function renderProfileChips() {
    const cs = currentConjointState();
    const wrap = el("profilesChips");
    wrap.innerHTML = cs.draft.profiles.map((p) => `
      <span class="chip">${escapeHtml(p)}<button data-profile="${escapeHtml(p)}" title="Quitar perfil">&times;</button></span>
    `).join("");
    wrap.querySelectorAll("button").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (cs.draft.profiles.length <= 2) {
          alert("Un conjoint necesita al menos dos perfiles.");
          return;
        }
        const profile = btn.dataset.profile;
        cs.draft.profiles = cs.draft.profiles.filter((p) => p !== profile);
        for (const k of Object.keys(cs.draft.choice_value_map)) {
          if (cs.draft.choice_value_map[k] === profile) delete cs.draft.choice_value_map[k];
        }
        renderProfileChips();
        renderAttributeGrid();
        renderChoiceGrid();
      });
    });

    const select = el("addProfileSelect");
    const remaining = cs.candidateProfiles.filter((p) => !cs.draft.profiles.includes(p));
    select.innerHTML = '<option value="">+ añadir perfil…</option>' + remaining.map((p) => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`).join("");
  }

  el("addProfileSelect").addEventListener("change", (e) => {
    if (!e.target.value) return;
    const cs = currentConjointState();
    cs.draft.profiles.push(e.target.value);
    e.target.value = "";
    renderProfileChips();
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
      const cs = currentConjointState();
      const name = el("newAttrName").value.trim();
      const label = el("newAttrLabel").value.trim() || name;
      if (!name) {
        el("newAttrError").hidden = false;
        el("newAttrError").textContent = "Indica un nombre.";
        return;
      }
      if (cs.draft.attributes.some((a) => a.name === name)) {
        el("newAttrError").hidden = false;
        el("newAttrError").textContent = "Ya existe un atributo con ese nombre.";
        return;
      }
      cs.draft.attributes.push({ name, label, columns: {} });
      closeModal();
      renderAttributeGrid();
    });
  });

  function renderAttributeGrid() {
    const cs = currentConjointState();
    const d = cs.draft;
    const wrap = el("mappingGridWrap");
    if (!d.tasks.length) {
      wrap.innerHTML = '<p class="empty-state">Añade al menos una tarea para empezar a mapear atributos.</p>';
      return;
    }
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
        const attrObj = cs.draft.attributes.find((a) => a.name === attr);
        if (!attrObj.columns[task]) attrObj.columns[task] = {};
        attrObj.columns[task][profile] = e.target.value || undefined;
        if (!e.target.value) delete attrObj.columns[task][profile];
        e.target.className = e.target.value ? "is-matched" : "is-unmatched";
      });
    });
    wrap.querySelectorAll(".remove-attr-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        cs.draft.attributes = cs.draft.attributes.filter((a) => a.name !== btn.dataset.attr);
        renderAttributeGrid();
      });
    });
  }

  async function choiceValueOptionsFor(cs, columns) {
    const uniqueCols = [...new Set(columns.filter(Boolean))];
    const missing = uniqueCols.filter((c) => !cs.choiceValueOptions[c]);
    await Promise.all(missing.map(async (col) => {
      const data = await getJson(`/api/columns/${state.sessionId}/values?column=${encodeURIComponent(col)}&limit=60`);
      cs.choiceValueOptions[col] = data.values.map((v) => v.value);
    }));
    const merged = new Set();
    for (const col of uniqueCols) (cs.choiceValueOptions[col] || []).forEach((v) => merged.add(v));
    return [...merged];
  }

  async function renderChoiceGrid() {
    const cs = currentConjointState();
    const d = cs.draft;
    const wrap = el("choiceGridWrap");
    if (!d.tasks.length) {
      wrap.innerHTML = "";
      return;
    }
    const observedValues = await choiceValueOptionsFor(cs, Object.values(d.choice_columns));

    let html = '<table class="mapping-grid"><thead><tr><th>Tarea</th><th>Columna de elección</th></tr></thead><tbody>';
    for (const task of d.tasks) {
      const current = d.choice_columns[task] || "";
      const cls = current ? "is-matched" : "is-unmatched";
      html += `<tr><th>${escapeHtml(task)}</th><td><select class="${cls}" data-task="${escapeHtml(task)}">${columnOptionsHtml(current)}</select></td></tr>`;
    }
    html += "</tbody></table>";
    html += '<div style="padding:14px"><p class="text-secondary" style="font-size:12.5px;margin-bottom:10px">¿Con qué valor se codifica cada perfil en la columna de elección? (detectado automáticamente contra los valores reales del fichero; corrígelo si hace falta)</p>';
    for (const p of d.profiles) {
      const raw = Object.entries(d.choice_value_map).find(([, v]) => v === p);
      const rawValue = raw ? raw[0] : "";
      const options = ['<option value="">(sin usar)</option>'];
      const seen = new Set();
      if (rawValue && !observedValues.includes(rawValue)) { options.push(`<option value="${escapeHtml(rawValue)}" selected>${escapeHtml(rawValue)}</option>`); seen.add(rawValue); }
      for (const v of observedValues) {
        if (seen.has(v)) continue;
        options.push(`<option value="${escapeHtml(v)}" ${v === rawValue ? "selected" : ""}>${escapeHtml(v)}</option>`);
      }
      html += `<label class="field" style="display:inline-flex;margin-right:16px"><span>Perfil ${escapeHtml(p)} = </span><select data-profile-value="${escapeHtml(p)}">${options.join("")}</select></label>`;
    }
    if (cs.unmatchedChoiceValues.length) {
      html += `<p class="text-muted" style="font-size:12px;margin-top:10px">Valores observados sin asignar a ningún perfil (p. ej. no respuesta): ${cs.unmatchedChoiceValues.map(escapeHtml).join(", ")}</p>`;
    }
    html += "</div>";
    wrap.innerHTML = html;

    wrap.querySelectorAll("select[data-task]").forEach((sel) => {
      sel.addEventListener("change", (e) => {
        cs.draft.choice_columns[e.target.dataset.task] = e.target.value || undefined;
        if (!e.target.value) delete cs.draft.choice_columns[e.target.dataset.task];
        e.target.className = e.target.value ? "is-matched" : "is-unmatched";
        renderChoiceGrid();
      });
    });
    wrap.querySelectorAll("select[data-profile-value]").forEach((sel) => {
      sel.addEventListener("change", (e) => {
        const profile = e.target.dataset.profileValue;
        for (const k of Object.keys(cs.draft.choice_value_map)) {
          if (cs.draft.choice_value_map[k] === profile) delete cs.draft.choice_value_map[k];
        }
        if (e.target.value) cs.draft.choice_value_map[e.target.value] = profile;
      });
    });
  }

  function renderUnmatchedColumns() {
    const cs = currentConjointState();
    const card = el("unmatchedCard");
    const wrap = el("unmatchedColumns");
    if (!cs.unmatchedColumns.length) { card.hidden = true; return; }
    card.hidden = false;
    wrap.innerHTML = cs.unmatchedColumns.map((c) => `<span class="chip">${escapeHtml(c)}</span>`).join("");
  }

  el("applyMappingBtn").addEventListener("click", applyMapping);

  async function applyMapping() {
    const id = state.activeExperimentId;
    const cs = currentConjointState();
    const d = cs.draft;
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
      const result = await postJson(`/api/mapping/${state.sessionId}/${id}/apply`, payload);
      issuesEl.innerHTML = result.issues.map((i) => `<div class="issue-list__item">${escapeHtml(i)}</div>`).join("");
      cs.reshapeSummary = result.summary;
      cs.reshapePreview = null;
      cs.amceResult = null;
      state.experiments[id].is_mapped = true;
      markStepDone("mapping");
      updateSidebarSummary();
      await loadReshapePreview();
      renderReshapeStepForActive();
      resetAmceStep();
      goToStep("reshape");
    } catch (err) {
      issuesEl.innerHTML = `<div class="issue-list__item">${escapeHtml(err.message)}</div>`;
    }
  }

  function updateSidebarSummary() {
    const exp = activeExperiment();
    el("sumRows").textContent = state.nRows.toLocaleString("es-ES");

    el("sumFilterRow").hidden = !exp.sample_filter;
    if (exp.sample_filter) {
      el("sumFilter").textContent = `Filtro: ${exp.sample_filter.column} ∈ {${exp.sample_filter.values.join(", ")}}`;
    }

    if (exp.kind === "conjoint") {
      const cs = currentConjointState();
      el("sumConjointRow").hidden = false;
      const s = cs.reshapeSummary;
      el("sumTasks").textContent = s ? s.n_tasks : "–";
      el("sumProfiles").textContent = s ? s.n_profiles : "–";
      el("sumAttrs").textContent = cs.draft ? cs.draft.attributes.length : "–";
    } else {
      el("sumConjointRow").hidden = true;
      const vs = state.vignette[exp.id];
      el("sumAttrs").textContent = vs && vs.draft ? vs.draft.attributes.length : "–";
    }
  }

  // =====================================================================
  // Conjunto de tipo "elección" · Paso 2 · Reestructuración
  // =====================================================================

  async function loadReshapePreview() {
    const cs = currentConjointState();
    cs.reshapePreview = await getJson(`/api/reshape/${state.sessionId}/${state.activeExperimentId}/preview?limit=50`);
  }

  function renderReshapeStepForActive() {
    const cs = currentConjointState();
    el("conjointReshapeContent").hidden = false;
    el("previewTitle").textContent = "Vista previa del fichero largo (formato tidy)";
    if (!cs.reshapeSummary) {
      el("reshapeEmpty").hidden = false;
      el("reshapeContent").hidden = true;
      return;
    }
    renderReshapeStep(cs);
  }

  function renderReshapeStep(cs) {
    const s = cs.reshapeSummary;
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

    renderPreviewTable(cs.reshapePreview);
  }

  function renderPreviewTable(preview) {
    if (!preview) return;
    const cols = preview.rows.length ? Object.keys(preview.rows[0]) : [];
    const thead = el("reshapePreviewTable").querySelector("thead");
    const tbody = el("reshapePreviewTable").querySelector("tbody");
    thead.innerHTML = `<tr>${cols.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr>`;
    tbody.innerHTML = preview.rows.map((row) => `<tr>${cols.map((c) => `<td>${row[c] === null || row[c] === undefined ? "" : escapeHtml(row[c])}</td>`).join("")}</tr>`).join("");
  }

  // =====================================================================
  // Conjunto de tipo "viñeta" · Paso 1 · Mapeo
  // =====================================================================

  async function ensureVignetteState(id) {
    if (state.vignette[id]) return;
    const suggestion = await getJson(`/api/vignette/${state.sessionId}/${id}/suggest`);
    const outcome = suggestion.candidate_outcome_columns[0] || "";
    state.vignette[id] = {
      candidateOutcomes: suggestion.candidate_outcome_columns,
      candidateAttributes: suggestion.candidate_attribute_columns,
      draft: {
        respondent_id: null,
        outcome_column: outcome,
        outcome_label: "",
        attributes: [],
      },
      summary: null,
      preview: null,
      amceResult: null,
    };
  }

  function currentVignetteState() {
    return state.vignette[state.activeExperimentId];
  }

  function renderVignetteMappingStep() {
    const vs = currentVignetteState();
    const d = vs.draft;

    el("vignetteRespondentIdSelect").innerHTML = '<option value="">(usar número de fila)</option>' + columnOptionsHtml(d.respondent_id).replace('<option value="">—</option>', "");
    el("vignetteRespondentIdSelect").value = d.respondent_id || "";

    el("vignetteOutcomeSelect").innerHTML = columnOptionsWithSuggestionsHtml(vs.candidateOutcomes, d.outcome_column);

    renderVignetteAttributeGrid();
    updateSidebarSummary();
  }

  el("vignetteRespondentIdSelect").addEventListener("change", (e) => {
    currentVignetteState().draft.respondent_id = e.target.value || null;
  });
  el("vignetteOutcomeSelect").addEventListener("change", (e) => {
    currentVignetteState().draft.outcome_column = e.target.value;
  });

  el("addVignetteAttributeBtn").addEventListener("click", () => {
    const vs = currentVignetteState();
    openModal(`
      <div class="modal-header"><h3>Añadir atributo del estímulo</h3><button class="modal-close" aria-label="Cerrar">&times;</button></div>
      <div class="modal-body">
        <label class="field"><span>Columna del fichero</span>
          <select id="newVAttrColumn">${columnOptionsWithSuggestionsHtml(vs.candidateAttributes, "")}</select>
        </label>
        <label class="field" style="margin-top:10px"><span>Nombre del atributo</span><input id="newVAttrName" type="text" placeholder="texto"></label>
        <div id="newVAttrError" class="modal-error" hidden></div>
      </div>
      <div class="modal-footer">
        <button class="btn btn--ghost modal-close">Cancelar</button>
        <button id="newVAttrSave" class="btn btn--primary">Añadir</button>
      </div>
    `);
    el("newVAttrSave").addEventListener("click", () => {
      const column = el("newVAttrColumn").value;
      const name = el("newVAttrName").value.trim() || column;
      if (vs.draft.attributes.some((a) => a.name === name)) {
        el("newVAttrError").hidden = false;
        el("newVAttrError").textContent = "Ya existe un atributo con ese nombre.";
        return;
      }
      vs.draft.attributes.push({ name, label: name, column });
      closeModal();
      renderVignetteAttributeGrid();
    });
  });

  function renderVignetteAttributeGrid() {
    const vs = currentVignetteState();
    const wrap = el("vignetteAttributeGridWrap");
    if (!vs.draft.attributes.length) {
      wrap.innerHTML = '<p class="empty-state">Añade al menos un atributo del estímulo (p. ej. la versión de texto mostrada).</p>';
      return;
    }
    let html = '<table class="mapping-grid"><thead><tr><th>Atributo</th><th>Columna</th><th></th></tr></thead><tbody>';
    for (const attr of vs.draft.attributes) {
      html += `<tr>
        <td>${escapeHtml(attr.label || attr.name)}</td>
        <td><select data-attr="${escapeHtml(attr.name)}">${columnOptionsHtml(attr.column)}</select></td>
        <td><button class="btn btn--icon btn--sm remove-vattr-btn" data-attr="${escapeHtml(attr.name)}" title="Quitar">&times;</button></td>
      </tr>`;
    }
    html += "</tbody></table>";
    wrap.innerHTML = html;

    wrap.querySelectorAll("select[data-attr]").forEach((sel) => {
      sel.addEventListener("change", (e) => {
        const attr = vs.draft.attributes.find((a) => a.name === e.target.dataset.attr);
        attr.column = e.target.value;
      });
    });
    wrap.querySelectorAll(".remove-vattr-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        vs.draft.attributes = vs.draft.attributes.filter((a) => a.name !== btn.dataset.attr);
        renderVignetteAttributeGrid();
      });
    });
  }

  el("applyVignetteMappingBtn").addEventListener("click", applyVignetteMapping);

  async function applyVignetteMapping() {
    const id = state.activeExperimentId;
    const vs = currentVignetteState();
    const d = vs.draft;
    if (!d.outcome_column) { alert("Elige una variable de resultado."); return; }
    if (!d.attributes.length) { alert("Añade al menos un atributo."); return; }

    const payload = {
      respondent_id: d.respondent_id || null,
      outcome_column: d.outcome_column,
      outcome_label: d.outcome_label || "",
      attributes: d.attributes.map((a) => ({ name: a.name, label: a.label || a.name, column: a.column })),
    };
    const issuesEl = el("vignetteMappingIssues");
    issuesEl.innerHTML = "";
    try {
      const result = await postJson(`/api/vignette/${state.sessionId}/${id}/apply`, payload);
      issuesEl.innerHTML = result.issues.map((i) => `<div class="issue-list__item">${escapeHtml(i)}</div>`).join("");
      vs.summary = result.summary;
      vs.preview = null;
      vs.amceResult = null;
      state.experiments[id].is_mapped = true;
      markStepDone("mapping");
      updateSidebarSummary();
      vs.preview = await getJson(`/api/vignette/${state.sessionId}/${id}/preview?limit=50`);
      renderVignetteReshapeStepForActive();
      resetAmceStep();
      goToStep("reshape");
    } catch (err) {
      issuesEl.innerHTML = `<div class="issue-list__item">${escapeHtml(err.message)}</div>`;
    }
  }

  function renderVignetteReshapeStepForActive() {
    const vs = currentVignetteState();
    el("conjointReshapeContent").hidden = true;
    el("previewTitle").textContent = "Vista previa de los datos del conjunto";
    if (!vs.summary) {
      el("reshapeEmpty").hidden = false;
      el("reshapeContent").hidden = true;
      return;
    }
    el("reshapeEmpty").hidden = true;
    el("reshapeContent").hidden = false;
    renderPreviewTable(vs.preview);
  }

  // =====================================================================
  // Paso 3 · Estimación (común a elección y viñeta)
  // =====================================================================

  function resetAmceStep() {
    const exp = activeExperiment();
    if (exp.kind === "conjoint") currentConjointState().amceResult = null;
    else currentVignetteState().amceResult = null;
    renderAmceStepForActive();
  }

  function renderAmceStepForActive() {
    const exp = activeExperiment();
    const attributes = exp.kind === "conjoint"
      ? currentConjointState().draft.attributes
      : currentVignetteState().draft.attributes;
    const mapped = exp.kind === "conjoint"
      ? !!currentConjointState().reshapeSummary
      : !!currentVignetteState().summary;

    if (!mapped || !attributes.length) {
      el("amceEmpty").hidden = false;
      el("amceContent").hidden = true;
      return;
    }
    el("amceEmpty").hidden = true;
    el("amceContent").hidden = false;

    el("amceAttributes").innerHTML = attributes.map((a) => `
      <label class="checklist-item">
        <input type="checkbox" class="amce-attr-check" value="${escapeHtml(a.name)}" checked>
        <span>${escapeHtml(a.label || a.name)}</span>
      </label>
    `).join("");

    renderBaselineSelectors();
    el("amceAttributes").querySelectorAll(".amce-attr-check").forEach((cb) => {
      cb.addEventListener("change", renderBaselineSelectors);
    });

    const existingResult = exp.kind === "conjoint" ? currentConjointState().amceResult : currentVignetteState().amceResult;
    if (existingResult) {
      renderAmceResult(existingResult);
      markStepDone("reshape");
    } else {
      el("amceResultEmpty").hidden = false;
      el("amceResultEmpty").textContent = 'Configura el modelo y pulsa "Estimar".';
      el("amceResult").hidden = true;
    }
  }

  function renderBaselineSelectors() {
    const exp = activeExperiment();
    const checked = Array.from(el("amceAttributes").querySelectorAll(".amce-attr-check:checked")).map((c) => c.value);
    let levelsByAttr = {};
    if (exp.kind === "conjoint") {
      const coverage = (currentConjointState().reshapeSummary && currentConjointState().reshapeSummary.attribute_coverage) || {};
      for (const attr of checked) levelsByAttr[attr] = (coverage[attr] && coverage[attr].levels) || [];
    } else {
      // Para viñetas no tenemos un resumen de cobertura previo: se deja sin
      // preseleccionar y el backend usa el primer nivel observado por defecto.
      for (const attr of checked) levelsByAttr[attr] = [];
    }
    el("amceBaselines").innerHTML = checked.map((attr) => {
      const levels = levelsByAttr[attr];
      return `
        <label class="field" style="margin-top:8px">
          <span>Referencia: ${escapeHtml(attr)}</span>
          <select data-baseline-attr="${escapeHtml(attr)}">
            <option value="">(por defecto)</option>
            ${levels.map((l) => `<option value="${escapeHtml(l)}">${escapeHtml(l)}</option>`).join("")}
          </select>
        </label>`;
    }).join("");
  }

  document.addEventListener("click", (e) => {
    const btn = e.target.closest("#amceMethodToggle .segmented__btn");
    if (!btn) return;
    document.querySelectorAll("#amceMethodToggle .segmented__btn").forEach((b) => b.classList.remove("is-active"));
    btn.classList.add("is-active");
    currentConjointState().amceMethod = btn.dataset.method;
  });

  el("runAmceBtn").addEventListener("click", runAmce);

  async function runAmce() {
    const exp = activeExperiment();
    const attributes = Array.from(el("amceAttributes").querySelectorAll(".amce-attr-check:checked")).map((c) => c.value);
    if (!attributes.length) { alert("Elige al menos un atributo."); return; }
    const baselines = {};
    el("amceBaselines").querySelectorAll("select[data-baseline-attr]").forEach((sel) => {
      if (sel.value) baselines[sel.dataset.baselineAttr] = sel.value;
    });

    el("runAmceBtn").disabled = true;
    el("runAmceBtn").textContent = "Estimando…";
    try {
      let result;
      if (exp.kind === "conjoint") {
        const cs = currentConjointState();
        result = await postJson(`/api/amce/${state.sessionId}/${exp.id}`, { method: cs.amceMethod, attributes, baselines });
        cs.amceResult = result;
      } else {
        const vs = currentVignetteState();
        result = await postJson(`/api/vignette/${state.sessionId}/${exp.id}/estimate`, { attributes, baselines });
        vs.amceResult = result;
      }
      renderAmceResult(result);
      markStepDone("reshape");
    } catch (err) {
      el("amceResultEmpty").hidden = false;
      el("amceResultEmpty").textContent = err.message;
      el("amceResult").hidden = true;
    } finally {
      el("runAmceBtn").disabled = false;
      el("runAmceBtn").textContent = "Estimar";
    }
  }

  function renderAmceResult(result) {
    const exp = activeExperiment();
    el("amceResultEmpty").hidden = true;
    el("amceResult").hidden = false;
    el("amceResultTitle").textContent = exp.kind === "conjoint" ? "Efecto Marginal Medio (AMCE)" : "Efecto estimado por nivel";

    const fitStats = [["N", result.n]];
    if (result.method === "ols") {
      fitStats.push(["Entrevistados", result.n_respondents], ["Conjuntos de elección", result.n_choice_sets], ["R²", fmt(result.r_squared, 3)]);
    } else if (result.method === "clogit") {
      fitStats.push(["Entrevistados", result.n_respondents], ["Conjuntos de elección", result.n_choice_sets], ["Log-verosimilitud", fmt(result.log_likelihood, 1)]);
      if (result.choice_sets_dropped) fitStats.push(["Conjuntos descartados", result.choice_sets_dropped]);
    } else if (result.method === "vignette_ols") {
      fitStats.push(["R²", fmt(result.r_squared, 3)], ["Media del resultado", fmt(result.outcome_mean, 2)]);
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

    const nTicks = 5;
    for (let i = 0; i <= nTicks; i++) {
      const v = xMin + ((xMax - xMin) * i) / nTicks;
      const x = xScale(v);
      svg += `<line class="dotplot__gridline" x1="${x}" y1="${marginTop - 8}" x2="${x}" y2="${y - 4}"></line>`;
      svg += `<text class="dotplot__axis-label" x="${x}" y="${y + 14}" text-anchor="middle">${v.toFixed(2)}</text>`;
    }
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
    const exp = activeExperiment();
    const result = exp.kind === "conjoint" ? currentConjointState().amceResult : currentVignetteState().amceResult;
    if (!result) return;
    const rows = result.coefficients;
    const header = ["attribute", "level", "baseline", "estimate", "std_err", "ci_low", "ci_high", "p_value", "significant_at_05"];
    const lines = [header.join(",")];
    for (const r of rows) {
      lines.push(header.map((h) => JSON.stringify(r[h] === undefined ? "" : r[h])).join(","));
    }
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    downloadBlob(blob, "amce_coeficientes.csv");
  });
})();
