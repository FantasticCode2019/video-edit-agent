"""Tests for video_editor schema, validator, and executor modules."""

from __future__ import annotations

import os
import tempfile

import pytest

from openharness.video_editor.schema import (
    AudioTrack,
    FillBackground,
    ImageOverlay,
    SubtitleConfig,
    SubtitleStyle,
    Transition,
    VideoClip,
    VideoEditRequest,
    VideoFilter,
    VideoOverlay,
)
from openharness.video_editor.validator import (
    ValidationResult,
    VideoEditValidationError,
    validate_request,
)
from openharness.video_editor.executor import to_ffmpeg_params, build_dry_run


# ---------------------------------------------------------------------------
# schema.py — VideoClip
# ---------------------------------------------------------------------------


class TestVideoClip:
    def test_defaults(self):
        clip = VideoClip(path="/tmp/v.mp4")
        assert clip.start_time == 0
        assert clip.duration is None
        assert clip.keep_original_audio is True

    def test_negative_start_time_rejected(self):
        with pytest.raises(Exception, match="start_time"):
            VideoClip(path="/tmp/v.mp4", start_time=-1)

    def test_zero_duration_rejected(self):
        with pytest.raises(Exception, match="duration"):
            VideoClip(path="/tmp/v.mp4", duration=0)

    def test_negative_duration_rejected(self):
        with pytest.raises(Exception, match="duration"):
            VideoClip(path="/tmp/v.mp4", duration=-5)

    def test_valid_clip(self):
        clip = VideoClip(path="/tmp/v.mp4", start_time=30, duration=60, keep_original_audio=False)
        assert clip.start_time == 30
        assert clip.duration == 60
        assert clip.keep_original_audio is False


# ---------------------------------------------------------------------------
# schema.py — AudioTrack
# ---------------------------------------------------------------------------


class TestAudioTrack:
    def test_defaults(self):
        track = AudioTrack(path="/tmp/a.mp3")
        assert track.delay == 0
        assert track.is_bg_music is False
        assert track.volume == 1.0
        assert track.fade_in_duration is None

    def test_negative_delay_rejected(self):
        with pytest.raises(Exception):
            AudioTrack(path="/tmp/a.mp3", delay=-1)

    def test_zero_volume_rejected(self):
        with pytest.raises(Exception, match="volume"):
            AudioTrack(path="/tmp/a.mp3", volume=0)

    def test_negative_fade_rejected(self):
        with pytest.raises(Exception):
            AudioTrack(path="/tmp/a.mp3", fade_in_duration=-1)

    def test_bgm_with_fade(self):
        track = AudioTrack(path="/tmp/bgm.mp3", is_bg_music=True, fade_in_duration=2, fade_out_duration=3)
        assert track.is_bg_music is True
        assert track.fade_in_duration == 2
        assert track.fade_out_duration == 3


# ---------------------------------------------------------------------------
# schema.py — SubtitleConfig
# ---------------------------------------------------------------------------


class TestSubtitleConfig:
    def test_file_mode_requires_path(self):
        with pytest.raises(Exception, match="file_path"):
            SubtitleConfig(mode="file")

    def test_file_mode_with_path(self):
        cfg = SubtitleConfig(mode="file", file_path="/tmp/sub.ass")
        assert cfg.file_path == "/tmp/sub.ass"

    def test_whisper_mode_defaults(self):
        cfg = SubtitleConfig(mode="whisper")
        assert cfg.language == "zh"
        assert cfg.file_path is None

    def test_invalid_mode_rejected(self):
        with pytest.raises(Exception):
            SubtitleConfig(mode="invalid")


# ---------------------------------------------------------------------------
# schema.py — ImageOverlay
# ---------------------------------------------------------------------------


class TestImageOverlay:
    def test_valid_overlay(self):
        img = ImageOverlay(path="/tmp/logo.png", start_time=0, end_time=10, box=[100, 100, 200, 50])
        assert img.rotate == 0

    def test_box_wrong_length_rejected(self):
        with pytest.raises(Exception, match="box"):
            ImageOverlay(path="/tmp/logo.png", start_time=0, end_time=10, box=[100, 100])

    def test_end_before_start_rejected(self):
        with pytest.raises(Exception, match="end_time"):
            ImageOverlay(path="/tmp/logo.png", start_time=10, end_time=5, box=[0, 0, 100, 100])


