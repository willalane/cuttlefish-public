#!/usr/bin/env python3
"""
gif_crop_picker.py  --  pick crop + rotation per GIF, then batch with ffmpeg.

Designed for fixed-camera clips where every GIF needs the same kind of
straighten-then-crop treatment, but you still want to eyeball each one.

What it does
------------
1. Extracts the FIRST and LAST frame of every .gif in a folder (saved to
   <folder>/_frames/) so you can confirm the region of interest holds across
   the whole clip.
2. Opens a tkinter reviewer showing first + last frame side by side, one GIF
   at a time:
       - Type a rotation angle (degrees, CLOCKWISE-positive, decimals OK) and
         hit Apply, or nudge with the +/- buttons.
       - Click-drag on the LEFT (first frame) to draw the crop window. It is
         mirrored onto the RIGHT (last frame) so you can confirm it still works
         at the end of the clip.
       - The crop is clamped STRICTLY inside the original frame size, so the
         output can never exceed the input dimensions and no padding/fill is
         ever introduced.
3. Saves per-file settings to <folder>/crop_settings.json (auto-saved as you
   navigate, and resumable).
4. Writes apply_crops.bat (Windows) and apply_crops.sh with one ffmpeg command
   per GIF, ROTATION FIRST then CROP:
       ffmpeg -y -i "in.gif" -vf "rotate=A*PI/180,crop=w:h:x:y" "cropped/in.gif"

Rotation convention
-------------------
Positive degrees = clockwise, matching ffmpeg's `rotate` filter. The on-screen
preview negates the sign for PIL (which rotates counter-clockwise on positive),
so what you see is what ffmpeg will produce.

Dependencies: Pillow  (pip install pillow). tkinter ships with standard Python.

Usage:
    python gif_crop_picker.py [folder]
If no folder is given, a folder-picker dialog opens.
"""

import os
import sys
import json
from PIL import Image

PREVIEW_FILL = (40, 40, 40)   # marks rotation-exposed corners on screen only
MAX_W, MAX_H = 560, 560       # max on-screen size of each frame
OUT_SUBDIR = "cropped"


# --------------------------------------------------------------------------- #
# Pure logic (no GUI) -- frame extraction + ffmpeg script generation
# --------------------------------------------------------------------------- #
def extract_frames(folder):
    """Save first/last frame of each GIF; return [{name, first, last}]."""
    frames_dir = os.path.join(folder, "_frames")
    os.makedirs(frames_dir, exist_ok=True)
    gifs = sorted(f for f in os.listdir(folder) if f.lower().endswith(".gif"))
    pairs = []
    for name in gifs:
        path = os.path.join(folder, name)
        try:
            im = Image.open(path)
        except Exception as e:
            print(f"  skip {name}: {e}")
            continue
        n = getattr(im, "n_frames", 1)
        stem = os.path.splitext(name)[0]
        first_p = os.path.join(frames_dir, f"{stem}__first.png")
        last_p = os.path.join(frames_dir, f"{stem}__last.png")
        try:
            im.seek(0)
            im.convert("RGB").save(first_p)
            im.seek(max(0, n - 1))
            im.convert("RGB").save(last_p)
        except Exception as e:
            print(f"  skip {name}: {e}")
            continue
        pairs.append({"name": name, "first": first_p, "last": last_p})
    return pairs


def build_vf(rec):
    """Build the ffmpeg -vf string: rotate (if any) THEN crop (if any)."""
    parts = []
    deg = float(rec.get("rotate", 0) or 0)
    if abs(deg) > 1e-9:
        # rotate keeps ow=iw, oh=ih by default -> output never grows.
        parts.append(f"rotate={deg}*PI/180")
    c = rec.get("crop")
    if c:
        parts.append(f"crop={c['w']}:{c['h']}:{c['x']}:{c['y']}")
    return ",".join(parts)


