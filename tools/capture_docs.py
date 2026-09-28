"""Capture the real UI with an empty, isolated receiver (no hardware access).

Requires the dev extra and Chrome. Run: uv run python tools/capture_docs.py
"""

from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from werkzeug.serving import make_server

from hdmi_transfer.adapters.capture.capture_manager import CaptureManager
from hdmi_transfer.adapters.capture.device_registry import DeviceRegistry
from hdmi_transfer.interfaces.web import create_app

ROOT = Path(__file__).resolve().parents[1]


def no_capture(*args, **kwargs):
    raise RuntimeError("Documentation capture must never open hardware")


def main():
    destination = ROOT / "docs" / "images"
    destination.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="hdmi-docs-") as temporary:
        app = create_app(output_dir=temporary, runtime=False)
        app._device_registry = DeviceRegistry(Path(temporary) / "devices.json")
        app._capture_manager = CaptureManager(opener=no_capture)
        server = make_server("127.0.0.1", 0, app, threaded=True)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        options = webdriver.ChromeOptions()
        options.page_load_strategy = "eager"
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1600,1100")
        options.add_argument("--force-device-scale-factor=1")
        options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
        try:
            with webdriver.Chrome(options=options) as browser:
                base = f"http://127.0.0.1:{server.server_port}"
                wait = WebDriverWait(browser, 20)
                for route, name in [("/", "receiver"), ("/sender", "sender"), ("/settings", "settings")]:
                    browser.get(base + route)
                    wait.until(lambda driver: driver.execute_script("return document.readyState") != "loading")
                    if name == "receiver":
                        wait.until(lambda driver: "Detecting" not in driver.find_element(By.ID, "deviceSelect").text)
                    if name == "sender":
                        browser.switch_to.frame("sender-frame")
                        sample = Path(temporary) / "hello-hdmi.txt"
                        sample.write_text("Hello from HDMI Transfer!\n", encoding="utf-8")
                        browser.find_element(By.ID, "fileInput").send_keys(str(sample))
                        wait.until(lambda driver: driver.find_element(By.ID, "startBtn").is_enabled())
                        wait.until(lambda driver: "Detecting" not in driver.find_element(By.ID, "detectedHz").text)
                        browser.switch_to.default_content()
                    assert browser.save_screenshot(str(destination / f"{name}.png"))
                    errors = [entry for entry in browser.get_log("browser") if entry["level"] == "SEVERE"]
                    if errors:
                        raise RuntimeError(f"Browser errors on {route}: {errors}")
                    print(f"Captured {name}.png")
                browser.get((ROOT / "sender.html").as_uri())
                browser.find_element(By.ID, "fileInput").send_keys(str(sample))
                wait.until(lambda driver: driver.find_element(By.ID, "startBtn").is_enabled())
                assert "offline" in browser.find_element(By.ID, "modeCallout").text
                errors = [entry for entry in browser.get_log("browser") if entry["level"] == "SEVERE"]
                if errors:
                    raise RuntimeError(f"Standalone sender errors: {errors}")
                print("Local file:// sender: sample loaded, offline mode verified")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            app.shutdown_runtime()


if __name__ == "__main__":
    main()
