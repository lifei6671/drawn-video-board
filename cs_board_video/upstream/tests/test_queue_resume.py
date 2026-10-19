import asyncio
import base64
import io
import importlib.util
import json
import queue
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from PIL import Image
from starlette.requests import Request


RELEASE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE_ROOT))
SPEC = importlib.util.spec_from_file_location("whiteboard_release_server", RELEASE_ROOT / "webapp" / "server.py")
assert SPEC and SPEC.loader
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)


class QueueResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        SERVER.JOBS_DIR = Path(self.temporary.name)
        self.original_styles_dir = SERVER.STYLES_DIR
        self.original_styles_path = SERVER.STYLES_PATH
        SERVER.STYLES_DIR = Path(self.temporary.name) / "styles"
        SERVER.STYLES_PATH = Path(self.temporary.name) / "styles.json"
        SERVER.JOBS = {}
        SERVER.VOICE_QUEUE = queue.Queue()
        SERVER.MODEL_QUEUE = queue.Queue()
        SERVER.ensure_pipeline_workers = lambda: None

    def tearDown(self) -> None:
        SERVER.STYLES_DIR = self.original_styles_dir
        SERVER.STYLES_PATH = self.original_styles_path
        self.temporary.cleanup()

    def job(self, job_id: str) -> dict:
        return {
            "id": job_id,
            "status": "queued",
            "stage": "等待语音克隆",
            "progress": 1,
            "created_at": 1.0,
            "started_at": 1.0,
            "queue_order": 1,
            "queue_stage": "voice",
            "job_type": "generate",
            "copy": "这是一段用于验证任务断点恢复的测试文案。",
            "style": SERVER.DEFAULT_STYLE,
            "scenes_per_image": 1,
            "pen_text": "",
            "include_key_text": True,
            "include_subtitles": True,
            "stroke_detail": "detailed",
            "timings": {},
        }

    def test_task_name_defaults_to_first_fifteen_script_characters(self) -> None:
        name = SERVER.normalized_task_name("", "  一二三四五六七八九十\n十一十二十三十四十五十六  ", "job-test")
        self.assertEqual(name, "一二三四五六七八九十十一十二十")

    def test_explicit_task_name_is_preserved(self) -> None:
        self.assertEqual(SERVER.normalized_task_name("  我的任务  ", "备用文案", "job-test"), "我的任务")

    def test_normalize_standard_scene_count_merges_small_over_split(self) -> None:
        candidate = [
            {"title": f"场景 {index}", "concept": f"概念 {index}", "elements": [f"元素 {index}"]}
            for index in range(69)
        ]

        normalized = SERVER.normalize_standard_scene_count(candidate, 67)

        self.assertEqual(len(normalized), 67)
        self.assertIn("场景", normalized[0]["title"])
        self.assertIn("元素", normalized[-1]["elements"][0])

    def test_normalize_standard_scene_count_rejects_large_over_split(self) -> None:
        candidate = [{"title": f"场景 {index}"} for index in range(80)]

        with self.assertRaisesRegex(RuntimeError, "返回 80 幕，预期 67 幕"):
            SERVER.normalize_standard_scene_count(candidate, 67)

    def test_aspect_ratio_specs_are_normalized_and_prompted(self) -> None:
        self.assertEqual(SERVER.normalize_aspect_ratio("9:16"), "9:16")
        self.assertEqual(SERVER.normalize_aspect_ratio("4:3"), "16:9")
        prompt = SERVER.build_board_prompt(
            [{"title": "竖屏", "concept": "测试", "elements": ["主体"], "text": "测试文案。"}],
            SERVER.DEFAULT_STYLE,
            aspect_ratio="9:16",
        )
        self.assertIn("9:16", prompt)

    def test_fit_image_to_aspect_uses_exact_canvas_dimensions(self) -> None:
        image_path = Path(self.temporary.name) / "source.png"
        Image.new("RGB", (1536, 1024), (255, 255, 255)).save(image_path)

        SERVER.fit_image_to_aspect(image_path, "9:16")

        with Image.open(image_path) as image:
            self.assertEqual(image.size, (864, 1536))

    def test_remotion_props_use_selected_canvas_dimensions(self) -> None:
        scenes = [{
            "start_frame": 0,
            "end_frame": 30,
            "timed_cues": [{
                "id": "cue-1", "anchor_text": "测试", "start_frame": 0, "end_frame": 30,
                "spoken_start_ms": 0, "spoken_end_ms": 1000, "enter_ids": ["node-1"],
                "focus_id": "node-1", "alignment_coverage": 1.0, "alignment_confidence": 1.0,
            }],
        }]

        props = SERVER.remotion_infographic_props(scenes, SERVER.INFOGRAPHIC_STYLE, 1000, aspect_ratio="1:1")

        self.assertEqual((props["width"], props["height"]), (1024, 1024))

    def test_custom_reference_prompt_replaces_default_character(self) -> None:
        prompt = SERVER.build_board_prompt(
            [{"title": "相遇", "concept": "小昌和小林交谈", "elements": ["小昌挥手", "小林回应"], "text": "两个人见面了。"}],
            "自定义参考",
            "输入图1是风格参考。输入图2定义人物“小昌”，输入图3定义人物“小林”。",
            True,
        )
        self.assertIn("人物“小昌”", prompt)
        self.assertIn("人物“小林”", prompt)
        self.assertNotIn("同一主角固定为：中国青年男性", prompt)

    def test_paper_metaphor_routes_process_copy_to_machine_reference(self) -> None:
        paths, instruction = SERVER.paper_metaphor_reference_context([
            {"title": "自动化流程", "concept": "把生产系统变成稳定流程", "text": "系统自动完成每个步骤。"}
        ])
        self.assertEqual(paths[0].name, "03-process-machine.png")
        self.assertIn("流程", instruction)
        self.assertIn("禁止照搬", instruction)

    def test_paper_metaphor_prompt_keeps_story_character(self) -> None:
        prompt = SERVER.build_board_prompt(
            [{"title": "小猴改正", "concept": "小猴向大家道歉", "elements": ["小猴低头道歉"], "text": "小猴认识到了错误。"}],
            SERVER.PAPER_METAPHOR_STYLE,
            "输入图仅作为纸艺风格参考。",
        )
        self.assertIn("动物、人物身份与年龄不得被替换", prompt)
        self.assertNotIn("同一主角固定为：中国青年男性", prompt)

    def test_unknown_style_never_silently_falls_back(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "后台未加载画面风格"):
            SERVER.style_recipe("不存在的风格")

    def test_custom_style_recipe_is_persisted_and_supports_renamed_alias(self) -> None:
        SERVER.save_custom_styles([{
            "id": "custom-style-1",
            "name": "我的胶片风",
            "aliases": ["旧胶片风"],
            "description": "暖色颗粒",
            "recipe": "暖色胶片颗粒，深色墨线，低饱和配色。",
            "image_filename": "",
            "deleted": False,
            "created_at": 1.0,
            "updated_at": 1.0,
        }])

        self.assertIn("暖色胶片颗粒", SERVER.style_recipe("我的胶片风"))
        self.assertIn("暖色胶片颗粒", SERVER.style_recipe("旧胶片风"))

    def test_builtin_style_can_be_edited_and_keeps_old_name_alias(self) -> None:
        original_name = "极简粗线简笔白板风"
        style_id = SERVER.BUILTIN_STYLE_BY_ID["builtin-minimal-whiteboard"]["id"]
        self.assertIn("暖白色纯净背景", SERVER.style_recipe(original_name))

        updated = SERVER.update_style(style_id, {
            "name": "我的白板风",
            "description": "自定义简介",
            "recipe": "深蓝纸张背景，细黑线条，低饱和橙色点缀，保留充足留白。",
        })

        self.assertTrue(updated["builtin"])
        self.assertEqual(updated["name"], "我的白板风")
        self.assertIn("深蓝纸张背景", SERVER.style_recipe("我的白板风"))
        self.assertIn("深蓝纸张背景", SERVER.style_recipe(original_name))
        self.assertEqual(
            next(item for item in SERVER.list_styles()["items"] if item["id"] == style_id)["name"],
            "我的白板风",
        )

        with self.assertRaisesRegex(SERVER.HTTPException, "不可删除"):
            SERVER.delete_style(style_id)

    def test_snapshot_keeps_reference_summary_private(self) -> None:
        job_id = "reference-snapshot"
        metadata = self.job(job_id)
        metadata.update(reference_mode="custom", character_count=2, visual_references={"style_image": "secret-name.png"})
        SERVER.JOBS[job_id] = metadata
        snapshot = SERVER.job_snapshot(job_id)
        self.assertEqual(snapshot["reference_mode"], "custom")
        self.assertEqual(snapshot["character_count"], 2)
        self.assertNotIn("visual_references", snapshot)

    def test_failed_snapshot_can_be_retried(self) -> None:
        job_id = "failed-snapshot"
        metadata = self.job(job_id)
        metadata.update(status="error", error="temporary model failure")
        SERVER.JOBS[job_id] = metadata
        self.assertTrue(SERVER.job_snapshot(job_id)["can_retry"])

    def test_manual_retry_requeues_same_job(self) -> None:
        job_id = "manual-retry"
        job_dir = SERVER.JOBS_DIR / job_id
        job_dir.mkdir(parents=True)
        metadata = self.job(job_id)
        metadata.update(status="error", error="model failed", finished_at=2.0)
        SERVER.JOBS[job_id] = metadata
        captured = []
        original = SERVER.enqueue_job_from_checkpoint
        SERVER.enqueue_job_from_checkpoint = lambda current_id, item: captured.append((current_id, item["status"]))
        try:
            request = Request({"type": "http", "client": ("198.51.100.8", 1234), "headers": []})
            snapshot = SERVER.retry_failed_job(job_id, request)
        finally:
            SERVER.enqueue_job_from_checkpoint = original
        self.assertEqual(captured, [(job_id, "queued")])
        self.assertEqual(snapshot["status"], "queued")
        self.assertEqual(snapshot["manual_retry_count"], 1)
        self.assertIsNone(snapshot.get("error"))

    def test_provider_retries_transient_502(self) -> None:
        failed = mock.Mock(is_error=True, status_code=502, text="gateway")
        succeeded = mock.Mock(is_error=False, status_code=200)
        succeeded.json.return_value = {"output_text": "ok"}
        client = mock.MagicMock()
        client.__enter__.return_value.post.side_effect = [failed, failed, succeeded]
        with mock.patch.object(SERVER.httpx, "Client", return_value=client), mock.patch.object(SERVER.time, "sleep"):
            payload = SERVER.provider_post({"api_key": "test", "base_url": "https://example.test"}, "responses", {"model": "test"})
        self.assertEqual(payload["output_text"], "ok")
        self.assertEqual(client.__enter__.return_value.post.call_count, 3)

    def test_scene_durations_fit_voice_track_exactly(self) -> None:
        scenes = [
            {"text": "短句", "duration_ms": 2000},
            {"text": "这是一段明显更长的中间文案", "duration_ms": 12000},
            {"text": "结尾", "duration_ms": 2000},
        ]
        changed = SERVER.fit_scene_durations(scenes, 5.123)
        self.assertTrue(changed)
        self.assertEqual(sum(scene["duration_ms"] for scene in scenes), 5123)
        self.assertGreaterEqual(scenes[-1]["duration_ms"], 1000)

    def test_old_scene_clip_with_extra_half_second_is_rejected(self) -> None:
        with mock.patch.object(SERVER, "valid_media_file", return_value=True), mock.patch.object(SERVER, "probe_duration", return_value=2.5):
            self.assertFalse(SERVER.valid_timed_video(Path("old.mp4"), 2000))
        with mock.patch.object(SERVER, "valid_media_file", return_value=True), mock.patch.object(SERVER, "probe_duration", return_value=2.04):
            self.assertTrue(SERVER.valid_timed_video(Path("current.mp4"), 2000))

    def test_restore_converts_running_job_back_to_queue(self) -> None:
        job_id = "restore-test"
        job_dir = SERVER.JOBS_DIR / job_id
        job_dir.mkdir(parents=True)
        metadata = self.job(job_id)
        metadata.update(status="running", current_phase="images", phase_started_at=1.0)
        (job_dir / "job.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")

        SERVER.restore_jobs()

        self.assertEqual(SERVER.JOBS[job_id]["status"], "queued")
        self.assertEqual(SERVER.JOBS[job_id]["resume_count"], 1)
        self.assertIsNone(SERVER.JOBS[job_id]["current_phase"])
        self.assertEqual(SERVER.JOBS[job_id]["task_name"], "这是一段用于验证任务断点恢复的")

    def test_missing_voice_returns_to_voice_queue(self) -> None:
        job_id = "voice-test"
        job_dir = SERVER.JOBS_DIR / job_id
        job_dir.mkdir(parents=True)
        (job_dir / "reference.wav").write_bytes(b"reference")
        SERVER.JOBS[job_id] = self.job(job_id)

        SERVER.resume_pending_jobs()

        self.assertEqual(SERVER.VOICE_QUEUE.qsize(), 1)
        self.assertEqual(SERVER.MODEL_QUEUE.qsize(), 0)

    def test_valid_voice_skips_to_model_queue(self) -> None:
        job_id = "model-test"
        job_dir = SERVER.JOBS_DIR / job_id
        job_dir.mkdir(parents=True)
        (job_dir / "reference.wav").write_bytes(b"reference")
        with wave.open(str(job_dir / "voice.wav"), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(b"\x00\x00" * 16000)
        SERVER.JOBS[job_id] = self.job(job_id)

        with mock.patch.object(SERVER, "valid_media_file", side_effect=lambda path: Path(path).name == "voice.wav"):
            SERVER.resume_pending_jobs()

        self.assertEqual(SERVER.VOICE_QUEUE.qsize(), 0)
        self.assertEqual(SERVER.MODEL_QUEUE.qsize(), 1)

    def test_macos_output_directory_picker_returns_selected_path(self) -> None:
        result = mock.Mock(returncode=0, stdout="/tmp/video-output\n", stderr="")
        with mock.patch.object(SERVER.sys, "platform", "darwin"), mock.patch.object(SERVER.subprocess, "run", return_value=result) as run:
            selected = SERVER.select_output_directory()

        self.assertEqual(selected, {"cancelled": False, "path": str(Path("/tmp/video-output").resolve())})
        run.assert_called_once()

    def test_macos_output_directory_picker_handles_cancel(self) -> None:
        result = mock.Mock(returncode=1, stdout="", stderr="execution error: User canceled. (-128)")
        with mock.patch.object(SERVER.sys, "platform", "darwin"), mock.patch.object(SERVER.subprocess, "run", return_value=result):
            selected = SERVER.select_output_directory()

        self.assertEqual(selected, {"cancelled": True, "path": ""})


class VoiceLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.original_voices_dir = SERVER.VOICES_DIR
        SERVER.VOICES_DIR = Path(self.temporary.name) / "voices"
        self.media_patch = mock.patch.object(SERVER, "valid_media_file", return_value=True)
        self.media_patch.start()

    def tearDown(self) -> None:
        self.media_patch.stop()
        SERVER.VOICES_DIR = self.original_voices_dir
        self.temporary.cleanup()

    def test_voice_library_crud(self) -> None:
        upload = SERVER.UploadFile(file=io.BytesIO(b"test audio"), filename="sample.wav")
        created = asyncio.run(SERVER.create_voice("  我的   音色  ", upload))

        self.assertEqual(created["name"], "我的 音色")
        self.assertEqual(SERVER.list_voices()["items"][0]["id"], created["id"])
        metadata, audio_path = SERVER.voice_record(created["id"])
        self.assertEqual(metadata["filename"], "reference.wav")
        self.assertEqual(audio_path.read_bytes(), b"test audio")

        renamed = SERVER.rename_voice(created["id"], {"name": "旁白音色"})
        self.assertEqual(renamed["name"], "旁白音色")
        self.assertEqual(Path(SERVER.get_voice_audio(created["id"]).path).name, "reference.wav")

        self.assertEqual(SERVER.delete_voice(created["id"])["deleted"], True)
        self.assertEqual(SERVER.list_voices()["items"], [])
        with self.assertRaises(SERVER.HTTPException):
            SERVER.voice_record(created["id"])


class TTSPreprocessingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.pronunciation_path = Path(self.temporary.name) / "pronunciation.yaml"
        self.pronunciation_path.write_text(
            "phrases:\n"
            "  - phrase: 银行\n"
            "    char: 行\n"
            "    pinyin: HANG2\n"
            "  - phrase: 行走\n"
            "    char: 行\n"
            "    pinyin: XING2\n",
            encoding="utf-8",
        )
        self.path_patch = mock.patch.object(SERVER, "PRONUNCIATION_PATH", self.pronunciation_path)
        self.path_patch.start()

    def tearDown(self) -> None:
        self.path_patch.stop()
        self.temporary.cleanup()

    def test_preprocesses_only_tts_copy(self) -> None:
        source = "GPT-5 支持 3-5 个版本，-2 行银行，行走，甲-乙。"
        expected = "GPT-5 支持 3到5 个版本，负2 行银<行|HANG2>，<行|XING2>走，甲，乙。"
        self.assertEqual(SERVER.preprocess_tts_text(source), expected)

    def test_synthesis_receives_processed_copy(self) -> None:
        with mock.patch.object(SERVER, "_synthesize_voice_once") as synthesize:
            SERVER.synthesize_voice({}, Path("reference.wav"), "GPT-5 和银行", Path("voice.wav"))

        self.assertEqual(synthesize.call_args.args[2], "GPT-5 和银<行|HANG2>")

    def test_tts_settings_are_forwarded_to_gradio(self) -> None:
        reference = Path(self.temporary.name) / "reference.wav"
        reference.write_bytes(b"reference")
        generated = Path(self.temporary.name) / "generated.wav"
        generated.write_bytes(b"generated")
        client = mock.Mock()
        client.view_api.return_value = {
            "named_endpoints": {
                "/gen_single": {
                    "parameters": [{
                        "type": {"enum": ["Same as the voice reference", "Use emotion reference audio", "Use emotion vectors"]},
                        "parameter_default": "Same as the voice reference",
                    }]
                }
            }
        }
        client.submit.return_value.result.return_value = str(generated)
        config = {
            "tts_url": "http://127.0.0.1:7860",
            "tts_mode": "gradio",
            "tts_emotion_mode": 2,
            "tts_emotion_weight": 0.4,
            "tts_emotion_vectors": [0.1] * 8,
            "tts_emotion_text": "坚定而温暖",
            "tts_emotion_random": True,
            "tts_do_sample": False,
            "tts_top_p": 0.7,
            "tts_top_k": 12,
            "tts_temperature": 0.9,
            "tts_length_penalty": 0.2,
            "tts_num_beams": 4,
            "tts_repetition_penalty": 5,
            "tts_max_mel_tokens": 900,
            "tts_max_text_tokens_per_segment": 80,
        }
        with mock.patch.object(SERVER, "Client", return_value=client), mock.patch.object(SERVER, "handle_file", return_value="reference-file"):
            SERVER._synthesize_voice_once(config, reference, "测试文本", Path(self.temporary.name) / "voice.wav")

        arguments = client.submit.call_args.args
        self.assertEqual(arguments[0], "Use emotion vectors")
        self.assertEqual(arguments[5], 0.4)
        self.assertEqual(list(arguments[6:14]), [0.1] * 8)
        self.assertEqual(arguments[14:16], ("坚定而温暖", True))
        self.assertEqual(arguments[16:26], (80, 1.0, False, 0.7, 12, 0.9, 0.2, 4, 5, 900))


class LibraryPaginationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.original_voices_dir = SERVER.VOICES_DIR
        self.original_styles_dir = SERVER.STYLES_DIR
        self.original_styles_path = SERVER.STYLES_PATH
        SERVER.VOICES_DIR = Path(self.temporary.name) / "voices"
        SERVER.STYLES_DIR = Path(self.temporary.name) / "styles"
        SERVER.STYLES_PATH = Path(self.temporary.name) / "styles.json"
        SERVER.JOBS_DIR = Path(self.temporary.name) / "jobs"
        SERVER.JOBS = {}
        self.media_patch = mock.patch.object(SERVER, "valid_media_file", return_value=True)
        self.media_patch.start()

    def tearDown(self) -> None:
        self.media_patch.stop()
        SERVER.VOICES_DIR = self.original_voices_dir
        SERVER.STYLES_DIR = self.original_styles_dir
        SERVER.STYLES_PATH = self.original_styles_path
        self.temporary.cleanup()

    def test_voice_search_and_pagination_return_metadata(self) -> None:
        for name in ("女声旁白", "男声旁白", "环境音"):
            upload = SERVER.UploadFile(file=io.BytesIO(b"test audio"), filename=f"{name}.wav")
            asyncio.run(SERVER.create_voice(name, upload))

        result = SERVER.list_voices(search="旁白", page=2, page_size=1)

        self.assertEqual(result["total"], 2)
        self.assertEqual(result["pages"], 2)
        self.assertEqual(result["page"], 2)
        self.assertEqual(len(result["items"]), 1)

    def test_style_search_and_detail_include_all_persisted_fields(self) -> None:
        result = SERVER.list_styles(search="白板", page=1, page_size=1)

        self.assertGreater(result["total"], 0)
        item = result["items"][0]
        self.assertIn("image_filename", item)
        self.assertIn("deleted", item)
        self.assertIn("type", item)
        self.assertIn("updated_at", item)

    def test_standalone_image_uses_shared_or_dedicated_provider(self) -> None:
        buffer = io.BytesIO()
        Image.new("RGB", (8, 8), "white").save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        cases = [
            ({}, "https://text.example.test/v1", "shared-test-key"),
            ({"image_base_url": "https://image.example.test/v1"}, "https://image.example.test/v1", "shared-test-key"),
            ({"image_api_key": "image-test-key"}, "https://text.example.test/v1", "image-test-key"),
            ({"api_key": "", "image_base_url": "https://image.example.test/v1", "image_api_key": "image-test-key"}, "https://image.example.test/v1", "image-test-key"),
        ]
        for overrides, expected_url, expected_key in cases:
            with self.subTest(overrides=overrides):
                config = dict(SERVER.DEFAULT_CONFIG, api_key="shared-test-key", base_url="https://text.example.test/v1")
                config.update(overrides)
                with mock.patch.object(SERVER, "load_config", return_value=config), mock.patch.object(
                    SERVER, "STATE_DIR", Path(self.temporary.name)
                ), mock.patch.object(SERVER, "provider_post", return_value={"data": [{"b64_json": encoded}]}) as provider:
                    result = SERVER.generate_standalone_image({
                        "prompt": "A clear educational illustration",
                        "style_name": "白板",
                        "style_recipe": "bold black outlines",
                        "aspect_ratio": "1:1",
                        "quality": "high",
                    })
                provider.assert_called_once()
                resolved, endpoint, payload = provider.call_args.args
                self.assertEqual(resolved["base_url"], expected_url)
                self.assertEqual(resolved["api_key"], expected_key)
                self.assertEqual(endpoint, "images/generations")
                self.assertEqual(payload["quality"], "high")
                self.assertEqual(payload["size"], "1024x1024")
                self.assertIn("bold black outlines", payload["prompt"])
                self.assertEqual(result["image"], f"data:image/png;base64,{encoded}")
                self.assertEqual(result["style_name"], "白板")
                self.assertEqual(config["base_url"], "https://text.example.test/v1")
                self.assertEqual(list(Path(self.temporary.name).glob("image-lab-*")), [])
                self.assertEqual(SERVER.JOBS, {})

    def test_standalone_image_requires_shared_or_image_credentials(self) -> None:
        with mock.patch.object(SERVER, "load_config", return_value=SERVER.DEFAULT_CONFIG.copy()), mock.patch.object(
            SERVER, "provider_post"
        ) as provider:
            with self.assertRaises(SERVER.HTTPException) as caught:
                SERVER.generate_standalone_image({"prompt": "An educational illustration"})
        self.assertEqual(caught.exception.status_code, 400)
        provider.assert_not_called()

    def test_image_provider_settings_coexist_with_output_directory(self) -> None:
        config = dict(
            SERVER.DEFAULT_CONFIG,
            api_key="shared-test-key",
            image_api_key="image-test-key",
            image_base_url="https://image.example.test/v1",
            tts_url_2="http://127.0.0.1:7861",
        )
        config_path = Path(self.temporary.name) / "config.json"
        output_dir = Path(self.temporary.name) / "output"
        with mock.patch.object(SERVER, "STATE_DIR", Path(self.temporary.name)), mock.patch.object(
            SERVER, "CONFIG_PATH", config_path
        ), mock.patch.object(SERVER, "load_config", return_value=config):
            result = SERVER.save_config({
                "image_api_key": SERVER.safe_config(config)["image_api_key"],
                "output_dir": str(output_dir),
            })
            saved = json.loads(config_path.read_text())
            self.assertTrue(output_dir.is_dir())
            self.assertEqual(saved["image_api_key"], "image-test-key")
            self.assertTrue(result["has_image_api_key"])
            self.assertIn("••••", result["image_api_key"])
            self.assertIn("••••", result["api_key"])
            cleared = {key: "" for key in ("image_base_url", "image_api_key", "tts_url_2", "output_dir")}
            result = SERVER.save_config(cleared)
            saved = json.loads(config_path.read_text())
            for key in cleared:
                self.assertEqual(saved[key], "")
            self.assertFalse(result["has_image_api_key"])
            self.assertEqual(saved["api_key"], "shared-test-key")

    def test_history_search_and_pagination_return_metadata(self) -> None:
        for index, task_name in enumerate(("课程开场", "产品介绍", "课程结尾"), 1):
            SERVER.JOBS[f"job-{index:02d}"] = {
                "id": f"job-{index:02d}",
                "status": "done",
                "stage": "已完成",
                "progress": 100,
                "created_at": float(index),
                "started_at": float(index),
                "task_name": task_name,
                "copy": task_name,
                "style": "极简粗线简笔白板风",
                "timings": {},
            }

        result = SERVER.list_jobs(search="课程", page=2, page_size=1)

        self.assertEqual(result["total"], 2)
        self.assertEqual(result["pages"], 2)
        self.assertEqual(result["page"], 2)
        self.assertEqual(result["items"][0]["task_name"], "课程开场")


if __name__ == "__main__":
    unittest.main()
