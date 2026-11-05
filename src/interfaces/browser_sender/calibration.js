// Offline confirmations are local user choices, never receiver acknowledgements.
const calibrationMemory = (() => {
  const storageKey = "hdmi_transfer_calibration_v1";
  function signature(config) {
    const signal = document.getElementById("canvas");
    return JSON.stringify([
      1, config.profileName, config.width, config.height, config.blockSize,
      config.bpc, config.protocol, config.fpsMode, config.manualFps,
      window.screen.width, window.screen.height, window.devicePixelRatio,
      window.screenX, window.screenY,
      signal.clientWidth || window.innerWidth,
      signal.clientHeight || window.innerHeight,
    ]);
  }
  function confirmed(config) {
    try { return localStorage.getItem(storageKey) === signature(config); }
    catch { return false; }
  }
  function remember(config) {
    try { localStorage.setItem(storageKey, signature(config)); } catch {}
  }
  function forget() {
    try { localStorage.removeItem(storageKey); } catch {}
  }
  return { confirmed, remember, forget };
})();