# ---------------------------------------------------------------------------
# schema.py — VideoEditRequest
# ---------------------------------------------------------------------------


class TestVideoEditRequest:
    def test_empty_videos_rejected(self):
        with pytest.raises(Exception, match="至少需要一个视频"):
            VideoEditRequest(videos=[])

    def test_invalid_resolution_rejected(self):
        with pytest.raises(Exception, match="resolution"):
            VideoEditRequest(
                videos=[VideoClip(path="/tmp/v.mp4")],
                resolution="invalid",
            )

    def test_negative_resolution_rejected(self):
        with pytest.raises(Exception, match="正整数"):
            VideoEditRequest(
                videos=[VideoClip(path="/tmp/v.mp4")],
                resolution="-100x200",
            )

    def test_minimal_valid_request(self):
        req = VideoEditRequest(videos=[VideoClip(path="/tmp/v.mp4")])
        assert req.resolution == "1920x1080"
        assert req.output_filename == "output.mp4"
        assert req.audios == []
        assert req.subtitles is None

    def test_full_request(self):
        req = VideoEditRequest(
            videos=[
                VideoClip(path="/tmp/v1.mp4", keep_original_audio=False),
                VideoClip(path="/tmp/v2.mp4", start_time=10, duration=30),
            ],
            audios=[
                AudioTrack(path="/tmp/tts.mp3"),
                AudioTrack(path="/tmp/bgm.mp3", is_bg_music=True, fade_in_duration=1),
            ],
            subtitles=SubtitleConfig(mode="file", file_path="/tmp/sub.ass"),
            video_filter=VideoFilter(saturation=1.2),
            resolution="1280x720",
            output_filename="final.mp4",
        )
        assert len(req.videos) == 2
        assert len(req.audios) == 2
        assert req.video_filter.saturation == 1.2


# ---------------------------------------------------------------------------
# validator.py
# ---------------------------------------------------------------------------


class TestValidator:
    def _make_temp_file(self, tmp_path, name="test.mp4"):
        p = tmp_path / name
        p.write_bytes(b"\x00")
        return str(p)

    def test_valid_request_passes(self, tmp_path):
        video_path = self._make_temp_file(tmp_path, "v.mp4")
        req = VideoEditRequest(videos=[VideoClip(path=video_path)])
        result = validate_request(req)
        assert result.ok
        assert result.errors == []

    def test_missing_video_file_raises(self, tmp_path):
        req = VideoEditRequest(videos=[VideoClip(path="/nonexistent/video.mp4")])
        with pytest.raises(VideoEditValidationError) as exc_info:
            validate_request(req)
        assert "文件不存在" in exc_info.value.errors[0]

    def test_missing_audio_file_raises(self, tmp_path):
        video_path = self._make_temp_file(tmp_path, "v.mp4")
        req = VideoEditRequest(
            videos=[VideoClip(path=video_path)],
            audios=[AudioTrack(path="/nonexistent/audio.mp3")],
        )
        with pytest.raises(VideoEditValidationError) as exc_info:
            validate_request(req)
        assert "audios[0]" in exc_info.value.errors[0]

    def test_missing_subtitle_file_raises(self, tmp_path):
        video_path = self._make_temp_file(tmp_path, "v.mp4")
        req = VideoEditRequest(
            videos=[VideoClip(path=video_path)],
            subtitles=SubtitleConfig(mode="file", file_path="/nonexistent/sub.ass"),
        )
        with pytest.raises(VideoEditValidationError) as exc_info:
            validate_request(req)
        assert "字幕文件不存在" in exc_info.value.errors[0]

    def test_missing_image_file_raises(self, tmp_path):
        video_path = self._make_temp_file(tmp_path, "v.mp4")
        req = VideoEditRequest(
            videos=[VideoClip(path=video_path)],
            images=[ImageOverlay(path="/nonexistent/img.png", start_time=0, end_time=5, box=[0, 0, 100, 100])],
        )
        with pytest.raises(VideoEditValidationError) as exc_info:
            validate_request(req)
        assert "images[0]" in exc_info.value.errors[0]

    def test_audio_delay_warning(self, tmp_path):
        video_path = self._make_temp_file(tmp_path, "v.mp4")
        audio_path = self._make_temp_file(tmp_path, "a.mp3")
        req = VideoEditRequest(
            videos=[VideoClip(path=video_path, duration=10)],
            audios=[AudioTrack(path=audio_path, delay=100)],
        )
        result = validate_request(req)
        assert result.ok
        assert any("delay" in w for w in result.warnings)

    def test_multiple_errors_collected(self, tmp_path):
        req = VideoEditRequest(
            videos=[VideoClip(path="/no/v1.mp4"), VideoClip(path="/no/v2.mp4")],
            audios=[AudioTrack(path="/no/a.mp3")],
        )
        with pytest.raises(VideoEditValidationError) as exc_info:
            validate_request(req)
        assert len(exc_info.value.errors) == 3


