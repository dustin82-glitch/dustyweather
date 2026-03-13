
import cv2
import numpy as np
import math
import os
from io import BytesIO
from PIL import Image as PILImage

class WindDirectionDetector:
    def __init__(self):
        pass

    def _ensure_bgr(self, image_input):
        # Path-like string
        if isinstance(image_input, (str, os.PathLike)):
            img = cv2.imread(str(image_input))
        # PIL Image
        elif isinstance(image_input, PILImage.Image):
            rgb = image_input.convert('RGB')
            arr = np.array(rgb)
            img = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        # NumPy array (assume OpenCV / BGR unless channels indicate otherwise)
        elif isinstance(image_input, np.ndarray):
            img = image_input
            if img.ndim == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            elif img.shape[2] == 4:
                img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
        # bytes or BytesIO (jpeg/png binary)
        elif isinstance(image_input, (bytes, BytesIO)):
            data = image_input.getvalue() if isinstance(image_input, BytesIO) else image_input
            arr = np.frombuffer(data, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        else:
            raise TypeError("Unsupported image input type")

        if img is None:
            raise FileNotFoundError("Cannot load image from provided input")

        return img

    def _detect_circle(self, img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.medianBlur(gray, 5)
        circles = cv2.HoughCircles(
            gray,
            cv2.HOUGH_GRADIENT,
            dp=1.2,
            minDist=200,
            param1=50,
            param2=30,
            minRadius=100,
            maxRadius=600
        )
        if circles is None:
            raise RuntimeError("Gauge circle not detected")
        circles = np.round(circles[0, :]).astype("int")
        return circles[0]  # (cx, cy, r)

    def _red_mask(self, img):
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        lower1 = np.array([0, 80, 80])
        upper1 = np.array([10, 255, 255])
        lower2 = np.array([170, 80, 80])
        upper2 = np.array([180, 255, 255])
        mask1 = cv2.inRange(hsv, lower1, upper1)
        mask2 = cv2.inRange(hsv, lower2, upper2)
        mask = cv2.bitwise_or(mask1, mask2)
        # small cleanups
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        return mask

    def _find_red_arc_angle(self, img, cx, cy, r, step_deg=2, thickness=8, min_votes=2):
        """
        Scan around the circumference (0..360 deg, 0 = up/12 o'clock) sampling a short radial
        strip at each angle. Mark angles that contain red pixels, group contiguous runs (with wrap),
        pick the largest run and return its mid-angle (degrees, 0=up, clockwise).
        """
        h, w = img.shape[:2]
        mask = self._red_mask(img)

        angles = []
        angle_list = list(range(0, 360, step_deg))
        votes = []
        coords_by_angle = []

        half_th = thickness / 2.0
        radial_samples = max(3, int(thickness))  # sample a few radii across the width
        radial_offsets = np.linspace(-half_th, half_th, radial_samples)

        for a in angle_list:
            rad = math.radians(a)
            cnt = 0
            coords = []
            for dr in radial_offsets:
                rr = r + dr
                x = int(round(cx + rr * math.sin(rad)))
                y = int(round(cy - rr * math.cos(rad)))
                if 0 <= x < w and 0 <= y < h:
                    if mask[y, x] > 0:
                        cnt += 1
                        coords.append((x, y))
            votes.append(cnt)
            coords_by_angle.append(coords)

        # mark angles with sufficient votes as red
        is_red = [v >= min_votes for v in votes]

        # find contiguous runs of True, handling wraparound
        runs = []
        i = 0
        N = len(is_red)
        while i < N:
            if not is_red[i]:
                i += 1
                continue
            j = i
            accum_coords = []
            while j < i + N and is_red[j % N]:
                accum_coords.extend(coords_by_angle[j % N])
                j += 1
            length = j - i
            runs.append((i, j - 1, length, accum_coords))
            i = j

        if not runs:
            raise RuntimeError("No red arc found on circumference")

        # pick best run: longest (tie-breaker: centroid distance to radius)
        best_run = max(runs, key=lambda t: t[2])

        start_idx, end_idx, length, accum_coords = best_run
        # collect angles in run (consider wrap)
        run_angles = []
        idx = start_idx
        for k in range(length):
            run_angles.append(angle_list[(idx + k) % N])
        # circular mean of angles
        angs_rad = np.radians(run_angles)
        sin_sum = np.sum(np.sin(angs_rad))
        cos_sum = np.sum(np.cos(angs_rad))
        mean_ang_rad = math.atan2(sin_sum, cos_sum)
        mean_ang_deg = (math.degrees(mean_ang_rad) + 360) % 360

        # The angle list uses 0 = up and increases clockwise (constructed that way).
        # compute centroid pixel (if any coords collected)
        if accum_coords:
            xs = [p[0] for p in accum_coords]
            ys = [p[1] for p in accum_coords]
            centroid_x = float(np.mean(xs))
            centroid_y = float(np.mean(ys))
        else:
            # fallback: compute point on circumference at mean angle
            rad = math.radians(mean_ang_deg)
            centroid_x = float(cx + r * math.sin(rad))
            centroid_y = float(cy - r * math.cos(rad))

        return mean_ang_deg, (centroid_x, centroid_y)

    def _extract_red_pixels(self, img):
        # keep original behavior for other callers (returns all red points)
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        lower1 = np.array([0, 80, 80])
        upper1 = np.array([10, 255, 255])
        lower2 = np.array([170, 80, 80])
        upper2 = np.array([180, 255, 255])
        mask1 = cv2.inRange(hsv, lower1, upper1)
        mask2 = cv2.inRange(hsv, lower2, upper2)
        mask = cv2.bitwise_or(mask1, mask2)
        ys, xs = np.where(mask > 0)
        if len(xs) == 0:
            raise RuntimeError("No red arc detected")
        return np.column_stack((xs, ys))

    def _compute_angle(self, pts, cx, cy):
        angles = []
        for x, y in pts:
            dx = x - cx
            dy = cy - y  # invert Y so 12 o'clock = 0 degrees
            ang = math.degrees(math.atan2(dx, dy)) % 360
            angles.append(ang)
        return float(np.mean(angles))

    def get_angle(self, image_input):
        """
        Accepts:
         - file path (str / PathLike)
         - PIL.Image.Image
         - NumPy array (OpenCV BGR)
         - bytes or BytesIO with image bytes
        Returns angle in degrees (0 = up/12 o'clock, clockwise).
        """
        img = self._ensure_bgr(image_input)
        cx, cy, r = self._detect_circle(img)

        # Prefer circumference-based locator for the red indicator
        try:
            angle_deg, centroid = self._find_red_arc_angle(img, cx, cy, r,
                                                           step_deg=2, thickness=max(6, int(r*0.06)),
                                                           min_votes=1)
            return angle_deg
        except Exception:
            # fallback to original broad extraction
            red_pts = self._extract_red_pixels(img)
            angle = self._compute_angle(red_pts, cx, cy)
            return angle
