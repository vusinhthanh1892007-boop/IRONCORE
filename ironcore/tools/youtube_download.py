"""
IronCore Tool: YouTube Download
================================
Download YouTube videos/audio using yt-dlp.
Supports: video, audio-only, metadata extraction.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from ironcore.core.engine import RiskLevel
from ironcore.skills.registry import SkillParameterSchema, skill

logger = logging.getLogger(__name__)

_OUTPUT_DIR = os.environ.get("IRONCORE_MEDIA_DIR", "/tmp/ironcore-media")


def _ensure_output_dir() -> Path:
    p = Path(_OUTPUT_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


async def _run_ytdlp(args: list[str]) -> dict:
    """Run yt-dlp as a subprocess and capture output."""
    proc = await asyncio.create_subprocess_exec(
        "yt-dlp", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {"error": "Download timed out after 300s"}

    return {
        "stdout": (stdout or b"").decode("utf-8", errors="replace"),
        "stderr": (stderr or b"").decode("utf-8", errors="replace"),
        "exit_code": proc.returncode,
    }


@skill(
    name="youtube_download",
    version="1.0.0",
    description="Download a YouTube video or extract its audio. Returns the local file path.",
    long_description=(
        "Uses yt-dlp to download YouTube content. Supports full video download, "
        "audio-only extraction (mp3/wav), and metadata-only mode. "
        "Requires yt-dlp to be installed (pip install yt-dlp)."
    ),
    author="brain",
    tags=["youtube", "video", "audio", "download", "media"],
    risk_level=RiskLevel.MEDIUM,
    requires_network=True,
    estimated_latency_ms=30000.0,
    cost_tier="free",
    parameters=[
        SkillParameterSchema(name="url", type="string", description="YouTube video URL", required=True),
        SkillParameterSchema(
            name="mode",
            type="string",
            description="'video', 'audio', or 'info' (metadata only)",
            required=False,
            default="video",
            enum_values=["video", "audio", "info"],
        ),
        SkillParameterSchema(
            name="quality",
            type="string",
            description="Video quality: 'best', '1080', '720', '480'",
            required=False,
            default="best",
        ),
        SkillParameterSchema(
            name="audio_format",
            type="string",
            description="Audio format when mode=audio: 'mp3', 'wav', 'aac'",
            required=False,
            default="mp3",
        ),
    ],
)
async def youtube_download(
    url: str,
    mode: str = "video",
    quality: str = "best",
    audio_format: str = "mp3",
) -> str:
    """Download YouTube content or extract metadata."""
    if not url or "youtube.com" not in url and "youtu.be" not in url:
        return json.dumps({"error": "Invalid YouTube URL"})

    output_dir = _ensure_output_dir()

    if mode == "info":
        result = await _run_ytdlp([
            "--dump-json", "--no-download", "--no-playlist", url,
        ])
        if result.get("exit_code", 1) != 0:
            return json.dumps({"error": result.get("stderr", "Failed to fetch info")})
        try:
            info = json.loads(result["stdout"])
            return json.dumps({
                "title": info.get("title"),
                "duration": info.get("duration"),
                "uploader": info.get("uploader"),
                "view_count": info.get("view_count"),
                "description": (info.get("description") or "")[:2000],
                "thumbnail": info.get("thumbnail"),
                "formats_available": len(info.get("formats", [])),
            }, ensure_ascii=False)
        except json.JSONDecodeError:
            return json.dumps({"error": "Failed to parse video info"})

    # Build yt-dlp arguments
    output_template = str(output_dir / "%(title)s.%(ext)s")
    args = [
        "--no-playlist",
        "--restrict-filenames",
        "-o", output_template,
    ]

    if mode == "audio":
        args.extend([
            "-x",
            "--audio-format", audio_format,
            "--audio-quality", "0",
        ])
    else:
        if quality == "best":
            args.extend(["-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"])
        else:
            args.extend(["-f", f"bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/best[height<={quality}]/best"])

    args.append(url)

    # Print filename to stdout
    args.extend(["--print", "after_move:filepath"])

    result = await _run_ytdlp(args)

    if result.get("exit_code", 1) != 0:
        return json.dumps({
            "error": result.get("stderr", "Download failed"),
            "exit_code": result.get("exit_code"),
        })

    filepath = result.get("stdout", "").strip().split("\n")[-1].strip()
    if filepath and os.path.exists(filepath):
        file_size = os.path.getsize(filepath)
        return json.dumps({
            "status": "downloaded",
            "mode": mode,
            "filepath": filepath,
            "size_bytes": file_size,
            "size_mb": round(file_size / (1024 * 1024), 2),
        })

    return json.dumps({
        "status": "completed",
        "mode": mode,
        "output": result.get("stdout", "")[:2000],
        "note": "File downloaded but path could not be determined. Check output directory.",
    })
