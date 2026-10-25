/*
 * Live view of Jarvis's knowledge graph: loads a snapshot, follows the event stream (SSE) and
 * draws it with force-graph. Everything that comes from the database is text somebody said out
 * loud, so it only reaches the page through textContent or escapeHtml.
 */
(function () {
  "use strict";

  var TYPES = [
    "persona",
    "lugar",
    "proyecto",
    "dispositivo",
    "preferencia",
    "tarea",
    "evento",
    "concepto",
  ];
  var TYPE_LABELS = {
    persona: "Personas",
    lugar: "Lugares",
    proyecto: "Proyectos",
    dispositivo: "Dispositivos",
    preferencia: "Preferencias",
    tarea: "Tareas",
    evento: "Eventos",
    concepto: "Conceptos",
  };
  var ROOT_KEY = "usuario";
  var HALO_MS = 3000;
  var FLUSH_DELAY_MS = 80;
  var RECONNECT_DELAY_MS = 5000;
  var UNAVAILABLE_RETRY_MS = 10000;
  var PAGE_SIZE = 1000;
  var PLAY_STEP_MS = 350;
  var PREFS_KEY = "memoria_preferences";

  var GraphState = window.GraphState;
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  var els = {
    graph: document.getElementById("graph"),
    status: document.getElementById("status"),
    counts: document.getElementById("counts"),
    empty: document.getElementById("empty"),
    panel: document.getElementById("controls"),
    search: document.getElementById("search"),
    searchResult: document.getElementById("search-result"),
    types: document.getElementById("types"),
    showExpired: document.getElementById("show-expired"),
    fit: document.getElementById("fit"),
    historyToggle: document.getElementById("history-toggle"),
    detail: document.getElementById("detail"),
    historyBar: document.getElementById("history-bar"),
    play: document.getElementById("play"),
    timeline: document.getElementById("timeline"),
    timelineLabel: document.getElementById("timeline-label"),
    backToLive: document.getElementById("back-to-live"),
  };

  var colors = {};
  var prefs = loadPrefs();

  var graphId = null;
  var liveState = GraphState.createState();
  var cache = GraphState.createCache();
  var shownState = liveState;
  var mode = "live"; // "live" | "history"
  var buffer = []; // live events received while the history is open
  var historyEvents = [];
  var playTimer = null;
  var source = null;
  var reconnectTimer = null;
  var flushTimer = null;
  var redrawTimer = null;
  var pending = { nodes: new Set(), links: new Set() };
  var selectedId = null;
  var searchMatches = [];
  var searchIndex = 0;

  // ---------------------------------------------------------------- preferences

  function loadPrefs() {
    var defaults = { hiddenTypes: [], showExpired: false };
    try {
      var stored = JSON.parse(window.localStorage.getItem(PREFS_KEY));
      if (stored && Array.isArray(stored.hiddenTypes)) {
        return { hiddenTypes: stored.hiddenTypes, showExpired: Boolean(stored.showExpired) };
      }
    } catch (error) {
      /* storage unavailable or corrupt: use the defaults */
    }
    return defaults;
  }

  function savePrefs() {
    try {
      window.localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
    } catch (error) {
      /* storage unavailable: the choice just is not remembered */
    }
  }

  // --------------------------------------------------------------------- helpers

  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
    });
  }

  function fold(text) {
    return String(text)
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .toLowerCase();
  }

  function day(iso) {
    return iso ? String(iso).slice(0, 10) : "";
  }

  function idOf(end) {
    return typeof end === "object" && end !== null ? end.id : end;
  }

  function nodeRadius(node) {
    return Math.sqrt(Math.max(0, nodeVal(node))) * 4;
  }

  function readColors() {
    var style = window.getComputedStyle(document.documentElement);
    function read(name, fallback) {
      return style.getPropertyValue(name).trim() || fallback;
    }
    TYPES.forEach(function (type) {
      colors[type] = read("--graph-" + type, "#888888");
    });
    colors.link = read("--graph-link", "rgba(148,163,184,0.7)");
    colors.linkExpired = read("--graph-link-expired", "rgba(148,163,184,0.3)");
    colors.text = read("--site-text", "#f1f5f9");
    colors.background = read("--site-bg", "#0a0f18");
  }

  // ----------------------------------------------------------------- graph styling

  function nodeVal(node) {
    return node.key === ROOT_KEY ? 8 : 2 + Math.min(node.degree || 0, 10) * 0.6;
  }

  function nodeColor(node) {
    return colors[node.type] || colors.concepto;
  }

  function nodeVisible(node) {
    return prefs.hiddenTypes.indexOf(node.type) === -1;
  }

  function linkVisible(link) {
    var source = cache.nodes.get(idOf(link.source));
    var target = cache.nodes.get(idOf(link.target));
    return Boolean(source && target && nodeVisible(source) && nodeVisible(target));
  }

  function nodeLabelHtml(node) {
    var html = "<strong>" + escapeHtml(node.name) + "</strong><br>" + escapeHtml(node.type);
    if (node.aliases && node.aliases.length) {
      html += "<br>También: " + node.aliases.map(escapeHtml).join(", ");
    }
    return html;
  }

  function linkLabelHtml(link) {
    var html = escapeHtml(link.fact) + "<br>" + escapeHtml(link.type);
    html += " · desde " + escapeHtml(day(link.valid_from));
    if (link.valid_to) {
      html += " · caducada el " + escapeHtml(day(link.valid_to));
      if (link.invalidation_reason) {
        html += " (" + escapeHtml(link.invalidation_reason) + ")";
      }
    }
    return html;
  }

  function paintNode(node, context, globalScale) {
    if (node.x === undefined || !nodeVisible(node)) return;
    var radius = nodeRadius(node);
    var age = performance.now() - (node.__bornAt || -Infinity);
    if (age < HALO_MS && !reduceMotion.matches) {
      var progress = age / HALO_MS;
      context.save();
      context.globalAlpha = 1 - progress;
      context.strokeStyle = nodeColor(node);
      context.lineWidth = 2 / globalScale;
      context.beginPath();
      context.arc(node.x, node.y, radius + (4 + progress * 14) / globalScale, 0, 2 * Math.PI);
      context.stroke();
      context.restore();
    }
    if (globalScale > 1.2) {
      var size = 12 / globalScale;
      context.font = size + "px Inter, -apple-system, sans-serif";
      context.textAlign = "center";
      context.textBaseline = "top";
      context.fillStyle = colors.text;
      context.fillText(node.name, node.x, node.y + radius + 2 / globalScale);
    }
  }

  var graph = new window.ForceGraph(els.graph)
    .nodeId("id")
    .nodeVal(nodeVal)
    .nodeColor(nodeColor)
    .nodeLabel(nodeLabelHtml)
    .nodeVisibility(nodeVisible)
    .nodeCanvasObjectMode(function () {
      return "after";
    })
    .nodeCanvasObject(paintNode)
    .linkLabel(linkLabelHtml)
    .linkVisibility(linkVisible)
    .linkColor(function (link) {
      return link.valid_to ? colors.linkExpired : colors.link;
    })
    .linkWidth(function (link) {
      return link.valid_to ? 1 : 1.5;
    })
    .linkLineDash(function (link) {
      return link.valid_to ? [4, 4] : null;
    })
    .linkDirectionalArrowLength(4)
    .linkDirectionalArrowRelPos(1)
    .linkDirectionalParticleWidth(3)
    .linkDirectionalParticleColor(function () {
      return colors.text;
    })
    .cooldownTime(15000)
    .onNodeClick(function (node) {
      showDetail(node.id);
    })
    .onBackgroundClick(hideDetail)
    .onNodeHover(function (node) {
      els.graph.style.cursor = node ? "pointer" : "";
    });

  function applyColors() {
    readColors();
    graph.backgroundColor(colors.background).nodeColor(nodeColor);
  }

  // The canvas cannot read CSS variables, so the colours are copied and refreshed with the theme.
  applyColors();
  var colorScheme = window.matchMedia("(prefers-color-scheme: light)");
  if (colorScheme.addEventListener) {
    colorScheme.addEventListener("change", applyColors);
  }

  function resizeGraph() {
    graph.width(els.graph.clientWidth).height(els.graph.clientHeight);
  }

  resizeGraph();
  if (window.ResizeObserver) {
    new ResizeObserver(resizeGraph).observe(els.graph);
  } else {
    window.addEventListener("resize", resizeGraph);
  }

  // The halo needs repaints even after the simulation has cooled down.
  function keepRedrawing(milliseconds) {
    if (reduceMotion.matches) return;
    graph.autoPauseRedraw(false);
    window.clearTimeout(redrawTimer);
    redrawTimer = window.setTimeout(function () {
      graph.autoPauseRedraw(true);
    }, milliseconds);
  }

  // -------------------------------------------------------------------- rendering

  function render(state, options) {
    shownState = state;
    var data = GraphState.toGraphData(state, { showExpired: prefs.showExpired }, cache);
    var fresh = options && options.fresh ? options.fresh : new Set();
    if (fresh.size) placeNearNeighbours(data, fresh);
    var now = performance.now();
    fresh.forEach(function (id) {
      var node = cache.nodes.get(id);
      if (node) node.__bornAt = now;
    });
    graph.graphData(data);
    updateCounts(state);
    if (selectedId !== null) {
      if (state.nodes.has(selectedId)) showDetail(selectedId);
      else hideDetail();
    }
    if (fresh.size || (options && options.newLinks && options.newLinks.size)) {
      keepRedrawing(HALO_MS + 300);
    }
    if (options && options.newLinks && options.newLinks.size && !reduceMotion.matches) {
      emitParticlesLater(options.newLinks);
    }
  }

  // A new node starts next to a neighbour so it does not shoot out from the centre.
  function placeNearNeighbours(data, freshIds) {
    var byId = new Map();
    data.nodes.forEach(function (node) {
      byId.set(node.id, node);
    });
    freshIds.forEach(function (id) {
      var node = byId.get(id);
      if (!node || node.x !== undefined) return;
      var anchor = null;
      data.links.forEach(function (link) {
        if (anchor) return;
        var otherId = null;
        if (idOf(link.source) === id) otherId = idOf(link.target);
        else if (idOf(link.target) === id) otherId = idOf(link.source);
        var other = otherId === null ? null : byId.get(otherId);
        if (other && other.x !== undefined) anchor = other;
      });
      if (anchor) {
        node.x = anchor.x + (Math.random() - 0.5) * 40;
        node.y = anchor.y + (Math.random() - 0.5) * 40;
      }
    });
  }

  function emitParticlesLater(linkIds) {
    window.setTimeout(function () {
      linkIds.forEach(function (id) {
        var link = cache.links.get(id);
        if (link && typeof link.source === "object" && typeof link.target === "object") {
          graph.emitParticle(link);
        }
      });
    }, 150);
  }

  function updateCounts(state) {
    var active = 0;
    var expired = 0;
    state.links.forEach(function (link) {
      if (!state.nodes.has(link.source) || !state.nodes.has(link.target)) return;
      if (link.valid_to) expired += 1;
      else active += 1;
    });
    var text = state.nodes.size + " entidades · " + active + " relaciones";
    if (expired) text += " (+" + expired + " caducadas)";
    els.counts.textContent = text;
    els.empty.hidden = !(state.nodes.size <= 1 && state.links.size === 0);
  }

  function setStatus(kind, text) {
    els.status.textContent = text;
    els.status.className = "status status-" + kind;
  }

  // ------------------------------------------------------------------ live updates

  function queueLive(event) {
    if (mode === "history") {
      buffer.push(event);
      updateHistoryLabel();
      return;
    }
    noteEvent(event);
    scheduleFlush();
  }

  function noteEvent(event) {
    var changes = GraphState.applyEvent(liveState, event);
    if (changes.nodeIds.length === 0 && changes.linkIds.length === 0 && !changes.removedNodeIds.length) {
      return;
    }
    if (event.op === "entity_created") pending.nodes.add(event.data.id);
    if (event.op === "relation_created") pending.links.add(event.data.id);
  }

  function scheduleFlush() {
    if (flushTimer !== null) return;
    flushTimer = window.setTimeout(flush, FLUSH_DELAY_MS);
  }

  function flush() {
    flushTimer = null;
    var fresh = pending.nodes;
    var newLinks = pending.links;
    pending = { nodes: new Set(), links: new Set() };
    if (mode !== "live") return;
    render(liveState, { fresh: fresh, newLinks: newLinks });
  }

  function closeSource() {
    if (source !== null) {
      source.close();
      source = null;
    }
    window.clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }

  function connect(since) {
    closeSource();
    source = new EventSource("/api/memory/stream?since=" + since);
    source.onopen = function () {
      if (mode === "live") setStatus("live", "● En directo");
    };
    source.onerror = function () {
      if (mode === "live") setStatus("reconnecting", "Reconectando…");
      // The browser retries by itself unless the server refused the stream.
      if (source !== null && source.readyState === EventSource.CLOSED) {
        closeSource();
        reconnectTimer = window.setTimeout(load, RECONNECT_DELAY_MS);
      }
    };
    source.addEventListener("graph", function (message) {
      queueLive(JSON.parse(message.data));
    });
    source.addEventListener("reset", function () {
      closeSource();
      graphId = null;
      load();
    });
  }

  async function load() {
    window.clearTimeout(reconnectTimer);
    if (mode === "live") setStatus("reconnecting", "Conectando…");
    var snapshot;
    try {
      var response = await fetch("/api/memory/graph", { cache: "no-store" });
      if (response.status === 503) {
        setStatus("offline", "Memoria en grafo no disponible");
        reconnectTimer = window.setTimeout(load, UNAVAILABLE_RETRY_MS);
        return;
      }
      if (!response.ok) throw new Error("HTTP " + response.status);
      snapshot = await response.json();
    } catch (error) {
      setStatus("offline", "Sin conexión");
      reconnectTimer = window.setTimeout(load, RECONNECT_DELAY_MS);
      return;
    }
    var rebuilt = snapshot.graph_id !== graphId;
    if (rebuilt) {
      // First load, or the database was rebuilt: nothing from the old graph is valid.
      graphId = snapshot.graph_id;
      cache = GraphState.createCache();
      historyEvents = [];
      graph.graphData({ nodes: [], links: [] });
    }
    liveState = GraphState.fromSnapshot(snapshot);
    buffer = [];
    pending = { nodes: new Set(), links: new Set() };
    if (rebuilt && mode === "history") {
      leaveHistory();
    } else if (mode === "live") {
      render(liveState, {});
    }
    connect(snapshot.version);
  }

  // ------------------------------------------------------------------------ history

  async function fetchHistory() {
    var since = historyEvents.length ? historyEvents[historyEvents.length - 1].version : 0;
    for (var pages = 0; pages < 1000; pages += 1) {
      var response = await fetch("/api/memory/events?since=" + since + "&limit=" + PAGE_SIZE, {
        cache: "no-store",
      });
      if (!response.ok) throw new Error("HTTP " + response.status);
      var page = await response.json();
      if (page.graph_id !== graphId) throw new Error("The graph was rebuilt");
      if (page.events.length === 0) return;
      historyEvents = historyEvents.concat(page.events);
      since = page.next;
    }
  }

  async function enterHistory() {
    els.historyToggle.disabled = true;
    try {
      await fetchHistory();
    } catch (error) {
      els.searchResult.textContent = "No se pudo cargar la historia.";
      els.historyToggle.disabled = false;
      return;
    }
    els.historyToggle.disabled = false;
    mode = "history";
    buffer = [];
    els.historyBar.hidden = false;
    els.timeline.max = String(historyEvents.length);
    els.timeline.value = String(historyEvents.length);
    setStatus("history", "Historia");
    showHistoryAt(historyEvents.length);
  }

  function showHistoryAt(count) {
    updateHistoryLabel();
    render(GraphState.stateAt(historyEvents, count), {});
  }

  function updateHistoryLabel() {
    var count = Number(els.timeline.value);
    var text = "Evento " + count + " de " + historyEvents.length;
    if (count > 0 && historyEvents[count - 1]) {
      text += " · " + day(historyEvents[count - 1].ts);
    }
    if (buffer.length) text += " · " + buffer.length + " nuevos en directo";
    els.timelineLabel.textContent = text;
  }

  function stopPlaying() {
    window.clearInterval(playTimer);
    playTimer = null;
    els.play.textContent = "▶";
    els.play.setAttribute("aria-label", "Reproducir");
  }

  function togglePlay() {
    if (playTimer !== null) {
      stopPlaying();
      return;
    }
    if (Number(els.timeline.value) >= historyEvents.length) els.timeline.value = "0";
    showHistoryAt(Number(els.timeline.value));
    els.play.textContent = "⏸";
    els.play.setAttribute("aria-label", "Pausar");
    playTimer = window.setInterval(function () {
      var next = Number(els.timeline.value) + 1;
      els.timeline.value = String(next);
      showHistoryAt(next);
      if (next >= historyEvents.length) stopPlaying();
    }, PLAY_STEP_MS);
  }

  function leaveHistory() {
    stopPlaying();
    mode = "live";
    els.historyBar.hidden = true;
    var missed = buffer;
    buffer = [];
    missed.forEach(noteEvent);
    var fresh = pending.nodes;
    var newLinks = pending.links;
    pending = { nodes: new Set(), links: new Set() };
    render(liveState, { fresh: fresh, newLinks: newLinks });
    setStatus(
      source !== null && source.readyState === EventSource.OPEN ? "live" : "reconnecting",
      source !== null && source.readyState === EventSource.OPEN ? "● En directo" : "Reconectando…"
    );
  }

  // ----------------------------------------------------------------------- controls

  function buildTypeFilters() {
    TYPES.forEach(function (type) {
      var label = document.createElement("label");
      label.className = "type-filter";
      var box = document.createElement("input");
      box.type = "checkbox";
      box.checked = prefs.hiddenTypes.indexOf(type) === -1;
      var swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.background = "var(--graph-" + type + ")";
      var text = document.createElement("span");
      text.textContent = TYPE_LABELS[type];
      label.appendChild(box);
      label.appendChild(swatch);
      label.appendChild(text);
      box.addEventListener("change", function () {
        prefs.hiddenTypes = prefs.hiddenTypes.filter(function (hidden) {
          return hidden !== type;
        });
        if (!box.checked) prefs.hiddenTypes.push(type);
        savePrefs();
        graph.nodeVisibility(nodeVisible).linkVisibility(linkVisible);
        keepRedrawing(300);
      });
      els.types.appendChild(label);
    });
  }

  function search() {
    var query = fold(els.search.value.trim());
    searchMatches = [];
    searchIndex = 0;
    if (query) {
      shownState.nodes.forEach(function (node) {
        var names = [node.name].concat(node.aliases || []);
        if (
          names.some(function (name) {
            return fold(name).indexOf(query) !== -1;
          })
        ) {
          searchMatches.push(node.id);
        }
      });
    }
    if (!query) {
      els.searchResult.textContent = "";
    } else if (searchMatches.length === 0) {
      els.searchResult.textContent = "Sin resultados";
    } else {
      focusMatch();
    }
  }

  function focusMatch() {
    var id = searchMatches[searchIndex % searchMatches.length];
    var node = cache.nodes.get(id);
    els.searchResult.textContent =
      searchMatches.length === 1
        ? "1 resultado"
        : "Resultado " + ((searchIndex % searchMatches.length) + 1) + " de " + searchMatches.length;
    if (!node || node.x === undefined) return;
    node.__bornAt = performance.now();
    keepRedrawing(HALO_MS + 300);
    graph.centerAt(node.x, node.y, 600);
    graph.zoom(3, 600);
    showDetail(id);
  }

  function showDetail(id) {
    var node = shownState.nodes.get(id);
    if (!node) return;
    selectedId = id;
    els.detail.replaceChildren();
    var title = document.createElement("h2");
    title.textContent = node.name;
    var meta = document.createElement("p");
    meta.className = "detail-meta";
    meta.textContent = node.type + " · desde " + day(node.created_at);
    els.detail.appendChild(title);
    els.detail.appendChild(meta);
    if (node.aliases && node.aliases.length) {
      var aliases = document.createElement("p");
      aliases.className = "detail-meta";
      aliases.textContent = "También: " + node.aliases.join(", ");
      els.detail.appendChild(aliases);
    }
    var list = document.createElement("ul");
    shownState.links.forEach(function (link) {
      if (link.source !== id && link.target !== id) return;
      if (!shownState.nodes.has(link.source) || !shownState.nodes.has(link.target)) return;
      var item = document.createElement("li");
      item.textContent =
        link.fact + (link.valid_to ? " (caducada el " + day(link.valid_to) + ")" : "");
      if (link.valid_to) item.className = "expired";
      list.appendChild(item);
    });
    if (list.children.length) els.detail.appendChild(list);
    els.detail.hidden = false;
  }

  function hideDetail() {
    selectedId = null;
    els.detail.hidden = true;
  }

  function bindControls() {
    els.showExpired.checked = prefs.showExpired;
    els.showExpired.addEventListener("change", function () {
      prefs.showExpired = els.showExpired.checked;
      savePrefs();
      render(shownState, {});
    });
    els.search.addEventListener("input", search);
    els.search.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && searchMatches.length) {
        event.preventDefault();
        searchIndex += 1;
        focusMatch();
      }
    });
    els.fit.addEventListener("click", function () {
      graph.zoomToFit(400, 40);
    });
    els.historyToggle.addEventListener("click", function () {
      if (mode === "history") leaveHistory();
      else enterHistory();
    });
    els.backToLive.addEventListener("click", leaveHistory);
    els.play.addEventListener("click", togglePlay);
    els.timeline.addEventListener("input", function () {
      stopPlaying();
      showHistoryAt(Number(els.timeline.value));
    });
    // On a phone the controls start collapsed so they do not cover the graph.
    if (window.matchMedia("(max-width: 640px)").matches) {
      els.panel.open = false;
    }
  }

  buildTypeFilters();
  bindControls();
  load();
})();