def build_ffmpeg_scripts(folder, pairs, settings):
    """Write apply_crops.bat and apply_crops.sh. Return (bat_path, sh_path)."""
    note_bat = [
        "@echo off",
        "REM Run this from inside the folder that holds the GIFs.",
        "REM rotation is applied first, then crop; output stays within input size.",
        "REM If GIF colors look off after re-encoding, swap a line for the",
        "REM palette-preserving form, e.g.:",
        "REM ffmpeg -y -i \"in.gif\" -vf \"rotate=A*PI/180,crop=w:h:x:y,split[a][b];[a]palettegen[p];[b][p]paletteuse\" \"cropped/in.gif\"",
        f'mkdir "{OUT_SUBDIR}" 2>nul',
        "",
    ]
    note_sh = [
        "#!/usr/bin/env bash",
        "# Run this from inside the folder that holds the GIFs.",
        "# rotation is applied first, then crop; output stays within input size.",
        "# If GIF colors look off after re-encoding, swap a line for the",
        "# palette-preserving form, e.g.:",
        "# ffmpeg -y -i \"in.gif\" -vf \"rotate=A*PI/180,crop=w:h:x:y,split[a][b];[a]palettegen[p];[b][p]paletteuse\" \"cropped/in.gif\"",
        "set -e",
        f'mkdir -p "{OUT_SUBDIR}"',
        "",
    ]
    bat_lines = list(note_bat)
    sh_lines = list(note_sh)
    for p in pairs:
        name = p["name"]
        rec = settings.get(name)
        if not rec:
            continue
        vf = build_vf(rec)
        out = f"{OUT_SUBDIR}/{name}"
        arg = f' -vf "{vf}"' if vf else ""
        bat_lines.append(f'ffmpeg -y -i "{name}"{arg} "{out}"')
        sh_lines.append(f'ffmpeg -y -i "{name}"{arg} "{out}"')

    bat = os.path.join(folder, "apply_crops.bat")
    sh = os.path.join(folder, "apply_crops.sh")
    with open(bat, "w", encoding="utf-8", newline="") as f:
        f.write("\r\n".join(bat_lines) + "\r\n")
    with open(sh, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(sh_lines) + "\n")
    try:
        os.chmod(sh, 0o755)
    except Exception:
        pass
    return bat, sh


