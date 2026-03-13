"""
Polls RGYC wind image every minute, extracts wind speed and direction from blue overlay boxes.
"""
import os
import json

import requests
from io import BytesIO

import pytesseract
# python

import subprocess
from datetime import datetime
import time
from PIL import Image, ImageTk, ImageOps, ImageEnhance, ImageFilter, ImageDraw, ImageFont

# Set this to your installed tesseract.exe path if not in PATH
# Example path: `C:\\Program Files\\Tesseract-OCR\\tesseract.exe`
pytesseract.pytesseract.tesseract_cmd = r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe"


# Cloudflare Worker endpoint and API key
# Default points to the Jarvis worker RGYC ingest path in this repo.
WORKER_ENDPOINT = os.environ.get(
    "RGYC_WORKER_ENDPOINT",
    "https://weather-api.dustin-popp82.workers.dev/rgyc-wind"
)
WORKER_API_KEY = os.environ.get("RGYC_WORKER_API_KEY") or os.environ.get("DEVICE_TOKEN")


# Verify tesseract is callable
try:
    # Option A: using subprocess to check the binary directly
    out = subprocess.run([pytesseract.pytesseract.tesseract_cmd, "--version"], capture_output=True, text=True, check=True)
    print("Tesseract version (subprocess):", out.stdout.splitlines()[0])
except Exception as e:
    print("Tesseract executable not found or failed to run:", e)

# Quick OCR smoke test using an image with text
img = Image.new("RGB", (200, 60), color="white")
draw = ImageDraw.Draw(img)
# If a TTF font is available, you can specify it; fallback to default
try:
    font = ImageFont.truetype("arial.ttf", 24)
except Exception:
    font = None
draw.text((10, 10), "123.4°", fill="black", font=font)

try:
    text = pytesseract.image_to_string(img, config="--psm 7 -c tessedit_char_whitelist=0123456789.°")
    print("OCR result:", repr(text.strip()))
except Exception as e:
    print("pytesseract call failed:", e)

# Set this to the actual image URL
IMAGE_URL = "https://rgyc.com.au/wind/10_beacon.jpg"

# Crop boxes for OCR (left, top, right, bottom)
# These are initial guesses — you'll tune them after first run
CROP_WIND_SPEED = (611, 151, 682, 175)     # Right box: Wind Speed
CROP_DIRECTION = (613, 178, 678, 203)      # Right box: Direction (True Head)
CROP_MAX = (27, 62, 101, 104)               # Left box: Max Wind Speed
CROP_MIN = (319, 61, 386, 101)              # Left box: Min Wind Speed
CROP_AVG = (152, 189, 268, 251)        # Left box: Avg Wind Speed

def preprocess_region(region: Image.Image) -> Image.Image:
    """Tune for red-on-black text: use red channel, increase contrast, upscale, invert."""
    rgb = region.convert("RGB")
    r, g, b = rgb.split()
    img = r
    img = ImageOps.autocontrast(img, cutoff=1)
    img = ImageEnhance.Contrast(img).enhance(1.6)
    img = img.resize((max(1, img.width * 3), max(1, img.height * 3)), Image.BICUBIC)
    img = img.filter(ImageFilter.MedianFilter(size=3)).convert("L")
    threshold = 120
    img = img.point(lambda p: 255 if p > threshold else 0, mode="1")
    img = ImageOps.invert(img.convert("L"))
    img = img.filter(ImageFilter.MedianFilter(size=3))
    return img

# OCR config for digits + decimal + degree symbol
OCR_CONFIG = "--psm 7 -c tessedit_char_whitelist=0123456789.°"


def parse_number(value):
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    cleaned = "".join(ch for ch in s if ch in "0123456789.-")
    if cleaned in {"", ".", "-", "-."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None

def fetch_image():
    """
    Downloads the latest wind image from RGYC.
    """
    r = requests.get(IMAGE_URL, timeout=5)
    r.raise_for_status()
    return Image.open(BytesIO(r.content))

def extract_text(img, crop_box):
    """
    Crops the image and runs OCR on the specified region.
    """
    region = img.crop(crop_box)

    region = preprocess_region(region)

    text = pytesseract.image_to_string(region, config=OCR_CONFIG)
    return text.strip()

def send_reading_to_worker(payload: dict):
    """Sends a single wind reading to the Cloudflare Worker and logs the HTTP response."""
    headers = {"Content-Type": "application/json"}
    if WORKER_API_KEY:
        headers["Authorization"] = f"Bearer {WORKER_API_KEY}"

    auth_state = "set" if WORKER_API_KEY else "missing"
    print(f"[Worker] POST {WORKER_ENDPOINT} auth={auth_state} payload={json.dumps(payload, default=str)[:200]}")

    try:
        resp = requests.post(
            WORKER_ENDPOINT,
            headers=headers,
            json=payload,
            timeout=5,
        )
        try:
            body_preview = resp.text[:200]
        except Exception:
            body_preview = "<no body>"

        if resp.ok:
            print(f"[Worker] OK {resp.status_code} - {body_preview}")
        else:
            print(f"[Worker] Non-2xx response: {resp.status_code} - {body_preview}")
    except requests.RequestException as e:
        print(f"[Worker] Error sending reading: {e}")


def poll_loop(start_immediately: bool = True):
    """
    Poll loop: if `start_immediately` is True the first iteration runs
    immediately (downloads & processes an image) even if not on a minute boundary.
    Subsequent iterations align to the minute boundary as before.
    """
    first_run = True
    while True:
        try:
            if first_run and start_immediately:
                # run immediately on first iteration
                pass
            else:
                # align to next minute boundary
                now = datetime.now()
                sleep_seconds = 60 - now.second - now.microsecond / 1_000_000
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)

            img = fetch_image()
            wind_speed = extract_text(img, CROP_WIND_SPEED)
            direction = extract_text(img, CROP_DIRECTION)
            max_val = extract_text(img, CROP_MAX)
            min_val = extract_text(img, CROP_MIN)
            avg_val = extract_text(img, CROP_AVG)

            now_local = datetime.now()
            ts_local = now_local.strftime('%Y-%m-%d %H:%M:%S')
            # Use naive UTC for now; if your system clock is local, consider using pytz/zoneinfo
            from datetime import timezone
            now_utc = datetime.now(timezone.utc)
            ts_utc = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

            print(f"[{ts_local}] Wind: {wind_speed} knots | Direction: {direction}")
            print(f"                       Max:  {max_val} knots | Min:  {min_val} knots | Avg:  {avg_val} knots")

            payload = {
                "source": "rgyc_beacon",
                "device_id": "rgyc-beacon",
                "time_local": ts_local,
                "time_utc": ts_utc,
                "wind_speed_kts": parse_number(wind_speed),
                "wind_dir": parse_number(direction),
                "max_kts": parse_number(max_val),
                "min_kts": parse_number(min_val),
                "avg_kts": parse_number(avg_val),
                "image_url": IMAGE_URL,
            }

            send_reading_to_worker(payload)

            first_run = False

        except Exception as e:
            print("Error:", e)
            time.sleep(5)


if __name__ == "__main__":
    # call with True to process immediately once on startup
    poll_loop(start_immediately=True)
