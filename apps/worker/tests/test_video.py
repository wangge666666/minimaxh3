import pytest

from comfy_hub_worker.references import normalize_reference
from comfy_hub_worker.video import faststart, finalize_video, make_poster, validate_video


def test_real_mp4_decodes_audio_and_video(synthetic_mp4):
    meta = validate_video(synthetic_mp4, {"width": 640, "height": 384})
    assert meta["fps"] == 24
    assert meta["audio_codec"] == "aac"
    assert abs(meta["duration"] - 124 / 24) < 0.2


def test_mp4_dimension_mismatch_is_rejected(synthetic_mp4):
    with pytest.raises(ValueError, match="尺寸"):
        validate_video(synthetic_mp4, {"width": 512, "height": 512})


def test_fake_video_is_rejected():
    with pytest.raises(ValueError, match="MP4"):
        validate_video(b"this is not a video", {"width": 640, "height": 384})


def test_exact_ratio_export_crops_padding_and_optionally_removes_audio(synthetic_mp4):
    job = {"width": 640, "height": 360, "frames": 124, "fps": 24, "sound": False}
    output = finalize_video(synthetic_mp4, job)
    meta = validate_video(output, job)
    assert meta["height"] == 360
    assert not meta["audio_codec"]


def test_requested_frame_count_is_checked_even_with_small_duration_difference(synthetic_mp4):
    with pytest.raises(ValueError, match="帧数"):
        validate_video(synthetic_mp4, {"width": 640, "height": 384, "frames": 123})


def test_reference_video_and_audio_are_decoded_and_normalized(synthetic_mp4):
    video, suffix, mime, audio = normalize_reference(synthetic_mp4, "video", max_duration=5.17)
    assert suffix == ".mp4" and mime == "video/mp4" and audio
    assert len(video) > 1024
    wav, suffix, mime, audio = normalize_reference(synthetic_mp4, "audio")
    assert suffix == ".wav" and mime == "audio/wav" and audio
    assert wav[:4] == b"RIFF"


def test_invalid_reference_media_fails_before_submission():
    with pytest.raises(ValueError, match="时长"):
        normalize_reference(b"fake .mp4", "video")


def test_poster_is_a_small_jpeg_from_the_video(synthetic_mp4):
    import io

    from PIL import Image

    poster = make_poster(synthetic_mp4)
    with Image.open(io.BytesIO(poster)) as image:
        assert image.format == "JPEG" and max(image.size) <= 640
        assert image.width / image.height == 640 / 384
    assert len(poster) < 256 * 1024


def test_native_size_mp4_is_remuxed_for_progressive_playback(synthetic_mp4, tmp_path):
    source, target = tmp_path / "source.mp4", tmp_path / "tail.mp4"
    source.write_bytes(synthetic_mp4)
    from comfy_hub_worker.references import ffmpeg

    ffmpeg(["-v", "error", "-y", "-i", str(source), "-c", "copy", str(target)])
    assert not faststart(target.read_bytes())
    result = finalize_video(target.read_bytes(), {"width": 640, "height": 384})
    assert faststart(result)
    validate_video(result, {"width": 640, "height": 384})
