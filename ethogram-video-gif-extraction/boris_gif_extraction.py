# -*- coding: utf-8 -*-
"""
boris_gif_extraction.py

Step 2 of the behavioural-GIF pipeline: cut behaviour clips out of the source
videos coded in a BORIS project and write them as GIFs, one subfolder per
behaviour.

The original version (written by ChatGPT to a specification by the repository
author) had the project path, video folder, behaviours, and window intervals
hard-coded. This version chooses them interactively, so it works on any BORIS
project without editing the source:

  - pick the .boris file with a file dialog
  - pick the video folder only when the project stores relative video paths
    (absolute paths are used as-is)
  - tick which behaviour codes to extract, which codes are windows to intersect
    against, and set padding / fps / quality, all read from what is actually
    present in the project

BORIS project format: 7.0 JSON. See https://www.boris.unito.it/

Requirements:
  - ffmpeg and ffprobe on PATH
  - gifsicle on PATH (optional; used for extra compression if present)
  - Python: tqdm (optional progress bar); tkinter (ships with standard Python)
"""

import json
import ntpath
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:                      # progress bar is optional
    def tqdm(iterable, **_):
        return iterable


# Default quality / clip settings shown in the setup window.
DEFAULTS = {
    "pad_sec": 1.0,
    "fps": "10",            # number, or "source" for the video's own rate
    "max_colors": 128,
    "dither": "bayer",      # bayer | none | sierra2 | sierra2_4a | floyd_steinberg
    "bayer_scale": 5,
    "gifsicle_colors": 128,
    "gifsicle_lossy": 80,   # blank disables the gifsicle pass
}

DATE_SUFFIX_RE = re.compile(r"_(\d{8})$")   # trailing _DDMMYYYY / _YYYYMMDD token