# ---------------------------------------------------------------------------
# executor.py — to_ffmpeg_params
# ---------------------------------------------------------------------------


class TestToFfmpegParams:
    def test_minimal_conversion(self):
        req = VideoEditRequest(videos=[VideoClip(path="/tmp/v.mp4")])
        params = to_ffmpeg_params(req)
        assert len(params["video_info_list"]) == 1
        assert params["video_info_list"][0]["path"] == "/tmp/v.mp4"
        assert params["video_info_list"][0]["keep_original_audio"] is True
        assert params["audio_info_list"] == []
        assert params["resolution"] == "1920x1080"

    def test_audio_conversion(self):
        req = VideoEditRequest(
            videos=[VideoClip(path="/tmp/v.mp4")],
            audios=[
                AudioTrack(path="/tmp/tts.mp3", delay=5),
                AudioTrack(path="/tmp/bgm.mp3", is_bg_music=True, fade_in_duration=2),
            ],
        )
        params = to_ffmpeg_params(req)
        assert len(params["audio_info_list"]) == 2
        assert params["audio_info_list"][0]["delay"] == 5
        assert params["audio_info_list"][0]["is_bg_music"] is False
        assert params["audio_info_list"][1]["is_bg_music"] is True
        assert params["audio_info_list"][1]["fade_in_duration"] == 2

    def test_image_conversion(self):
        req = VideoEditRequest(
            videos=[VideoClip(path="/tmp/v.mp4")],
            images=[ImageOverlay(path="/tmp/logo.png", start_time=0, end_time=10, box=[100, 200, 50, 50], rotate=45)],
        )
        params = to_ffmpeg_params(req)
        assert len(params["image_info_list"]) == 1
        assert params["image_info_list"][0]["box"] == [100, 200, 50, 50]
        assert params["image_info_list"][0]["rotate"] == 45

    def test_video_filter_conversion(self):
        req = VideoEditRequest(
            videos=[VideoClip(path="/tmp/v.mp4")],
            video_filter=VideoFilter(brightness=0.1, contrast=1.5, saturation=1.2),
        )
        params = to_ffmpeg_params(req)
        assert params["video_filter"]["brightness"] == 0.1
        assert params["video_filter"]["contrast"] == 1.5

    def test_duration_included_when_set(self):
        req = VideoEditRequest(
            videos=[VideoClip(path="/tmp/v.mp4", start_time=30, duration=60)],
        )
        params = to_ffmpeg_params(req)
        assert params["video_info_list"][0]["duration"] == 60
        assert params["video_info_list"][0]["start_time"] == 30

    def test_duration_omitted_when_none(self):
        req = VideoEditRequest(videos=[VideoClip(path="/tmp/v.mp4")])
        params = to_ffmpeg_params(req)
        assert "duration" not in params["video_info_list"][0]


# ---------------------------------------------------------------------------
# executor.py — build_dry_run
# ---------------------------------------------------------------------------


class TestBuildDryRun:
    def test_dry_run_with_valid_files(self, tmp_path):
        video_path = tmp_path / "v.mp4"
        video_path.write_bytes(b"\x00")
        req = VideoEditRequest(videos=[VideoClip(path=str(video_path))])
        result = build_dry_run(req)
        assert "params" in result
        assert "warnings" in result
        assert result["subtitle_mode"] is None

    def test_dry_run_with_subtitles(self, tmp_path):
        video_path = tmp_path / "v.mp4"
        video_path.write_bytes(b"\x00")
        sub_path = tmp_path / "sub.ass"
        sub_path.write_text("subtitle content")
        req = VideoEditRequest(
            videos=[VideoClip(path=str(video_path))],
            subtitles=SubtitleConfig(mode="file", file_path=str(sub_path)),
        )
        result = build_dry_run(req)
        assert result["subtitle_mode"] == "file"

    def test_dry_run_fails_on_missing_file(self):
        req = VideoEditRequest(videos=[VideoClip(path="/nonexistent.mp4")])
        with pytest.raises(VideoEditValidationError):
            build_dry_run(req)


