"""Decode local reference files before allowing them into a GPU workflow."""

import io
import re
import subprocess
import tempfile
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageOps


def ffmpeg(args: list[str], timeout=45, check=True):
    result = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-nostdin", "-threads", "2", *args],
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode:
        raise ValueError("素材无法完整解码，请换一个有效的媒体文件")
    return result


def media_input(path: Path) -> list[str]:
    return [
        "-protocol_whitelist",
        "file,pipe",
        "-format_whitelist",
        "mov,matroska,webm,wav,mp3,flac,ogg,aac",
        "-i",
        str(path),
    ]


def normalize_reference(data: bytes, kind: str, *, canvas=None, max_duration=15.0):
    if kind == "image":
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > 16_000_000:
                raise ValueError("参考图片超过 1600 万像素")
            image = ImageOps.exif_transpose(image).convert("RGB")
            if canvas:
                image = ImageOps.fit(image, canvas, method=Image.Resampling.LANCZOS)
            stream = io.BytesIO()
            image.save(stream, format="PNG")
            return stream.getvalue(), ".png", "image/png", False
    if kind not in {"video", "audio"} or not data or len(data) > 20 * 1024 * 1024:
        raise ValueError("参考素材类型或大小无效")
    with tempfile.TemporaryDirectory(prefix="hub-reference-") as temp:
        source = Path(temp) / "input"
        source.write_bytes(data)
        info = ffmpeg([*media_input(source)], timeout=10, check=False).stderr.decode(
            errors="replace"
        )
        match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", info)
        if not match:
            raise ValueError("无法读取素材时长")
        seconds = int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3])
        if not (2 if kind == "video" else 0.1) <= seconds <= 15.1:
            raise ValueError("参考视频需为 2–15 秒，参考音频需为 0.1–15 秒")
        has_audio = bool(re.search(r"Stream .*Audio:", info))
        out = Path(temp) / ("reference.mp4" if kind == "video" else "reference.wav")
        args = [
            "-v",
            "error",
            "-xerror",
            "-y",
            *media_input(source),
            "-t",
            str(min(seconds, max_duration)),
        ]
        if kind == "video":
            dimensions = re.search(r"Video:.*? (\d{2,5})x(\d{2,5})(?:[ ,\[])", info)
            if not dimensions or int(dimensions[1]) * int(dimensions[2]) > 16_000_000:
                raise ValueError("参考视频画面无效或超过 1600 万像素")
            args += [
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-vf",
                "scale=w='min(768,iw)':h='min(768,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,fps=24",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-threads",
                "2",
                "-c:a",
                "aac",
                "-ac",
                "2",
                "-ar",
                "32000",
                "-movflags",
                "+faststart",
            ]
        else:
            if not has_audio:
                raise ValueError("参考音频中没有可读取的声音")
            args += ["-map", "0:a:0", "-vn", "-c:a", "pcm_s16le", "-ac", "2", "-ar", "32000"]
        ffmpeg([*args, str(out)])
        result = out.read_bytes()
        if not result or len(result) > 20 * 1024 * 1024:
            raise ValueError("处理后的参考素材超过 20 MB")
        return result, out.suffix, "video/mp4" if kind == "video" else "audio/wav", has_audio
