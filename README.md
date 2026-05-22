# StoryCut AI

StoryCut AI is a local Windows desktop MVP for creators who make legal, transformative movie review and storytelling videos. It helps with video metadata, audio extraction, timestamped transcription, transcript search, clip planning, FFmpeg clip export, and rule-based narration script drafting.

The app does not include features for bypassing copyright detection, evading Content ID, disguising copyrighted footage, or guaranteeing copyright safety. The checklist is guidance only, not legal advice.

## Features

- Create, save, and load local projects from a chosen `.storycut.json` location.
- Refresh the currently loaded project from disk with `Refresh Project` or `F5` without restarting the app.
- Import large video files by path without copying the source media.
- Read duration, file size, resolution, FPS, codecs, and audio availability with FFprobe.
- Extract mono WAV audio with FFmpeg for transcription.
- Transcribe audio locally with faster-whisper and save timestamped segments to SQLite.
- Import existing `.txt` transcript/subtitle files, including plain DownSub exports.
- Extract embedded Indonesian subtitle streams from imported videos when the subtitle is text-based.
- Import external subtitle files such as `.srt`, `.vtt`, `.ass`, and `.ssa`.
- Extract visual scene frames with FFmpeg for manual scene notes.
- Draft visual scene notes automatically with an optional local BLIP vision model.
- Search transcript text and view results in a table.
- Add transcript segments to an editable cut list.
- Visually preview the imported video, scrub the timeline, mark in/out points, and add cuts like a conventional video editor.
- Edit clip start and end timestamps manually.
- Apply a visual timeline selection directly to an existing cut list row.
- Export selected clips with FFmpeg.
- Build one chronological random rough-cut video from short source clips.
- Select a source video range for rough-cut export with a draggable range slider.
- Export multiple rough-cut parts from different source ranges, then combine the finished parts into one MP4.
- Keep rough-cut source clips at five seconds or shorter.
- Use a short conflict video clip from the source as the rough-cut hook.
- Fill each scene with nearby video snippets instead of repeating one clip when possible.
- Add light zoom, alternating mirror, fade transitions, and color grading for review pacing.
- Mute source audio by default and optionally replace it with a selected royalty-free music file.
- Set a target final duration for rough-cut exports, with a 10-15 minute recap workflow in mind.
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

For visual clip editing, use the `Visual Cut` tab. Import a video, scrub the preview timeline, click `Mark In` and `Mark Out`, then click `Add Cut` to place that range in the cut list. Selecting an existing cut row loads its range back into the visual editor, so you can adjust the start/end points and click `Apply to Selected`.

For visual rough cuts, use the `Rough Cut` tab. It samples source clips at five seconds or shorter, keeps them in chronological order, puts a short conflict video clip at the start, fills each scene with nearby snippets so it has enough narration space, targets an approximate final duration, and exports one MP4. Use `Source Range` to render only a portion of the source video first, for example minute 10 to minute 25. Export another range afterward, then use `Combine Parts` to merge the finished rough-cut parts. The rough-cut controls can add light zoom, alternating mirror, fade transitions, and color grading for review/storytelling rhythm. Source audio is muted by default; choose a royalty-free music file if you want a new background track. These tools are provided for original commentary, review, and education, not for hiding or disguising copyrighted footage.

Set `Target final duration` above zero when you want a specific output length. In that mode, the app calculates how many scenes are needed from the target duration and trims the final export to that target. `Max clips` is only used when `Target final duration` is `0 min`.

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
2. Click `Import Video`.
3. Confirm metadata appears in the Media panel.
4. Open `Visual Cut`, scrub the video preview, use `Mark In` / `Mark Out`, then click `Add Cut`.
5. Select a cut row to load its range back into the visual editor, adjust it, then click `Apply to Selected`.
6. Select cut list rows and click `Export Selected Clips`.
7. Open `Rough Cut`, drag `Source Range` to choose the source section, keep `Clip length` at `5 sec`, set `Target final duration`, then click `Export Rough Cut Video`.
8. Repeat with the next source range when needed, then click `Combine Parts` to merge the finished rough-cut outputs.
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
- Add project-level media relinking when a source video moves.
- Add more advanced local script outlining while keeping creator commentary central.
- Add automated tests around timestamp parsing, project persistence, and FFmpeg command generation.