# --------------------------------------------------------------------------- #
# Generic helpers
# --------------------------------------------------------------------------- #
def run_command(cmd):
    result = subprocess.run(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed:\n{' '.join(map(str, cmd))}\n\n{result.stderr}")
    return result


def pair_state_events(times):
    """Turn an ordered list of state-event times into (start, stop) pairs."""
    intervals = []
    if len(times) % 2 != 0:
        print(f"WARNING: odd number of state events ({len(times)}); "
              f"last event ignored.")
    for i in range(0, len(times) - 1, 2):
        start_t, stop_t = times[i], times[i + 1]
        if stop_t > start_t:
            intervals.append((start_t, stop_t))
    return intervals


def overlap(a0, a1, b0, b1):
    start, end = max(a0, b0), min(a1, b1)
    return (start, end) if end > start else None


def intersect_with_windows(interval, windows):
    start, end = interval
    out = []
    for w0, w1 in windows:
        ov = overlap(start, end, w0, w1)
        if ov is not None:
            out.append(ov)
    return out


def slugify(code):
    s = re.sub(r"[^A-Za-z0-9]+", "_", str(code).strip().lower()).strip("_")
    return s or "behaviour"


def path_is_absolute(p):
    # recognise Windows drive paths even when run on another OS
    return (os.path.isabs(p) or ntpath.isabs(p)
            or bool(re.match(r"^[A-Za-z]:[\\/]", str(p))))


def clean_video_stem(name, strip_date):
    stem = Path(name).stem
    if strip_date:
        stem = DATE_SUFFIX_RE.sub("", stem)
    return stem


def resolve_video_path(stored_path, video_dir):
    """Find the video on disk: absolute path as-is, else basename in video_dir."""
    if path_is_absolute(stored_path) and Path(stored_path).exists():
        return Path(stored_path)
    base = ntpath.basename(str(stored_path))
    if video_dir:
        direct = Path(video_dir) / base
        if direct.exists():
            return direct
        hits = list(Path(video_dir).rglob(base))
        if hits:
            return hits[0]
    if Path(stored_path).exists():
        return Path(stored_path)
    return None


def ffprobe_fps_length(video_path):
    fps = length = None
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=r_frame_rate",
             "-show_entries", "format=duration", "-of", "json", str(video_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        data = json.loads(r.stdout or "{}")
        rate = (data.get("streams") or [{}])[0].get("r_frame_rate", "")
        if "/" in rate:
            num, den = rate.split("/")
            if float(den) != 0:
                fps = float(num) / float(den)
        dur = data.get("format", {}).get("duration")
        if dur is not None:
            length = float(dur)
    except Exception:
        pass
    return fps, length


def get_fps_length(obs, stored_path, video_path):
    """Read fps/length from BORIS media_info, falling back to ffprobe."""
    fps = length = None
    media = obs.get("media_info", {})
    try:
        fps = float(media["fps"][stored_path])
    except Exception:
        pass
    try:
        length = float(media["length"][stored_path])
    except Exception:
        pass
    if fps is None or length is None:
        f2, l2 = ffprobe_fps_length(video_path)
        fps = fps if fps else f2
        length = length if length else l2
    return fps, length


# --------------------------------------------------------------------------- #
# BORIS parsing
# --------------------------------------------------------------------------- #
def discover_codes(project):
    """Map every behaviour code present to its event count and seen modifiers."""
    info = {}
    for obs in project.get("observations", {}).values():
        for ev in obs.get("events", []):
            if len(ev) < 3:
                continue
            code = str(ev[2])
            rec = info.setdefault(code, {"count": 0, "modifiers": set()})
            rec["count"] += 1
            if len(ev) > 3 and ev[3]:
                rec["modifiers"].add(str(ev[3]))
    return info


def project_needs_video_dir(project):
    for obs in project.get("observations", {}).values():
        try:
            stored = obs["file"]["1"][0]
        except Exception:
            continue
        if not path_is_absolute(stored):
            return True
    return False


def collect_behaviour_intervals(events, code, modifier=None):
    times = []
    mod = (modifier or "").strip().lower()
    for ev in events:
        if len(ev) < 3 or str(ev[2]) != code:
            continue
        if mod:
            ev_mod = str(ev[3]).lower() if len(ev) > 3 and ev[3] is not None else ""
            if mod not in ev_mod:
                continue
        times.append(float(ev[0]))
    times.sort()
    return pair_state_events(times)


def collect_window_intervals(events, window_codes):
    times = {c: [] for c in window_codes}
    for ev in events:
        if len(ev) < 3:
            continue
        code = str(ev[2])
        if code in window_codes:
            times[code].append(float(ev[0]))
    windows = []
    for code, ts in times.items():
        ts.sort()
        windows.extend(pair_state_events(ts))
    return windows


# --------------------------------------------------------------------------- #
# GIF creation (two-pass palette, then optional gifsicle compression)
# --------------------------------------------------------------------------- #
def make_gif(video_path, start_time, duration, output_gif, fps,
             max_colors, dither, bayer_scale, gifsicle_colors, gifsicle_lossy):
    with tempfile.TemporaryDirectory() as td:
        palette = str(Path(td) / "palette.png")

        vf_palette = (f"fps={fps},"
                      f"palettegen=max_colors={max_colors}:stats_mode=full")
        run_command(["ffmpeg", "-y", "-ss", str(start_time), "-t", str(duration),
                     "-i", str(video_path), "-vf", vf_palette, palette])

        if str(dither).lower() == "none":
            paletteuse = "paletteuse=dither=none"
        else:
            paletteuse = f"paletteuse=dither={dither}:bayer_scale={bayer_scale}"
        vf_gif = f"fps={fps}[x];[x][1:v]{paletteuse}"
        run_command(["ffmpeg", "-y", "-ss", str(start_time), "-t", str(duration),
                     "-i", str(video_path), "-i", palette,
                     "-lavfi", vf_gif, str(output_gif)])

        gifsicle = shutil.which("gifsicle")
        if gifsicle is not None and gifsicle_lossy is not None:
            subprocess.run([gifsicle, "-O3", f"--lossy={gifsicle_lossy}",
                            "--colors", str(gifsicle_colors),
                            str(output_gif), "-o", str(output_gif)],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)


# --------------------------------------------------------------------------- #
# Extraction (no GUI; driven by a config dict)
# --------------------------------------------------------------------------- #
def run_extraction(project, cfg):
    out_root = Path(cfg["output_root"])
    out_root.mkdir(parents=True, exist_ok=True)
    for b in cfg["behaviours"]:
        (out_root / b["token"]).mkdir(parents=True, exist_ok=True)

    window_codes = set(cfg.get("windows", []))

    for obs_name, obs in tqdm(project.get("observations", {}).items(),
                              desc="Observations"):
        try:
            stored = obs["file"]["1"][0]
            video_path = resolve_video_path(stored, cfg.get("video_dir"))
            if video_path is None:
                print(f"WARNING: video not found: {ntpath.basename(str(stored))}")
                continue

            events = obs.get("events", [])
            source_fps, length = get_fps_length(obs, stored, video_path)
            if length is None:
                print(f"WARNING: no duration for {obs_name}; skipping")
                continue

            windows = (collect_window_intervals(events, window_codes)
                       if window_codes else None)
            if window_codes and not windows:
                print(f"WARNING: no window intervals in {obs_name}")
                continue

            base = clean_video_stem(ntpath.basename(str(stored)), cfg["strip_date"])

            for b in cfg["behaviours"]:
                intervals = collect_behaviour_intervals(
                    events, b["code"], b.get("modifier"))
                if not intervals:
                    print(f"WARNING: no '{b['code']}' events in {obs_name}")
                    continue

                segments = []
                for iv in intervals:
                    if windows is not None:
                        segments.extend(intersect_with_windows(iv, windows))
                    else:
                        segments.append(iv)

                counter = 0
                for start, stop in segments:
                    counter += 1
                    start = max(0.0, start - b["pad"])
                    stop = min(length, stop + b["pad"])
                    duration = stop - start
                    if duration <= 0:
                        continue
                    fps = source_fps if b["fps"] == "source" else b["fps"]
                    if not fps or fps <= 0:
                        fps = source_fps or 10
                    outfile = (out_root / b["token"]
                               / f"{base}_{b['token']}_{counter}.gif")
                    make_gif(video_path, start, duration, outfile, fps,
                             cfg["max_colors"], cfg["dither"], cfg["bayer_scale"],
                             cfg["gifsicle_colors"], cfg["gifsicle_lossy"])
                    print(outfile)

        except Exception as e:
            print(f"ERROR processing {obs_name}: {e}")


# --------------------------------------------------------------------------- #
# Setup GUI (tkinter imported lazily so the logic above stays importable)
# --------------------------------------------------------------------------- #
def configure(project, boris_path):
    import tkinter as tk
    from tkinter import filedialog, messagebox

    codes = discover_codes(project)
    needs_video_dir = project_needs_video_dir(project)

    root = tk.Tk()
    root.title("BORIS GIF extraction - setup")
    state = {"ok": False, "cfg": None}

    # --- paths -----------------------------------------------------------
    paths = tk.LabelFrame(root, text="Paths", padx=8, pady=6)
    paths.pack(fill="x", padx=8, pady=6)

    tk.Label(paths, text="BORIS file:").grid(row=0, column=0, sticky="w")
    tk.Label(paths, text=boris_path, anchor="w").grid(row=0, column=1,
                                                      columnspan=2, sticky="w")

    tk.Label(paths, text="Output folder:").grid(row=1, column=0, sticky="w")
    out_var = tk.StringVar()
    tk.Entry(paths, textvariable=out_var, width=60).grid(row=1, column=1, sticky="we")
    tk.Button(paths, text="Browse",
              command=lambda: out_var.set(
                  filedialog.askdirectory(title="Output folder") or out_var.get())
              ).grid(row=1, column=2, padx=4)

    tk.Label(paths, text="Video folder:").grid(row=2, column=0, sticky="w")
    vid_var = tk.StringVar()
    vid_entry = tk.Entry(paths, textvariable=vid_var, width=60)
    vid_entry.grid(row=2, column=1, sticky="we")
    vid_btn = tk.Button(paths, text="Browse",
                        command=lambda: vid_var.set(
                            filedialog.askdirectory(title="Video folder")
                            or vid_var.get()))
    vid_btn.grid(row=2, column=2, padx=4)
    note = ("Required: project stores relative video paths."
            if needs_video_dir else
            "Optional: project stores absolute video paths (used as-is).")
    tk.Label(paths, text=note, fg="#555").grid(row=3, column=1, sticky="w")
    if not needs_video_dir:
        vid_entry.config(state="disabled")
        vid_btn.config(state="disabled")
    paths.columnconfigure(1, weight=1)

    # --- behaviour table (scrollable) ------------------------------------
    tbl_frame = tk.LabelFrame(
        root, text="Codes found in project  -  tick behaviours to extract "
                   "and/or codes to use as windows", padx=4, pady=4)
    tbl_frame.pack(fill="both", expand=True, padx=8, pady=6)

    canvas = tk.Canvas(tbl_frame, height=240)
    sb = tk.Scrollbar(tbl_frame, orient="vertical", command=canvas.yview)
    inner = tk.Frame(canvas)
    inner.bind("<Configure>",
               lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.configure(yscrollcommand=sb.set)
    canvas.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")

    headers = ["Code (count)", "Extract", "Token", "Modifier contains",
               "Pad (s)", "fps", "Window"]
    for c, h in enumerate(headers):
        tk.Label(inner, text=h, font=("Segoe UI", 9, "bold")).grid(
            row=0, column=c, padx=4, sticky="w")

    rows = []
    for r, (code, meta) in enumerate(
            sorted(codes.items(), key=lambda kv: -kv[1]["count"]), start=1):
        extract_var = tk.BooleanVar(value=False)
        window_var = tk.BooleanVar(value=False)
        token_var = tk.StringVar(value=slugify(code))
        mod_var = tk.StringVar(value="")
        pad_var = tk.StringVar(value=str(DEFAULTS["pad_sec"]))
        fps_var = tk.StringVar(value=str(DEFAULTS["fps"]))

        tk.Label(inner, text=f"{code}  ({meta['count']})", anchor="w").grid(
            row=r, column=0, padx=4, sticky="w")
        tk.Checkbutton(inner, variable=extract_var).grid(row=r, column=1)
        tk.Entry(inner, textvariable=token_var, width=14).grid(row=r, column=2, padx=2)
        tk.Entry(inner, textvariable=mod_var, width=18).grid(row=r, column=3, padx=2)
        tk.Entry(inner, textvariable=pad_var, width=6).grid(row=r, column=4, padx=2)
        tk.Entry(inner, textvariable=fps_var, width=8).grid(row=r, column=5, padx=2)
        tk.Checkbutton(inner, variable=window_var).grid(row=r, column=6)

        rows.append({"code": code, "extract": extract_var, "window": window_var,
                     "token": token_var, "modifier": mod_var,
                     "pad": pad_var, "fps": fps_var})

    # --- quality ---------------------------------------------------------
    q = tk.LabelFrame(root, text="GIF quality", padx=8, pady=6)
    q.pack(fill="x", padx=8, pady=6)
    qvars = {}

    def qfield(col, label, key, width=8, options=None):
        tk.Label(q, text=label).grid(row=0, column=col * 2, sticky="e", padx=2)
        var = tk.StringVar(value=str(DEFAULTS[key]))
        qvars[key] = var
        if options:
            tk.OptionMenu(q, var, *options).grid(row=0, column=col * 2 + 1, sticky="w")
        else:
            tk.Entry(q, textvariable=var, width=width).grid(
                row=0, column=col * 2 + 1, sticky="w", padx=2)

    qfield(0, "max_colors", "max_colors", 6)
    qfield(1, "dither", "dither",
           options=["bayer", "none", "sierra2", "sierra2_4a", "floyd_steinberg"])
    qfield(2, "bayer_scale", "bayer_scale", 4)
    qfield(3, "gifsicle colors", "gifsicle_colors", 6)
    qfield(4, "gifsicle lossy", "gifsicle_lossy", 6)
    tk.Label(q, text="(leave gifsicle lossy blank to skip gifsicle)",
             fg="#555").grid(row=1, column=0, columnspan=10, sticky="w")

    strip_var = tk.BooleanVar(value=False)
    tk.Checkbutton(root, variable=strip_var,
                   text="Strip trailing _DATE token (8 digits) from filenames"
                   ).pack(anchor="w", padx=10)

    # --- run / cancel ----------------------------------------------------
    def on_run():
        out_root = out_var.get().strip()
        if not out_root:
            messagebox.showwarning("Missing", "Choose an output folder.")
            return
        if needs_video_dir and not vid_var.get().strip():
            messagebox.showwarning("Missing", "This project uses relative video "
                                              "paths - choose the video folder.")
            return
        behaviours = []
        windows = []
        for row in rows:
            if row["window"].get():
                windows.append(row["code"])
            if not row["extract"].get():
                continue
            try:
                pad = float(row["pad"].get())
            except ValueError:
                messagebox.showwarning("Invalid",
                                       f"Pad for '{row['code']}' must be a number.")
                return
            fps_text = row["fps"].get().strip().lower()
            if fps_text in ("source", "src", "original"):
                fps = "source"
            else:
                try:
                    fps = float(fps_text)
                except ValueError:
                    messagebox.showwarning(
                        "Invalid",
                        f"fps for '{row['code']}' must be a number or 'source'.")
                    return
            behaviours.append({"code": row["code"],
                               "token": slugify(row["token"].get()),
                               "modifier": row["modifier"].get().strip() or None,
                               "pad": pad, "fps": fps})
        if not behaviours:
            messagebox.showwarning("Nothing to do",
                                   "Tick at least one behaviour to extract.")
            return

        try:
            max_colors = int(qvars["max_colors"].get())
            bayer_scale = int(qvars["bayer_scale"].get())
            gifsicle_colors = int(qvars["gifsicle_colors"].get())
            lossy_text = qvars["gifsicle_lossy"].get().strip()
            gifsicle_lossy = int(lossy_text) if lossy_text else None
        except ValueError:
            messagebox.showwarning("Invalid", "Quality fields must be whole numbers.")
            return

        state["cfg"] = {
            "output_root": out_root,
            "video_dir": vid_var.get().strip() or None,
            "behaviours": behaviours,
            "windows": windows,
            "strip_date": strip_var.get(),
            "max_colors": max_colors,
            "dither": qvars["dither"].get(),
            "bayer_scale": bayer_scale,
            "gifsicle_colors": gifsicle_colors,
            "gifsicle_lossy": gifsicle_lossy,
        }
        state["ok"] = True
        root.destroy()

    btns = tk.Frame(root)
    btns.pack(fill="x", padx=8, pady=8)
    tk.Button(btns, text="Run extraction", command=on_run).pack(side="right")
    tk.Button(btns, text="Cancel", command=root.destroy).pack(side="right", padx=6)

    root.mainloop()
    return state["cfg"] if state["ok"] else None


# --------------------------------------------------------------------------- #
def main():
    import tkinter as tk
    from tkinter import filedialog

    picker = tk.Tk()
    picker.withdraw()
    boris_path = filedialog.askopenfilename(
        title="Select BORIS project file",
        filetypes=[("BORIS project", "*.boris"), ("JSON", "*.json"),
                   ("All files", "*.*")])
    picker.destroy()
    if not boris_path:
        print("No BORIS file selected.")
        return

    with open(boris_path, "r", encoding="utf-8") as f:
        project = json.load(f)

    cfg = configure(project, boris_path)
    if cfg is None:
        print("Cancelled.")
        return

    run_extraction(project, cfg)
    print("Done. GIFs written under", cfg["output_root"])


if __name__ == "__main__":
    main()