# ---------------------------------------------------------------------------
# Phase 2: Advanced features — schema
# ---------------------------------------------------------------------------


class TestVideoClipAdvanced:
    def test_speed_default(self):
        clip = VideoClip(path="/tmp/v.mp4")
        assert clip.speed == 1.0
        assert clip.reverse is False
        assert clip.crop is None
        assert clip.filter is None

    def test_speed_range_rejected(self):
        with pytest.raises(Exception, match="speed"):
            VideoClip(path="/tmp/v.mp4", speed=0)
        with pytest.raises(Exception, match="speed"):
            VideoClip(path="/tmp/v.mp4", speed=-1)
        with pytest.raises(Exception, match="speed"):
            VideoClip(path="/tmp/v.mp4", speed=101)

    def test_valid_speed(self):
        clip = VideoClip(path="/tmp/v.mp4", speed=0.5)
        assert clip.speed == 0.5
        clip2 = VideoClip(path="/tmp/v.mp4", speed=2.0)
        assert clip2.speed == 2.0

    def test_reverse(self):
        clip = VideoClip(path="/tmp/v.mp4", reverse=True)
        assert clip.reverse is True

    def test_crop_wrong_length(self):
        with pytest.raises(Exception, match="crop"):
            VideoClip(path="/tmp/v.mp4", crop=[100, 100])

    def test_crop_valid(self):
        clip = VideoClip(path="/tmp/v.mp4", crop=[0, 0, 1920, 1080])
        assert clip.crop == [0, 0, 1920, 1080]

    def test_per_clip_filter(self):
        clip = VideoClip(
            path="/tmp/v.mp4",
            filter=VideoFilter(brightness=0.1, contrast=1.5, saturation=1.2),
        )
        assert clip.filter.brightness == 0.1
        assert clip.filter.contrast == 1.5


class TestVideoOverlay:
    def test_defaults(self):
        ov = VideoOverlay(path="/tmp/pip.webm", start_time=0, end_time=10, box=[0, 0, 640, 360])
        assert ov.keep_overlay_audio is False
        assert ov.ss == 0

    def test_ss_negative_rejected(self):
        with pytest.raises(Exception, match="ss"):
            VideoOverlay(path="/tmp/pip.webm", start_time=0, end_time=10, box=[0, 0, 640, 360], ss=-1)

    def test_end_before_start_rejected(self):
        with pytest.raises(Exception, match="end_time"):
            VideoOverlay(path="/tmp/pip.webm", start_time=10, end_time=5, box=[0, 0, 640, 360])

    def test_box_wrong_length(self):
        with pytest.raises(Exception, match="box"):
            VideoOverlay(path="/tmp/pip.webm", start_time=0, end_time=10, box=[0, 0])


class TestTransition:
    def test_defaults(self):
        t = Transition(type="fade")
        assert t.type == "fade"
        assert t.duration == 1.0

    def test_duration_positive(self):
        with pytest.raises(Exception, match="duration"):
            Transition(type="fade", duration=0)
        with pytest.raises(Exception, match="duration"):
            Transition(type="fade", duration=-1)

    def test_all_transition_types(self):
        for ttype in [
            "fade", "fadeblack", "fadewhite", "slideleft", "slideright",
            "slideup", "slidedown", "circlecrop", "circleopen", "circleclose",
            "dissolve", "pixelize", "radial", "smoothleft", "smoothright",
            "smoothup", "smoothdown", "wipeleft", "wiperight", "wipeup", "wipedown",
        ]:
            t = Transition(type=ttype, duration=0.5)
            assert t.type == ttype
            assert t.duration == 0.5

    def test_invalid_type_rejected(self):
        with pytest.raises(Exception):
            Transition(type="invalid_transition")


class TestFillBackground:
    def test_defaults(self):
        fb = FillBackground()
        assert fb.type == "black"
        assert fb.image_path is None

    def test_blur_type(self):
        fb = FillBackground(type="blur")
        assert fb.type == "blur"

    def test_image_type_requires_path(self):
        fb = FillBackground(type="image", image_path="/tmp/bg.png")
        assert fb.type == "image"
        assert fb.image_path == "/tmp/bg.png"


