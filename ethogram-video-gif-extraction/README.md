# GIF creation pipeline from BORIS project files for ethogram clips

This is the pipeline I use to turn behaviours coded in [BORIS](https://www.boris.unito.it/)
from overhead video into a set of short, straightened, cropped GIFs suitable for
an ethogram (a labelled catalogue of behaviour types). My footage is filmed
from a fixed overhead camera, so every clip needs the same kind of treatment:
cut the behaviour out of the long recording, then straighten and crop it down to
the region of interest. If using a non-stabilized camera, such as a GoPro strapped
to your chest, the script may still work IF there is not too much shakiness/change
in position between the first frame and final frame, although in that case, it 
might be better to modify the script to extract more than 2 timepoints to ensure
crop regions do not lose any regions of interest.

Two separate scripts handle the automatable parts. The rest is deliberate manual 
work, because deciding which clips are good examples of a behaviour is a judgement 
call which I feel is important to leave in the hands of the experimenter.

The pipeline design and workflow logic are my own. The two Python scripts were 
developed to my specification using AI-assisted coding tools. The extraction script
(`boris_gif_extraction.py`) was initially generated with ChatGPT and later modified
and generalized with Claude 4.8. The crop-selection utility (`gif_crop_picker.py`)
was written with Claude 4.8. The README was initially drafted with Claude 4.8 and
subsequently reviewed and edited by me. See [Credits](#credits) for additional details.

Development and testing were conducted in June 2026 on a Windows 11 system. Testing
was limited to a single hardware and software configuration, and no systematic
compatibility testing or version-comparison trials were performed.

*Importantly, the script as-is benefits from an NVIDIA GPU, although CPU options are given.*

**Hardware**

* HP OMEN 25L desktop
* AMD Ryzen 5 5600G CPU
* NVIDIA GeForce RTX 3060 GPU
* 16 GB RAM (15.8 GB usable)

**Software**

* Windows 11 Version 25H2 (OS Build 26200.8457)
* Python 3.10.19
* Conda 25.11.1
* FFmpeg 2025-01-05 (full build from Gyan.dev)
* Spyder 6.1.2
* BORIS 8.27.10

Users running different operating systems, hardware configurations, Python environments,
or software versions may encounter behaviour that has not been tested.

## The pipeline

1. **Code your videos in BORIS.** Score the behaviours of interest, and, if you
   use them, mark the time windows / phases you want to restrict clips to. All of
   these should be recorded as state events (start/stop pairs). As a side note,
   at least for me, BORIS plays nice with .avi videos and is not pleased when asked
   to handle .mov or .mp4 videos, so conversion may helpful if videos are choppy or
   difficult to work with. One approach that has worked well for me is converting
   videos to AVI format using H.264 encoding with a short keyframe interval (e.g.,
   one keyframe every 10–15 frames) and no B-frames. Frequent keyframes improve
   seeking accuracy because BORIS can jump to nearby frames more readily, while
   disabling B-frames reduces dependence on future and past frames during navigation.
   The trade-off is increased file size. Depending on the source videos and hardware,
   users may wish to experiment with different encoding settings. For users converting
   files with FFmpeg, the following Windows Command Prompt command will process all
   .mp4 files in a folder and create AVI copies with settings that have worked well in 
   BORIS (replace `PATH_TO_FOLDER` with the location of your videos; the `-g 15` option
   inserts a keyframe every 15 frames, while `-bf 0` disables B-frames):

   ```bat
   for %F in ("PATH_TO_FOLDER\*.mp4") do ffmpeg.exe -y -i "%F" -an -c:v h264_nvenc -b:v 0 -profile:v high -g 15 -bf 0 "%~dpnF.avi"
   ```

   **This command needs an NVIDIA GPU.** `-c:v h264_nvenc` is NVIDIA's hardware
   encoder and requires both an NVIDIA GPU and an ffmpeg build that includes nvenc
   (the Gyan.dev full build does). If you have no NVIDIA GPU, or you get an
   `Unknown encoder 'h264_nvenc'` error, use the CPU encoder `libx264` instead. It
   is slower but works anywhere; `-crf 18` sets near-visually-lossless quality
   (lower is higher quality / larger files):

   ```bat
   for %F in ("PATH_TO_FOLDER\*.mp4") do ffmpeg.exe -y -i "%F" -an -c:v libx264 -crf 18 -preset medium -g 15 -bf 0 "%~dpnF.avi"
   ```
2. **Extract behaviour GIFs.** Run `boris_gif_extraction.py`. It reads the
   project, you pick which behaviours to cut and which codes act as windows, and
   it writes one full-resolution GIF per instance into a folder per behaviour.
3. **Audit and curate.** Look through the extracted GIFs and decide which to
   keep. Delete the ones you don't want, or move the keepers into a separate
   folder. This step is entirely manual and is the point of extracting at full
   resolution first.
4. **Pick crop and rotation.** Run `gif_crop_picker.py` on the folder of GIFs you
   kept. For each clip you set a rotation angle and draw a crop window; it saves
   your choices and writes a batch script.
5. **Apply the crop.** Run the generated `apply_crops.bat` (or `apply_crops.sh`).
   The cropped clips are written to a `cropped/` subfolder.

If you do not use BORIS, you can start at step 4: the crop picker works on any
folder of GIFs and does not depend on the rest of the pipeline.

## What you need

- **Python 3.8 or newer** (developed and tested on 3.10).
- **ffmpeg and ffprobe** on your PATH (both come with an ffmpeg install). Check
  with `ffmpeg -version`. On Windows: `winget install ffmpeg`, or use the Gyan.dev
  full build used during testing.
- **gifsicle** on your PATH (optional). If present, the extraction script uses it
  for extra compression; if absent, it is skipped. On Windows, install it via a
  package manager such as Chocolatey (`choco install gifsicle`) or download a build
  from the gifsicle website and put it on your PATH.
- **Python packages:** `tqdm` (progress bar; optional). `tkinter` ships with the
  standard Python installer on Windows and macOS; on some Linux distributions
  install it with `sudo apt install python3-tk`.
- **Pillow** is needed only by the crop picker: `pip install pillow`.

Both `requirements.txt` (pip) and `environment.yml` (conda) install the Python
packages for you; see [Installation](#installation).

### A note on PATH

"On your PATH" means you can run a program by name from any terminal without typing
its full location. To check what you have, open a new terminal and run each of:

```bat
ffmpeg -version
ffprobe -version
gifsicle --version
```

If any of these reports something like `'ffmpeg' is not recognized`, that program
is either not installed or its folder has not been added to your PATH. On Windows,
add the folder that contains the `.exe` to the PATH environment variable
(Settings → System → About → Advanced system settings → Environment Variables →
edit `Path`), then open a new terminal so the change takes effect. ffmpeg and
ffprobe live in the same folder, so adding it once covers both. gifsicle is only
needed if you want the optional extra-compression pass.

## Files in this repository

- `boris_gif_extraction.py`: step 2, the extraction tool.
- `gif_crop_picker.py`: step 4, the crop / rotation picker.
- `requirements.txt`: Python dependencies for pip.
- `environment.yml`: equivalent conda environment.
- `LICENSE`: MIT licence (full text).
- `.gitignore`: excludes generated output, caches, and editor/OS files.
- `README.md`: this file.

## The scripts

### boris_gif_extraction.py (step 2)

Cuts behaviour clips out of the source videos and writes them as GIFs. Everything
is chosen at runtime, so the script runs on any BORIS project without editing it.

When you run it:

- A file dialog asks for the `.boris` project file.
- A setup window reads the project and shows every behaviour code that appears in
  it, with the number of events for each. For each code you can tick **Extract**
  (cut clips from this behaviour) and/or **Window** (use this code's intervals to
  restrict where clips are taken from). Per extracted behaviour you can set the
  output filename token, an optional modifier filter, the padding in seconds, and
  the output fps (a number, or `source` for the video's own rate).
- A video-folder field is required only when the project stores relative video
  paths; if the paths are absolute they are used directly. Choose the top-level
  folder within which subfolders are contained relative to the .boris project.
- Quality settings (palette colours, dither, gifsicle compression) are exposed in
  the same window.

How it reads a BORIS project (format 7.0 JSON): `observations` is a dict, one
entry per video. Each observation has `file`, where `file["1"][0]` is the video
path, and `events`, a list where element 0 is the time in seconds and element 2
is the behaviour code (element 3, if present, is the modifier). Behaviours are
treated as state events: for each code the times in order alternate start, stop,
start, stop, and are paired accordingly. Per-video frame rate and length come
from `media_info`, with an ffprobe fallback if that information is missing.

Window intersection: if you mark one or more codes as windows, every behaviour
instance is intersected with those windows and only the overlapping portions are
written, one clip per overlap. If you mark no windows, whole instances are
written.

Output: one subfolder per behaviour under your chosen output folder. Filenames
are `<video stem>_<token>_<n>`, where `n` counts that behaviour's instances
within that video from 1. The optional "strip trailing _DATE" box removes a final
8-digit date token from the video name before building the filename (this matches
my own naming convention; leave it off if your filenames don't end in a date).

Quality: clips are cut at full resolution with no scaling, on the assumption you
will crop later. GIFs use the two-pass palette method (`palettegen` then
`paletteuse`) for reasonable quality at full size, then an optional `gifsicle`
pass for further compression. Lower the palette colours or raise the gifsicle
lossy value to trade quality for smaller files.

### gif_crop_picker.py (step 4)

Lets you set a rotation and crop for each GIF visually, then writes ffmpeg
commands that apply them in a batch.

When you run it (`python gif_crop_picker.py [folder]`; with no argument it opens a
folder dialog), it first extracts the first and last frame of each GIF into a
`_frames/` subfolder, then opens a reviewer showing those two frames side by
side. For each clip:

- Type a rotation angle in degrees (clockwise-positive; decimals allowed) and
  press Apply, or use the `+/-` buttons. Both frames rotate live.
- Click and drag on the first frame to draw the crop window; the same box is
  mirrored onto the last frame so you can confirm it still fits at the end of the
  clip.
- Prev / Next move between clips and auto-save as you go.
- There is no option to zoom in or out at this time. However, the full clip should
  be automatically resized to fit the window.

Rotation is applied first, then crop. The crop is clamped to the original frame
dimensions, so the output never exceeds the input size and no padding is
introduced. Rotation that swings a frame's corners out of view shows those
corners as grey in the preview; keep the crop box inside the live image or those
edges will appear in the output.

On exit it writes `crop_settings.json` (your choices, editable and resumable) and
`apply_crops.bat` / `apply_crops.sh` containing one ffmpeg command per clip:

```
ffmpeg -y -i "in.gif" -vf "rotate=A*PI/180,crop=w:h:x:y" "cropped/in.gif"
```

Rotation convention: positive degrees rotate clockwise, matching ffmpeg's
`rotate` filter, so the preview matches the output.

## Installation

Get the files either way:

- Install with git (clone the repository), or
- Download the repository as a ZIP using the green "Code" button on GitHub, then
  unzip it.

Open a terminal in the resulting folder and install the Python dependencies with
either pip or conda:

```bash
pip install -r requirements.txt
```

or, if you use conda:

```bash
conda env create -f environment.yml
conda activate boris-gif-pipeline
```

ffmpeg, ffprobe, and (optionally) gifsicle are not Python packages and are not
installed by either command; install them separately and put them on your PATH
(see [What you need](#what-you-need)).

## Usage, step by step

### Step 1 - BORIS coding

Code your videos in BORIS as usual. Record the target behaviours, and any phase
or window intervals you want to restrict to, as state events.

### Step 2 - extract

```bash
python boris_gif_extraction.py
```

Pick the `.boris` file, fill in the setup window (output folder; video folder if
the project uses relative paths; tick behaviours and windows; set padding, fps,
and quality), then click Run extraction. Progress prints to the console, with a
line per clip written and a warning for any missing video or empty behaviour.

### Step 3 - audit and curate

Open the per-behaviour folders and review the GIFs. Delete the ones you don't
want, or copy the keepers into a new folder. The crop picker in the next step
works on whichever folder you point it at, so either approach is fine.

### Step 4 - pick crop and rotation

```bash
python gif_crop_picker.py
```

Choose the folder of curated GIFs. Set rotation and crop for each clip, then
choose Finish & exit.

### Step 5 - apply the crop

Open the GIF folder, double-click `apply_crops.bat`, and wait for it to finish.
The cropped clips appear in a `cropped/` subfolder. If you would rather see any
errors, run it from a terminal instead (in File Explorer, click the address bar,
type `cmd`, press Enter, then type `apply_crops.bat`).

## Output layout

```
OUTPUT_ROOT/                 (step 2)
  peering/        op_..._peering_1.gif, ...
  circumnav/      ...
  passing_clouds/ ...

curated_folder/              (step 3, your choice)
  _frames/                   (step 4: extracted first/last frames)
  crop_settings.json         (step 4)
  apply_crops.bat            (step 4)
  apply_crops.sh             (step 4)
  cropped/                   (step 5: the finished clips)
```

## Troubleshooting

- **`'ffmpeg' is not recognized` / `'ffprobe' is not recognized`.** ffmpeg is not
  installed or not on PATH. Install it and reopen the terminal (see the PATH note
  under "What you need").
- **`Unknown encoder 'h264_nvenc'` during the step-1 conversion.** Your machine
  has no NVIDIA GPU, or your ffmpeg build lacks nvenc. Use the `libx264` CPU
  command given in step 1 instead.
- **The batch window closes instantly in step 5.** Run `apply_crops.bat` from a
  terminal (the address-bar `cmd` method above) so error messages stay on screen.
- **A behaviour shows "no events".** That code had no instances in that
  observation, or your modifier filter excluded them all. The script skips and
  continues.
- **A video is reported as not found.** For relative paths, check the video
  folder you selected actually contains the file named in the project. The script
  also searches subfolders. For absolute paths, check the file still exists at the
  recorded location.
- **No window intervals found.** You marked a code as a window but that
  observation has no paired start/stop events for it. Clips for that observation
  are skipped; mark no windows if you want whole instances.
- **GIF colours look banded after re-encoding.** In step 5, each script includes
  a commented palette-preserving ffmpeg variant; swap it in for the affected clip.
  In step 2, raise `max_colors` or change the dither.
- **A black sliver along an edge of a cropped clip.** The crop box reached into a
  rotation-exposed corner. Re-open that clip in the crop picker, nudge the crop
  inward, and regenerate.
- **Odd number of state events warning.** A behaviour or window has an unpaired
  start or stop in BORIS. The script ignores the last unpaired event; fix the
  coding in BORIS if the clip count looks wrong.

## Credits

- Pipeline design, specification, and workflow: Willa M. Lane.
- `boris_gif_extraction.py`: written by ChatGPT to the author's specification,
  then generalised for interactive use by Claude Opus 4.8.
- `gif_crop_picker.py`: written by Claude Opus 4.8 to the author's
  specification.
- [BORIS](https://www.boris.unito.it/) is developed at the University of Turin
  and is not affiliated with this project.

## License

Released under the MIT License; the full text is in the [LICENSE](LICENSE) file.
