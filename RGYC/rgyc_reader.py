# rgyc_reader.py
from io import BytesIO
from datetime import datetime
from PIL import Image, ImageOps, ImageEnhance, ImageFilter
import pytesseract
from wind_direction import WindDirectionDetector
import os
import requests

WORKER_ENDPOINT = os.environ.get(
    "RGYC_WORKER_ENDPOINT",
    "https://weather-api.dustin-popp82.workers.dev/rgyc-wind"
)
WORKER_API_KEY = os.environ.get("RGYC_WORKER_API_KEY")


pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

IMAGE_URL = "https://rgyc.com.au/wind/10_beacon.jpg"

CROP_WIND_SPEED = (152, 189, 268, 251)
CROP_DIRECTION  = (613, 178, 678, 203)

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

def preprocess_region(region: Image.Image) -> Image.Image:
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

def fetch_image():
    r = requests.get(IMAGE_URL, timeout=5)
    r.raise_for_status()
    return Image.open(BytesIO(r.content))

def extract_text(img, crop_box):
    region = img.crop(crop_box)
    region = preprocess_region(region)
    text = pytesseract.image_to_string(region, config=OCR_CONFIG)
    return text.strip()

def get_rgyc_reading():
    img = fetch_image()
    wind_speed = extract_text(img, CROP_WIND_SPEED)

    detector = WindDirectionDetector()
    angle = detector.get_angle(img)  # numeric degrees

    now_local = datetime.now()
    time_local = now_local.strftime('%Y-%m-%d %H:%M:%S')
    from datetime import timezone
    now_utc = datetime.now(timezone.utc)
    time_utc = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

    return {
        "time": time_local,             # keep for backward compatibility
        "time_utc": time_utc,
        "source": "rgyc_beacon",
        "device_id": "rgyc-beacon",
        "wind_speed_kts": parse_number(wind_speed),
        "wind_dir": parse_number(angle),              # numeric degrees
        "image_url": IMAGE_URL,
    }

def send_current_reading_to_worker():
    """
    Convenience function: gets a fresh reading and posts it to the Worker.
    """
    reading = get_rgyc_reading()
    payload = {
        "source": reading.get("source", "rgyc_beacon"),
        "time_local": reading["time"],
        "time_utc": reading["time_utc"],
        "wind_speed_kts": reading["wind_speed_kts"],
        "wind_dir": reading["wind_dir"],  # numeric angle
        "image_url": reading["image_url"],
    }

    headers = {"Content-Type": "application/json"}
    if WORKER_API_KEY:
        headers["Authorization"] = f"Bearer {WORKER_API_KEY}"

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
