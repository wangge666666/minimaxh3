import subprocess

import imageio_ffmpeg
import pytest


@pytest.fixture(scope="module")
def synthetic_mp4(tmp_path_factory):
    path = tmp_path_factory.mktemp("h3-video-test") / "fixture.mp4"
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=navy:s=640x384:r=24",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-frames:v",
            "124",
            "-t",
            str(124 / 24),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(path),
        ],
        capture_output=True,
        timeout=20,
        check=True,
    )
    return path.read_bytes()