def load_settings(folder):
    sp = os.path.join(folder, "crop_settings.json")
    if os.path.exists(sp):
        try:
            with open(sp, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_settings(folder, settings):
    sp = os.path.join(folder, "crop_settings.json")
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    return sp


# --------------------------------------------------------------------------- #
# GUI (tkinter imported lazily so the module stays importable without a display)
# --------------------------------------------------------------------------- #
def pick_folder():
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    folder = filedialog.askdirectory(title="Select folder of GIFs")
    root.destroy()
    return folder


def run_gui(folder, pairs, settings):
    import tkinter as tk
    from tkinter import messagebox
    from PIL import ImageTk

    class Picker(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title("GIF crop + rotate picker")
            self.folder = folder
            self.pairs = pairs
            self.settings = settings
            self.idx = 0

            self.first_orig = None
            self.last_orig = None
            self.W = self.H = 0
            self.scale = 1.0
            self.angle = 0.0
            self.crop = None              # (x, y, w, h) in original pixels
            self.tk_first = self.tk_last = None
            self._drag = None

            self._build_ui()
            self.protocol("WM_DELETE_WINDOW", self.on_close)
            self.load_index(0)

        # ---- UI ---------------------------------------------------------- #
        def _build_ui(self):
            top = tk.Frame(self)
            top.pack(fill="x", padx=8, pady=4)
            self.info = tk.Label(top, text="", anchor="w",
                                 font=("Segoe UI", 10, "bold"))
            self.info.pack(side="left")

            mid = tk.Frame(self)
            mid.pack(padx=8)
            lf = tk.Frame(mid)
            lf.grid(row=0, column=0, padx=4)
            rf = tk.Frame(mid)
            rf.grid(row=0, column=1, padx=4)
            tk.Label(lf, text="FIRST frame  (drag to draw crop)").pack()
            tk.Label(rf, text="LAST frame  (confirm it still fits)").pack()
            self.cv_first = tk.Canvas(lf, width=MAX_W, height=MAX_H, bg="#222",
                                      highlightthickness=1,
                                      highlightbackground="#555")
            self.cv_first.pack()
            self.cv_last = tk.Canvas(rf, width=MAX_W, height=MAX_H, bg="#222",
                                     highlightthickness=1,
                                     highlightbackground="#555")
            self.cv_last.pack()
            self.cv_first.bind("<ButtonPress-1>", self.on_press)
            self.cv_first.bind("<B1-Motion>", self.on_motion)
            self.cv_first.bind("<ButtonRelease-1>", self.on_release)

            ctl = tk.Frame(self)
            ctl.pack(fill="x", padx=8, pady=6)
            tk.Label(ctl, text="Rotation (deg, CW+):").pack(side="left")
            self.angle_var = tk.StringVar(value="0")
            e = tk.Entry(ctl, textvariable=self.angle_var, width=8)
            e.pack(side="left")
            e.bind("<Return>", lambda _e: self.apply_angle())
            tk.Button(ctl, text="Apply", command=self.apply_angle).pack(
                side="left", padx=2)
            for d in (-1, -0.5, -0.1, 0.1, 0.5, 1):
                tk.Button(ctl, text=f"{d:+g}", width=4,
                          command=lambda dd=d: self.nudge(dd)).pack(side="left")
            tk.Button(ctl, text="Clear crop",
                      command=self.clear_crop).pack(side="left", padx=10)

            self.readout = tk.Label(self, text="", anchor="w", fg="#0a6")
            self.readout.pack(fill="x", padx=8)

            nav = tk.Frame(self)
            nav.pack(fill="x", padx=8, pady=8)
            tk.Button(nav, text="\u25c0 Prev", command=self.prev).pack(side="left")
            tk.Button(nav, text="Next \u25b6", command=self.nxt).pack(
                side="left", padx=4)
            tk.Button(nav, text="Save", command=self.save).pack(
                side="left", padx=4)
            tk.Button(nav, text="Generate ffmpeg script",
                      command=self.generate).pack(side="left", padx=4)
            tk.Button(nav, text="Finish & exit",
                      command=self.on_close).pack(side="right")

        # ---- data <-> state ---------------------------------------------- #
        def commit(self):
            if not self.pairs:
                return
            rec = {"rotate": round(self.angle, 4)}
            if self.crop:
                x, y, w, h = self.crop
                rec["crop"] = {"x": x, "y": y, "w": w, "h": h}
            self.settings[self.pairs[self.idx]["name"]] = rec

        def load_index(self, i):
            if not self.pairs:
                return
            self.idx = max(0, min(i, len(self.pairs) - 1))
            p = self.pairs[self.idx]
            self.first_orig = Image.open(p["first"]).convert("RGB")
            self.last_orig = Image.open(p["last"]).convert("RGB")
            self.W, self.H = self.first_orig.size
            self.scale = min(MAX_W / self.W, MAX_H / self.H, 1.0)
            rec = self.settings.get(p["name"], {})
            self.angle = float(rec.get("rotate", 0.0))
            self.angle_var.set(f"{self.angle:g}")
            c = rec.get("crop")
            self.crop = (c["x"], c["y"], c["w"], c["h"]) if c else None
            self.render()

        # ---- rendering --------------------------------------------------- #
        def _preview(self, img):
            # CW-positive input -> negate for PIL (which is CCW-positive)
            rot = img.rotate(-self.angle, resample=Image.BICUBIC,
                             expand=False, fillcolor=PREVIEW_FILL)
            dw = max(1, int(round(self.W * self.scale)))
            dh = max(1, int(round(self.H * self.scale)))
            return rot.resize((dw, dh), Image.BILINEAR)

        def render(self):
            self.tk_first = ImageTk.PhotoImage(self._preview(self.first_orig))
            self.tk_last = ImageTk.PhotoImage(self._preview(self.last_orig))
            self.cv_first.delete("all")
            self.cv_last.delete("all")
            self.cv_first.create_image(0, 0, anchor="nw", image=self.tk_first)
            self.cv_last.create_image(0, 0, anchor="nw", image=self.tk_last)
            self.draw_crop()
            self.update_info()

        def draw_crop(self):
            self.cv_first.delete("crop")
            self.cv_last.delete("crop")
            if not self.crop:
                return
            x, y, w, h = self.crop
            s = self.scale
            box = (x * s, y * s, (x + w) * s, (y + h) * s)
            for cv in (self.cv_first, self.cv_last):
                cv.create_rectangle(*box, outline="#00e5ff", width=2, tags="crop")

        def update_info(self):
            p = self.pairs[self.idx]
            self.info.config(
                text=f"[{self.idx + 1}/{len(self.pairs)}]  {p['name']}   "
                     f"{self.W}\u00d7{self.H}px")
            if self.crop:
                x, y, w, h = self.crop
                ctxt = f"crop  x={x} y={y} w={w} h={h}"
            else:
                ctxt = "crop: (none -> full frame)"
            self.readout.config(text=f"rotation {self.angle:g}\u00b0    |    {ctxt}")

        # ---- mouse ------------------------------------------------------- #
        def on_press(self, ev):
            self._drag = (ev.x, ev.y)

        def on_motion(self, ev):
            if not self._drag:
                return
            x0, y0 = self._drag
            self.cv_first.delete("crop")
            self.cv_last.delete("crop")
            self.cv_first.create_rectangle(x0, y0, ev.x, ev.y,
                                           outline="#00e5ff", width=2, tags="crop")

        def on_release(self, ev):
            if not self._drag:
                return
            x0, y0 = self._drag
            self._drag = None
            s = self.scale
            ox0, oy0 = x0 / s, y0 / s
            ox1, oy1 = ev.x / s, ev.y / s
            x = int(round(min(ox0, ox1)))
            y = int(round(min(oy0, oy1)))
            w = int(round(abs(ox1 - ox0)))
            h = int(round(abs(oy1 - oy0)))
            # clamp STRICTLY within original frame size
            x = max(0, min(x, self.W))
            y = max(0, min(y, self.H))
            w = max(0, min(w, self.W - x))
            h = max(0, min(h, self.H - y))
            self.crop = (x, y, w, h) if (w >= 2 and h >= 2) else None
            self.commit()
            self.render()

        # ---- controls ---------------------------------------------------- #
        def apply_angle(self):
            try:
                self.angle = float(self.angle_var.get())
            except ValueError:
                messagebox.showwarning(
                    "Invalid", "Rotation must be a number, e.g. 21 or -3.5")
                return
            self.commit()
            self.render()

        def nudge(self, d):
            self.angle = round(self.angle + d, 4)
            self.angle_var.set(f"{self.angle:g}")
            self.commit()
            self.render()

        def clear_crop(self):
            self.crop = None
            self.commit()
            self.render()

        def prev(self):
            self.commit()
            save_settings(self.folder, self.settings)
            self.load_index(self.idx - 1)

        def nxt(self):
            self.commit()
            save_settings(self.folder, self.settings)
            self.load_index(self.idx + 1)

        def save(self):
            self.commit()
            sp = save_settings(self.folder, self.settings)
            messagebox.showinfo("Saved", f"Saved to:\n{sp}")

        def generate(self):
            self.commit()
            save_settings(self.folder, self.settings)
            bat, sh = build_ffmpeg_scripts(self.folder, self.pairs, self.settings)
            messagebox.showinfo("Generated", f"Wrote:\n{bat}\n{sh}")

        def on_close(self):
            self.commit()
            save_settings(self.folder, self.settings)
            build_ffmpeg_scripts(self.folder, self.pairs, self.settings)
            self.destroy()

    Picker().mainloop()


# --------------------------------------------------------------------------- #
def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else pick_folder()
    if not folder:
        print("No folder selected.")
        return
    folder = os.path.abspath(folder)
    print("Extracting first/last frames from", folder)
    pairs = extract_frames(folder)
    if not pairs:
        print("No GIFs found.")
        return
    print(f"Found {len(pairs)} GIFs. Launching reviewer...")
    settings = load_settings(folder)
    run_gui(folder, pairs, settings)
    print("Done. Wrote crop_settings.json, apply_crops.bat and apply_crops.sh to",
          folder)


if __name__ == "__main__":
    main()