class TestVideoEditRequestAdvanced:
    def test_overlay_videos_default_empty(self):
        req = VideoEditRequest(videos=[VideoClip(path="/tmp/v.mp4")])
        assert req.overlay_videos == []
        assert req.transitions is None
        assert req.fps == 30
        assert req.bitrate is None

    def test_fps_positive(self):
        req = VideoEditRequest(videos=[VideoClip(path="/tmp/v.mp4")], fps=60)
        assert req.fps == 60

    def test_fps_zero_rejected(self):
        with pytest.raises(Exception, match="fps"):
            VideoEditRequest(videos=[VideoClip(path="/tmp/v.mp4")], fps=0)

    def test_transitions_wrong_count_rejected(self):
        # 2 videos = 1 transition is correct, should NOT raise
        req = VideoEditRequest(
            videos=[VideoClip(path="/tmp/v1.mp4"), VideoClip(path="/tmp/v2.mp4")],
            transitions=[Transition(type="fade")],
        )
        assert len(req.transitions) == 1
        # 2 videos = 2 transitions is WRONG
        with pytest.raises(Exception, match="transitions 数量"):
            VideoEditRequest(
                videos=[VideoClip(path="/tmp/v1.mp4"), VideoClip(path="/tmp/v2.mp4")],
                transitions=[Transition(type="fade"), Transition(type="slideleft")],
            )
        # Three videos = 2 transitions
        req2 = VideoEditRequest(
            videos=[
                VideoClip(path="/tmp/v1.mp4"),
                VideoClip(path="/tmp/v2.mp4"),
                VideoClip(path="/tmp/v3.mp4"),
            ],
            transitions=[
                Transition(type="fade"),
                Transition(type="slideleft"),
            ],
        )
        assert len(req2.transitions) == 2

    def test_transitions_count_exactly_n_minus_one(self):
        # 1 video, 0 transitions = valid
        req = VideoEditRequest(videos=[VideoClip(path="/tmp/v.mp4")])
        assert req.transitions is None
        # 1 video, 0 transitions = valid (explicit)
        req2 = VideoEditRequest(
            videos=[VideoClip(path="/tmp/v.mp4")],
            transitions=[],
        )
        assert req2.transitions == []
        # 1 video, 1 transition = INVALID
        with pytest.raises(Exception, match="transitions 数量"):
            VideoEditRequest(
                videos=[VideoClip(path="/tmp/v.mp4")],
                transitions=[Transition(type="fade")],
            )

    def test_full_advanced_request(self):
        req = VideoEditRequest(
            videos=[
                VideoClip(path="/tmp/v1.mp4", speed=0.5, reverse=True),
                VideoClip(path="/tmp/v2.mp4", filter=VideoFilter(saturation=1.3)),
            ],
            overlay_videos=[
                VideoOverlay(path="/tmp/pip.webm", start_time=0, end_time=30, box=[1400, 50, 480, 270]),
            ],
            fill_background=FillBackground(type="blur"),
            fps=60,
            bitrate="8000k",
            transitions=[Transition(type="dissolve", duration=1.5)],
        )
        assert len(req.videos) == 2
        assert req.videos[0].speed == 0.5
        assert req.videos[0].reverse is True
        assert req.transitions[0].type == "dissolve"
        assert req.overlay_videos[0].box == [1400, 50, 480, 270]
        assert req.fill_background.type == "blur"
        assert req.fps == 60
        assert req.bitrate == "8000k"


# ---------------------------------------------------------------------------
# Phase 2: Advanced features — validator
# ---------------------------------------------------------------------------


