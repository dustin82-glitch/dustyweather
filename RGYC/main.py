from io import BytesIO

from wind_direction import WindDirectionDetector
import requests
from PIL import Image, ImageOps, ImageEnhance, ImageFilter, ImageDraw, ImageFont

if __name__ == "__main__":
    detector = WindDirectionDetector()

    IMAGE_URL = "https://rgyc.com.au/wind/10_beacon.jpg"

    def fetch_image():
        r = requests.get(IMAGE_URL, timeout=5)
        r.raise_for_status()
        return Image.open(BytesIO(r.content))

    angle = detector.get_angle(fetch_image())
    print(f"Wind direction (center of red arc): {angle:.2f}°")
