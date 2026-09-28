# Handoff: Install the /watch skill from Jonas's fork

You are setting up the `/watch` skill inside Claude Code for Jonas Nicolas. He is usually on his phone, so do everything you can yourself and only ask him for what only he can provide.

## What this is

`/watch` gives a coding agent the ability to actually watch a video: a YouTube URL or local file becomes timestamped frames plus a transcript. Repo (his fork, MIT): https://github.com/jonasnicolas/claude-video — upstream is bradautomates/claude-video.

The end goal after setup: the "YouTube-to-Agent Engine" workflow. Jonas pastes a tutorial video, two readers watch it and write up what they see, they are wrong in different ways, and Jonas only manually checks where they disagree. The output is a working skill inside the agent that runs the workflow the video taught.

## Step 1: Install the plugin

Run these **inside a Claude Code session**, one at a time:

```
/plugin marketplace add jonasnicolas/claude-video
/plugin install watch@claude-video
```

If `/watch` does not appear afterward, start a new Claude Code session and ask for the watch skill by name. Do NOT install from the upstream URL; Jonas forked it so upstream changes can't break his setup.

## Step 2: Pick an engine

### Option A: Gemini engine (recommended, fastest)

No media tools needed. The agent sends the YouTube URL straight to Google's video model and relays the timestamped answer.

1. Ask Jonas for his Google AI Studio API key (he has one; he uses it for bulk AI work).
2. Write it to `~/.config/watch/.env` as:

```
GEMINI_API_KEY=the-key-he-gave-you
```

3. Set file permissions to 0600.
4. Note: local files uploaded this way are deleted after the answer (or auto-expire within 48h). Don't use this engine for sensitive videos; use Option B for those.

### Option B: Local engine (private videos, nothing uploaded)

Needs Python 3.10+, ffmpeg/ffprobe, latest yt-dlp, and Deno. Have the agent run the bundled `setup.py --check` first and report what's missing. Install per OS:

- **Windows (PowerShell):** `winget install --id Gyan.FFmpeg --exact`, `winget install --id yt-dlp.yt-dlp --exact`, `winget install --id DenoLand.Deno --exact`, plus Python 3.10+ from python.org. Verify with `python --version`.
- **WSL2 / Ubuntu:** `sudo apt install python3 ffmpeg pipx`, then `pipx install "yt-dlp[default,curl-cffi]"` and `pipx ensurepath`, then install Deno per docs.deno.com.

Transcription fallback: native captions come first automatically. If a video has no captions and speech matters, ask Jonas to choose: local WhisperX (no key; needs ~3GB disk and 8GB RAM; run `setup.py --install-whisperx`), his Groq key (`GROQ_API_KEY`), or skip (`none` = captions only).

## Step 3: Prove it works

```
/watch https://youtu.be/dQw4w9WgXcQ --detail balanced
```

Ask: what happens at the 30 second mark? Success = a timestamped visual summary. Then try a real tutorial URL of Jonas's choosing with `--detail transcript` for full evidence.

## Ongoing rules

- Keep yt-dlp on its **latest** release. YouTube routinely breaks older ones; a 403 usually means "update yt-dlp and retry once."
- This skill does NOT work in Claude Chat, Cowork, or browser surfaces. Only Claude Code (terminal, VS Code, or a Code session in Claude Desktop) and other local agents.
- Config lives in `~/.config/watch/.env`. Never paste keys into chat logs or commit them.
- Best accuracy on videos under 10 minutes, or use `--start`/`--end` to focus an interval.
