Import("env")

from pathlib import Path
from urllib.request import urlopen

GAUGE_URL = "https://cdn.jsdelivr.net/npm/canvas-gauges@2.1.7/gauge.min.js"
PROJECT_DIR = Path(env.subst("$PROJECT_DIR"))
GAUGE_DST = PROJECT_DIR / "src" / "data" / "gauge.min.js"
WEBFILES_HDR = PROJECT_DIR / "src" / "webfiles.h"


def _sync_embedded_gauge(payload):
    source = WEBFILES_HDR.read_text(encoding="utf-8")
    marker = 'const char GAUGE_JS[] PROGMEM = R"rawliteral('
    start = source.find(marker)
    if start < 0:
        raise RuntimeError("GAUGE_JS marker not found in webfiles.h")

    data_start = source.find("\n", start)
    if data_start < 0:
        raise RuntimeError("Could not find GAUGE_JS payload start")
    data_start += 1

    end_marker = '\n)rawliteral";'
    data_end = source.find(end_marker, data_start)
    if data_end < 0:
        raise RuntimeError("Could not find GAUGE_JS payload end")

    new_source = source[:data_start] + payload + source[data_end:]
    if new_source != source:
        WEBFILES_HDR.write_text(new_source, encoding="utf-8")
        print("[webui] Synced embedded GAUGE_JS in src/webfiles.h")


def _download_gauge(*args, **kwargs):
    print("[webui] Downloading gauge.min.js...")
    try:
        with urlopen(GAUGE_URL, timeout=15) as response:
            payload = response.read().decode("utf-8")

        if "RadialGauge" not in payload:
            raise RuntimeError("Downloaded gauge.min.js does not look valid")

        GAUGE_DST.parent.mkdir(parents=True, exist_ok=True)
        GAUGE_DST.write_text(payload, encoding="utf-8")
        print("[webui] Updated src/data/gauge.min.js")
        _sync_embedded_gauge(payload)
    except Exception as exc:
        print(f"[webui] gauge.min.js download skipped: {exc}")


# Run immediately when script is loaded so embedded assets are updated before compilation.
_download_gauge()