class TestValidatorAdvanced:
    def _make_temp_file(self, tmp_path, name="test.mp4"):
        p = tmp_path / name
        p.write_bytes(b"\x00")
        return str(p)

    def test_missing_overlay_file_raises(self, tmp_path):
        video_path = self._make_temp_file(tmp_path, "v.mp4")
        req = VideoEditRequest(
            videos=[VideoClip(path=video_path)],
            overlay_videos=[
                VideoOverlay(path="/nonexistent/pip.webm", start_time=0, end_time=10, box=[0, 0, 640, 360]),
            ],
        )
        with pytest.raises(VideoEditValidationError) as exc_info:
            validate_request(req)
        assert "overlay_videos[0]" in exc_info.value.errors[0]

    def test_missing_bg_image_raises(self, tmp_path):
        video_path = self._make_temp_file(tmp_path, "v.mp4")
        req = VideoEditRequest(
            videos=[VideoClip(path=video_path)],
            fill_background=FillBackground(type="image", image_path="/nonexistent/bg.png"),
        )
        with pytest.raises(VideoEditValidationError) as exc_info:
            validate_request(req)
        assert "背景图片不存在" in exc_info.value.errors[0]

    def test_invalid_bitrate_format(self, tmp_path):
        video_path = self._make_temp_file(tmp_path, "v.mp4")
        req = VideoEditRequest(
            videos=[VideoClip(path=video_path)],
            bitrate="invalid",
        )
        with pytest.raises(VideoEditValidationError) as exc_info:
            validate_request(req)
        assert "bitrate 格式无效" in exc_info.value.errors[0]

    def test_valid_bitrate_formats(self, tmp_path):
        video_path = self._make_temp_file(tmp_path, "v.mp4")
        for br in ["5000k", "10M", "8000K", "25M"]:
            req = VideoEditRequest(videos=[VideoClip(path=video_path)], bitrate=br)
            result = validate_request(req)
            assert result.ok, f"bitrate={br} should be valid"

    def test_speed_extreme_warning(self, tmp_path):
        video_path = self._make_temp_file(tmp_path, "v.mp4")
        # very slow
        req = VideoEditRequest(videos=[VideoClip(path=video_path, speed=0.1)])
        result = validate_request(req)
        assert result.ok
        assert any("极慢" in w for w in result.warnings)
        # very fast
        req2 = VideoEditRequest(videos=[VideoClip(path=video_path, speed=5.0)])
        result2 = validate_request(req2)
        assert result2.ok
        assert any("极快" in w for w in result2.warnings)

    def test_overlay_timeline_warning(self, tmp_path):
        video_path = self._make_temp_file(tmp_path, "v.mp4")
        req = VideoEditRequest(
            videos=[VideoClip(path=video_path, duration=10)],
            overlay_videos=[
                VideoOverlay(path=video_path, start_time=0, end_time=100, box=[0, 0, 100, 100]),
            ],
        )
        result = validate_request(req)
        assert result.ok
        assert any("overlay_videos[0].end_time" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Phase 2: Advanced features — executor to_ffmpeg_params
# ---------------------------------------------------------------------------


class TestToFfmpegParamsAdvanced:
    def test_overlay_videos_conversion(self):
        req = VideoEditRequest(
            videos=[VideoClip(path="/tmp/v.mp4")],
            overlay_videos=[
                VideoOverlay(
                    path="/tmp/pip.webm",
                    start_time=0,
                    end_time=30,
                    box=[1400, 50, 480, 270],
                    keep_overlay_audio=True,
                    ss=5,
                ),
            ],
        )
        params = to_ffmpeg_params(req)
        assert len(params["overlay_video_list"]) == 1
        assert params["overlay_video_list"][0]["path"] == "/tmp/pip.webm"
        assert params["overlay_video_list"][0]["box"] == [1400, 50, 480, 270]
        assert params["overlay_video_list"][0]["keep_original_audio"] is True
        assert params["overlay_video_list"][0]["ss"] == 5

    def test_fill_background_conversion(self):
        req = VideoEditRequest(
            videos=[VideoClip(path="/tmp/v.mp4")],
            fill_background=FillBackground(type="blur"),
        )
        params = to_ffmpeg_params(req)
        assert params["fill_background"]["selected_type"] == "blur"

        req2 = VideoEditRequest(
            videos=[VideoClip(path="/tmp/v.mp4")],
            fill_background=FillBackground(type="image", image_path="/tmp/bg.png"),
        )
        params2 = to_ffmpeg_params(req2)
        assert params2["fill_background"]["selected_type"] == "image"
        assert params2["fill_background"]["image_vid"] == "/tmp/bg.png"

    def test_fps_bitrate_conversion(self):
        req = VideoEditRequest(videos=[VideoClip(path="/tmp/v.mp4")], fps=60, bitrate="5000k")
        params = to_ffmpeg_params(req)
        assert params["fps"] == 60
        assert params["bitrate"] == "5000k"

    def test_transitions_conversion(self):
        req = VideoEditRequest(
            videos=[
                VideoClip(path="/tmp/v1.mp4"),
                VideoClip(path="/tmp/v2.mp4"),
                VideoClip(path="/tmp/v3.mp4"),
            ],
            transitions=[
                Transition(type="fade", duration=1.0),
                Transition(type="slideleft", duration=0.5),
            ],
        )
        params = to_ffmpeg_params(req)
        assert params["transitions"][0]["type"] == "fade"
        assert params["transitions"][0]["duration"] == 1.0
        assert params["transitions"][1]["type"] == "slideleft"
        assert params["transitions"][1]["duration"] == 0.5

    def test_speed_reverse_not_in_params(self):
        """Per-clip speed/reverse are handled by preprocessing, not passed to run_ffmpeg."""
        req = VideoEditRequest(
            videos=[VideoClip(path="/tmp/v.mp4", speed=2.0, reverse=True)],
        )
        params = to_ffmpeg_params(req)
        # speed/reverse don't appear in video_info_list — preprocessing handles them
        assert params["video_info_list"][0]["path"] == "/tmp/v.mp4"
        assert "speed" not in params["video_info_list"][0]
        assert "reverse" not in params["video_info_list"][0]

    def test_empty_overlay_videos(self):
        req = VideoEditRequest(videos=[VideoClip(path="/tmp/v.mp4")])
        params = to_ffmpeg_params(req)
        assert params["overlay_video_list"] == []

    def test_none_fill_background(self):
        req = VideoEditRequest(videos=[VideoClip(path="/tmp/v.mp4")])
        params = to_ffmpeg_params(req)
        assert params["fill_background"] == {}

    def test_none_transitions(self):
        req = VideoEditRequest(videos=[VideoClip(path="/tmp/v.mp4")])
        params = to_ffmpeg_params(req)
        assert params["transitions"] is None


# ---------------------------------------------------------------------------
# Phase 3: Subtitle style + highlight — schema
# ---------------------------------------------------------------------------


class TestSubtitleStyle:
    def test_all_defaults(self):
        style = SubtitleStyle()
        assert style.font is None
        assert style.font_size is None
        assert style.font_color is None
        assert style.bold is False
        assert style.italic is False
        assert style.stroke_width is None
        assert style.stroke_color is None
        assert style.shadow_color is None
        assert style.bg_color is None
        assert style.alignment is None
        assert style.pos_x is None
        assert style.pos_y is None
        assert style.rotate == 0

    def test_full_style(self):
        style = SubtitleStyle(
            font="思源黑体",
            font_size=28,
            font_color="#FFFF00",
            bold=True,
            italic=True,
            stroke_width=2,
            stroke_color="#000000",
            shadow_color="#333333",
            bg_color="#0000FF",
            alignment=5,
            pos_x=100,
            pos_y=200,
            rotate=15,
        )
        assert style.font == "思源黑体"
        assert style.font_size == 28
        assert style.font_color == "#FFFF00"
        assert style.bold is True
        assert style.stroke_width == 2
        assert style.alignment == 5
        assert style.pos_x == 100
        assert style.rotate == 15

    def test_alignment_range(self):
        # valid
        for a in [1, 2, 3, 4, 5, 6, 7, 8, 9]:
            SubtitleStyle(alignment=a)
        # invalid
        with pytest.raises(Exception, match="alignment"):
            SubtitleStyle(alignment=0)
        with pytest.raises(Exception, match="alignment"):
            SubtitleStyle(alignment=10)


class TestSubtitleConfigExtended:
    def test_whisper_with_style(self):
        cfg = SubtitleConfig(
            mode="whisper",
            language="zh",
            style=SubtitleStyle(font="微软雅黑", font_size=24, font_color="#FFFFFF"),
        )
        assert cfg.style.font == "微软雅黑"
        assert cfg.style.font_size == 24

    def test_whisper_with_highlight(self):
        cfg = SubtitleConfig(
            mode="whisper",
            highlight_keywords=["重点", "注意"],
            highlight_style=SubtitleStyle(font_color="#FF4500", bold=True, stroke_width=2),
        )
        assert cfg.highlight_keywords == ["重点", "注意"]
        assert cfg.highlight_style.font_color == "#FF4500"
        assert cfg.highlight_style.bold is True
        assert cfg.highlight_style.stroke_width == 2

    def test_whisper_style_defaults_none(self):
        cfg = SubtitleConfig(mode="whisper")
        assert cfg.style is None
        assert cfg.highlight_keywords is None
        assert cfg.highlight_style is None

    def test_file_mode_ignores_style(self):
        """style only affects whisper mode; file mode should still accept it silently."""
        cfg = SubtitleConfig(
            mode="file",
            file_path="/tmp/sub.ass",
            style=SubtitleStyle(font="Arial"),
        )
        assert cfg.style.font == "Arial"
        # Style is stored but only used in whisper path


# ---------------------------------------------------------------------------
# Phase 3: gen_ass with style — integration test
# ---------------------------------------------------------------------------


class TestGenAssWithStyle:
    def test_styled_subtitle_output(self):
        from openharness.video_editor.subtitle_gen import gen_ass
        subtitle_list = [
            {
                "start": 0,
                "end": 5,
                "text": "测试字幕",
                "font": "思源黑体",
                "font_size": 28,
                "font_color": "#FFFF00",
                "bold": True,
                "stroke_width": 2,
                "stroke_color": "#000000",
            },
        ]
        ass = gen_ass(subtitle_list, video_width=1920, video_height=1080)
        assert "\\fn思源黑体" in ass
        assert "\\fs28" in ass
        assert "\\b1" in ass
        assert "\\bord2" in ass

    def test_keyword_highlight_output(self):
        from openharness.video_editor.subtitle_gen import gen_ass
        subtitle_list = [
            {
                "start": 0,
                "end": 5,
                "text": "这是一个重点内容",
                "highlights": [{
                    "keywords": ["重点"],
                    "style": {"font_color": "FF0000", "bold": True},
                }],
            },
        ]
        ass = gen_ass(subtitle_list)
        assert "重点" in ass
        # ASS uses BGR: FF0000 (red) → &H0000FF& in ASS format
        assert "0000ff" in ass.lower()

    def test_multiple_keywords_highlight(self):
        from openharness.video_editor.subtitle_gen import gen_ass
        subtitle_list = [
            {
                "start": 0,
                "end": 5,
                "text": "请注意重点内容",
                "highlights": [{
                    "keywords": ["注意", "重点"],
                    "style": {"font_color": "FF4500", "bold": True},
                }],
            },
        ]
        ass = gen_ass(subtitle_list)
        assert "注意" in ass
        assert "重点" in ass

    def test_no_match_falls_back_to_normal(self):
        from openharness.video_editor.subtitle_gen import gen_ass
        subtitle_list = [
            {
                "start": 0,
                "end": 5,
                "text": "普通文本",
                "highlights": [{
                    "keywords": ["不存在"],
                    "style": {"font_color": "FF0000"},
                }],
            },
        ]
        ass = gen_ass(subtitle_list)
        assert "普通文本" in ass

    def test_keyword_highlight_with_stroke_and_shadow(self):
        from openharness.video_editor.subtitle_gen import gen_ass
        subtitle_list = [
            {
                "start": 0,
                "end": 5,
                "text": "这是重点内容",
                "highlights": [{
                    "keywords": ["重点"],
                    "style": {
                        "font_color": "FF0000",
                        "bold": True,
                        "stroke_width": 3,
                        "stroke_color": "000000",
                        "shadow_color": "333333",
                    },
                }],
            },
        ]
        ass = gen_ass(subtitle_list)
        assert "重点" in ass
        # ASS uses BGR: FF0000 (red RGB) → &H0000FF& in ASS format
        assert "0000ff" in ass.lower()
        assert "\\bord3" in ass

    def test_keyword_highlight_with_bg_color(self):
        from openharness.video_editor.subtitle_gen import gen_ass
        subtitle_list = [
            {
                "start": 0,
                "end": 5,
                "text": "注意安全",
                "highlights": [{
                    "keywords": ["注意"],
                    "style": {
                        "font_color": "FFFFFF",
                        "bold": True,
                        "bg_color": "FF0000",
                    },
                }],
            },
        ]
        ass = gen_ass(subtitle_list)
        assert "注意" in ass
        assert "\\bord1" in ass

    def test_position_subtitle_output(self):
        from openharness.video_editor.subtitle_gen import gen_ass
        subtitle_list = [
            {
                "start": 0,
                "end": 5,
                "text": "定位字幕",
                "pos": "100,200",
            },
        ]
        ass = gen_ass(subtitle_list)
        assert "\\pos(100,200)" in ass
