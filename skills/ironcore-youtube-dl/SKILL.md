---
name: ironcore-youtube-dl
description: Download YouTube videos or extract audio (MP3) using yt-dlp. Supports any YouTube URL.
metadata: {"openclaw": {"emoji": "▶️", "requires": {"bins": ["yt-dlp", "python3"]}}}
---

# IronCore YouTube Downloader

Download YouTube videos or extract audio using yt-dlp. Fast, reliable, supports all quality options.

## When to use
- User asks to download a YouTube video or audio
- User gives a YouTube URL and wants the file locally
- User wants to extract MP3/audio from a video
- User wants to get video metadata without downloading

## Prerequisites check
Before running, verify yt-dlp is installed:
```bash
yt-dlp --version || pip install yt-dlp
```

## Modes

### Download video (default, best quality)
```bash
URL="YOUTUBE_URL_HERE"
OUTPUT_DIR="$HOME/Downloads"
yt-dlp -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" \
  --merge-output-format mp4 \
  -o "$OUTPUT_DIR/%(title)s.%(ext)s" \
  "$URL" 2>&1 | tail -20
echo "Downloaded to: $OUTPUT_DIR"
```

### Extract audio only (MP3)
```bash
URL="YOUTUBE_URL_HERE"
OUTPUT_DIR="$HOME/Downloads"
yt-dlp -x --audio-format mp3 --audio-quality 192K \
  -o "$OUTPUT_DIR/%(title)s.%(ext)s" \
  "$URL" 2>&1 | tail -20
echo "Audio saved to: $OUTPUT_DIR"
```

### Get metadata only (no download)
```bash
URL="YOUTUBE_URL_HERE"
yt-dlp --dump-json --no-download "$URL" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'Title     : {d.get(\"title\")}')
print(f'Duration  : {d.get(\"duration_string\", str(d.get(\"duration\")) + \"s\")}')
print(f'Views     : {d.get(\"view_count\", 0):,}')
print(f'Uploader  : {d.get(\"uploader\")}')
print(f'Upload    : {d.get(\"upload_date\")}')
print(f'Resolution: {d.get(\"resolution\", \"N/A\")}')
print(f'Filesize  : ~{d.get(\"filesize_approx\", 0)//1024//1024}MB')
"
```

## Steps
1. Identify what the user wants: full video, audio only, or metadata
2. Extract the YouTube URL from the user's message
3. Determine output directory (default: `$HOME/Downloads`)
4. Run the appropriate command above, replacing `YOUTUBE_URL_HERE`
5. Report the file path and size when done

## Notes
- yt-dlp is the maintained fork of youtube-dl and works with YouTube as of 2026
- Maximum timeout: 5 minutes for large files
- Output directory defaults to `~/Downloads` — ask user if they prefer a different location
- Playlist URLs are supported; will download all videos in the playlist
