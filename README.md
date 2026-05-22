# StoryCut AI

StoryCut AI is a local Windows desktop MVP for creators who make legal, transformative movie review and storytelling videos. It helps with video metadata, audio extraction, timestamped transcription, transcript search, clip planning, FFmpeg clip export, and rule-based narration script drafting.

The app does not include features for bypassing copyright detection, evading Content ID, disguising copyrighted footage, or guaranteeing copyright safety. The checklist is guidance only, not legal advice.

## Features

- Create, save, and load local projects from a chosen `.storycut.json` location.
- Refresh the currently loaded project from disk with `Refresh Project` or `F5` without restarting the app.
- Import large Video Ori files by path without copying the source media.
- Read duration, file size, resolution, FPS, codecs, and audio availability with FFprobe.
- Extract mono WAV audio with FFmpeg for transcription.
- Transcribe audio locally with faster-whisper and save timestamped segments to SQLite.
- Import existing `.txt` transcript/subtitle files, including plain DownSub exports.
- Extract embedded Indonesian subtitle streams from imported videos when the subtitle is text-based.
- Import external subtitle files such as `.srt`, `.vtt`, `.ass`, and `.ssa`.
- Extract visual scene frames with FFmpeg for manual scene notes.
- Draft visual scene notes automatically with an optional local BLIP vision model.
- Search transcript text and view results in a table.
- Use the `File` menu for New Project, Open Project, Save Project, Import Video Ori, and Export Video.
- Work in an editor-style layout with Video Ori preview, rough-cut preview, Manual Clips, and the main timeline.
- Add transcript segments or visual selections into Manual Clips.
- Visually preview the imported Video Ori, scrub the timeline, mark in/out points, and save manual cuts.
- Edit clip start and end timestamps manually.
- Drag Manual Clips into the main rough-cut timeline, reorder them, split them, delete them, and trim them to the current Video Ori selection.
- Preview selected timeline clips and export the final timeline as MP4 with resolution, FPS, bitrate, output name, and save location settings.
- Build one chronological random rough-cut video from short Video Ori clips.
- Build a rough-cut timeline from Video Ori using the draggable range slider.
- Export multiple rough-cut parts from different Video Ori ranges, then combine the finished parts into one MP4.
- Keep rough-cut Video Ori clips at five seconds or shorter.
- Use a short conflict video clip from Video Ori as the rough-cut hook.
- Fill each scene with nearby video snippets instead of repeating one clip when possible.
- Add light zoom, alternating mirror, fade transitions, and color grading for review pacing.
- Mute Video Ori audio by default and optionally replace it with a selected royalty-free music file.
- Set the rough-cut target duration as a percentage of the full Video Ori or selected Video Ori range.
- Generate a local rule-based YouTube narration draft in Bahasa Indonesia or English.
- Generate a ready-to-read Indonesian movie plot recap script from transcript text and optional visual scene notes.
- Save generated narration scripts as `.txt`.
- Generate an analysis-oriented draft with these sections:
  - Pancingan / Hook
  - Pembuka / Setup
  - Konflik / Conflict
  - Alur utama / Main story
  - Klimaks / Climax
  - Analisis / Analysis
  - Penutup / Closing
- Store export/progress logs in the project file.
- Package as a Windows `.exe` with PyInstaller.

## Project Structure

```text
storycut_ai/
  main.py
  requirements.txt
  README.md
  app/
    gui/
      main_window.py
      widgets.py
    core/
      video_utils.py
      audio_utils.py
      transcriber.py
      scene_utils.py
      vision_captioner.py
      montage.py
      cutter.py
      script_generator.py
      project_manager.py
      database.py
    projects/
```

## Requirements

- Windows 10 or newer.
- Python 3.11 recommended. Python 3.14 is not recommended for local translation support because `sentencepiece` may fail to build on Windows.
- FFmpeg installed locally, with `ffmpeg.exe` and `ffprobe.exe` available on `PATH`.
- Python packages from `requirements.txt`.
- Optional for burned-in subtitle OCR: Tesseract OCR for Windows.
- Optional for foreign voice to Indonesian script: Argos Translate English -> Indonesian model.
- Optional for automatic visual scene notes: local BLIP image captioning model.

The app does not require paid APIs or web services. faster-whisper runs locally. If you use a named model such as `base`, make sure the model is already available on the machine or enter a local model path in the model field.

The script generator can output an Indonesian draft. The `Alur Cerita Film` mode cleans transcript/subtitle text into a ready-to-read recap narration, similar to Indonesian movie recap scripts. It is rule-based, so it works best when the transcript already contains narration or Indonesian subtitle text. Raw foreign-language audio should be paired with Indonesian subtitles, then use `Extract ID Subtitles`, `Import Subtitle File`, or `OCR Burned Subtitles`.

For visual clip editing, use the `Editor` tab. Import Video Ori, scrub the Video Ori preview, click `Mark In` and `Mark Out`, then click `Save Manual Clip` to place that range in `Manual Clips`. Manual Clips stay in that panel until you drag them into the main timeline or click `Add to Timeline`.

The main timeline is non-destructive: every rough-cut or manual clip still points back to Video Ori timestamps. You can drag Manual Clips into the start, middle, end, or between existing timeline clips, reorder timeline rows, split a selected clip, delete clips, zoom the timeline rows, and trim a selected timeline clip to the current Video Ori selection.

For visual rough cuts, use the `Rough Cut` tab. It samples Video Ori clips at five seconds or shorter, keeps them in chronological order, puts a short conflict video clip at the start, fills each scene with nearby snippets so it has enough narration space, targets an approximate final duration, and exports one MP4. Use `Video Ori Range` to render or build only a portion of Video Ori first, for example minute 10 to minute 25. Export another range afterward, then use `Combine Parts` to merge the finished rough-cut parts. The rough-cut controls can add light zoom, alternating mirror, fade transitions, and color grading for review/storytelling rhythm. Video Ori audio is muted by default; choose a royalty-free music file if you want a new background track. These tools are provided for original commentary, review, and education, not for hiding or disguising copyrighted footage.

