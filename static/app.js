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
    design: {},               // id -> {designFilename, designColumns, taskColumn, profileColumn, draft, reshapeSummary, reshapePreview, amceResult, amceMethod}
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
  function openModal(html, opts) {
    modalBody.className = "modal" + (opts && opts.wide ? " modal--help" : "");
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

  // ---------- Ayuda (guía paso a paso) ----------
  const HELP_SECTIONS = [
    {
      id: "help-upload",
      title: "1 · Sube el archivo",
      body: `
        <p>Arrastra o selecciona tu base en <code>.xlsx</code>, <code>.csv</code>, <code>.dta</code> (Stata) o
        <code>.sav</code> (SPSS). Al subirlo se crea automáticamente un primer conjunto ("Conjunto 1", tipo
        Elección) con una sugerencia de mapeo ya aplicada — no hace falta empezar desde cero.</p>
        <p>Todo se procesa en memoria durante esta sesión: no se guarda en disco ni se envía a ningún sitio.</p>`,
    },
    {
      id: "help-conjuntos",
      title: "2 · Conjuntos (varios experimentos en un mismo archivo)",
      body: `
        <p>Un <strong>conjunto</strong> es un experimento dentro de tu sesión. Si tu archivo contiene más de uno
        (p. ej. un conjoint de elección y una o varias viñetas, o el mismo diseño repetido para submuestras
        distintas), usa el botón <strong>+</strong> del panel "Conjuntos" para añadir cada uno por separado, en
        vez de tener que subir varios archivos o perder el trabajo ya hecho.</p>
        <ul>
          <li><strong>Elección</strong>: perfiles enfrentados (A vs B…) de los que el entrevistado elige uno → AMCE.</li>
          <li><strong>Viñeta</strong>: un único perfil o estímulo, valorado en una escala → estimación por OLS. Puedes
          añadir <strong>varios atributos</strong> a la vez (p. ej. el texto mostrado y, por separado, la foto
          mostrada, si el estímulo varió en más de una dimensión a la vez). La variable de resultado se elige de un
          desplegable con dos grupos: "Sugeridas" y "Todas las demás columnas" — si la que buscas no sale entre las
          sugeridas (p. ej. porque en una submuestra pequeña casi todo el mundo respondió el mismo valor y hay pocos
          niveles distintos), sigue estando disponible en el segundo grupo.</li>
        </ul>
        <p>Cada conjunto de la barra lateral se puede renombrar (✎), duplicar como plantilla (⧉, copia el mapeo
        ya hecho para no repetirlo) o eliminar (×). Cambiar de conjunto no borra el trabajo de los demás.</p>`,
    },
    {
      id: "help-filtro",
      title: "3 · Submuestra de este conjunto",
      body: `
        <p>Úsalo cuando el archivo reparte varios experimentos entre distintas submuestras de la misma encuesta
        (p. ej. una columna <code>EXPERIMENTO</code> con valores 1/2/3). Elige esa columna y marca qué valores
        pertenecen a <em>este</em> conjunto en concreto: el resto de pasos (mapeo, reestructuración, estimación)
        solo verán esas filas.</p>
        <p>Si dejas la columna vacía, el conjunto usa el archivo completo. Cambiar el filtro después de haber
        aplicado un mapeo lo reinicia, porque las columnas detectadas pueden variar según la submuestra.</p>`,
    },
    {
      id: "help-estructura",
      title: "4 · Estructura del experimento",
      body: `
        <p>Para conjuntos de tipo Elección:</p>
        <ul>
          <li><strong>Columna identificadora del entrevistado</strong>: el ID único de cada persona. Si no hay
          ninguna, deja "(usar número de fila)".</li>
          <li><strong>Tareas detectadas</strong>: cada tarea es una pantalla de elección (p. ej. <code>cj1</code>,
          <code>cj2</code>…). Aparecen como chips; quítalas con la × o añade las que falten desde el desplegable
          "+ añadir tarea…" — nunca hace falta escribirlas a mano, se eligen de lo que el propio archivo contiene.</li>
          <li><strong>Perfiles por tarea</strong>: las opciones que se enfrentan en cada tarea (normalmente A/B).
          Un conjoint necesita al menos dos.</li>
        </ul>`,
    },
    {
      id: "help-atributos",
      title: "5 · Atributos por tarea y perfil",
      body: `
        <p>La rejilla cruza cada tarea con cada atributo × perfil: cada celda es la columna del archivo que
        contiene ese valor concreto (p. ej. "rol" del perfil A en la tarea <code>cj1</code>). Una celda en verde
        significa que hay una columna asignada; en naranja, que falta.</p>
        <p>Usa "+ Añadir atributo" para incorporar un rasgo que no se haya detectado, o la × de la cabecera para
        quitar uno que no necesites en el análisis.</p>
        <p>Justo debajo, la <strong>columna de elección por tarea</strong> indica qué columna registra la
        respuesta, y a qué perfil corresponde cada valor real observado (p. ej. "Perfil A" → A). Esto se detecta
        automáticamente contra los valores del archivo; corrígelo solo si ves algo raro en los avisos del paso
        siguiente.</p>`,
    },
    {
      id: "help-diseno-externo",
      title: "6 · Elección con diseño externo",
      body: `
        <p>Úsalo cuando el fichero de respuestas solo guarda qué perfil ganó cada tarea y un código de versión
        aleatoria, sin los atributos de cada perfil incrustados como columnas (p. ej. "Candidato/a 1" vs
        "Candidato/a 2", con los rasgos de cada candidato en un fichero de diseño aparte).</p>
        <ul>
          <li>Sube el <strong>fichero de diseño</strong> (el que generó la aleatorización) y confirma qué columna
          es la tarea/pantalla y cuál el perfil/posición.</li>
          <li>Pulsa "Detectar mapeo": propone la columna de elección de cada tarea y, entre el resto de columnas
          del diseño, cuáles parecen <strong>claves de cruce</strong> (una variable de contexto, como la versión
          asignada a cada entrevistado) frente a <strong>atributos</strong> que entrarán en la estimación.</li>
          <li>Para cada clave de cruce, indica la columna equivalente en el fichero de respuestas y revisa la
          tabla de correspondencia de valores (p. ej. "Versión 19" del fichero de respuestas → "19" del diseño):
          la sugerencia automática puede fallar en casos concretos (nombres de región distintos, etc.), así que
          conviene repasarla antes de aplicar el mapeo.</li>
        </ul>`,
    },
    {
      id: "help-reestructuracion",
      title: "7 · Reestructuración",
      body: `
        <p>Al pulsar "Aplicar mapeo", el archivo (una fila por entrevistado) se convierte en formato largo: una
        fila por cada perfil visto en cada tarea. Verás un resumen con entrevistados, tareas, perfiles, conjuntos
        de elección y filas resultantes, más una vista previa de esas filas.</p>
        <p>Los avisos de calidad señalan problemas reales antes de estimar nada: conjuntos de elección sin ningún
        perfil marcado como elegido, más de un perfil elegido a la vez, o atributos con valores perdidos. Si
        salen muchos, suele apuntar a un problema en el mapeo del paso anterior (revisa la columna de elección).</p>`,
    },
    {
      id: "help-amce",
      title: "8 · Estimación (AMCE / viñeta)",
      body: `
        <p>Elige el <strong>método</strong> (solo para Elección): OLS con errores agrupados por entrevistado, o
        logit condicional dentro de cada conjunto de elección. Marca qué atributos incluir y, si quieres, cambia
        el nivel de referencia de cada uno.</p>
        <p>El <strong>dot plot</strong> muestra un punto por nivel de atributo (la estimación) y una línea
        horizontal (su intervalo de confianza al 95%); en azul intenso los efectos significativos, más tenues los
        que no lo son, y en gris el nivel de referencia (siempre en 0). La tabla de abajo trae los mismos datos en
        números, con error estándar y p-valor. Puedes exportar el gráfico en SVG/PNG y los coeficientes en CSV.</p>
        <p>En conjuntos de tipo Viñeta el resultado se lee igual, pero el efecto es sobre la variable de resultado
        continua, no sobre la probabilidad de ser elegido.</p>`,
    },
    {
      id: "help-tablas",
      title: "9 · Tablas comparativas (solo viñeta)",
      body: `
        <p>Cuando no hay una única variable dependiente clara y lo que interesa es comparar varias preguntas a la
        vez según el estímulo que le tocó a cada entrevistado, este paso evita tener que elegir "la" variable de
        resultado y repetir la estimación una y otra vez.</p>
        <ul>
          <li><strong>Comparar variables por atributo</strong>: marca en la lista (con buscador) tantas variables
          de resultado como quieras y pulsa "Generar tablas". Por cada una y cada atributo ya mapeado obtienes una
          tabla cruzada (recuentos y % por columna) y, si la variable es numérica, la media por grupo.</li>
          <li><strong>+ Recodificar variable</strong>: crea una nueva columna dicotómica a partir de una numérica
          (p. ej. "grave" = Sí si la gravedad es ≥ 8), útil para leer una escala de 0-10 como un simple % en vez de
          11 filas. La columna nueva queda disponible de inmediato en la lista de variables.</li>
          <li><strong>Conjunto de respuesta múltiple</strong>: para preguntas de marca-todas-las-que-apliquen, con
          una columna binaria por opción (p. ej. "¿cuáles crees que son los motivos…?"). Añade cada columna con su
          etiqueta y, si quieres, desglosa por un atributo ya mapeado; el % se calcula sobre quienes respondieron
          algo en ese conjunto, no sobre el total de la muestra.</li>
        </ul>`,
    },
  ];

  function renderHelpContent() {
    const toc = HELP_SECTIONS.map((s) => `<a href="#${s.id}">${escapeHtml(s.title)}</a>`).join("");
    const sections = HELP_SECTIONS.map((s) => `
      <div class="help-section" id="${s.id}">
        <h4>${escapeHtml(s.title)}</h4>
        ${s.body}
      </div>
    `).join("");
    return `
      <div class="modal-header"><h3>Guía paso a paso</h3><button class="modal-close" aria-label="Cerrar">&times;</button></div>
      <div class="help-toc">${toc}</div>
      ${sections}
    `;
  }

  el("helpBtn").addEventListener("click", () => {
    openModal(renderHelpContent(), { wide: true });
  });

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
    state.design = {};
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
      const kindLabel = { vignette: "Viñeta", conjoint_design: "Diseño externo" }[e.kind] || "Elección";
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
            <option value="conjoint_design">Elección con diseño externo (atributos en otro fichero)</option>
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
      } else if (exp.kind === "conjoint_design" && state.design[id]) {
        state.design[created.id] = JSON.parse(JSON.stringify(state.design[id]));
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
      delete state.design[id];
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
    el("designMappingPanel").hidden = exp.kind !== "conjoint_design";
    el("amceMethodField").hidden = exp.kind === "vignette";

    if (exp.kind === "conjoint") {
      await ensureConjointState(id);
      renderMappingStep();
      renderReshapeStepForActive();
      renderAmceStepForActive();
    } else if (exp.kind === "vignette") {
      await ensureVignetteState(id);
      renderVignetteMappingStep();
      renderVignetteReshapeStepForActive();
      renderAmceStepForActive();
      renderTablesStep();
    } else {
      await ensureDesignState(id);
      renderDesignMappingStep();
      renderReshapeStepForActive();
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

  const STEPS_BY_KIND = {
    conjoint: ["mapping", "reshape", "amce"],
    vignette: ["mapping", "reshape", "amce", "tables"],
    conjoint_design: ["mapping", "reshape", "amce"],
  };
  const STEP_LABELS = {
    conjoint: { mapping: "Mapeo de variables", reshape: "Reestructuración", amce: "Estimación AMCE" },
    vignette: { mapping: "Mapeo de variables", reshape: "Vista previa", amce: "Estimación", tables: "Tablas comparativas" },
    conjoint_design: { mapping: "Mapeo y cruce del diseño", reshape: "Reestructuración", amce: "Estimación AMCE" },
  };
  let currentStep = "mapping";

  function renderStepperAndTabs(kind) {
    const steps = STEPS_BY_KIND[kind];
    const labels = STEP_LABELS[kind];
    el("stepper").innerHTML = steps.map((step, i) => `
      <div class="stepper__step" data-step="${step}">
        <span class="stepper__num">${i + 1}</span><span>${escapeHtml(labels[step])}</span>
      </div>
    `).join("");
    el("tabs").innerHTML = steps.map((step, i) => `
      <button class="tab" data-tab="${step}">${i + 1} · ${escapeHtml(labels[step])}</button>
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
    if (exp.kind === "conjoint_design" && state.design[exp.id]) {
      if (state.design[exp.id].reshapeSummary) markStepDone("mapping");
      if (state.design[exp.id].amceResult) markStepDone("reshape");
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
  function columnOptionsWithSuggestionsHtml(suggested, selected, noneLabel) {
    const suggestedSet = new Set(suggested);
    const rest = state.columns.filter((c) => !suggestedSet.has(c.name));
    const optionHtml = (c) => {
      const label = c.label && c.label !== c.name ? `${c.label} (${c.name})` : c.name;
      return `<option value="${escapeHtml(c.name)}" ${c.name === selected ? "selected" : ""}>${escapeHtml(label)}</option>`;
    };
    let html = noneLabel ? `<option value="" ${selected ? "" : "selected"}>${escapeHtml(noneLabel)}</option>` : "";
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
      issuesEl.innerHTML = result.issues.map((i) => `<div class="issue-list__item${i.severity === "info" ? " issue-list__item--info" : ""}">${escapeHtml(i.text)}</div>`).join("");
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

    if (isChoiceLikeKind(exp.kind)) {
      const cs = currentAmceCapableState();
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
    const cs = currentAmceCapableState();
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

    // Un conjunto de elección sin perfil elegido puede ser un problema de mapeo
    // (un valor real que no se tradujo a ningún perfil) o, simplemente, que el
    // entrevistado no contestó esa tarea (NS/NC y similares) — algo normal en
    // cualquier encuesta. Se distinguen para no alarmar quandto es lo segundo.
    const unmapped = s.unmapped_choice_values || { missing_like: [], unrecognized: [] };
    const onlyNonResponse = unmapped.missing_like.length > 0 && unmapped.unrecognized.length === 0;

    const warnings = [];
    if (s.choice_sets_without_selection > 0) {
      if (onlyNonResponse) {
        warnings.push({
          info: true,
          text: `${s.choice_sets_without_selection} conjunto(s) de elección sin perfil elegido (${s.missing_choice_rows} filas) — corresponden a códigos de no respuesta en la columna de elección: ${unmapped.missing_like.join(", ")}. Es normal si la encuesta permite no contestar, no hace falta corregir nada.`,
        });
      } else {
        const detail = unmapped.unrecognized.length
          ? ` Valores sin traducir a ningún perfil: ${unmapped.unrecognized.join(", ")}.`
          : "";
        warnings.push({
          info: false,
          text: `${s.choice_sets_without_selection} conjunto(s) de elección sin perfil elegido (${s.missing_choice_rows} filas).${detail} Revisa la columna de elección o el mapeo de valores.`,
        });
      }
    }
    if (s.choice_sets_with_multiple_selections > 0) {
      warnings.push({ info: false, text: `${s.choice_sets_with_multiple_selections} conjunto(s) de elección con más de un perfil marcado como elegido.` });
    }
    for (const [attr, cov] of Object.entries(s.attribute_coverage)) {
      if (cov.n_missing > 0) warnings.push({ info: false, text: `El atributo "${attr}" tiene ${cov.n_missing} valores perdidos.` });
    }
    el("reshapeWarnings").hidden = warnings.length === 0;
    el("reshapeWarningsList").innerHTML = warnings.map((w) => `<div class="issue-list__item${w.info ? " issue-list__item--info" : ""}">${escapeHtml(w.text)}</div>`).join("");

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

  // Descarga del fichero completo ya reestructurado/mapeado (no solo la
  // vista previa limitada): un simple cambio de `location.href` basta, ya
  // que la respuesta lleva `Content-Disposition: attachment` y el navegador
  // la trata como descarga sin salir de la SPA.
  el("downloadButtons").querySelectorAll("button[data-download-format]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const exp = activeExperiment();
      const base = isChoiceLikeKind(exp.kind)
        ? `/api/reshape/${state.sessionId}/${exp.id}/download`
        : `/api/vignette/${state.sessionId}/${exp.id}/download`;
      window.location.href = `${base}?format=${btn.dataset.downloadFormat}`;
    });
  });

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
      tablesSelectedColumns: [],
      tablesResult: null,
      batteryResult: null,
      multiResponseItems: [{ column: "", label: "" }],
      multiResponseGroupAttribute: "",
      multiResponseResult: null,
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

    el("vignetteOutcomeSelect").innerHTML = columnOptionsWithSuggestionsHtml(
      vs.candidateOutcomes, d.outcome_column, '(ninguna — usaré "Estimar batería")'
    );

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
    renderMultiResponseGroupSelect(); // el desglose de "Tablas" depende de qué atributos hay mapeados
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
    if (!d.attributes.length) { alert("Añade al menos un atributo."); return; }

    const payload = {
      respondent_id: d.respondent_id || null,
      outcome_column: d.outcome_column || null,
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
  // Conjunto de tipo "viñeta" · Paso 4 · Tablas comparativas
  // =====================================================================

  function renderTablesStep() {
    const vs = currentVignetteState();
    renderTablesColumnChecklist();
    renderMultiResponseGroupSelect();
    renderMultiResponseItems();

    // Sin esto, al cambiar de un conjunto con resultados a otro que todavía
    // no los tiene, se quedaba viendo la tabla del conjunto anterior.
    if (vs.tablesResult) {
      renderTablesResult(vs.tablesResult);
    } else {
      el("tablesResultEmpty").hidden = false;
      el("tablesResultEmpty").textContent = 'Elige variables arriba y pulsa "Generar tablas".';
      el("tablesResult").hidden = true;
      el("tablesResult").innerHTML = "";
    }

    if (vs.batteryResult) {
      renderBatteryResult(vs.batteryResult);
    } else {
      el("batteryResultEmpty").hidden = false;
      el("batteryResultEmpty").textContent = 'Elige variables arriba y pulsa "Estimar batería".';
      el("batteryResult").hidden = true;
      el("batteryResult").innerHTML = "";
    }

    if (vs.multiResponseResult) {
      renderMultiResponseResult(vs.multiResponseResult);
    } else {
      el("multiResponseResult").innerHTML = "";
    }
  }

  function renderTablesColumnChecklist(filterText) {
    const vs = currentVignetteState();
    const wrap = el("tablesColumnChecklist");
    const q = (filterText || "").trim().toLowerCase();
    const selected = new Set(vs.tablesSelectedColumns);
    const cols = state.columns.filter((c) => {
      if (!q) return true;
      return c.name.toLowerCase().includes(q) || (c.label || "").toLowerCase().includes(q);
    });
    wrap.innerHTML = cols.map((c) => {
      const label = c.label && c.label !== c.name ? `${c.label} (${c.name})` : c.name;
      return `
        <label class="checklist-item">
          <input type="checkbox" class="tables-col-check" value="${escapeHtml(c.name)}" ${selected.has(c.name) ? "checked" : ""}>
          <span>${escapeHtml(label)}</span>
        </label>`;
    }).join("") || '<p class="text-muted" style="font-size:12.5px;padding:6px">Sin coincidencias.</p>';

    wrap.querySelectorAll(".tables-col-check").forEach((cb) => {
      cb.addEventListener("change", (e) => {
        if (e.target.checked) vs.tablesSelectedColumns.push(e.target.value);
        else vs.tablesSelectedColumns = vs.tablesSelectedColumns.filter((c) => c !== e.target.value);
      });
    });
  }

  el("tablesColumnSearch").addEventListener("input", (e) => renderTablesColumnChecklist(e.target.value));

  el("generateTablesBtn").addEventListener("click", async () => {
    const vs = currentVignetteState();
    if (!vs.summary) { alert('Aplica primero el mapeo en el paso "Mapeo de variables".'); return; }
    if (!vs.tablesSelectedColumns.length) { alert("Elige al menos una variable."); return; }
    try {
      const result = await postJson(
        `/api/vignette/${state.sessionId}/${state.activeExperimentId}/crosstab`,
        { outcome_columns: vs.tablesSelectedColumns }
      );
      vs.tablesResult = result;
      renderTablesResult(result);
    } catch (err) {
      el("tablesResultEmpty").hidden = false;
      el("tablesResultEmpty").textContent = err.message;
      el("tablesResult").hidden = true;
    }
  });

  function renderTablesResult(result) {
    el("tablesResultEmpty").hidden = true;
    el("tablesResult").hidden = false;
    el("tablesResult").innerHTML = result.tables.map((t) => renderCrosstabCard(t)).join("");
  }

  function renderCrosstabCard(t) {
    if (!t.n) {
      return `<div class="card"><h3>${escapeHtml(t.outcome_label)} × ${escapeHtml(t.group_label)}</h3>
        <p class="empty-state">Sin filas con ambos valores presentes.</p></div>`;
    }
    let summaryHtml = "";
    if (t.numeric_summary) {
      summaryHtml = '<div class="stat-grid" style="margin-bottom:16px">' + t.group_levels.map((level) => {
        const s = t.numeric_summary[level];
        return `<div class="stat-tile"><span class="stat-tile__label">${escapeHtml(level)} (n=${s.n})</span><span class="stat-tile__value">${fmt(s.mean, 2)}</span></div>`;
      }).join("") + `<div class="stat-tile"><span class="stat-tile__label">Total (n=${t.numeric_summary.__total__.n})</span><span class="stat-tile__value">${fmt(t.numeric_summary.__total__.mean, 2)}</span></div></div>`;
    }
    let tableHtml = '<div class="table-scroll"><table><thead><tr><th></th>' +
      t.group_levels.map((l) => `<th>${escapeHtml(l)}</th>`).join("") + "</tr></thead><tbody>";
    for (const row of t.row_levels) {
      tableHtml += `<tr><th>${escapeHtml(row)}</th>` + t.group_levels.map((level) => {
        const n = t.counts[row][level];
        const pct = t.percentages[row][level];
        return `<td>${fmt(pct, 1)}% <span class="text-muted">(${n})</span></td>`;
      }).join("") + "</tr>";
    }
    tableHtml += `<tr><th>Total</th>` + t.group_levels.map((l) => `<td><strong>${t.column_totals[l]}</strong></td>`).join("") + "</tr>";
    tableHtml += "</tbody></table></div>";

    return `<div class="card">
      <h3>${escapeHtml(t.outcome_label)} × ${escapeHtml(t.group_label)}</h3>
      ${summaryHtml}
      ${tableHtml}
    </div>`;
  }

  el("runBatteryBtn").addEventListener("click", async () => {
    const vs = currentVignetteState();
    if (!vs.summary) { alert('Aplica primero el mapeo en el paso "Mapeo de variables".'); return; }
    if (!vs.tablesSelectedColumns.length) { alert("Elige al menos una variable."); return; }
    try {
      const result = await postJson(
        `/api/vignette/${state.sessionId}/${state.activeExperimentId}/battery`,
        { outcome_columns: vs.tablesSelectedColumns }
      );
      vs.batteryResult = result;
      renderBatteryResult(result);
    } catch (err) {
      el("batteryResultEmpty").hidden = false;
      el("batteryResultEmpty").textContent = err.message;
      el("batteryResult").hidden = true;
    }
  });

  function renderBatteryResult(result) {
    el("batteryResultEmpty").hidden = true;
    el("batteryResult").hidden = false;

    let html = "";
    if (result.skipped.length) {
      html += `<div class="card">
        <h3>Variables omitidas</h3>
        <p class="text-secondary" style="font-size:12.5px;margin-bottom:8px">
          No se pudieron tratar como escala numérica (o no quedaron filas completas), así que no se han
          incluido en la estimación:
        </p>
        <div class="issue-list">
          ${result.skipped.map((s) => `<div class="issue-list__item"><strong>${escapeHtml(s.outcome_label)}</strong>: ${escapeHtml(s.reason)}</div>`).join("")}
        </div>
      </div>`;
    }

    html += result.results.map((r, i) => {
      const fitLine = `n=${r.n} · R²=${fmt(r.r_squared, 3)} · media=${fmt(r.outcome_mean, 2)}`;
      return `<div class="card">
        <div class="dotplot-toolbar">
          <h3 style="margin:0">${escapeHtml(r.outcome_label)}</h3>
          <span class="text-muted" style="font-size:12.5px">${fitLine}</span>
        </div>
        <div id="batteryDotplot-${i}" class="dotplot-wrap"></div>
        <div class="legend">
          <span class="legend__item"><span class="legend__swatch" style="background:var(--good)"></span>Significativo al 95%</span>
          <span class="legend__item"><span class="legend__swatch" style="background:var(--critical)"></span>No significativo</span>
          <span class="legend__item"><span class="legend__swatch" style="background:var(--text-muted)"></span>Nivel de referencia</span>
        </div>
        <div class="table-scroll" style="margin-top:14px">
          <table>
            <thead><tr><th>Atributo</th><th>Nivel</th><th>Referencia</th><th>Estimación</th><th>EE</th><th>IC 95%</th><th>p</th></tr></thead>
            <tbody>${coefTableRowsHtml(r.plot_rows)}</tbody>
          </table>
        </div>
      </div>`;
    }).join("");

    el("batteryResult").innerHTML = html;
    result.results.forEach((r, i) => {
      el(`batteryDotplot-${i}`).innerHTML = buildDotplotSvg(r.plot_rows);
    });
  }

  // ---------- Conjunto de respuesta múltiple ----------

  function renderMultiResponseGroupSelect() {
    const vs = currentVignetteState();
    const select = el("multiResponseGroupSelect");
    const attrs = vs.draft.attributes || [];
    select.innerHTML = '<option value="">(sin desglosar)</option>' +
      attrs.map((a) => `<option value="${escapeHtml(a.name)}" ${a.name === vs.multiResponseGroupAttribute ? "selected" : ""}>${escapeHtml(a.label || a.name)}</option>`).join("");
  }
  el("multiResponseGroupSelect").addEventListener("change", (e) => {
    currentVignetteState().multiResponseGroupAttribute = e.target.value;
  });

  function renderMultiResponseItems() {
    const vs = currentVignetteState();
    const wrap = el("multiResponseItemsWrap");
    wrap.innerHTML = vs.multiResponseItems.map((item, i) => `
      <div class="mapping-toolbar" style="margin-bottom:6px" data-mr-row="${i}">
        <label class="field" style="flex:1"><span>Columna</span>${columnSelectHtml(item.column, i)}</label>
        <label class="field" style="flex:1"><span>Etiqueta</span><input type="text" data-mr-label="${i}" value="${escapeHtml(item.label)}"></label>
        <button class="btn btn--icon btn--sm" data-mr-remove="${i}" title="Quitar" style="align-self:flex-end">&times;</button>
      </div>
    `).join("");

    wrap.querySelectorAll("select[data-mr-column]").forEach((sel) => {
      sel.addEventListener("change", (e) => {
        const i = Number(e.target.dataset.mrColumn);
        vs.multiResponseItems[i].column = e.target.value;
      });
    });
    wrap.querySelectorAll("input[data-mr-label]").forEach((input) => {
      input.addEventListener("change", (e) => {
        const i = Number(e.target.dataset.mrLabel);
        vs.multiResponseItems[i].label = e.target.value;
      });
    });
    wrap.querySelectorAll("button[data-mr-remove]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const i = Number(e.target.dataset.mrRemove);
        vs.multiResponseItems.splice(i, 1);
        if (!vs.multiResponseItems.length) vs.multiResponseItems.push({ column: "", label: "" });
        renderMultiResponseItems();
      });
    });
  }

  function columnSelectHtml(selected, index) {
    return `<select data-mr-column="${index}">${columnOptionsHtml(selected)}</select>`;
  }

  el("addMultiResponseItemBtn").addEventListener("click", () => {
    currentVignetteState().multiResponseItems.push({ column: "", label: "" });
    renderMultiResponseItems();
  });

  el("runMultiResponseBtn").addEventListener("click", async () => {
    const vs = currentVignetteState();
    if (!vs.summary) { alert('Aplica primero el mapeo en el paso "Mapeo de variables".'); return; }
    const items = vs.multiResponseItems.filter((it) => it.column);
    if (!items.length) { alert("Añade al menos una columna."); return; }
    try {
      const result = await postJson(
        `/api/vignette/${state.sessionId}/${state.activeExperimentId}/multi-response`,
        { items: items.map((it) => ({ column: it.column, label: it.label || it.column })), group_attribute: vs.multiResponseGroupAttribute || null }
      );
      vs.multiResponseResult = result;
      renderMultiResponseResult(result);
    } catch (err) {
      el("multiResponseResult").innerHTML = `<div class="issue-list__item">${escapeHtml(err.message)}</div>`;
    }
  });

  function renderMultiResponseTable(title, rows, baseN) {
    let html = `<h4 style="font-size:13px;margin-bottom:8px">${escapeHtml(title)} <span class="text-muted" style="font-weight:400">(base n=${baseN})</span></h4>`;
    html += '<div class="table-scroll"><table><thead><tr><th>Opción</th><th>n</th><th>% de casos</th></tr></thead><tbody>';
    for (const row of rows) {
      html += `<tr><td>${escapeHtml(row.label)}</td><td>${row.n}</td><td>${row.pct_of_cases === null ? "—" : fmt(row.pct_of_cases, 1) + "%"}</td></tr>`;
    }
    html += "</tbody></table></div>";
    return html;
  }

  function renderMultiResponseResult(result) {
    let html = renderMultiResponseTable("Global", result.overall, result.base_n);
    if (result.by_group) {
      for (const [level, group] of Object.entries(result.by_group)) {
        html += `<div style="margin-top:18px">${renderMultiResponseTable(`${result.group_label}: ${level}`, group.rows, group.base_n)}</div>`;
      }
    }
    el("multiResponseResult").innerHTML = html;
  }

  // ---------- Recodificación de variables ----------

  el("openRecodeBtn").addEventListener("click", () => {
    openModal(`
      <div class="modal-header"><h3>Recodificar variable</h3><button class="modal-close" aria-label="Cerrar">&times;</button></div>
      <div class="modal-body">
        <p class="text-secondary" style="font-size:12.5px;margin-bottom:12px">
          Crea una nueva columna dicotómica a partir de una variable numérica (p. ej. "grave" = Sí si la
          gravedad es ≥ 8, si no No). La nueva columna queda disponible en toda la sesión.
        </p>
        <label class="field"><span>Variable de origen</span><select id="recodeSourceColumn">${columnOptionsHtml("")}</select></label>
        <div class="mapping-toolbar" style="margin-top:10px">
          <label class="field"><span>Operador</span>
            <select id="recodeOperator">
              <option value=">=">&ge;</option>
              <option value=">">&gt;</option>
              <option value="<=">&le;</option>
              <option value="<">&lt;</option>
              <option value="==">=</option>
            </select>
          </label>
          <label class="field"><span>Umbral</span><input id="recodeThreshold" type="number" step="any" value="1"></label>
        </div>
        <div class="mapping-toolbar" style="margin-top:10px">
          <label class="field"><span>Etiqueta si se cumple</span><input id="recodeTrueLabel" type="text" value="Sí"></label>
          <label class="field"><span>Etiqueta si no se cumple</span><input id="recodeFalseLabel" type="text" value="No"></label>
        </div>
        <label class="field" style="margin-top:10px"><span>Nombre de la nueva columna</span><input id="recodeNewColumn" type="text" placeholder="gravedad_bin"></label>
        <label class="field" style="margin-top:10px"><span>Etiqueta descriptiva (opcional)</span><input id="recodeNewLabel" type="text"></label>
        <div id="recodeError" class="modal-error" hidden></div>
      </div>
      <div class="modal-footer">
        <button class="btn btn--ghost modal-close">Cancelar</button>
        <button id="recodeSave" class="btn btn--primary">Crear</button>
      </div>
    `);
    el("recodeSave").addEventListener("click", async () => {
      const payload = {
        source_column: el("recodeSourceColumn").value,
        new_column: el("recodeNewColumn").value.trim(),
        new_label: el("recodeNewLabel").value.trim(),
        operator: el("recodeOperator").value,
        threshold: Number(el("recodeThreshold").value),
        true_label: el("recodeTrueLabel").value.trim() || "Sí",
        false_label: el("recodeFalseLabel").value.trim() || "No",
      };
      if (!payload.source_column || !payload.new_column) {
        el("recodeError").hidden = false;
        el("recodeError").textContent = "Indica la variable de origen y el nombre de la nueva columna.";
        return;
      }
      try {
        const result = await postJson(`/api/columns/${state.sessionId}/recode`, payload);
        state.columns = result.columns;
        closeModal();
        renderTablesColumnChecklist(el("tablesColumnSearch").value);
      } catch (err) {
        el("recodeError").hidden = false;
        el("recodeError").textContent = err.message;
      }
    });
  });

  // =====================================================================
  // Conjunto de tipo "elección con diseño externo" · Paso 1 · Mapeo
  // =====================================================================

  function blankDesignState() {
    return {
      designFilename: null,
      designNRows: 0,
      designColumns: [],
      taskColumn: null,
      profileColumn: null,
      tasks: [],
      profiles: [],
      remainingColumns: [],
      joinKeyCandidates: [],
      draft: {
        respondent_id: null,
        choice_columns: {},
        choice_value_map: {},
        columnRoles: {},   // design_column -> "attribute" | "joinkey"
        attributes: [],    // [{name, label, design_column}]
        joinKeys: {},       // design_column -> {respondent_column, value_map, default_design_value}
      },
      unmatchedChoiceValues: [],
      choiceValueOptions: {},
      joinKeyValueCache: {},   // design_column -> design_values[]
      reshapeSummary: null,
      reshapePreview: null,
      amceResult: null,
      amceMethod: "ols",
    };
  }

  async function ensureDesignState(id) {
    if (state.design[id]) return;
    state.design[id] = blankDesignState();
  }

  function currentDesignState() {
    return state.design[state.activeExperimentId];
  }

  function renderDesignMappingStep() {
    const ds = currentDesignState();

    el("designFileInfo").hidden = !ds.designFilename;
    if (ds.designFilename) {
      el("designFileName").textContent = ds.designFilename;
      el("designFileRows").textContent = ds.designNRows.toLocaleString("es-ES");
    }

    const hasDesign = ds.designColumns.length > 0;
    el("designTaskProfileCard").hidden = !hasDesign;
    if (hasDesign) {
      const colOptions = (selected) => ds.designColumns.map((c) => `<option value="${escapeHtml(c)}" ${c === selected ? "selected" : ""}>${escapeHtml(c)}</option>`).join("");
      el("designTaskColumnSelect").innerHTML = colOptions(ds.taskColumn);
      el("designProfileColumnSelect").innerHTML = colOptions(ds.profileColumn);
    }

    const hasStructure = ds.tasks.length > 0;
    el("designStructureCard").hidden = !hasStructure;
    el("designColumnsCard").hidden = !hasStructure;
    if (hasStructure) {
      el("designRespondentIdSelect").innerHTML = '<option value="">(usar número de fila)</option>' + columnOptionsHtml(ds.draft.respondent_id).replace('<option value="">—</option>', "");
      el("designRespondentIdSelect").value = ds.draft.respondent_id || "";
      renderDesignChoiceGrid();
      renderDesignColumnsList();
    }
    updateSidebarSummary();
  }

  el("designRespondentIdSelect").addEventListener("change", (e) => {
    currentDesignState().draft.respondent_id = e.target.value || null;
  });

  // ---------- Subida del fichero de diseño ----------

  const designDropzone = el("designDropzone");
  const designFileInput = el("designFileInput");

  ["dragenter", "dragover"].forEach((evtName) =>
    designDropzone.addEventListener(evtName, (e) => { e.preventDefault(); designDropzone.classList.add("is-dragover"); })
  );
  ["dragleave", "drop"].forEach((evtName) =>
    designDropzone.addEventListener(evtName, (e) => { e.preventDefault(); designDropzone.classList.remove("is-dragover"); })
  );
  designDropzone.addEventListener("drop", (e) => {
    const file = e.dataTransfer.files[0];
    if (file) handleDesignUpload(file);
  });
  designFileInput.addEventListener("change", () => {
    if (designFileInput.files[0]) handleDesignUpload(designFileInput.files[0]);
  });

  function setDesignUploadStatus(message, type) {
    const statusEl = el("designUploadStatus");
    statusEl.hidden = !message;
    statusEl.textContent = message || "";
    statusEl.className = "upload-status" + (type ? ` is-${type}` : "");
  }

  async function handleDesignUpload(file) {
    setDesignUploadStatus("Procesando archivo…", "loading");
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await fetch(`/api/design/${state.sessionId}/${state.activeExperimentId}/upload`, { method: "POST", body: formData });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Error al procesar el archivo.");
      setDesignUploadStatus("", null);

      const ds = currentDesignState();
      ds.designFilename = data.filename;
      ds.designNRows = data.n_rows;
      ds.designColumns = data.design_columns;
      ds.taskColumn = data.design_task_column;
      ds.profileColumn = data.design_profile_column;
      ds.tasks = [];
      ds.profiles = [];
      ds.reshapeSummary = null;
      ds.reshapePreview = null;
      ds.amceResult = null;
      if (state.experiments[state.activeExperimentId]) state.experiments[state.activeExperimentId].has_design_file = true;
      renderDesignMappingStep();
    } catch (err) {
      setDesignUploadStatus(err.message, "error");
    }
  }

  // ---------- Detección de tarea/perfil/elección/claves de cruce ----------

  el("designDetectBtn").addEventListener("click", detectDesignMapping);

  async function detectDesignMapping() {
    const ds = currentDesignState();
    const taskCol = el("designTaskColumnSelect").value;
    const profileCol = el("designProfileColumnSelect").value;
    if (!taskCol || !profileCol) { alert("Elige la columna de tarea y la de perfil."); return; }
    if (taskCol === profileCol) { alert("La columna de tarea y la de perfil no pueden ser la misma."); return; }
    ds.taskColumn = taskCol;
    ds.profileColumn = profileCol;

    const params = new URLSearchParams({ task_column: taskCol, profile_column: profileCol });
    const suggestion = await getJson(`/api/design/${state.sessionId}/${state.activeExperimentId}/suggest?${params}`);

    ds.tasks = suggestion.tasks;
    ds.profiles = suggestion.profiles;
    ds.remainingColumns = suggestion.remaining_columns;
    ds.joinKeyCandidates = suggestion.join_key_candidates;
    ds.unmatchedChoiceValues = suggestion.unmatched_choice_values;

    ds.draft.choice_columns = suggestion.choice_columns;
    ds.draft.choice_value_map = suggestion.choice_value_map;
    ds.draft.columnRoles = {};
    ds.draft.joinKeys = {};
    ds.draft.attributes = [];
    ds.joinKeyValueCache = {};

    const candidateByCol = {};
    for (const jk of suggestion.join_key_candidates) candidateByCol[jk.design_column] = jk;

    for (const col of suggestion.remaining_columns) {
      const candidate = candidateByCol[col];
      if (candidate) {
        ds.draft.columnRoles[col] = "joinkey";
        ds.draft.joinKeys[col] = {
          respondent_column: candidate.respondent_column || "",
          value_map: { ...candidate.value_map },
          default_design_value: candidate.default_design_value || "",
        };
        ds.joinKeyValueCache[col] = candidate.design_values;
      } else {
        ds.draft.columnRoles[col] = "attribute";
        ds.draft.attributes.push({ name: col, label: col, design_column: col });
      }
    }

    renderDesignMappingStep();
  }

  // ---------- Columna de elección por tarea ----------

  async function designChoiceValueOptionsFor(ds, columns) {
    const uniqueCols = [...new Set(columns.filter(Boolean))];
    const missing = uniqueCols.filter((c) => !ds.choiceValueOptions[c]);
    await Promise.all(missing.map(async (col) => {
      const data = await getJson(`/api/columns/${state.sessionId}/values?column=${encodeURIComponent(col)}&limit=60`);
      ds.choiceValueOptions[col] = data.values.map((v) => v.value);
    }));
    const merged = new Set();
    for (const col of uniqueCols) (ds.choiceValueOptions[col] || []).forEach((v) => merged.add(v));
    return [...merged];
  }

  async function renderDesignChoiceGrid() {
    const ds = currentDesignState();
    const wrap = el("designChoiceGridWrap");
    if (!ds.tasks.length) { wrap.innerHTML = ""; return; }

    const observedValues = await designChoiceValueOptionsFor(ds, Object.values(ds.draft.choice_columns));

    let html = '<table class="mapping-grid"><thead><tr><th>Tarea</th><th>Columna de elección</th></tr></thead><tbody>';
    for (const task of ds.tasks) {
      const current = ds.draft.choice_columns[task] || "";
      const cls = current ? "is-matched" : "is-unmatched";
      html += `<tr><th>${escapeHtml(task)}</th><td><select class="${cls}" data-task="${escapeHtml(task)}">${columnOptionsHtml(current)}</select></td></tr>`;
    }
    html += "</tbody></table>";
    html += '<div style="padding:14px"><p class="text-secondary" style="font-size:12.5px;margin-bottom:10px">¿Con qué valor se codifica cada perfil en la columna de elección?</p>';
    for (const p of ds.profiles) {
      const raw = Object.entries(ds.draft.choice_value_map).find(([, v]) => v === p);
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
    if (ds.unmatchedChoiceValues.length) {
      html += `<p class="text-muted" style="font-size:12px;margin-top:10px">Valores observados sin asignar a ningún perfil: ${ds.unmatchedChoiceValues.map(escapeHtml).join(", ")}</p>`;
    }
    html += "</div>";
    wrap.innerHTML = html;

    wrap.querySelectorAll("select[data-task]").forEach((sel) => {
      sel.addEventListener("change", (e) => {
        ds.draft.choice_columns[e.target.dataset.task] = e.target.value || undefined;
        if (!e.target.value) delete ds.draft.choice_columns[e.target.dataset.task];
        e.target.className = e.target.value ? "is-matched" : "is-unmatched";
        renderDesignChoiceGrid();
      });
    });
    wrap.querySelectorAll("select[data-profile-value]").forEach((sel) => {
      sel.addEventListener("change", (e) => {
        const profile = e.target.dataset.profileValue;
        for (const k of Object.keys(ds.draft.choice_value_map)) {
          if (ds.draft.choice_value_map[k] === profile) delete ds.draft.choice_value_map[k];
        }
        if (e.target.value) ds.draft.choice_value_map[e.target.value] = profile;
      });
    });
  }

  // ---------- Atributos y claves de cruce ----------

  function renderDesignColumnsList() {
    const ds = currentDesignState();
    const wrap = el("designColumnsList");
    if (!ds.remainingColumns.length) {
      wrap.innerHTML = '<p class="empty-state">El diseño no tiene columnas además de la tarea y el perfil.</p>';
      return;
    }
    wrap.innerHTML = ds.remainingColumns.map((col) => {
      const role = ds.draft.columnRoles[col] || "attribute";
      let inner;
      if (role === "attribute") {
        const attr = ds.draft.attributes.find((a) => a.design_column === col) || { label: col };
        inner = `<label class="field" style="margin-top:8px"><span>Etiqueta</span><input type="text" data-attr-label="${escapeHtml(col)}" value="${escapeHtml(attr.label)}"></label>`;
      } else {
        const jk = ds.draft.joinKeys[col] || { respondent_column: "", value_map: {}, default_design_value: "" };
        inner = `
          <div class="mapping-toolbar" style="margin-top:8px">
            <label class="field"><span>Columna en las respuestas</span>
              <select data-jk-respondent="${escapeHtml(col)}">${columnOptionsHtml(jk.respondent_column)}</select>
            </label>
          </div>
          <div data-jk-values="${escapeHtml(col)}"></div>
        `;
      }
      return `
        <div class="card" style="margin-bottom:12px;padding:14px 16px">
          <div class="mapping-toolbar" style="margin-bottom:0;align-items:center">
            <strong>${escapeHtml(col)}</strong>
            <select data-role="${escapeHtml(col)}" style="margin-left:auto">
              <option value="attribute" ${role === "attribute" ? "selected" : ""}>Atributo (entra en la estimación)</option>
              <option value="joinkey" ${role === "joinkey" ? "selected" : ""}>Clave de cruce</option>
            </select>
          </div>
          ${inner}
        </div>
      `;
    }).join("");

    wrap.querySelectorAll("select[data-role]").forEach((sel) => {
      sel.addEventListener("change", (e) => {
        const col = e.target.dataset.role;
        const role = e.target.value;
        ds.draft.columnRoles[col] = role;
        if (role === "attribute") {
          delete ds.draft.joinKeys[col];
          if (!ds.draft.attributes.some((a) => a.design_column === col)) {
            ds.draft.attributes.push({ name: col, label: col, design_column: col });
          }
        } else {
          ds.draft.attributes = ds.draft.attributes.filter((a) => a.design_column !== col);
          if (!ds.draft.joinKeys[col]) ds.draft.joinKeys[col] = { respondent_column: "", value_map: {}, default_design_value: "" };
        }
        renderDesignColumnsList();
      });
    });

    wrap.querySelectorAll("input[data-attr-label]").forEach((input) => {
      input.addEventListener("change", (e) => {
        const col = e.target.dataset.attrLabel;
        const attr = ds.draft.attributes.find((a) => a.design_column === col);
        if (attr) attr.label = e.target.value || col;
      });
    });

    wrap.querySelectorAll("select[data-jk-respondent]").forEach((sel) => {
      sel.addEventListener("change", async (e) => {
        const col = e.target.dataset.jkRespondent;
        const respondentCol = e.target.value;
        ds.draft.joinKeys[col].respondent_column = respondentCol;
        if (respondentCol) {
          const params = new URLSearchParams({ respondent_column: respondentCol, design_column: col });
          const suggestion = await getJson(`/api/design/${state.sessionId}/${state.activeExperimentId}/value-map-suggestion?${params}`);
          ds.draft.joinKeys[col].value_map = suggestion.value_map;
          ds.draft.joinKeys[col].default_design_value = suggestion.default_design_value || "";
          ds.joinKeyValueCache[col] = suggestion.design_values;
        }
        renderJoinKeyValueTable(col);
      });
    });

    for (const col of ds.remainingColumns) {
      if ((ds.draft.columnRoles[col] || "attribute") === "joinkey") renderJoinKeyValueTable(col);
    }
  }

  async function renderJoinKeyValueTable(designCol) {
    const ds = currentDesignState();
    const container = document.querySelector(`[data-jk-values="${CSS.escape(designCol)}"]`);
    if (!container) return;
    const jk = ds.draft.joinKeys[designCol];
    if (!jk.respondent_column) {
      container.innerHTML = '<p class="text-muted" style="font-size:12px">Elige antes la columna de respuestas.</p>';
      return;
    }

    let designValues = ds.joinKeyValueCache[designCol];
    if (!designValues) {
      const data = await getJson(`/api/design/${state.sessionId}/${state.activeExperimentId}/design-values?column=${encodeURIComponent(designCol)}`);
      designValues = data.design_values;
      ds.joinKeyValueCache[designCol] = designValues;
    }
    const observedData = await getJson(`/api/columns/${state.sessionId}/values?column=${encodeURIComponent(jk.respondent_column)}&limit=60`);
    const observedValues = observedData.values.map((v) => v.value);

    const designOptions = (selected) => ['<option value="">(sin traducir)</option>', ...designValues.map((v) => `<option value="${escapeHtml(v)}" ${v === selected ? "selected" : ""}>${escapeHtml(v)}</option>`)].join("");

    let html = `<label class="field" style="margin-top:10px"><span>Valor por defecto (para lo que no se traduzca)</span><select data-jk-default="${escapeHtml(designCol)}">${designOptions(jk.default_design_value)}</select></label>`;
    html += '<table class="mapping-grid" style="margin-top:10px"><thead><tr><th>Valor en respuestas</th><th>Valor en el diseño</th></tr></thead><tbody>';
    for (const v of observedValues) {
      const mapped = jk.value_map[v] || "";
      html += `<tr><td>${escapeHtml(v)}</td><td><select data-jk-value="${escapeHtml(designCol)}" data-jk-observed="${escapeHtml(v)}">${designOptions(mapped)}</select></td></tr>`;
    }
    html += "</tbody></table>";
    container.innerHTML = html;

    container.querySelector("select[data-jk-default]").addEventListener("change", (e) => {
      jk.default_design_value = e.target.value;
    });
    container.querySelectorAll("select[data-jk-value]").forEach((sel) => {
      sel.addEventListener("change", (e) => {
        const observed = e.target.dataset.jkObserved;
        if (e.target.value) jk.value_map[observed] = e.target.value;
        else delete jk.value_map[observed];
      });
    });
  }

  // ---------- Aplicar mapeo ----------

  el("applyDesignMappingBtn").addEventListener("click", applyDesignMapping);

  async function applyDesignMapping() {
    const id = state.activeExperimentId;
    const ds = currentDesignState();
    const d = ds.draft;

    if (!ds.tasks.length) { alert('Pulsa "Detectar mapeo" primero.'); return; }
    if (!d.attributes.length) { alert("Marca al menos una columna del diseño como atributo."); return; }

    const joinKeys = [];
    for (const col of ds.remainingColumns) {
      if ((d.columnRoles[col] || "attribute") !== "joinkey") continue;
      const jk = d.joinKeys[col];
      if (!jk || !jk.respondent_column) {
        alert(`Falta elegir la columna de respuestas para la clave de cruce "${col}".`);
        return;
      }
      joinKeys.push({
        design_column: col,
        respondent_column: jk.respondent_column,
        value_map: jk.value_map,
        default_design_value: jk.default_design_value || null,
      });
    }

    const payload = {
      respondent_id: d.respondent_id || null,
      tasks: ds.tasks,
      profiles: ds.profiles,
      design_task_column: ds.taskColumn,
      design_profile_column: ds.profileColumn,
      choice_columns: d.choice_columns,
      choice_value_map: d.choice_value_map,
      join_keys: joinKeys,
      attributes: d.attributes.map((a) => ({ name: a.name, label: a.label || a.name, design_column: a.design_column })),
    };

    const issuesEl = el("designMappingIssues");
    issuesEl.innerHTML = "";
    try {
      const result = await postJson(`/api/design/${state.sessionId}/${id}/apply`, payload);
      issuesEl.innerHTML = result.issues.map((i) => `<div class="issue-list__item${i.severity === "info" ? " issue-list__item--info" : ""}">${escapeHtml(i.text)}</div>`).join("");
      ds.reshapeSummary = result.summary;
      ds.reshapePreview = null;
      ds.amceResult = null;
      state.experiments[id].is_mapped = true;
      markStepDone("mapping");
      updateSidebarSummary();
      ds.reshapePreview = await getJson(`/api/reshape/${state.sessionId}/${id}/preview?limit=50`);
      renderReshapeStepForActive();
      resetAmceStep();
      goToStep("reshape");
    } catch (err) {
      issuesEl.innerHTML = `<div class="issue-list__item">${escapeHtml(err.message)}</div>`;
    }
  }

  // =====================================================================
  // Paso 3 · Estimación (común a elección y viñeta)
  // =====================================================================

  // El conjunto con diseño externo reutiliza tal cual el endpoint y el
  // formulario de AMCE del conjoint normal (mismo formato de fichero largo);
  // solo la viñeta necesita un tratamiento distinto (sin método OLS/clogit,
  // sin conjuntos de elección).
  function isChoiceLikeKind(kind) {
    return kind === "conjoint" || kind === "conjoint_design";
  }

  function currentAmceCapableState() {
    const exp = activeExperiment();
    if (exp.kind === "conjoint") return currentConjointState();
    if (exp.kind === "conjoint_design") return currentDesignState();
    return currentVignetteState();
  }

  function resetAmceStep() {
    currentAmceCapableState().amceResult = null;
    renderAmceStepForActive();
  }

  function renderAmceStepForActive() {
    const exp = activeExperiment();
    const cs = currentAmceCapableState();
    const attributes = cs.draft.attributes;
    const mapped = isChoiceLikeKind(exp.kind) ? !!cs.reshapeSummary : !!cs.summary;

    if (!mapped || !attributes.length) {
      el("amceEmpty").hidden = false;
      el("amceEmpty").textContent = "Completa el paso anterior antes de estimar el modelo.";
      el("amceContent").hidden = true;
      return;
    }
    // Una viñeta puede no tener una única variable de resultado (una
    // batería de preguntas en su lugar): no hay nada que estimar aquí, hay
    // que ir al paso "Tablas comparativas" y usar "Estimar batería".
    if (!isChoiceLikeKind(exp.kind) && !cs.draft.outcome_column) {
      el("amceEmpty").hidden = false;
      el("amceEmpty").textContent = 'Este conjunto no tiene una única variable de resultado mapeada. Ve al paso "4 · Tablas comparativas" y usa "Estimar batería" para estimar cada variable de la batería.';
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

    const existingResult = cs.amceResult;
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
    const cs = currentAmceCapableState();
    const checked = Array.from(el("amceAttributes").querySelectorAll(".amce-attr-check:checked")).map((c) => c.value);
    let levelsByAttr = {};
    if (isChoiceLikeKind(exp.kind)) {
      const coverage = (cs.reshapeSummary && cs.reshapeSummary.attribute_coverage) || {};
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
    currentAmceCapableState().amceMethod = btn.dataset.method;
  });

  el("runAmceBtn").addEventListener("click", runAmce);

  async function runAmce() {
    const exp = activeExperiment();
    const cs = currentAmceCapableState();
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
      if (isChoiceLikeKind(exp.kind)) {
        result = await postJson(`/api/amce/${state.sessionId}/${exp.id}`, { method: cs.amceMethod, attributes, baselines });
      } else {
        result = await postJson(`/api/vignette/${state.sessionId}/${exp.id}/estimate`, { attributes, baselines });
      }
      cs.amceResult = result;
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
    el("amceResultTitle").textContent = isChoiceLikeKind(exp.kind) ? "Efecto Marginal Medio (AMCE)" : "Efecto estimado por nivel";

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
    tbody.innerHTML = coefTableRowsHtml(result.plot_rows);
  }

  // Extraído de renderAmceResult() para reutilizarlo en la tabla de
  // coeficientes de cada variable de la estimación por batería.
  function coefTableRowsHtml(plotRows) {
    return plotRows.map((row) => {
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
    el("dotplotWrap").innerHTML = buildDotplotSvg(plotRows);
  }

  // Extraído de renderDotplot() para poder dibujar más de un dot plot a la
  // vez (uno por variable de resultado en la estimación por batería) sin
  // depender del contenedor único #dotplotWrap.
  function buildDotplotSvg(plotRows) {
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
      const sigCls = row.is_baseline ? "" : row.significant_at_05 ? " is-sig" : " is-nonsig";
      if (!row.is_baseline && row.ci_low !== null) {
        const x1 = xScale(row.ci_low);
        const x2 = xScale(row.ci_high);
        svg += `<line class="dotplot__ci${sigCls}" x1="${x1}" y1="${row.y}" x2="${x2}" y2="${row.y}"></line>`;
      }
      const pointCls = row.is_baseline ? "dotplot__point is-baseline" : `dotplot__point${sigCls}`;
      svg += `<circle class="${pointCls}" cx="${cx}" cy="${row.y}" r="4.5"></circle>`;
    }

    svg += "</svg>";
    return svg;
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
      good: cssVar("--good"),
      critical: cssVar("--critical"),
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
    const sigColor = (n) => (n.classList.contains("is-sig") ? palette.good : n.classList.contains("is-nonsig") ? palette.critical : palette.textMuted);
    clone.querySelectorAll(".dotplot__ci").forEach((n) => {
      n.setAttribute("stroke", sigColor(n));
      n.setAttribute("stroke-width", "1.6");
    });
    clone.querySelectorAll(".dotplot__point").forEach((n) => {
      n.setAttribute("fill", n.classList.contains("is-baseline") ? palette.textMuted : sigColor(n));
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
    const result = currentAmceCapableState().amceResult;
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

  // ---------- Exportación genérica de tablas ya renderizadas (imagen/Excel) ----------
  function extractTableRows(tableEl) {
    const headers = Array.from(tableEl.querySelectorAll("thead th")).map((th) => th.textContent.trim());
    return Array.from(tableEl.querySelectorAll("tbody tr")).map((tr) => {
      const cells = Array.from(tr.querySelectorAll("td")).map((td) => td.textContent.trim());
      const row = {};
      headers.forEach((h, i) => { row[h] = cells[i] ?? ""; });
      return row;
    });
  }

  // Igual que buildExportableSvg() para el dot plot: en vez de envolver el
  // <table> del DOM en un <foreignObject> (que Chromium marca como "tainted"
  // al rasterizarlo a canvas, aunque todo el contenido sea del mismo origen,
  // y hace fallar canvas.toBlob()), reconstruimos la tabla con primitivas
  // SVG nativas (<text>/<line>), igual que el dot plot dibuja puntos y ejes.
  function buildExportableTableSvg(tableEl) {
    const svgNS = "http://www.w3.org/2000/svg";
    const fontFamily = "system-ui, -apple-system, 'Segoe UI', sans-serif";
    const palette = {
      textPrimary: cssVar("--text-primary"),
      textMuted: cssVar("--text-muted"),
      good: cssVar("--good"),
      gridline: cssVar("--gridline"),
      baseline: cssVar("--baseline"),
      surfaceRaised: cssVar("--surface-raised"),
    };

    const headerCells = Array.from(tableEl.querySelectorAll("thead th")).map((th) => th.textContent.trim());
    const bodyRows = Array.from(tableEl.querySelectorAll("tbody tr")).map((tr) =>
      Array.from(tr.querySelectorAll("td")).map((td) => ({
        text: td.textContent.trim(),
        significant: td.classList.contains("text-significant"),
        muted: td.classList.contains("text-muted"),
      }))
    );
    const nCols = headerCells.length;
    const padX = 10;

    const measureCanvas = document.createElement("canvas");
    const mctx = measureCanvas.getContext("2d");
    const colWidths = new Array(nCols).fill(0);
    headerCells.forEach((text, i) => {
      mctx.font = `600 11.5px ${fontFamily}`;
      colWidths[i] = Math.max(colWidths[i], mctx.measureText(text.toUpperCase()).width);
    });
    bodyRows.forEach((row) => {
      row.forEach((cell, i) => {
        mctx.font = `${cell.significant ? "600" : "400"} 13.5px ${fontFamily}`;
        colWidths[i] = Math.max(colWidths[i] || 0, mctx.measureText(cell.text).width);
      });
    });

    const colX = [];
    let x = 0;
    for (let i = 0; i < nCols; i++) {
      colX.push(x);
      x += colWidths[i] + padX * 2;
    }
    const width = Math.ceil(x);
    const headerHeight = 34;
    const rowHeight = 32;
    const height = headerHeight + bodyRows.length * rowHeight;

    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("xmlns", svgNS);
    svg.setAttribute("width", String(width));
    svg.setAttribute("height", String(height));
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("font-family", fontFamily);

    const bg = document.createElementNS(svgNS, "rect");
    bg.setAttribute("width", String(width));
    bg.setAttribute("height", String(height));
    bg.setAttribute("fill", palette.surfaceRaised);
    svg.appendChild(bg);

    function addText(text, colIndex, cy, opts) {
      const t = document.createElementNS(svgNS, "text");
      const alignRight = colIndex > 0;
      const tx = alignRight ? colX[colIndex] + colWidths[colIndex] + padX : colX[colIndex] + padX;
      t.setAttribute("x", String(tx));
      t.setAttribute("y", String(cy));
      t.setAttribute("text-anchor", alignRight ? "end" : "start");
      t.setAttribute("font-size", opts.fontSize || "13.5");
      t.setAttribute("font-weight", opts.bold ? "600" : "400");
      t.setAttribute("fill", opts.fill || palette.textPrimary);
      t.textContent = opts.uppercase ? text.toUpperCase() : text;
      svg.appendChild(t);
    }

    headerCells.forEach((text, i) =>
      addText(text, i, headerHeight - 12, { fontSize: "11.5", bold: true, fill: palette.textMuted, uppercase: true })
    );
    const headerLine = document.createElementNS(svgNS, "line");
    headerLine.setAttribute("x1", "0");
    headerLine.setAttribute("x2", String(width));
    headerLine.setAttribute("y1", String(headerHeight));
    headerLine.setAttribute("y2", String(headerHeight));
    headerLine.setAttribute("stroke", palette.baseline);
    svg.appendChild(headerLine);

    bodyRows.forEach((row, ri) => {
      const rowY = headerHeight + ri * rowHeight;
      const cy = rowY + rowHeight / 2 + 5;
      row.forEach((cell, ci) => {
        const fill = cell.significant ? palette.good : cell.muted ? palette.textMuted : palette.textPrimary;
        addText(cell.text, ci, cy, { bold: cell.significant, fill });
      });
      if (ri < bodyRows.length - 1) {
        const line = document.createElementNS(svgNS, "line");
        const ly = rowY + rowHeight;
        line.setAttribute("x1", "0");
        line.setAttribute("x2", String(width));
        line.setAttribute("y1", String(ly));
        line.setAttribute("y2", String(ly));
        line.setAttribute("stroke", palette.gridline);
        svg.appendChild(line);
      }
    });

    return { svg, width, height };
  }

  el("exportTablePngBtn").addEventListener("click", () => {
    const tableEl = el("amceCoefTable");
    if (!tableEl.querySelector("tbody tr")) return;
    const { svg, width, height } = buildExportableTableSvg(tableEl);
    const serialized = new XMLSerializer().serializeToString(svg);
    const svgBlob = new Blob([serialized], { type: "image/svg+xml" });
    const url = URL.createObjectURL(svgBlob);
    const img = new Image();
    img.onload = () => {
      const scale = 2;
      const canvas = document.createElement("canvas");
      canvas.width = width * scale;
      canvas.height = height * scale;
      const ctx = canvas.getContext("2d");
      ctx.scale(scale, scale);
      ctx.drawImage(img, 0, 0);
      URL.revokeObjectURL(url);
      canvas.toBlob((blob) => downloadBlob(blob, "amce_coeficientes.png"));
    };
    img.src = url;
  });

  el("exportTableXlsxBtn").addEventListener("click", async () => {
    const tableEl = el("amceCoefTable");
    const rows = extractTableRows(tableEl);
    if (!rows.length) return;
    try {
      const res = await fetch("/api/export/table", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rows, filename: "amce_coeficientes", format: "xlsx" }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "No se pudo exportar la tabla.");
      }
      const blob = await res.blob();
      downloadBlob(blob, "amce_coeficientes.xlsx");
    } catch (err) {
      alert(err.message);
    }
  });
})();
