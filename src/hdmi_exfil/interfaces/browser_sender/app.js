  const BPC_LEVELS = {
    1: [0, 255],
    2: [0, 85, 170, 255],
    3: [0, 36, 73, 109, 146, 182, 219, 255],
  };

  const config = {
    protocol: "fountain", bpc: 1,
    profileName: "balanced", width: 1920, height: 1080, blockSize: 8,
    fountainRedundancy: 1.5,
    sequentialRedundancy: 1,
    fountainAutoStop: false,
    targetFps: 60, fpsMode: "profile", manualFps: 60, detectedHz: null,
    cols: 0, rows: 0, bitsPerFrame: 0, bytesPerFrame: 0, payloadSize: 0,
  };
  const runtimeOptions = {
    apiBaseUrl: "",
    debugTitle: false,
  };

  function recalcDerived() {
    config.cols = config.width / config.blockSize;
    config.rows = config.height / config.blockSize;
    config.bitsPerFrame = config.rows * config.cols * 3 * config.bpc;
    config.bytesPerFrame = config.bitsPerFrame / 8;
    const headerLen = config.protocol === "fountain" ? FOUNTAIN_HEADER_LEN : SEQ_HEADER_LEN;
    config.payloadSize = config.bytesPerFrame - headerLen;
  }

  function getEffectiveFps() {
    const maxHz = config.detectedHz || 60;
    let fps;
    if (config.fpsMode === "manual") fps = config.manualFps;
    else if (config.fpsMode === "profile") {
      const p = PROFILES[config.profileName];
      fps = p ? p.targetFps : 60;
    } else fps = maxHz;
    return Math.min(fps, maxHz);
  }

  function bytesPerFrameForBpc(bpc) {
    return (config.rows * config.cols * 3 * bpc) / 8;
  }

  // ── Refresh rate detection ─────────────
  function detectRefreshRate() {
    return new Promise((resolve) => {
      const samples = []; let lastTime = 0, frameCount = 0;
      function measure(ts) {
        if (lastTime > 0) samples.push(ts - lastTime);
        lastTime = ts; frameCount++;
        if (frameCount < 90) requestAnimationFrame(measure);
        else {
          const valid = samples.slice(5).sort((a, b) => a - b);
          const median = valid[Math.floor(valid.length / 2)];
          const hz = Math.round(1000 / median);
          const common = [30,60,75,90,100,120,144,165,180,240,360];
          resolve(common.reduce((b, r) => Math.abs(r - hz) < Math.abs(b - hz) ? r : b));
        }
      }
      requestAnimationFrame(measure);
    });
  }

  // ── CRC32 ──────────────────────────────
  const CRC32_TABLE = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let j = 0; j < 8; j++) c = (c & 1) ? ((c >>> 1) ^ 0xEDB88320) : (c >>> 1);
    CRC32_TABLE[i] = c >>> 0;
  }
  function crc32(bytes) {
    let crc = 0xFFFFFFFF;
    for (let i = 0; i < bytes.length; i++) crc = CRC32_TABLE[(crc ^ bytes[i]) & 0xFF] ^ (crc >>> 8);
    return (crc ^ 0xFFFFFFFF) >>> 0;
  }
  async function computeSHA256(uint8Array) {
    return new Uint8Array(await crypto.subtle.digest('SHA-256', uint8Array));
  }

  // ── DOM ────────────────────────────────
  const canvas = document.getElementById("canvas");
  const ctx = canvas.getContext("2d", { alpha: false });
  ctx.imageSmoothingEnabled = false;
  let imageData = ctx.createImageData(config.width, config.height);
  let buf = new Uint32Array(imageData.data.buffer);

  const canvasWrap = document.getElementById("canvas-wrap");
  const hud = document.getElementById("hud");

  const dropZone = document.getElementById("dropZone");
  const fileInput = document.getElementById("fileInput");
  const fileInputAlt = document.getElementById("fileInputAlt");
  const fileNameEl = document.getElementById("fileName");
  const fileSizeEl = document.getElementById("fileSize");
  const fileChunksEl = document.getElementById("fileChunks");
  const chipProfile = document.getElementById("chipProfile");
  const chipSpeed = document.getElementById("chipSpeed");
  const chipFps = document.getElementById("chipFps");

  const startBtn = document.getElementById("startBtn");
  const stopBtn = document.getElementById("stopBtn");

  const bpcSelect = document.getElementById("bpcSelect");
  const protocolSelect = document.getElementById("protocolSelect");
  const profileSelect = document.getElementById("profileSelect");
  const resolutionSelect = document.getElementById("resolutionSelect");
  const blockSizeSelect = document.getElementById("blockSizeSelect");
  const fountainRedundancyRow = document.getElementById("fountainRedundancyRow");
  const fountainAutoStopInput = document.getElementById("fountainAutoStopInput");
  const fountainRedundancyInput = document.getElementById("fountainRedundancyInput");
  const sequentialRedundancyRow = document.getElementById("sequentialRedundancyRow");
  const sequentialRedundancyInput = document.getElementById("sequentialRedundancyInput");
  const fpsModeSelect = document.getElementById("fpsModeSelect");
  const manualFpsInput = document.getElementById("manualFpsInput");
  const manualRow = document.getElementById("manualRow");
  const detectedHzEl = document.getElementById("detectedHz");
  const derivedStatsEl = document.getElementById("derivedStats");
  const configWarningEl = document.getElementById("configWarning");
  const advToggle = document.getElementById("advToggle");
  const advBody = document.getElementById("advBody");

  const statusLabel = document.getElementById("statusLabel");
  const headerFrames = document.getElementById("headerFrames");
  const headerK = document.getElementById("headerK");
  const headerTime = document.getElementById("headerTime");
  const headerFps = document.getElementById("headerFps");
  const hudFps = document.getElementById("hudFps");
  const hudFrames = document.getElementById("hudFrames");
  const hudK = document.getElementById("hudK");
  const hudTime = document.getElementById("hudTime");

  const textEncoder = new TextEncoder();
  const preflightNameBytes = textEncoder.encode(PREFLIGHT_FILENAME);
  let preflightPayloadPromise = null;
  const FOUNTAIN_RECEIVER_WAIT_POLL_MS = 300;
  const FOUNTAIN_RECEIVER_WAIT_MIN_MS = 30000;

  // ── State ──────────────────────────────
  const state = {
    chunks: [], K: 0, seed: 1, frame: 0, running: false,
    bits: new Uint8Array(config.rows * config.cols * 3),
    vals: new Uint8Array(config.rows * config.cols * 3),
    raf: null,
    rawWrapped: null, rawBytes: null, sha256Hash: null,
    fileName: null, fileSize: 0, startTime: 0,
    lastRenderAt: 0,
    rsdCdf: null,
    fountainTargetFrames: 0,
    // Sequential state
    seqPhase: "start", // "start" | "data" | "end"
    seqDataIdx: 0, seqRepeat: 0,
    phase: "idle",
    preflightFrames: 0,
    preflightPayload: null,
    preflightPhase: "path",
    preflightRenderBpc: PREFLIGHT_BITS_PER_CHANNEL,
    preflightRequestedBpc: PREFLIGHT_BITS_PER_CHANNEL,
    preflightNegotiatedBpc: PREFLIGHT_BITS_PER_CHANNEL,
    receiverDrivenFountainStop: false,
  };

  // ── Config ─────────────────────────────
  function validateConfig() {
    if (config.width % config.blockSize !== 0 || config.height % config.blockSize !== 0) {
      configWarningEl.textContent = `${config.width}x${config.height} not divisible by block size ${config.blockSize}`;
      configWarningEl.style.display = "block";
      configWarningEl.className = "side-note warn";
      return false;
    }
    configWarningEl.style.display = "none";
    return true;
  }

  function applyConfig() {
    recalcDerived();
    const valid = validateConfig();
    canvas.width = config.width; canvas.height = config.height;
    imageData = ctx.createImageData(config.width, config.height);
    buf = new Uint32Array(imageData.data.buffer);
    state.vals = new Uint8Array(config.rows * config.cols * 3);
    if (state.rawBytes) {
      rechunk();
      startBtn.disabled = !valid;
    } else { startBtn.disabled = true; }
    updateDerivedStats(); updateChips(); saveSettings();
  }

  const STORAGE_KEY = "hdmi_exfil_sender_settings";
  function saveSettings() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify({
      settingsVersion: 2,
      protocol: config.protocol, bpc: config.bpc,
      profileName: config.profileName, width: config.width, height: config.height,
      blockSize: config.blockSize, fpsMode: config.fpsMode, manualFps: config.manualFps,
      fountainRedundancy: config.fountainRedundancy,
      sequentialRedundancy: config.sequentialRedundancy,
      fountainAutoStop: config.fountainAutoStop,
    })); } catch(e) {}
  }
  function loadSettings() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY); if (!raw) return;
      const d = JSON.parse(raw);
      const isLegacySettings = Number(d.settingsVersion || 0) < 2;
      if (d.protocol) config.protocol = d.protocol;
      if (d.bpc && [1,2,3].includes(d.bpc)) config.bpc = d.bpc;
      if (d.profileName && PROFILES[d.profileName]) {
        const p = PROFILES[d.profileName];
        Object.assign(config, { profileName: d.profileName, width: p.width, height: p.height, blockSize: p.blockSize, targetFps: p.targetFps });
      } else if (d.profileName === "custom") {
        config.profileName = "custom";
        if (d.width) config.width = d.width; if (d.height) config.height = d.height;
        if (d.blockSize) config.blockSize = d.blockSize;
      }
      if (isLegacySettings) config.fpsMode = "profile";
      else if (d.fpsMode) config.fpsMode = d.fpsMode;
      if (d.manualFps) config.manualFps = d.manualFps;
      if (typeof d.fountainRedundancy === "number" && Number.isFinite(d.fountainRedundancy)) {
        config.fountainRedundancy = Math.max(0, Math.min(5, d.fountainRedundancy));
      }
      if (typeof d.sequentialRedundancy === "number" && Number.isFinite(d.sequentialRedundancy)) {
        config.sequentialRedundancy = Math.max(1, Math.min(16, Math.floor(d.sequentialRedundancy)));
      } else if (isLegacySettings) {
        config.sequentialRedundancy = 1;
      }
      if (typeof d.fountainAutoStop === "boolean") config.fountainAutoStop = d.fountainAutoStop;
    } catch(e) {}
  }

  function parseBoolParam(value) {
    if (value == null || value === "") return null;
    const normalized = String(value).trim().toLowerCase();
    if (["1", "true", "yes", "on"].includes(normalized)) return true;
    if (["0", "false", "no", "off"].includes(normalized)) return false;
    return null;
  }

  function applyUrlParams() {
    const params = new URLSearchParams(window.location.search);
    const protocol = params.get("protocol");
    if (protocol === "fountain" || protocol === "sequential") {
      config.protocol = protocol;
    }

    const bpc = Number(params.get("bpc"));
    if ([1, 2, 3].includes(bpc)) config.bpc = bpc;

    const profileName = params.get("profile");
    if (profileName && PROFILES[profileName]) {
      const p = PROFILES[profileName];
      Object.assign(config, {
        profileName,
        width: p.width,
        height: p.height,
        blockSize: p.blockSize,
        targetFps: p.targetFps,
      });
    }

    const fpsMode = params.get("fpsMode");
    if (["auto", "profile", "manual"].includes(fpsMode)) {
      config.fpsMode = fpsMode;
    }

    const manualFps = Number(params.get("manualFps"));
    if (Number.isFinite(manualFps) && manualFps >= 1 && manualFps <= 360) {
      config.manualFps = manualFps;
      if (config.fpsMode === "manual") config.targetFps = manualFps;
    }

    const fountainRedundancy = Number(params.get("fountainRedundancy"));
    if (Number.isFinite(fountainRedundancy)) {
      config.fountainRedundancy = Math.max(0, Math.min(5, fountainRedundancy));
    }

    const sequentialRedundancy = Number(params.get("sequentialRepeat") || params.get("sequentialRedundancy"));
    if (Number.isFinite(sequentialRedundancy)) {
      config.sequentialRedundancy = Math.max(1, Math.min(16, Math.floor(sequentialRedundancy)));
    }

    const fountainAutoStop = parseBoolParam(params.get("fountainAutoStop"));
    if (fountainAutoStop !== null) {
      config.fountainAutoStop = fountainAutoStop;
    }
    const apiBaseUrl = params.get("apiBaseUrl");
    runtimeOptions.apiBaseUrl = apiBaseUrl ? apiBaseUrl.trim() : "";
    runtimeOptions.debugTitle = parseBoolParam(params.get("debugTitle")) === true;

    return {
      payloadUrl: params.get("payload") || params.get("payloadUrl") || "",
      payloadName: params.get("name") || params.get("payloadName") || "",
      autoStart: parseBoolParam(params.get("autostart")) === true,
    };
  }

  function resolveReceiverApiUrl(path) {
    return new URL(path, runtimeOptions.apiBaseUrl || window.location.origin).toString();
  }

  function updateDebugTitle() {
    if (!runtimeOptions.debugTitle) return;
    let status = "IDLE";
    if (state.running) {
      if (state.phase === "preflight") status = "PREFLIGHT";
      else if (state.phase === "wait_complete") status = "WAIT_RX";
      else status = "TX";
    }
    document.title =
      `HDMI Exfil — Sender [${status}] ` +
      `f=${state.frame} k=${state.K} ` +
      `inner=${window.innerWidth}x${window.innerHeight} ` +
      `screen=${window.screenX},${window.screenY}`;
  }

  function fmtSize(b) {
    if (b < 1024) return b + " B";
    if (b < 1048576) return (b / 1024).toFixed(1) + " KB";
    return (b / 1048576).toFixed(2) + " MB";
  }

  function getDisplayedThroughputKbps() {
    const fps = getEffectiveFps();
    const repeats = config.protocol === "sequential"
      ? Math.max(1, config.sequentialRedundancy)
      : 1;
    return (config.payloadSize * fps) / repeats / 1024;
  }

  function updateDerivedStats() {
    const fps = getEffectiveFps();
    const kbps = getDisplayedThroughputKbps().toFixed(1);
    let extra = "";
    if (config.protocol === "fountain" && state.K > 0) {
      if (config.fountainAutoStop && state.fountainTargetFrames > 0) {
        const target = state.fountainTargetFrames;
        extra = `<br>Target droplets: ${target} (${config.fountainRedundancy.toFixed(2)}x K)`;
      } else {
        extra = "<br>Target droplets: manual stop (loop)";
      }
    } else if (config.protocol === "sequential" && config.sequentialRedundancy > 1) {
      extra = `<br>Frame repeat: ${config.sequentialRedundancy}x`;
    }
    derivedStatsEl.innerHTML =
      `${config.cols}x${config.rows} blocks &middot; ${config.payloadSize} B/frame<br>` +
      `~${kbps} KB/s throughput${extra}`;
    hudFps.textContent = fps;
    headerFps.textContent = fps;
  }

  function updateChips() {
    const fps = getEffectiveFps();
    const kbps = getDisplayedThroughputKbps().toFixed(1);
    const names = { speed: "Speed", balanced: "Balanced", quality: "Quality", custom: "Custom" };
    const protoNames = { fountain: "Fountain", sequential: "Sequential" };
    document.getElementById("chipProtocol").textContent = protoNames[config.protocol] || config.protocol;
    chipProfile.textContent = names[config.profileName] || config.profileName;
    chipSpeed.textContent = "~" + kbps + " KB/s";
    chipFps.textContent = fps + " fps";
  }

  function setSettingsEnabled(enabled) {
    [
      bpcSelect,
      protocolSelect,
      profileSelect,
      resolutionSelect,
      blockSizeSelect,
      fountainAutoStopInput,
      fpsModeSelect,
      manualFpsInput,
      sequentialRedundancyInput,
    ].forEach(el => el.disabled = !enabled);
    fountainRedundancyInput.disabled = !enabled || !config.fountainAutoStop;
  }

  function refreshProtocolControls() {
    fountainRedundancyRow.style.display = config.protocol === "fountain" ? "" : "none";
    sequentialRedundancyRow.style.display = config.protocol === "sequential" ? "" : "none";
    fountainAutoStopInput.checked = !!config.fountainAutoStop;
    fountainRedundancyInput.disabled = state.running || !config.fountainAutoStop;
    sequentialRedundancyInput.disabled = state.running;
  }

  // ── Core helpers ───────────────────────
  function wrapWithMetadata(file, rawBytes, sha256Hash) {
    const nameBytes = textEncoder.encode((file && file.name) || "payload.bin");
    const total = 4 + 32 + 2 + nameBytes.length + rawBytes.length;
    const out = new Uint8Array(total); const view = new DataView(out.buffer);
    let offset = 0;
    view.setUint32(offset, rawBytes.length, false); offset += 4;
    out.set(sha256Hash, offset); offset += 32;
    view.setUint16(offset, nameBytes.length, false); offset += 2;
    out.set(nameBytes, offset); offset += nameBytes.length;
    out.set(rawBytes, offset);
    return out;
  }

  function sleep(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  async function getPreflightPayload() {
    if (!preflightPayloadPromise) {
      preflightPayloadPromise = computeSHA256(PREFLIGHT_FILE_BYTES).then((sha256Hash) => {
        const total = 4 + 32 + 2 + preflightNameBytes.length;
        const payload = new Uint8Array(total);
        const view = new DataView(payload.buffer);
        let offset = 0;
        view.setUint32(offset, PREFLIGHT_FILE_BYTES.length, false);
        offset += 4;
        payload.set(sha256Hash, offset);
        offset += 32;
        view.setUint16(offset, preflightNameBytes.length, false);
        offset += 2;
        payload.set(preflightNameBytes, offset);
        return payload;
      });
    }
    return new Uint8Array(await preflightPayloadPromise);
  }

  function applyPreflightVisualFiller(frameBytes, usedPrefixLen) {
    const start = Math.max(0, usedPrefixLen | 0);
    if (start >= frameBytes.length) return;
    const pattern = PREFLIGHT_FILLER_BYTES;
    for (let offset = start; offset < frameBytes.length; offset += pattern.length) {
      const length = Math.min(pattern.length, frameBytes.length - offset);
      frameBytes.set(pattern.subarray(0, length), offset);
    }
  }

  async function getReceiverStatus() {
    const response = await fetch(resolveReceiverApiUrl("/api/receive/status"), { cache: "no-store" });
    if (!response.ok) throw new Error(`Receiver status unavailable (${response.status})`);
    return response.json();
  }

  async function shouldUseReceiverPreflight() {
    try {
      const status = await getReceiverStatus();
      return status.active && status.preflight_required === true;
    } catch {
      return false;
    }
  }

  async function waitForReceiverPreflight() {
    const deadline = performance.now() + PREFLIGHT_TIMEOUT_MS;
    let transferCandidateDeadline = 0;
    let transferCandidateBpc = Math.max(PREFLIGHT_BITS_PER_CHANNEL, config.bpc | 0);
    while (state.running && state.phase === "preflight") {
      try {
        const status = await getReceiverStatus();
        if (status.preflight_state === "ok") {
          const negotiated = Number(status.transfer_bpc || transferCandidateBpc || config.bpc);
          return {
            ok: true,
            transferBpc: [1, 2, 3].includes(negotiated) ? negotiated : config.bpc,
          };
        }
        if (status.active === false) return { ok: false, reason: "receiver_inactive" };

        const stage = String(status.preflight_stage || "path");
        if (stage === "transfer") {
          const requestedBpc = Number(status.requested_transfer_bpc || config.bpc);
          if (state.preflightPhase !== "transfer") {
            state.preflightPhase = "transfer";
            state.preflightRequestedBpc = [1, 2, 3].includes(requestedBpc)
              ? requestedBpc
              : Math.max(PREFLIGHT_BITS_PER_CHANNEL, config.bpc | 0);
            transferCandidateBpc = state.preflightRequestedBpc;
            state.preflightRenderBpc = transferCandidateBpc;
            transferCandidateDeadline =
              performance.now() + PREFLIGHT_TRANSFER_CANDIDATE_TIMEOUT_MS;
            configWarningEl.className = "side-note";
            configWarningEl.style.display = "";
            configWarningEl.textContent =
              `HDMI path validated. Probing transfer bpc=${transferCandidateBpc}...`;
          } else if (
            performance.now() >= transferCandidateDeadline
            && transferCandidateBpc > PREFLIGHT_BITS_PER_CHANNEL
          ) {
            const failedBpc = transferCandidateBpc;
            transferCandidateBpc -= 1;
            state.preflightRenderBpc = transferCandidateBpc;
            transferCandidateDeadline =
              performance.now() + PREFLIGHT_TRANSFER_CANDIDATE_TIMEOUT_MS;
            configWarningEl.className = "side-note warn";
            configWarningEl.style.display = "";
            configWarningEl.textContent =
              `Receiver did not confirm transfer bpc=${failedBpc}. Retrying bpc=${transferCandidateBpc}...`;
          }
        } else {
          state.preflightPhase = "path";
          state.preflightRenderBpc = PREFLIGHT_BITS_PER_CHANNEL;
          transferCandidateDeadline = 0;
        }
      } catch {
        // Keep rendering the preflight frame while the receiver catches up.
      }
      if (state.preflightPhase === "transfer" && transferCandidateDeadline > 0) {
        const transferTimedOut =
          transferCandidateBpc <= PREFLIGHT_BITS_PER_CHANNEL
          && performance.now() >= transferCandidateDeadline;
        if (transferTimedOut) {
          return { ok: false, reason: "transfer_bpc_timeout" };
        }
      } else if (performance.now() >= deadline) {
        return { ok: false, reason: "path_timeout" };
      }
      await sleep(PREFLIGHT_POLL_INTERVAL_MS);
    }
    return { ok: false, reason: "stopped" };
  }

  function applyNegotiatedTransferBpc(transferBpc) {
    if (![1, 2, 3].includes(transferBpc) || transferBpc === config.bpc) {
      return;
    }
    config.bpc = transferBpc;
    bpcSelect.value = String(transferBpc);
    recalcDerived();
    rechunk();
    saveSettings();
  }

  function getFountainReceiverWaitMaxMs() {
    const fps = Math.max(1, getEffectiveFps());
    const baseMs = state.fountainTargetFrames > 0
      ? Math.ceil((state.fountainTargetFrames / fps) * 1000)
      : 5000;
    return Math.max(FOUNTAIN_RECEIVER_WAIT_MIN_MS, baseMs * 20);
  }

  async function waitForReceiverCompletion() {
    const deadline = performance.now() + getFountainReceiverWaitMaxMs();
    while (state.running && state.phase === "wait_complete") {
      try {
        const status = await getReceiverStatus();
        if (status.active === false) return true;
      } catch {
        // Keep transmitting while the receiver finishes or reconnects.
      }
      if (performance.now() >= deadline) return false;
      await sleep(FOUNTAIN_RECEIVER_WAIT_POLL_MS);
    }
    return false;
  }

  async function maybeSwitchFountainToReceiverWait() {
    if (!state.running || !state.receiverDrivenFountainStop || state.phase === "wait_complete") {
      return;
    }
    state.phase = "wait_complete";
    statusLabel.textContent = "Awaiting receiver";
    statusLabel.style.color = "var(--yellow)";
    configWarningEl.className = "side-note";
    configWarningEl.style.display = "";
    configWarningEl.textContent =
      "Receiver still active after local fountain target. Continuing droplets...";
    updateDebugTitle();

    const completed = await waitForReceiverCompletion();
    if (!state.running || state.phase !== "wait_complete") return;

    if (completed) {
      stopSending({
        statusText: "Completed",
        saveHistory: true,
      });
      return;
    }

    stopSending({
      saveHistory: false,
      statusText: "Receiver timeout",
      warningText: (
        "Receiver still active after local fountain target. "
        + "Transmission stopped after timeout."
      ),
    });
  }

  function sliceIntoChunks(bytes) {
    const ps = config.payloadSize;
    const K = Math.ceil(bytes.length / ps);
    const chunks = new Array(K);
    for (let i = 0; i < K; i++) {
      const chunk = new Uint8Array(ps);
      chunk.set(bytes.subarray(i * ps, Math.min((i + 1) * ps, bytes.length)));
      chunks[i] = chunk;
    }
    return { K, chunks };
  }

  // ── PRNG + Robust Soliton ─────────────
  function createPRNG(seed) {
    let a = seed >>> 0;
    return () => {
      a = (a + 0x9e3779b9) >>> 0;
      let t = a ^ (a >>> 16); t = Math.imul(t, 0x21f0aaad) >>> 0;
      t ^= t >>> 15; t = Math.imul(t, 0x735a2d97) >>> 0; t ^= t >>> 15;
      return t >>> 0;
    };
  }
  const RSD_C = 0.1, RSD_DELTA = 0.05;
  const RSD_CDF_CACHE_MAX = 8;
  const rsdCdfCache = new Map();
  function robustSolitonCdf(K) {
    const cached = rsdCdfCache.get(K);
    if (cached) return cached;
    if (K === 1) return [0.0, 1.0];
    const rho = new Array(K+1).fill(0); rho[1] = 1.0/K;
    for (let d = 2; d <= K; d++) rho[d] = 1.0/(d*(d-1));
    const S = RSD_C * Math.log(K/RSD_DELTA) * Math.sqrt(K);
    const pivot = Math.max(1, Math.floor(K/S));
    const tau = new Array(K+1).fill(0);
    for (let d = 1; d < Math.min(pivot,K+1); d++) tau[d] = S/(K*d);
    if (pivot <= K) tau[pivot] += (S/K)*Math.log(S/RSD_DELTA);
    let Z = 0; for (let d = 1; d <= K; d++) Z += rho[d]+tau[d];
    const cdf = new Array(K+1).fill(0); let cum = 0;
    for (let d = 1; d <= K; d++) { cum += (rho[d]+tau[d])/Z; cdf[d] = cum; }
    cdf[K] = 1.0;
    if (rsdCdfCache.size >= RSD_CDF_CACHE_MAX) rsdCdfCache.clear();
    rsdCdfCache.set(K, cdf);
    return cdf;
  }
  function sampleDegree(cdf, r) {
    let lo = 1, hi = cdf.length-1;
    while (lo < hi) { const mid = (lo+hi)>>1; if (cdf[mid] < r) lo = mid+1; else hi = mid; }
    return Math.max(1, Math.min(lo, cdf.length-1));
  }
  function chooseIndices(seed, K) {
    const next = createPRNG(seed);
    const cdf = (
      state.rsdCdf && state.rsdCdf.length === K + 1
        ? state.rsdCdf
        : robustSolitonCdf(K)
    );
    let degree = Math.min(sampleDegree(cdf, next()/0x100000000), K);
    const indices = new Set();
    while (indices.size < degree) indices.add(next() % K);
    return Array.from(indices);
  }
  function buildDroplet(seed) {
    const ps = config.payloadSize;
    const idxs = chooseIndices(seed, state.K);
    const payload = new Uint8Array(ps);
    for (const idx of idxs) { const chunk = state.chunks[idx]; for (let i = 0; i < ps; i++) payload[i] ^= chunk[i]; }
    return payload;
  }

  // ── Sequential frame builders ──────────
  function buildSeqFrame(frameType, frameIndex, totalFrames, payload, bytesPerFrame = config.bytesPerFrame) {
    const frameBytes = new Uint8Array(bytesPerFrame);
    const view = new DataView(frameBytes.buffer);
    // Pre-CRC header (13 bytes)
    view.setUint16(0, SEQ_MAGIC, false);
    view.setUint8(2, frameType);
    view.setUint32(3, frameIndex, false);
    view.setUint32(7, totalFrames, false);
    view.setUint16(11, payload.length, false);
    // CRC32 over pre-CRC header + payload
    const crcInput = new Uint8Array(SEQ_HEADER_PRE_CRC + payload.length);
    crcInput.set(frameBytes.subarray(0, SEQ_HEADER_PRE_CRC));
    crcInput.set(payload, SEQ_HEADER_PRE_CRC);
    view.setUint32(13, crc32(crcInput), false);
    // Payload
    frameBytes.set(payload, SEQ_HEADER_LEN);
    return frameBytes;
  }

  function buildSeqStartPayload() {
    const nameBytes = textEncoder.encode(state.fileName || "payload.bin");
    const meta = new Uint8Array(4 + 32 + 2 + nameBytes.length);
    const mv = new DataView(meta.buffer);
    mv.setUint32(0, state.fileSize, false);
    meta.set(state.sha256Hash, 4);
    mv.setUint16(36, nameBytes.length, false);
    meta.set(nameBytes, 38);
    return meta;
  }

  function sliceSeqChunks(rawBytes) {
    const ps = config.payloadSize;
    const K = Math.ceil(rawBytes.length / ps);
    const chunks = new Array(K);
    for (let i = 0; i < K; i++) {
      chunks[i] = rawBytes.slice(i * ps, Math.min((i + 1) * ps, rawBytes.length));
    }
    return { K, chunks };
  }

  // ── Encoding ───────────────────────────
  function bytesToValues(bytes, bpc = config.bpc) {
    let p = 0;
    if (bpc === 1) {
      for (let i = 0; i < bytes.length; i++) {
        const b = bytes[i];
        state.vals[p++]=(b>>7)&1; state.vals[p++]=(b>>6)&1; state.vals[p++]=(b>>5)&1; state.vals[p++]=(b>>4)&1;
        state.vals[p++]=(b>>3)&1; state.vals[p++]=(b>>2)&1; state.vals[p++]=(b>>1)&1; state.vals[p++]=b&1;
      }
    } else {
      // Extract bpc-bit groups from byte stream using a bit buffer.
      // Important: outer loop must NOT check byteIdx — after reading the
      // last byte there are still bits in the buffer to extract.
      let bitBuf = 0, bitsLeft = 0;
      const mask = (1 << bpc) - 1;
      const totalVals = config.rows * config.cols * 3;
      let byteIdx = 0;
      while (p < totalVals) {
        while (bitsLeft < bpc && byteIdx < bytes.length) {
          bitBuf = (bitBuf << 8) | bytes[byteIdx++];
          bitsLeft += 8;
        }
        if (bitsLeft >= bpc) {
          bitsLeft -= bpc;
          state.vals[p++] = (bitBuf >> bitsLeft) & mask;
        } else {
          break; // no more bits available
        }
      }
    }
  }
  function drawValues(vals, bpc = config.bpc) {
    const W = config.width, BS = config.blockSize, R = config.rows, C = config.cols;
    const levels = BPC_LEVELS[bpc];
    let vi = 0;
    for (let r = 0; r < R; r++) { const sy = r*BS;
      for (let c = 0; c < C; c++) {
        const rV = levels[vals[vi++]], gV = levels[vals[vi++]], bV = levels[vals[vi++]];
        const color = 0xFF000000|(bV<<16)|(gV<<8)|rV;
        const sx = c*BS;
        for (let y = 0; y < BS; y++) { const ro = (sy+y)*W+sx; buf.fill(color, ro, ro+BS); }
      }
    }
    ctx.putImageData(imageData, 0, 0);
  }

  // ── Render loop ────────────────────────
  let lastFrameTime = 0;

  function renderFountainFrame() {
    const seed = state.seed >>> 0;
    const payload = buildDroplet(seed);
    const expectedDroplets = (state.fountainTargetFrames > 0)
      ? state.fountainTargetFrames >>> 0
      : 0;
    const frameBytes = new Uint8Array(config.bytesPerFrame);
    const view = new DataView(frameBytes.buffer);
    view.setUint16(0, FOUNTAIN_MAGIC, false);
    view.setUint32(2, seed, false);
    view.setUint16(6, state.K, false);
    view.setUint32(8, expectedDroplets, false);
    frameBytes.set(payload, FOUNTAIN_HEADER_LEN);
    const crcData = new Uint8Array(FOUNTAIN_HEADER_PRE_CRC + payload.length);
    crcData.set(frameBytes.subarray(0, FOUNTAIN_HEADER_PRE_CRC));
    crcData.set(payload, FOUNTAIN_HEADER_PRE_CRC);
    view.setUint32(FOUNTAIN_HEADER_PRE_CRC, crc32(crcData), false);
    bytesToValues(frameBytes, config.bpc); drawValues(state.vals, config.bpc);
    state.seed = (state.seed + 1) >>> 0; if (state.seed === 0) state.seed = 1;
  }

  function renderSeqFrame() {
    let frameBytes;
    const seqRedundancy = Math.max(1, config.sequentialRedundancy | 0);
    if (state.seqPhase === "start") {
      const meta = buildSeqStartPayload();
      frameBytes = buildSeqFrame(FRAME_TYPE_START, 0, state.K, meta);
      state.seqRepeat++;
      if (state.seqRepeat >= seqRedundancy) {
        state.seqPhase = "data"; state.seqDataIdx = 0; state.seqRepeat = 0;
      }
    } else if (state.seqPhase === "data") {
      const chunk = state.chunks[state.seqDataIdx];
      frameBytes = buildSeqFrame(FRAME_TYPE_DATA, state.seqDataIdx, state.K, chunk);
      state.seqRepeat++;
      if (state.seqRepeat >= seqRedundancy) {
        state.seqRepeat = 0; state.seqDataIdx++;
        if (state.seqDataIdx >= state.K) { state.seqPhase = "end"; }
      }
    } else {
      frameBytes = buildSeqFrame(FRAME_TYPE_END, state.K, state.K, new Uint8Array([0]));
      state.seqRepeat++;
      if (state.seqRepeat >= seqRedundancy) {
        // Loop: restart transmission
        state.seqPhase = "start"; state.seqRepeat = 0;
      }
    }
    bytesToValues(frameBytes, config.bpc); drawValues(state.vals, config.bpc);
  }

  function renderPreflightFrame() {
    if (!state.preflightPayload) return;
    const preflightBpc = Math.max(
      PREFLIGHT_BITS_PER_CHANNEL,
      Math.min(3, state.preflightRenderBpc | 0),
    );
    const preflightBytesPerFrame = bytesPerFrameForBpc(preflightBpc);
    const frameBytes = buildSeqFrame(
      FRAME_TYPE_START,
      0,
      PREFLIGHT_TOTAL_FRAMES,
      state.preflightPayload,
      preflightBytesPerFrame,
    );
    applyPreflightVisualFiller(
      frameBytes,
      SEQ_HEADER_LEN + state.preflightPayload.length,
    );
    bytesToValues(frameBytes, preflightBpc);
    drawValues(state.vals, preflightBpc);
  }

  function renderFrame() {
    if (state.phase === "preflight") {
      renderPreflightFrame();
      state.preflightFrames += 1;
      state.lastRenderAt = performance.now();
      if (state.preflightFrames % 20 === 0) {
        hudFrames.textContent = state.preflightFrames;
        headerFrames.textContent = state.preflightFrames;
        const elapsed = (performance.now() - state.startTime) / 1000;
        const m = Math.floor(elapsed / 60), s = Math.floor(elapsed % 60);
        const t = `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
        hudTime.textContent = t;
        headerTime.textContent = t;
        updateDebugTitle();
      }
      return;
    }
    if (config.protocol === "fountain") renderFountainFrame();
    else renderSeqFrame();
    state.frame += 1;
    state.lastRenderAt = performance.now();
    if (
      config.protocol === "fountain"
      && config.fountainAutoStop
      && state.fountainTargetFrames > 0
      && state.frame >= state.fountainTargetFrames
    ) {
      if (state.receiverDrivenFountainStop) {
        void maybeSwitchFountainToReceiverWait();
        return;
      }
      stopSending();
      return;
    }
    if (state.frame % 20 === 0) {
      hudFrames.textContent = state.frame;
      headerFrames.textContent = state.frame;
      const elapsed = (performance.now() - state.startTime) / 1000;
      const m = Math.floor(elapsed / 60), s = Math.floor(elapsed % 60);
      const t = `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
      hudTime.textContent = t;
      headerTime.textContent = t;
      updateDebugTitle();
    }
  }
  function renderLoop(timestamp) {
    if (!state.running) return;
    try {
      const eFps = getEffectiveFps(), mHz = config.detectedHz || 60;
      if (eFps >= mHz) renderFrame();
      else {
        const interval = 1000 / eFps;
        if (timestamp - lastFrameTime >= interval * 0.95) {
          renderFrame();
          lastFrameTime = timestamp;
        }
      }
    } catch (err) {
      console.error("Sender render loop failed", err);
      configWarningEl.className = "side-note warn";
      configWarningEl.style.display = "";
      configWarningEl.textContent = "Render stall detected. Recovering loop...";
    } finally {
      if (state.running) state.raf = requestAnimationFrame(renderLoop);
    }
  }

  function checkViewportGeometry() {
    const vw = canvasWrap.clientWidth || window.innerWidth;
    const vh = canvasWrap.clientHeight || window.innerHeight;
    if (vw === config.width && vh === config.height) {
      if (!state.running) {
        configWarningEl.style.display = "none";
      }
      return;
    }
    configWarningEl.className = "side-note warn";
    configWarningEl.style.display = "";
    configWarningEl.textContent =
      `Viewport mismatch: ${vw}x${vh} (expected ${config.width}x${config.height}). ` +
      "Receiver auto-align may be required.";
  }

  // ── Start / Stop ───────────────────────
  async function startSending() {
    if (!state.chunks.length || !validateConfig() || state.running) return;
    state.running = true; state.seed = 1; state.frame = 0;
    state.seqPhase = "start"; state.seqDataIdx = 0; state.seqRepeat = 0;
      state.phase = "idle";
      state.preflightFrames = 0;
      state.preflightPayload = null;
      state.preflightPhase = "path";
      state.preflightRenderBpc = PREFLIGHT_BITS_PER_CHANNEL;
      state.preflightRequestedBpc = config.bpc;
      state.preflightNegotiatedBpc = config.bpc;
      state.receiverDrivenFountainStop = false;
    startBtn.disabled = true; stopBtn.disabled = false;
    setSettingsEnabled(false);
    statusLabel.textContent = "Starting";
    statusLabel.classList.remove("dim");
    statusLabel.style.color = "var(--yellow)";
    canvasWrap.classList.add("active");
    hud.classList.add("active");
    updateDebugTitle();
    const begin = async () => {
      if (!state.running) return;
      checkViewportGeometry();
      state.startTime = performance.now();
      state.lastRenderAt = state.startTime;
      lastFrameTime = 0;
      const shouldPreflight = await shouldUseReceiverPreflight();
      if (shouldPreflight) {
        state.preflightPayload = await getPreflightPayload();
        state.phase = "preflight";
        state.preflightFrames = 0;
        state.preflightPhase = "path";
        state.preflightRenderBpc = PREFLIGHT_BITS_PER_CHANNEL;
        state.preflightRequestedBpc = Math.max(PREFLIGHT_BITS_PER_CHANNEL, config.bpc | 0);
        state.preflightNegotiatedBpc = state.preflightRequestedBpc;
        statusLabel.textContent = "Preflight";
        statusLabel.style.color = "var(--yellow)";
        configWarningEl.className = "side-note";
        configWarningEl.style.display = "";
        configWarningEl.textContent = "Validating HDMI path on receiver...";
        renderLoop(0);
        const preflight = await waitForReceiverPreflight();
        if (!preflight.ok) {
          if (state.running) {
            const warningText = preflight.reason === "transfer_bpc_timeout"
              ? (
                "Receiver did not confirm any supported transfer bpc. "
                + "Check the HDMI duplication path or lower the target profile."
              )
              : (
                "Receiver did not confirm the HDMI preflight frame. "
                + "Check the HDMI duplication path."
              );
            stopSending({
              saveHistory: false,
              statusText: "Preflight failed",
              warningText,
            });
          }
          return;
        }
        state.preflightNegotiatedBpc = preflight.transferBpc;
        if (preflight.transferBpc !== config.bpc) {
          applyNegotiatedTransferBpc(preflight.transferBpc);
          configWarningEl.className = "side-note warn";
          configWarningEl.style.display = "";
          configWarningEl.textContent =
            `Transfer bpc downgraded automatically to ${preflight.transferBpc}.`;
        }
        await sleep(PREFLIGHT_SETTLE_MS);
      }
      if (!state.running) return;
      state.receiverDrivenFountainStop = (
        shouldPreflight
        && config.protocol === "fountain"
        && config.fountainAutoStop
      );
      state.phase = "transmitting";
      state.frame = 0;
      state.startTime = performance.now();
      state.lastRenderAt = state.startTime;
      headerFrames.textContent = "0";
      hudFrames.textContent = "0";
      statusLabel.textContent = "Transmitting";
      statusLabel.style.color = "var(--green)";
      if (configWarningEl.textContent === "Validating HDMI path on receiver...") {
        configWarningEl.style.display = "none";
        configWarningEl.textContent = "";
      }
      if (!state.raf) renderLoop(0);
    };
    const fsReq = document.documentElement.requestFullscreen
      ? document.documentElement.requestFullscreen()
      : Promise.resolve();
    Promise.resolve(fsReq).catch(() => {}).finally(() => setTimeout(begin, 120));
  }

  function stopSending(options = {}) {
    const {
      saveHistory = state.phase !== "preflight" && state.frame > 0 && !!state.fileName,
      statusText = "Stopped",
      warningText = "",
    } = options;
    const finalFrames = state.phase === "preflight" ? state.preflightFrames : state.frame;
    state.running = false;
    if (state.raf) cancelAnimationFrame(state.raf);
    state.raf = null;
    if (document.fullscreenElement) document.exitFullscreen();
    drawValues(new Uint8Array(config.rows * config.cols * 3));
    canvasWrap.classList.remove("active");
    hud.classList.remove("active");
    startBtn.disabled = !state.chunks.length; stopBtn.disabled = true;
    setSettingsEnabled(true);
    state.phase = "idle";
    state.preflightFrames = 0;
    state.preflightPayload = null;
    state.preflightPhase = "path";
    state.preflightRenderBpc = PREFLIGHT_BITS_PER_CHANNEL;
    state.preflightRequestedBpc = config.bpc;
    state.preflightNegotiatedBpc = config.bpc;
    state.receiverDrivenFountainStop = false;
    statusLabel.textContent = statusText;
    statusLabel.classList.add("dim");
    statusLabel.style.color = "";
    headerFrames.textContent = finalFrames;
    const elapsed = (performance.now() - state.startTime) / 1000;
    if (warningText) {
      configWarningEl.className = "side-note warn";
      configWarningEl.style.display = "";
      configWarningEl.textContent = warningText;
    } else if (
      configWarningEl.textContent === "Validating HDMI path on receiver..."
      || configWarningEl.textContent === "Receiver still active after local fountain target. Continuing droplets..."
    ) {
      configWarningEl.style.display = "none";
      configWarningEl.textContent = "";
    }
    updateDebugTitle();
    if (saveHistory) {
      saveHistory({
        type: "sent", filename: state.fileName, size: state.fileSize,
        duration: elapsed, speed: elapsed > 0 ? state.fileSize / elapsed : 0,
        success: true, timestamp: Date.now(),
        protocol: config.protocol,
        systemPath: "",
      });
    }
  }

  function saveHistory(entry) {
    try {
      const key = "hdmi_exfil_history";
      const items = JSON.parse(localStorage.getItem(key) || "[]");
      items.push(entry);
      if (items.length > 200) items.splice(0, items.length - 200);
      localStorage.setItem(key, JSON.stringify(items));
    } catch {}
  }

  // ── File handling ──────────────────────
  async function applyLoadedBytes(raw, fileName) {
    const sha256Hash = await computeSHA256(raw);
    state.rawBytes = raw;
    state.sha256Hash = sha256Hash;
    state.fileName = fileName;
    state.fileSize = raw.length;
    rechunk();
    startBtn.disabled = false; stopBtn.disabled = true;

    fileNameEl.textContent = fileName;
    fileSizeEl.textContent = fmtSize(raw.length);
    dropZone.classList.add("loaded");
  }

  function handleFile(file) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async () => {
      const raw = new Uint8Array(reader.result);
      await applyLoadedBytes(raw, file.name);
    };
    reader.readAsArrayBuffer(file);
  }

  async function loadPayloadFromUrl(url, suggestedName = "") {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) throw new Error(`Unable to fetch payload (${res.status})`);
    const raw = new Uint8Array(await res.arrayBuffer());
    let fileName = suggestedName;
    if (!fileName) {
      try {
        const parsed = new URL(url, window.location.href);
        fileName = parsed.pathname.split("/").filter(Boolean).pop() || "payload.bin";
      } catch {
        fileName = "payload.bin";
      }
    }
    await applyLoadedBytes(raw, fileName);
  }

  function rechunk() {
    if (!state.rawBytes) return;
    if (config.protocol === "fountain") {
      const wrapped = wrapWithMetadata({ name: state.fileName }, state.rawBytes, state.sha256Hash);
      state.rawWrapped = wrapped;
      const { K, chunks } = sliceIntoChunks(wrapped);
      state.chunks = chunks; state.K = K;
      state.rsdCdf = robustSolitonCdf(K);
      state.fountainTargetFrames = (config.fountainAutoStop && config.fountainRedundancy > 0)
        ? Math.ceil(state.K * config.fountainRedundancy)
        : 0;
    } else {
      const { K, chunks } = sliceSeqChunks(state.rawBytes);
      state.chunks = chunks; state.K = K;
      state.rsdCdf = null;
      state.fountainTargetFrames = 0;
    }
    state.seed = 1; state.frame = 0;
    fileChunksEl.textContent = state.K + " chunks";
    headerK.textContent = state.K; hudK.textContent = state.K;
    updateChips();
    updateDerivedStats();
  }

  fileInput.addEventListener("change", (e) => handleFile(e.target.files[0]));
  fileInputAlt.addEventListener("change", (e) => handleFile(e.target.files[0]));

  dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.classList.add("dragover"); });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault(); dropZone.classList.remove("dragover");
    if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
  });

  startBtn.addEventListener("click", startSending);
  stopBtn.addEventListener("click", stopSending);

  advToggle.addEventListener("click", () => {
    advToggle.classList.toggle("open");
    advBody.classList.toggle("open");
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.preventDefault(); if (state.running) stopSending(); }
    else if (e.key === " " && e.target === document.body) {
      e.preventDefault();
      if (state.running) stopSending();
      else if (state.chunks.length) startSending();
    }
  });

  document.addEventListener("fullscreenchange", () => {
    if (!state.running) return;
    if (document.fullscreenElement) return;
    // Keep streaming if fullscreen is lost (focus changes can trigger this).
    checkViewportGeometry();
    configWarningEl.className = "side-note warn";
    configWarningEl.style.display = "";
    configWarningEl.textContent =
      "Fullscreen exited. Transmission continues in windowed mode.";
  });

  setInterval(() => {
    if (!state.running) return;
    const dt = performance.now() - state.lastRenderAt;
    if (dt <= 2500) return;
    if (state.raf) cancelAnimationFrame(state.raf);
    state.raf = requestAnimationFrame(renderLoop);
    configWarningEl.className = "side-note warn";
    configWarningEl.style.display = "";
    configWarningEl.textContent =
      "Sender loop stalled briefly. Auto-restarting render loop...";
  }, 1000);

  // ── Settings events ────────────────────
  bpcSelect.addEventListener("change", () => {
    config.bpc = Number(bpcSelect.value);
    applyConfig();
  });
  protocolSelect.addEventListener("change", () => {
    config.protocol = protocolSelect.value;
    refreshProtocolControls();
    applyConfig();
  });
  profileSelect.addEventListener("change", () => {
    const name = profileSelect.value; if (name === "custom") return;
    const p = PROFILES[name];
    Object.assign(config, { profileName: name, width: p.width, height: p.height, blockSize: p.blockSize, targetFps: p.targetFps });
    resolutionSelect.value = `${p.width}x${p.height}`;
    blockSizeSelect.value = String(p.blockSize);
    if (config.fpsMode === "profile") { config.manualFps = p.targetFps; manualFpsInput.value = p.targetFps; }
    applyConfig();
  });
  resolutionSelect.addEventListener("change", () => {
    const [w, h] = resolutionSelect.value.split("x").map(Number);
    config.width = w; config.height = h;
    profileSelect.value = "custom"; config.profileName = "custom";
    applyConfig();
  });
  blockSizeSelect.addEventListener("change", () => {
    config.blockSize = Number(blockSizeSelect.value);
    profileSelect.value = "custom"; config.profileName = "custom";
    applyConfig();
  });
  fpsModeSelect.addEventListener("change", () => {
    config.fpsMode = fpsModeSelect.value;
    manualRow.style.display = config.fpsMode === "manual" ? "" : "none";
    if (config.fpsMode === "auto") config.targetFps = config.detectedHz || 60;
    else if (config.fpsMode === "profile") { const p = PROFILES[config.profileName]; config.targetFps = p ? p.targetFps : 60; }
    updateDerivedStats(); updateChips(); saveSettings();
  });
  manualFpsInput.addEventListener("change", () => {
    const val = Math.max(1, Math.min(360, Number(manualFpsInput.value)));
    config.manualFps = val; config.targetFps = val; manualFpsInput.value = val;
    updateDerivedStats(); updateChips(); saveSettings();
  });
  sequentialRedundancyInput.addEventListener("change", () => {
    const val = Math.max(1, Math.min(16, Math.floor(Number(sequentialRedundancyInput.value))));
    config.sequentialRedundancy = Number.isFinite(val) ? val : 1;
    sequentialRedundancyInput.value = String(config.sequentialRedundancy);
    updateDerivedStats();
    updateChips();
    saveSettings();
  });
  fountainRedundancyInput.addEventListener("change", () => {
    const val = Math.max(0, Math.min(5, Number(fountainRedundancyInput.value)));
    config.fountainRedundancy = Number.isFinite(val) ? val : 1.5;
    fountainRedundancyInput.value = config.fountainRedundancy.toFixed(2);
    if (state.rawBytes && config.protocol === "fountain") rechunk();
    updateDerivedStats();
    saveSettings();
  });
  fountainAutoStopInput.addEventListener("change", () => {
    config.fountainAutoStop = !!fountainAutoStopInput.checked;
    if (state.rawBytes && config.protocol === "fountain") rechunk();
    refreshProtocolControls();
    updateDerivedStats();
    saveSettings();
  });

  // ── Init ───────────────────────────────
  loadSettings();
  const urlOptions = applyUrlParams();
  recalcDerived();
  bpcSelect.value = String(config.bpc);
  protocolSelect.value = config.protocol;
  profileSelect.value = config.profileName;
  resolutionSelect.value = `${config.width}x${config.height}`;
  blockSizeSelect.value = String(config.blockSize);
  fountainRedundancyInput.value = config.fountainRedundancy.toFixed(2);
  sequentialRedundancyInput.value = String(config.sequentialRedundancy);
  fpsModeSelect.value = config.fpsMode;
  manualFpsInput.value = config.manualFps;
  manualRow.style.display = config.fpsMode === "manual" ? "" : "none";
  refreshProtocolControls();
  canvas.width = config.width; canvas.height = config.height;
  imageData = ctx.createImageData(config.width, config.height);
  buf = new Uint32Array(imageData.data.buffer);
  state.vals = new Uint8Array(config.rows * config.cols * 3);
  validateConfig();
  updateDerivedStats(); updateChips();
  updateDebugTitle();

  detectRefreshRate().then((hz) => {
    config.detectedHz = hz;
    detectedHzEl.textContent = `Monitor: ${hz} Hz detected`;
    hudFps.textContent = getEffectiveFps();
    headerFps.textContent = getEffectiveFps();
    if (config.fpsMode === "auto") config.targetFps = hz;
    updateDerivedStats(); updateChips();
  });

  if (urlOptions.payloadUrl) {
    loadPayloadFromUrl(urlOptions.payloadUrl, urlOptions.payloadName)
      .then(() => {
        if (!urlOptions.autoStart) return;
        window.setTimeout(() => {
          if (!state.running && state.chunks.length) startSending();
        }, 300);
      })
      .catch((err) => {
        console.error("Auto payload load failed", err);
        configWarningEl.className = "side-note warn";
        configWarningEl.style.display = "";
        configWarningEl.textContent = `Auto payload load failed: ${err.message || err}`;
      });
  }
