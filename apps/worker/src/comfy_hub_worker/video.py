import re
import subprocess
import tempfile
from pathlib import Path

import imageio_ffmpeg

from comfy_hub_worker.references import ffmpeg, media_input


def faststart(data: bytes) -> bool:
    offset = 0
    while offset + 8 <= len(data):
        size = int.from_bytes(data[offset : offset + 4], "big")
        kind = data[offset + 4 : offset + 8]
        if kind == b"moov":
            return True
        if kind == b"mdat":
            return False
        if size == 1:
            size = int.from_bytes(data[offset + 8 : offset + 16], "big")
        if size < 8:
            break
        offset += size
    return False


def make_poster(data: bytes) -> bytes:
    with tempfile.TemporaryDirectory(prefix="hub-poster-") as temp:
        source, target = Path(temp) / "video.mp4", Path(temp) / "poster.jpg"
        source.write_bytes(data)
        ffmpeg(
            [
                "-v",
                "error",
                "-y",
                *media_input(source),
                "-ss",
                "0.1",
                "-frames:v",
                "1",
                "-vf",
                "scale=w='min(640,iw)':h='min(640,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
                "-q:v",
                "3",
                str(target),
            ],
            timeout=15,
        )
        poster = target.read_bytes()
        if not poster or len(poster) > 256 * 1024:
            raise ValueError("视频封面过大或为空")
        return poster


def finalize_video(data: bytes, job: dict) -> bytes:
    # H3 samples a 32px grid. Crop only the small padding area for exact ratios.
    width, height = job["width"], job["height"]
    native = {
        **job,
        "width": (width + 31) // 32 * 32,
        "height": (height + 31) // 32 * 32,
        "sound": True,
    }
    validate_video(data, native)
    if (
        (width, height) == (native["width"], native["height"])
        and job.get("sound", True)
        and faststart(data)
    ):
        return data
    with tempfile.TemporaryDirectory(prefix="hub-export-") as temp:
        source, target = Path(temp) / "input.mp4", Path(temp) / "output.mp4"
        source.write_bytes(data)
        args = ["-v", "error", "-xerror", "-y", *media_input(source), "-map", "0:v:0"]
        if (width, height) != (native["width"], native["height"]):
            args += [
                "-vf",
                f"crop={width}:{height}:(iw-ow)/2:(ih-oh)/2",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-threads",
                "2",
            ]
        else:
            args += ["-c:v", "copy"]
        args += ["-map", "0:a:0", "-c:a", "copy"] if job.get("sound", True) else ["-an"]
        ffmpeg([*args, "-movflags", "+faststart", str(target)])
        output = target.read_bytes()
        validate_video(output, job)
        return output


def validate_video(data: bytes, job: dict) -> dict:
    if not 1024 <= len(data) <= 64 * 1024 * 1024 or data[4:8] != b"ftyp":
        raise ValueError("视频不是有效的 MP4 或超过 64 MB")
    with tempfile.TemporaryDirectory(prefix="hub-video-") as temp:
        path = Path(temp) / "result.mp4"
        path.write_bytes(data)
        frames = imageio_ffmpeg.read_frames(str(path))
        try:
            metadata = next(frames)
        finally:
            frames.close()
        if tuple(metadata["size"]) != (job["width"], job["height"]):
            raise ValueError("视频尺寸与任务不一致")
        if (
            abs(metadata["fps"] - job.get("fps", 24)) > 0.1
            or abs(metadata["duration"] - job.get("frames", 124) / job.get("fps", 24)) > 0.2
        ):
            raise ValueError("视频帧率或时长与任务不一致")
        sound = job.get("sound", True)
        if (
            metadata.get("codec") != "h264"
            or (sound and metadata.get("audio_codec") != "aac")
            or (not sound and metadata.get("audio_codec"))
        ):
            raise ValueError("预期 H.264 视频与 AAC 音频")
        result = subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-v",
                "error",
                "-xerror",
                "-nostdin",
                "-threads",
                "2",
                "-protocol_whitelist",
                "file,pipe",
                "-i",
                str(path),
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-progress",
                "pipe:1",
                "-nostats",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            timeout=45,
            check=False,
        )
        if result.returncode:
            raise ValueError("视频或音频解码失败")
        counts = re.findall(rb"(?:^|\n)frame=(\d+)", result.stdout)
        if not counts or int(counts[-1]) != job.get("frames", 124):
            raise ValueError("视频实际帧数与任务不一致")
        return {
            "width": metadata["size"][0],
            "height": metadata["size"][1],
            "fps": metadata["fps"],
            "duration": metadata["duration"],
            "codec": metadata["codec"],
            "audio_codec": metadata.get("audio_codec"),
        }
