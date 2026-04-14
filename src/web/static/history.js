(() => {
  const STORAGE_KEY = "hdmi_exfil_history";
  const PREFS_KEY = "hdmi_exfil_history_filters";
  const DEFAULT_PREFS = {
    search: "",
    type: "all",
    status: "all",
    protocol: "all",
    origin: "all",
    range: "all",
    sort: "newest",
  };

  const els = {
    tbody: document.getElementById("historyBody"),
    table: document.getElementById("historyTable"),
    emptyState: document.getElementById("emptyState"),
    emptyTitle: document.getElementById("emptyTitle"),
    emptySub: document.getElementById("emptySub"),
    countLabel: document.getElementById("countLabel"),
    noticeLabel: document.getElementById("noticeLabel"),
    resultsCopy: document.getElementById("resultsCopy"),
    refreshBtn: document.getElementById("refreshBtn"),
    clearBtn: document.getElementById("clearBtn"),
    clearFiltersBtn: document.getElementById("clearFiltersBtn"),
    searchInput: document.getElementById("searchInput"),
    typeFilter: document.getElementById("typeFilter"),
    statusFilter: document.getElementById("statusFilter"),
    protocolFilter: document.getElementById("protocolFilter"),
    originFilter: document.getElementById("originFilter"),
    rangeFilter: document.getElementById("rangeFilter"),
    sortSelect: document.getElementById("sortSelect"),
    statVisible: document.getElementById("statVisible"),
    statVisibleSub: document.getElementById("statVisibleSub"),
    statReceived: document.getElementById("statReceived"),
    statReceivedSub: document.getElementById("statReceivedSub"),
    statSent: document.getElementById("statSent"),
    statSentSub: document.getElementById("statSentSub"),
    filterTags: document.getElementById("filterTags"),
    confirmModal: document.getElementById("confirmModal"),
    confirmModalTitle: document.getElementById("confirmModalTitle"),
    confirmModalMessage: document.getElementById("confirmModalMessage"),
    confirmModalCancel: document.getElementById("confirmModalCancel"),
    confirmModalConfirm: document.getElementById("confirmModalConfirm"),
  };

  const tagMap = {
    search: ["tagSearch", "tagSearchText"],
    type: ["tagType", "tagTypeText"],
    status: ["tagStatus", "tagStatusText"],
    protocol: ["tagProtocol", "tagProtocolText"],
    origin: ["tagOrigin", "tagOriginText"],
    range: ["tagRange", "tagRangeText"],
  };

  let prefs = loadPrefs();
  let confirmState = null;
  let serverFiles = [];
  let serverFilesRequest = null;
  let mergedItems = [];
  let viewItems = [];

  function loadPrefs() {
    try {
      return { ...DEFAULT_PREFS, ...(JSON.parse(localStorage.getItem(PREFS_KEY) || "{}") || {}) };
    } catch {
      return { ...DEFAULT_PREFS };
    }
  }

  function savePrefs() {
    localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  }

  function getHistory() {
    try {
      const items = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
      return Array.isArray(items) ? items : [];
    } catch {
      return [];
    }
  }

  function setHistory(items) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
  }

  function formatSize(bytes) {
    if (bytes == null) return "--";
    const value = Number(bytes);
    if (!Number.isFinite(value)) return "--";
    if (value < 1024) return value + " B";
    if (value < 1048576) return (value / 1024).toFixed(1) + " KB";
    if (value < 1073741824) return (value / 1048576).toFixed(2) + " MB";
    return (value / 1073741824).toFixed(2) + " GB";
  }

  function formatDuration(seconds) {
    if (seconds == null) return "--";
    const value = Number(seconds);
    if (!Number.isFinite(value)) return "--";
    if (value < 60) return value.toFixed(1) + "s";
    return Math.floor(value / 60) + "m " + Math.round(value % 60) + "s";
  }

  function formatSpeed(bytesPerSecond) {
    if (bytesPerSecond == null) return "--";
    const value = Number(bytesPerSecond);
    if (!Number.isFinite(value)) return "--";
    if (value < 1024) return value.toFixed(0) + " B/s";
    if (value < 1048576) return (value / 1024).toFixed(1) + " KB/s";
    return (value / 1048576).toFixed(2) + " MB/s";
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function setNotice(message, isError = false) {
    els.noticeLabel.textContent = message || "";
    els.noticeLabel.className = "sub" + (isError ? " error" : "");
  }

  function parseJsonSafe(response) {
    return response.json().catch(() => ({}));
  }

  function normalizeProtocol(value) {
    const normalized = String(value || "").trim().toLowerCase();
    return normalized || "unknown";
  }

  function protocolLabel(value) {
    const normalized = normalizeProtocol(value);
    if (normalized === "fountain") return "Fountain";
    if (normalized === "sequential") return "Sequential";
    if (normalized === "disk") return "Disk import";
    if (normalized === "unknown") return "Unknown";
    return normalized.toUpperCase();
  }

  function typeLabel(value) {
    return value === "sent" ? "Sent" : "Received";
  }

  function statusInfo(item) {
    if (item.type === "received" && item.fileExists === false) return { key: "missing", label: "Missing", className: "status-missing" };
    if (item.imported && item.success == null) return { key: "on_disk", label: "On disk", className: "status-disk" };
    if (item.success) return { key: "ok", label: "OK", className: "status-ok" };
    return { key: "failed", label: "Failed", className: "status-fail" };
  }

  function originKey(item) {
    return item.imported ? "disk" : "history";
  }

  function originLabel(item) {
    return originKey(item) === "disk" ? "Receiver disk" : "Local log";
  }

  function locationFor(item) {
    if (item.systemPath) return item.systemPath;
    if (item.type === "sent") return "Browser-selected source file (path unavailable)";
    if (item.type === "received" && item.filename) {
      return item.fileExists === false ? "Missing from receiver output directory" : "Receiver output path unavailable";
    }
    return "--";
  }

  function periodCutoff(range) {
    const now = Date.now();
    if (range === "24h") return now - 24 * 60 * 60 * 1000;
    if (range === "7d") return now - 7 * 24 * 60 * 60 * 1000;
    if (range === "30d") return now - 30 * 24 * 60 * 60 * 1000;
    return null;
  }

  function inRange(item, range) {
    const cutoff = periodCutoff(range);
    return cutoff == null || Number(item.timestamp || 0) >= cutoff;
  }

  function matchesSearch(item, query) {
    if (!query) return true;
    const haystack = [
      item.filename,
      item.systemPath,
      locationFor(item),
      item.type,
      originLabel(item),
      protocolLabel(item.protocol),
      statusInfo(item).label,
    ].join(" ").toLowerCase();
    return haystack.includes(query.toLowerCase());
  }

  function sortItems(items) {
    const sorted = [...items];
    sorted.sort((left, right) => {
      const lt = Number(left.timestamp || 0);
      const rt = Number(right.timestamp || 0);
      if (prefs.sort === "oldest") return lt - rt;
      if (prefs.sort === "name_asc") return String(left.filename || "").localeCompare(String(right.filename || "")) || (rt - lt);
      if (prefs.sort === "name_desc") return String(right.filename || "").localeCompare(String(left.filename || "")) || (rt - lt);
      if (prefs.sort === "size_desc") return Number(right.size || 0) - Number(left.size || 0) || (rt - lt);
      if (prefs.sort === "speed_desc") return Number(right.speed || 0) - Number(left.speed || 0) || (rt - lt);
      if (prefs.sort === "duration_desc") return Number(right.duration || 0) - Number(left.duration || 0) || (rt - lt);
      if (prefs.sort === "status") return statusInfo(left).key.localeCompare(statusInfo(right).key) || (rt - lt);
      return rt - lt;
    });
    return sorted;
  }

  function findLocalHistoryIndex(item, items) {
    if (Number.isInteger(item.localIndex)) {
      const candidate = items[item.localIndex];
      if (candidate && candidate.timestamp === item.timestamp && candidate.filename === item.filename && candidate.type === item.type) {
        return item.localIndex;
      }
    }
    return items.findIndex((entry) => entry.timestamp === item.timestamp && entry.filename === item.filename && entry.type === item.type);
  }

  function buildItems() {
    const localItems = getHistory();
    const filesByName = new Map(serverFiles.map((file) => [file.filename, file]));
    const seenNames = new Set();
    const merged = localItems.map((item, localIndex) => {
      const disk = item.type === "received" && item.filename ? filesByName.get(item.filename) : null;
      if (disk) seenNames.add(disk.filename);
      return {
        ...item,
        imported: false,
        localIndex,
        size: item.size != null ? item.size : (disk ? disk.size : null),
        systemPath: item.systemPath || (disk ? disk.system_path : ""),
        fileExists: item.type === "received" && item.filename ? Boolean(disk) : item.fileExists,
        timestamp: item.timestamp != null ? item.timestamp : (disk ? disk.modified_ms : Date.now()),
      };
    });

    for (const file of serverFiles) {
      if (seenNames.has(file.filename)) continue;
      merged.push({
        type: "received",
        filename: file.filename,
        size: file.size,
        duration: null,
        speed: null,
        success: null,
        timestamp: file.modified_ms,
        protocol: "disk",
        systemPath: file.system_path,
        fileExists: true,
        imported: true,
        localIndex: null,
      });
    }
    return merged;
  }

  function filteredItems(items) {
    return sortItems(items.filter((item) => {
      const protocol = normalizeProtocol(item.protocol);
      const protocolGroup = (protocol === "fountain" || protocol === "sequential" || protocol === "disk") ? protocol : "other";
      if (prefs.type !== "all" && item.type !== prefs.type) return false;
      if (prefs.status !== "all" && statusInfo(item).key !== prefs.status) return false;
      if (prefs.protocol !== "all" && protocolGroup !== prefs.protocol) return false;
      if (prefs.origin !== "all" && originKey(item) !== prefs.origin) return false;
      if (!inRange(item, prefs.range)) return false;
      if (!matchesSearch(item, prefs.search.trim())) return false;
      return true;
    }));
  }

  function updateStats() {
    const received = viewItems.filter((item) => item.type === "received");
    const sent = viewItems.filter((item) => item.type === "sent");
    els.statVisible.textContent = String(viewItems.length);
    els.statVisibleSub.textContent = viewItems.length + " of " + mergedItems.length + " total items";
    els.statReceived.textContent = String(received.length);
    els.statReceivedSub.textContent = received.filter((item) => item.fileExists !== false).length + " files currently available on receiver";
    els.statSent.textContent = String(sent.length);
    els.statSentSub.textContent = viewItems.filter((item) => originKey(item) === "history").length + " locally recorded entries";
  }

  function setTag(key, value) {
    const [tagId, textId] = tagMap[key];
    const tag = document.getElementById(tagId);
    const text = document.getElementById(textId);
    if (!value) {
      tag.classList.remove("visible");
      text.textContent = "";
      return;
    }
    text.textContent = value;
    tag.classList.add("visible");
  }

  function renderFilterTags() {
    setTag("search", prefs.search.trim() ? 'Search: "' + prefs.search.trim() + '"' : "");
    setTag("type", prefs.type !== "all" ? "Type: " + typeLabel(prefs.type) : "");
    setTag("status", prefs.status !== "all" ? "Status: " + prefs.status.replace("_", " ") : "");
    setTag("protocol", prefs.protocol !== "all" ? "Protocol: " + protocolLabel(prefs.protocol) : "");
    setTag("origin", prefs.origin !== "all" ? "Source: " + (prefs.origin === "disk" ? "Receiver disk" : "Local log") : "");
    setTag("range", prefs.range !== "all" ? "Period: " + els.rangeFilter.selectedOptions[0].textContent : "");
  }

  function renderResultsText() {
    const text = viewItems.length === mergedItems.length
      ? "Showing <strong>" + viewItems.length + "</strong> items."
      : "Showing <strong>" + viewItems.length + "</strong> of <strong>" + mergedItems.length + "</strong> items.";
    const localCount = viewItems.filter((item) => originKey(item) === "history").length;
    const diskCount = viewItems.filter((item) => originKey(item) === "disk").length;
    els.resultsCopy.innerHTML = text + " Local log: <strong>" + localCount + "</strong> &middot; Receiver disk: <strong>" + diskCount + "</strong>.";
  }

  function renderEmptyState() {
    if (mergedItems.length === 0) {
      els.emptyTitle.textContent = "No history yet";
      els.emptySub.textContent = "Completed transfers and receiver output files will appear here.";
      return;
    }
    els.emptyTitle.textContent = "No results for current filters";
    els.emptySub.textContent = "Adjust the search, filters or period selection. The history exists, but nothing matches the current view.";
  }

  function renderRows() {
    els.tbody.innerHTML = "";
    for (const [index, item] of viewItems.entries()) {
      const date = new Date(Number(item.timestamp || 0));
      const dateText = Number.isFinite(date.getTime())
        ? date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
          + " " + date.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false })
        : "--";
      const status = statusInfo(item);
      const typeClass = item.type === "sent" ? "tag-sent" : "tag-received";
      const originClass = originKey(item) === "disk" ? "origin-disk" : "origin-history";
      const canDeleteFile = item.type === "received" && Boolean(item.filename) && item.fileExists !== false;
      const canOpenLocation = item.type === "received" && Boolean(item.filename) && Boolean(item.systemPath);
      const canDownload = canDeleteFile;
      const deleteLabel = canDeleteFile ? "Delete file" : "Delete entry";
      const downloadUrl = item.filename ? "/api/receive/download/" + encodeURIComponent(item.filename) : "";
      const actionButtons = [];
      if (canDownload) {
        actionButtons.push(`<a class="row-btn row-btn-open" href="${downloadUrl}">Download</a>`);
      }
      if (canOpenLocation) {
        actionButtons.push(`<button class="row-btn row-btn-open" data-action="open" data-index="${index}" type="button">Open location</button>`);
      }
      actionButtons.push(`<button class="row-btn row-btn-danger" data-action="delete" data-index="${index}" type="button">${escapeHtml(deleteLabel)}</button>`);
      const actionClass = "actions-" + actionButtons.length;

      const row = document.createElement("tr");
      row.innerHTML = `
        <td class="mono">${escapeHtml(dateText)}</td>
        <td>
          <div><span class="tag ${typeClass}">${escapeHtml(typeLabel(item.type))}</span></div>
          <div class="cell-sub"><span class="origin-tag ${originClass}">${escapeHtml(originLabel(item))}</span></div>
        </td>
        <td>
          <div class="cell-primary">${escapeHtml(item.filename || "--")}</div>
          <div class="cell-sub">${escapeHtml(protocolLabel(item.protocol))}</div>
        </td>
        <td class="path-cell"><div class="path-text${item.systemPath ? "" : " dim"}">${escapeHtml(locationFor(item))}</div></td>
        <td>${formatSize(item.size)}</td>
        <td>${formatDuration(item.duration)}</td>
        <td>${formatSpeed(item.speed)}</td>
        <td><span class="status-badge ${status.className}">${escapeHtml(status.label)}</span></td>
        <td class="actions-col">
          <div class="row-actions ${actionClass}">
            ${actionButtons.join("")}
          </div>
        </td>
      `;
      els.tbody.appendChild(row);
    }
  }

  function syncControls() {
    els.searchInput.value = prefs.search;
    els.typeFilter.value = prefs.type;
    els.statusFilter.value = prefs.status;
    els.protocolFilter.value = prefs.protocol;
    els.originFilter.value = prefs.origin;
    els.rangeFilter.value = prefs.range;
    els.sortSelect.value = prefs.sort;
  }

  function render() {
    mergedItems = buildItems();
    viewItems = filteredItems(mergedItems);
    updateStats();
    renderFilterTags();
    renderResultsText();
    renderEmptyState();
    els.countLabel.textContent = mergedItems.length === 0
      ? "No transfers recorded yet"
      : mergedItems.length + " total history item" + (mergedItems.length === 1 ? "" : "s");

    if (viewItems.length === 0) {
      els.table.style.display = "none";
      els.emptyState.style.display = "";
      els.tbody.innerHTML = "";
      return;
    }

    els.table.style.display = "";
    els.emptyState.style.display = "none";
    renderRows();
  }

  function applyControlChange() {
    prefs = {
      search: els.searchInput.value,
      type: els.typeFilter.value,
      status: els.statusFilter.value,
      protocol: els.protocolFilter.value,
      origin: els.originFilter.value,
      range: els.rangeFilter.value,
      sort: els.sortSelect.value,
    };
    savePrefs();
    render();
  }

  function clearFilters() {
    prefs = { ...DEFAULT_PREFS, sort: prefs.sort };
    savePrefs();
    syncControls();
    render();
  }

  function closeConfirmModal(confirmed) {
    if (!confirmState) return;
    const { resolve, previousFocus } = confirmState;
    confirmState = null;
    els.confirmModal.classList.add("hidden");
    els.confirmModal.setAttribute("aria-hidden", "true");
    els.confirmModalConfirm.textContent = "Confirm";
    els.confirmModalTitle.textContent = "Confirm action";
    els.confirmModalMessage.textContent = "";
    if (previousFocus && typeof previousFocus.focus === "function") previousFocus.focus();
    resolve(Boolean(confirmed));
  }

  function showConfirmModal({ title, message, confirmLabel }) {
    if (confirmState) closeConfirmModal(false);
    els.confirmModalTitle.textContent = title;
    els.confirmModalMessage.textContent = message;
    els.confirmModalConfirm.textContent = confirmLabel || "Confirm";
    els.confirmModal.classList.remove("hidden");
    els.confirmModal.setAttribute("aria-hidden", "false");
    return new Promise((resolve) => {
      confirmState = { resolve, previousFocus: document.activeElement };
      window.requestAnimationFrame(() => els.confirmModalConfirm.focus());
    });
  }

  async function refreshServerFiles({ silent = false } = {}) {
    if (!serverFilesRequest) {
      serverFilesRequest = fetch("/api/receive/files", { cache: "no-store" })
        .then(async (response) => {
          if (!response.ok) return [];
          const data = await parseJsonSafe(response);
          return Array.isArray(data) ? data : [];
        })
        .catch(() => {
          if (!silent) setNotice("Unable to refresh receiver files.", true);
          return [];
        })
        .finally(() => { serverFilesRequest = null; });
    }
    serverFiles = await serverFilesRequest;
    render();
  }

  async function deleteEntry(index) {
    const item = viewItems[index];
    if (!item) return;
    const canDeleteFile = item.type === "received" && Boolean(item.filename) && item.fileExists !== false;
    const hasLocalEntry = Number.isInteger(item.localIndex);
    const label = item.filename || "this entry";
    const confirmed = await showConfirmModal({
      title: canDeleteFile ? "Delete receiver file" : "Remove history entry",
      message: canDeleteFile
        ? (hasLocalEntry
          ? `Delete "${label}" from disk and remove it from the local history?`
          : `Delete "${label}" from the receiver output directory?`)
        : `Remove "${label}" from the local history list?`,
      confirmLabel: canDeleteFile ? "Delete file" : "Remove entry",
    });
    if (!confirmed) return;

    if (canDeleteFile) {
      const response = await fetch("/api/receive/file/" + encodeURIComponent(item.filename), { method: "DELETE" });
      if (!response.ok && response.status !== 404) {
        const data = await parseJsonSafe(response);
        setNotice(data.error || "Unable to delete the receiver file.", true);
        return;
      }
    }

    if (hasLocalEntry) {
      const localItems = getHistory();
      const localIndex = findLocalHistoryIndex(item, localItems);
      if (localIndex >= 0) {
        localItems.splice(localIndex, 1);
        setHistory(localItems);
      }
    }

    if (canDeleteFile) {
      await refreshServerFiles({ silent: true });
      setNotice("Receiver file deleted.");
      return;
    }

    setNotice("History entry removed.");
    render();
  }

  async function openLocation(index) {
    const item = viewItems[index];
    if (!item || item.type !== "received" || !item.filename) return;
    const response = await fetch("/api/receive/file/" + encodeURIComponent(item.filename) + "/reveal", { method: "POST" });
    const data = await parseJsonSafe(response);
    if (!response.ok) {
      setNotice(data.error || "Unable to open the file location.", true);
      return;
    }
    setNotice(data.opened === "directory" ? "Output folder opened." : "File location opened.");
  }

  els.refreshBtn.addEventListener("click", () => {
    setNotice("Refreshing receiver files...");
    refreshServerFiles().then(() => setNotice("History refreshed."));
  });
  els.clearBtn.addEventListener("click", () => {
    showConfirmModal({
      title: "Clear local history",
      message: "Clear the local browser history log? Files on disk will not be deleted.",
      confirmLabel: "Clear log",
    }).then((confirmed) => {
      if (!confirmed) return;
      localStorage.removeItem(STORAGE_KEY);
      setNotice("Local history cleared.");
      render();
    });
  });
  els.clearFiltersBtn.addEventListener("click", clearFilters);
  [els.searchInput, els.typeFilter, els.statusFilter, els.protocolFilter, els.originFilter, els.rangeFilter, els.sortSelect]
    .forEach((control) => control.addEventListener(control === els.searchInput ? "input" : "change", applyControlChange));

  els.filterTags.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-clear]");
    if (!button) return;
    const key = button.dataset.clear;
    if (key === "search") prefs.search = "";
    if (key === "type") prefs.type = "all";
    if (key === "status") prefs.status = "all";
    if (key === "protocol") prefs.protocol = "all";
    if (key === "origin") prefs.origin = "all";
    if (key === "range") prefs.range = "all";
    savePrefs();
    syncControls();
    render();
  });

  els.tbody.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const index = Number(button.dataset.index);
    if (!Number.isInteger(index)) return;
    if (button.dataset.action === "open") return void openLocation(index);
    if (button.dataset.action === "delete") deleteEntry(index);
  });

  els.confirmModalCancel.addEventListener("click", () => closeConfirmModal(false));
  els.confirmModalConfirm.addEventListener("click", () => closeConfirmModal(true));
  els.confirmModal.addEventListener("click", (event) => {
    if (event.target === els.confirmModal) closeConfirmModal(false);
  });

  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && confirmState) {
      event.preventDefault();
      closeConfirmModal(false);
    }
  });
  window.addEventListener("storage", (event) => {
    if (event.key === STORAGE_KEY || event.key === PREFS_KEY) {
      prefs = loadPrefs();
      syncControls();
      render();
    }
  });
  window.addEventListener("focus", () => {
    refreshServerFiles({ silent: true });
  });

  syncControls();
  render();
  refreshServerFiles({ silent: true });
  window.setInterval(() => {
    if (document.visibilityState !== "visible") return;
    refreshServerFiles({ silent: true });
  }, 5000);
})();
