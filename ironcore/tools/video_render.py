"""
IronCore Tool: Video Render / Compose
======================================
Compose video from images, audio, and text overlays using ffmpeg.
Supports: slideshow from images + audio, video concatenation, text overlay.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import List, Optional

from ironcore.core.engine import RiskLevel
from ironcore.skills.registry import SkillParameterSchema, skill

logger = logging.getLogger(__name__)

_OUTPUT_DIR = os.environ.get("IRONCORE_MEDIA_DIR", "/tmp/ironcore-media")


def _ensure_output_dir() -> Path:
    p = Path(_OUTPUT_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


async def _run_ffmpeg(args: list[str], timeout: int = 300) -> dict:
    """Execute ffmpeg and capture output."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {"error": f"ffmpeg timed out after {timeout}s", "exit_code": -1}

    return {
        "stdout": (stdout or b"").decode("utf-8", errors="replace"),
        "stderr": (stderr or b"").decode("utf-8", errors="replace"),
        "exit_code": proc.returncode,
    }


@skill(
    name="video_render",
    version="1.0.0",
    description="Compose a video from images, audio, and text. Uses ffmpeg for rendering.",
    long_description=(
        "Create videos from components: "
        "1) 'slideshow' mode: images + audio → video with transitions. "
        "2) 'concat' mode: concatenate multiple videos. "
        "3) 'overlay' mode: add text/subtitle overlay to existing video. "
        "Requires ffmpeg installed on the system."
    ),
    author="brain",
    tags=["video", "render", "ffmpeg", "compose", "media"],
    risk_level=RiskLevel.MEDIUM,
    requires_network=False,
    estimated_latency_ms=60000.0,
    cost_tier="free",
    parameters=[
        SkillParameterSchema(
            name="mode",
            type="string",
            description="Render mode: 'slideshow', 'concat', or 'overlay'",
            required=True,
            enum_values=["slideshow", "concat", "overlay"],
        ),
        SkillParameterSchema(
            name="inputs",
            type="list",
            description="List of input file paths (images for slideshow, videos for concat)",
            required=True,
        ),
        SkillParameterSchema(name="audio_path", type="string", description="Audio file to use as background track", required=False),
        SkillParameterSchema(name="duration_per_image", type="float", description="Seconds per image in slideshow mode", required=False, default=4.0),
        SkillParameterSchema(name="text", type="string", description="Text overlay content (for overlay mode)", required=False),
        SkillParameterSchema(name="output_format", type="string", description="Output format: 'mp4', 'webm'", required=False, default="mp4"),
        SkillParameterSchema(name="resolution", type="string", description="Output resolution: '1920x1080', '1280x720', etc.", required=False, default="1920x1080"),
    ],
)
async def video_render(
    mode: str,
    inputs: list,
    audio_path: Optional[str] = None,
    duration_per_image: float = 4.0,
    text: Optional[str] = None,
    output_format: str = "mp4",
    resolution: str = "1920x1080",
) -> str:
    """Render a video from components."""
    if not inputs:
        return json.dumps({"error": "No input files provided"})

    # Validate inputs exist
    missing = [f for f in inputs if not Path(f).exists()]
    if missing:
        return json.dumps({"error": f"Missing input files: {missing}"})

    output_dir = _ensure_output_dir()
    output_file = output_dir / f"video_{uuid.uuid4().hex[:12]}.{output_format}"

    width, height = resolution.split("x") if "x" in resolution else ("1920", "1080")

    if mode == "slideshow":
        # Create slideshow from images with optional audio
        # Write file list for ffmpeg concat demuxer
        list_file = output_dir / f"_list_{uuid.uuid4().hex[:8]}.txt"
        lines = []
        for img_path in inputs:
            safe_path = str(Path(img_path).resolve()).replace("'", "'\\''")
            lines.append(f"file '{safe_path}'")
            lines.append(f"duration {duration_per_image}")
        # Repeat last image to avoid cut
        if inputs:
            safe_path = str(Path(inputs[-1]).resolve()).replace("'", "'\\''")
            lines.append(f"file '{safe_path}'")
        list_file.write_text("\n".join(lines))

        args = [
            "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
            "-pix_fmt", "yuv420p",
        ]

        if audio_path and Path(audio_path).exists():
            args.extend(["-i", str(audio_path), "-c:a", "aac", "-shortest"])

        args.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "23", str(output_file)])

        result = await _run_ffmpeg(args)
        list_file.unlink(missing_ok=True)

    elif mode == "concat":
        # Concatenate multiple videos
        list_file = output_dir / f"_list_{uuid.uuid4().hex[:8]}.txt"
        lines = []
        for vid_path in inputs:
            safe_path = str(Path(vid_path).resolve()).replace("'", "'\\''")
            lines.append(f"file '{safe_path}'")
        list_file.write_text("\n".join(lines))

        args = [
            "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c", "copy", str(output_file),
        ]
        result = await _run_ffmpeg(args)
        list_file.unlink(missing_ok=True)

    elif mode == "overlay":
        # Add text overlay to video
        if not text:
            return json.dumps({"error": "Text is required for overlay mode"})

        escaped = text.replace("'", "\\'").replace(":", "\\:")
        args = [
            "-y", "-i", str(inputs[0]),
            "-vf", f"drawtext=text='{escaped}':fontsize=48:fontcolor=white:x=(w-text_w)/2:y=h-100:box=1:boxcolor=black@0.5:boxborderw=10",
            "-c:a", "copy",
            str(output_file),
        ]
        result = await _run_ffmpeg(args)

    else:
        return json.dumps({"error": f"Unknown mode: {mode}"})

    if result.get("exit_code", -1) != 0:
        return json.dumps({
            "error": "ffmpeg rendering failed",
            "stderr": result.get("stderr", "")[:2000],
            "exit_code": result.get("exit_code"),
        })

    if output_file.exists():
        return json.dumps({
            "status": "rendered",
            "filepath": str(output_file),
            "mode": mode,
            "size_bytes": output_file.stat().st_size,
            "size_mb": round(output_file.stat().st_size / (1024 * 1024), 2),
            "resolution": resolution,
        })

    return json.dumps({"error": "Output file was not created", "stderr": result.get("stderr", "")[:2000]})