Set `Target %` to make the final rough-cut duration proportional to the selected Video Ori range. For example, `12%` of a 100-minute full Video Ori becomes a 12-minute target, while `12%` of a selected 30-minute Video Ori range becomes a 3.6-minute target. `Target duration` is calculated automatically from that percentage. `Max clips` is only used when the calculated target duration is `0 min`.

For automatic visual notes, install local vision support, then use `Auto Describe Empty Notes` in the `Scenes` tab. The app fills empty notes from the extracted thumbnails and keeps them editable. Notes you already typed are preserved.

Install optional local vision support with:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_vision_support.ps1
```

You can also double-click `install_vision_support.cmd`. This installs local image captioning dependencies and downloads the BLIP model into the local model cache. Restart StoryCut AI after installation.

For foreign-language voice narration without usable subtitles, use `Voice -> ID Script`. It uses faster-whisper locally to translate speech to English, then Argos Translate locally to translate English to Indonesian.

Install optional local translation support with:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_translation_support.ps1
```

You can also double-click `install_translation_support.cmd`. Then restart StoryCut AI.

If you see a `sentencepiece` build error, your virtual environment is probably using Python 3.14. Double-click `setup_python311_env.cmd`, then run `install_translation_support.cmd` again.

If Indonesian subtitles are burned into the video image, use `OCR Burned Subtitles`. OCR is slower and less accurate than importing a real subtitle file, but it can recover readable Indonesian captions when the subtitle is clear.

Install optional OCR support with:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_ocr_support.ps1
```

You can also double-click `install_ocr_support.cmd`. Then restart StoryCut AI.

## Setup

From this folder:

```powershell
cd "D:\Project\Tools Editing\storycut_ai"
powershell -ExecutionPolicy Bypass -File .\setup_python311_env.ps1
```

You can also double-click `setup_python311_env.cmd`. This creates `.venv311`, installs dependencies, and refreshes the desktop shortcut. The launcher automatically prefers `.venv311` when it exists.

Check FFmpeg:

```powershell
ffmpeg -version
ffprobe -version
```

If those commands are not found but FFmpeg was installed by `winget`, restart PowerShell and StoryCut AI. The app also checks common WinGet install folders automatically. You can also place `ffmpeg.exe` and `ffprobe.exe` in:

```text
storycut_ai\bin\
```

Run the app:

```powershell
.\.venv311\Scripts\python.exe main.py
```

## Run By Clicking The Desktop Icon

After dependencies are installed, create a desktop shortcut:

```powershell
powershell -ExecutionPolicy Bypass -File .\create_desktop_shortcut.ps1
```

Then double-click `StoryCut AI` on the Desktop. The shortcut uses `launch_storycut_ai.vbs`, which starts the app with `pythonw.exe` so no terminal window opens.

## Refresh Project Without Restarting

Click `Refresh Project` or press `F5` to reload the currently opened `.storycut.json` file from disk. This is useful when project data changes while the app is already open. Python code changes still require restarting the app process.

## Basic Workflow

1. Click `New Project`, enter a name, then choose where to save the `.storycut.json` project file.
2. Use `File -> Import Video Ori`.
3. Confirm metadata appears in the Video Ori panel.
4. Open `Rough Cut`, drag `Video Ori Range`, set `Target %`, then click `Build Timeline`.
5. In `Editor`, scrub Video Ori, use `Mark In` / `Mark Out`, then click `Save Manual Clip`.
6. Drag Manual Clips into the main timeline wherever you want them, or select them and click `Add to Timeline`.
7. Edit the timeline with split, delete, reorder, trim-to-Video-Ori-selection, zoom, undo, and redo.
8. Set export resolution, FPS, bitrate, output file, then use `File -> Export Video` or the `Export Video` button.
9. Open `Subtitle Indonesia` to generate Indonesian SRT subtitles from video audio when needed.

## Timestamp Format

Editable clip timestamps accept seconds, `MM:SS.mmm`, or `HH:MM:SS.mmm`.

Examples:

```text
83.5
01:23.500
00:01:23.500
```

## Windows Build Instructions

Install dependencies first, then run PyInstaller from the `storycut_ai` folder:

```powershell
pyinstaller --noconfirm --clean --windowed --name "StoryCut AI" main.py
```

The executable will be created under:

```text
dist\StoryCut AI\StoryCut AI.exe
```

FFmpeg is not bundled by default. For a simple MVP install, keep `ffmpeg.exe` and `ffprobe.exe` on the system `PATH`.

To bundle FFmpeg binaries manually, put them in a local `bin` folder and build with:

```powershell
pyinstaller --noconfirm --clean --windowed --name "StoryCut AI" --add-binary "bin\ffmpeg.exe;." --add-binary "bin\ffprobe.exe;." main.py
```

If you bundle FFmpeg this way, update the app later to resolve the packaged binary path before calling FFmpeg.

## Notes For Future Improvements

- Add waveform-based trimming.
- Add scene-change detection so visual frames are sampled by shot boundaries instead of only fixed intervals.
- Add local model path browsing for faster-whisper.
- Add optional speaker labels when a reliable local diarization path is chosen.
- Add subtitle export formats such as `.srt` and `.vtt`.
- Add batch clip export presets.
- Add project-level media relinking when Video Ori moves.
- Add more advanced local script outlining while keeping creator commentary central.
- Add automated tests around timestamp parsing, project persistence, and FFmpeg command generation.
