# python
import math
import requests
from io import BytesIO
from tkinter import Tk, Canvas, Button, Entry, Label, filedialog
from PIL import Image, ImageTk
import numpy as np

from wind_direction import WindDirectionDetector

class SimpleWindGui:
    """
    Simple GUI to load an image, let the user optionally trace center/radius,
    run detection and visualize what the detector finds (circle, red rim samples,
    centroid and angle).
    """
    def __init__(self, master):
        self.master = master
        self.detector = WindDirectionDetector()

        self.img = None           # PIL image (full resolution)
        self.photo = None         # ImageTk photo for Canvas
        self.canvas = Canvas(master, bg="gray")
        self.canvas.pack(fill="both", expand=True)

        self.center = None
        self.radius = None
        self.angle = None

        # Controls
        self.url_entry = Entry(master, width=60)
        self.url_entry.insert(0, "https://rgyc.com.au/wind/10_beacon.jpg")
        self.url_entry.pack(side="left", padx=4, pady=4)
        Button(master, text="Load URL", command=self.load_url).pack(side="left")
        Button(master, text="Load File", command=self.load_file).pack(side="left")
        Button(master, text="Detect Angle", command=self.detect_angle).pack(side="left")
        Button(master, text="Show Detection", command=self.show_detection).pack(side="left")
        Button(master, text="Clear Trace", command=self.clear_trace).pack(side="left")
        Label(master, text="Click: center then edge").pack(side="left", padx=6)

        self.canvas.bind("<Button-1>", self.on_click)

    def load_url(self):
        url = self.url_entry.get().strip()
        if not url:
            return
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        self.img = Image.open(BytesIO(r.content)).convert("RGB")
        self._show_image()

    def load_file(self):
        path = filedialog.askopenfilename(filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.bmp;*.gif")])
        if not path:
            return
        self.img = Image.open(path).convert("RGB")
        self._show_image()

    def _show_image(self):
        # remove overlays then draw the image (image should be beneath overlays)
        self.canvas.delete("trace")
        self.canvas.delete("detected")
        w, h = self.img.size
        # Resize canvas to image size
        self.canvas.config(width=w, height=h)
        self.photo = ImageTk.PhotoImage(self.img)
        # create_image returns an image on the canvas; keep it without specific tag so overlays are drawn after
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)

    def clear_trace(self):
        self.center = None
        self.radius = None
        self.angle = None
        self.canvas.delete("trace")
        self.canvas.delete("detected")
        self.canvas.delete("trace_text")
        # redraw image if present
        if self.img:
            self._show_image()

    def on_click(self, event):
        if self.img is None:
            return
        x, y = event.x, event.y
        if self.center is None:
            self.center = (x, y)
            # small cross
            r = 6
            self.canvas.create_line(x - r, y, x + r, y, fill="lime", width=2, tags="trace")
            self.canvas.create_line(x, y - r, x, y + r, fill="lime", width=2, tags="trace")
        elif self.radius is None:
            cx, cy = self.center
            self.radius = math.hypot(x - cx, y - cy)
            # draw circle guide
            self.canvas.create_oval(cx - self.radius, cy - self.radius, cx + self.radius, cy + self.radius,
                                    outline="yellow", width=2, tags="trace")
            # optionally draw a small marker at clicked edge
            self.canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill="yellow", tags="trace")
        else:
            # reset trace if both already set
            self.clear_trace()
            self.on_click(event)

    def detect_angle(self):
        """Run detector.get_angle() and draw a result line (uses traced center/radius if present)."""
        if self.img is None:
            return
        try:
            angle = self.detector.get_angle(self.img)
            self.angle = float(angle)
        except Exception as e:
            self.canvas.delete("trace_text")
            self.canvas.create_text(10, 10, anchor="nw", text=f"Detect error: {e}", fill="red", tags="trace_text")
            return

        # draw result overlays
        self.canvas.delete("detected")
        self.canvas.delete("trace_text")

        # try to obtain detected circle for nicer overlay
        detected_center = None
        detected_radius = None
        try:
            if hasattr(self.detector, "_ensure_bgr") and hasattr(self.detector, "_detect_circle"):
                bgr = self.detector._ensure_bgr(self.img)
                cx_d, cy_d, r_d = self.detector._detect_circle(bgr)
                detected_center = (int(cx_d), int(cy_d))
                detected_radius = int(r_d)
        except Exception:
            pass

        # If user traced a center/radius, prefer that; otherwise use detected or image center
        if self.center is None:
            if detected_center:
                self.center = detected_center
                self.radius = detected_radius + 5
            else:
                w, h = self.img.size
                self.center = (w // 2, h // 2)
                self.radius = min(w, h) // 4

        cx, cy = self.center
        r = self.radius

        # Draw the detected circle (prefer detected circle values if available)
        if detected_center and detected_radius:
            dcx, dcy = detected_center
            dr = detected_radius
            self.canvas.create_oval(dcx - dr, dcy - dr, dcx + dr, dcy + dr,
                                    outline="cyan", width=2, tags="detected")
            self.canvas.create_oval(dcx - 4, dcy - 4, dcx + 4, dcy + 4, fill="cyan", outline="", tags="detected")
        else:
            self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                    outline="yellow", width=2, tags="detected")

        # Draw a line representing the computed angle
        try:
            rad = math.radians(self.angle)
            dx = r * math.sin(rad)
            dy = -r * math.cos(rad)
            x2 = cx + dx
            y2 = cy + dy
            self.canvas.create_line(cx, cy, x2, y2, fill="red", width=3, arrow="last", tags="detected")
            self.canvas.create_oval(x2 - 5, y2 - 5, x2 + 5, y2 + 5, fill="red", outline="", tags="detected")
        except Exception:
            pass

        #self.canvas.create_text(10, 10, anchor="nw", text=f"Angle: {self.angle:.2f}°", fill="white", tags="trace_text")
        self.draw_label(10,10, f"Angle: {self.angle:.2f}°", fg="white", bg="black")

    def show_detection(self):
        """Run detector internals and draw debug overlays: circle, sampled red rim points and centroid."""
        if self.img is None:
            return
        self.canvas.delete("detected")
        self.canvas.delete("trace_text")

        try:
            bgr = self.detector._ensure_bgr(self.img)
            cx, cy, r = self.detector._detect_circle(bgr)
            cx, cy, r = int(cx), int(cy), int(r)

            # draw detected circle and center
            self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                    outline="cyan", width=2, tags="detected")
            self.canvas.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill="cyan",
                                    outline="", tags="detected")

            # try to find red arc (gives mean angle + centroid)
            centroid = None
            angle_deg = None
            try:
                angle_deg, centroid = self.detector._find_red_arc_angle(bgr, cx, cy, r,
                                                                         step_deg=2,
                                                                         thickness=max(6, int(r * 0.06)),
                                                                         min_votes=1)
                self.angle = float(angle_deg)
            except Exception:
                centroid = None
                angle_deg = None

            # draw centroid and connecting line if found
            if centroid is not None:
                centroid_x, centroid_y = centroid
                self.canvas.create_line(cx, cy, centroid_x, centroid_y,
                                        fill="red", width=3, arrow="last", tags="detected")
                self.canvas.create_oval(centroid_x - 6, centroid_y - 6, centroid_x + 6, centroid_y + 6,
                                        fill="red", outline="", tags="detected")

            # additionally sample along the circumference and mark red pixels (visual debug)
            try:
                mask = self.detector._red_mask(bgr)
                h, w = mask.shape[:2]
                step = 2
                half_th = max(3, int(r * 0.03))
                radial_offsets = np.linspace(-half_th, half_th, max(3, int(half_th)))
                red_points = []
                for a in range(0, 360, step):
                    rad = math.radians(a)
                    found = False
                    for dr in radial_offsets:
                        rr = r + dr
                        x = int(round(cx + rr * math.sin(rad)))
                        y = int(round(cy - rr * math.cos(rad)))
                        if 0 <= x < w and 0 <= y < h and mask[y, x] > 0:
                            red_points.append((x, y))
                            found = True
                            break
                # draw small markers for red pixels
                for (x, y) in red_points:
                    self.canvas.create_oval(x - 2, y - 2, x + 2, y + 2, fill="pink", outline="black", tags="detected")
            except Exception:
                pass

            # show angle text
            # show angle text
            self.canvas.delete("trace_text")

            if self.angle is not None:
                self.draw_label(10, 10, f"Angle: {self.angle:.1f}°", fg="white", bg="black")
            else:
                self.draw_label(10, 10, "Angle: (no red arc)", fg="yellow", bg="black")



        except Exception as e:
            self.canvas.create_text(10, 10, anchor="nw", text=f"Detect error: {e}",
                                    fill="red", tags="trace_text")


    def draw_label(self, x, y, text, fg="white", bg="black"):
        # Create the text off-screen to measure it
        temp = self.canvas.create_text(x, y, anchor="nw", text=text,
                                       font=("Helvetica", 12, "bold"))
        bbox = self.canvas.bbox(temp)  # (x1, y1, x2, y2)
        self.canvas.delete(temp)

        # Draw background rectangle
        self.canvas.create_rectangle(
            bbox[0] - 4, bbox[1] - 2, bbox[2] + 4, bbox[3] + 2,
            fill=bg, outline=bg, tags="trace_text"
        )

        # Draw the text on top
        self.canvas.create_text(
            x, y, anchor="nw", text=text,
            fill=fg, font=("Helvetica", 12, "bold"),
            tags="trace_text"
        )


if __name__ == "__main__":
    root = Tk()
    root.title("RGYC wind tracer")
    app = SimpleWindGui(root)
    root.mainloop()
