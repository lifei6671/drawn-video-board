import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cs_board_video import workflow as w
from cs_board_video.cli import main, asset_import
from cs_board_video.project import Project, WorkflowError
from helpers import fixture, prepare_images, prepare_audio, prepare_plans, approve


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_gates_and_resume_do_not_approve(self):
        p = fixture(self.temp.name)
        before = dict(p.approvals)
        self.assertEqual(w.resume(p)["state"], "storyboard_review")
        self.assertEqual(p.approvals, before)
        with self.assertRaises(WorkflowError):
            w.render(p, False)
        approve(p, "storyboard")
        self.assertEqual(w.status(p)["state"], "style_review")

    def test_partial_storyboard_change_preserves_other_approval(self):
        p = fixture(self.temp.name, count=3)
        approve(p, "storyboard")
        scenes = p.scenes()
        unchanged = p.approvals["storyboard:scene-001"]
        scenes[2]["composition"] = "特写"
        p.save("narration/storyboard.json", {"scenes": scenes})
        self.assertTrue(p.approved("storyboard:scene-001", w.board_target(p, scenes[0])))
        self.assertFalse(p.approved("storyboard:scene-003", w.board_target(p, scenes[2])))
        self.assertEqual(p.approvals["storyboard:scene-001"], unchanged)

    def test_wrong_digest_and_empty_authorization_rejected(self):
        p = fixture(self.temp.name)
        for token, message in (("wrong", "确认"), (w.approval_target(p, "storyboard"), " ")):
            with self.assertRaises(WorkflowError):
                w.approve(p, "storyboard", token, message)
        self.assertFalse(p.approvals)
        with self.assertRaises(WorkflowError):
            w.approval_target(p, "preview", "scene-001")

    def test_script_coverage_rejects_reordered_text(self):
        p = fixture(self.temp.name, count=2)
        scenes = p.scenes()[::-1]
        for i, scene in enumerate(scenes, 1):
            scene["scene_id"] = f"scene-{i:03}"
        p.save("narration/storyboard.json", {"scenes": scenes})
        with self.assertRaises(WorkflowError):
            w.validate_storyboard(p)

    def test_path_escape_and_external_symlink(self):
        p = fixture(self.temp.name)
        for path in ("../escape.txt", str(Path(self.temp.name).resolve() / "escape")):
            with self.assertRaises(WorkflowError):
                p.path(path)
        link = p.root / "escape"
        try:
            link.symlink_to(Path(self.temp.name), target_is_directory=True)
        except OSError:
            if sys.platform != "win32":
                raise
            escaped_link = str(link).replace("'", "''")
            escaped_target = self.temp.name.replace("'", "''")
            subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                            f"New-Item -ItemType Junction -Path '{escaped_link}' -Target '{escaped_target}' | Out-Null"],
                           check=True, capture_output=True)
        try:
            with self.assertRaises(WorkflowError):
                p.path("escape/new.txt")
        finally:
            link.rmdir()

    def test_os_lock_released_and_blocks_other_process(self):
        p = fixture(self.temp.name)
        code = "from cs_board_video.project import Project; import sys; p=Project(sys.argv[1]);\nwith p.lock(): print('acquired')"
        with p.lock():
            result = subprocess.run([sys.executable, "-c", code, str(p.root)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
        with p.lock():
            pass

    def test_user_audio_skips_approval_generated_audio_cannot(self):
        p = prepare_audio(prepare_images(fixture(self.temp.name)))
        w.audio_ready(p)
        self.assertNotIn("audio", p.approvals)
        w.import_audio(p, p.path("audio/voice.wav"), "测试生成音频", generated=True)
        with self.assertRaises(WorkflowError):
            w.timeline_build(p)
        approve(p, "audio")
        w.timeline_build(p)

    def test_visual_check_is_required(self):
        p = prepare_images(fixture(self.temp.name))
        metadata = p.load("scenes/scene-001/image-metadata.json")
        metadata["checks"]["drawable"] = "FAIL"
        p.save("scenes/scene-001/image-metadata.json", metadata)
        with self.assertRaises(WorkflowError):
            w.images_ready(p)

    def test_annotation_rejects_overlap_and_stale_image(self):
        p = prepare_plans(prepare_audio(prepare_images(fixture(self.temp.name))))
        annotation = p.load("scenes/scene-001/annotation.json")
        annotation["elements"][1]["reveal"]["startMs"] = 0
        with self.assertRaises(WorkflowError):
            w.annotation_validate(p, "scene-001", annotation)
        plan = p.load("scenes/scene-001/drawing-plan.json")
        plan["image_sha256"] = "wrong"
        p.save("scenes/scene-001/drawing-plan.json", plan)
        with self.assertRaises(WorkflowError):
            w.annotation_build(p)

    def test_cli_input_errors_have_protocol_exit(self):
        self.assertEqual(main(["status", "--project", str(Path(self.temp.name) / "outside")]), 2)

    def test_asset_normalized_protected_paths_cannot_be_overwritten(self):
        p = fixture(self.temp.name)
        source = Path(self.temp.name) / "replacement.txt"
        source.write_text("替换数据", encoding="utf-8")
        before = p.hash("narration/original.txt")
        for dest in ("./narration/original.txt", "./approvals.json", "PROJECT.JSON", "render/command.lock"):
            if dest == "PROJECT.JSON" and sys.platform != "win32":
                continue
            with self.assertRaises(WorkflowError):
                asset_import(p, source, dest, True)
        self.assertEqual(before, p.hash("narration/original.txt"))

    def test_dimension_change_invalidates_only_technical_image_check(self):
        p = prepare_images(fixture(self.temp.name))
        metadata = p.hash("scenes/scene-001/image-metadata.json")
        p.data["config"].update(width=360, height=360)
        with self.assertRaises(WorkflowError):
            w.images_ready(p)
        self.assertEqual(metadata, p.hash("scenes/scene-001/image-metadata.json"))

    def test_annotation_build_preserves_valid_direct_edits(self):
        p = prepare_plans(prepare_audio(prepare_images(fixture(self.temp.name))))
        annotation = p.load("scenes/scene-001/annotation.json")
        annotation["elements"][0]["reveal"]["durationMs"] -= 100
        p.save("scenes/scene-001/annotation.json", annotation)
        before = p.hash("scenes/scene-001/annotation.json")
        self.assertEqual(w.annotation_build(p)["built"], [])
        self.assertEqual(before, p.hash("scenes/scene-001/annotation.json"))

    def test_failed_state_and_resume_checkpoint(self):
        p = fixture(self.temp.name)
        p.data["last_error"] = {"code": 5, "message": "模拟中断"}
        self.assertEqual(w.status(p)["state"], "failed")
        self.assertEqual(w.resume(p)["state"], "storyboard_review")
        self.assertFalse(p.approvals)


class RenderingIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_six_scene_preview_gate_incremental_resume_and_final_mp4(self):
        p = prepare_plans(prepare_audio(prepare_images(fixture(self.temp.name, count=6))))
        first = w.render(p, True, size=[320, 180])
        self.assertEqual(len(first["rendered"]), 6)
        w.compose(p, True)
        with self.assertRaises(WorkflowError):
            w.render(p, False)
        approve(p, "preview")
        w.render(p, False)
        w.compose(p, False)
        self.assertTrue(w.validate_final(p)["passed"])
        self.assertEqual(w.status(p)["state"], "completed")
        hashes = [p.hash(f"scenes/scene-{i:03}/final.mp4") for i in range(1, 7)]
        approvals = json.dumps(p.approvals, sort_keys=True)
        self.assertEqual(w.resume(p)["state"], "completed")
        self.assertEqual(json.dumps(p.approvals, sort_keys=True), approvals)
        annotation = p.load("scenes/scene-003/annotation.json")
        annotation["elements"][0]["reveal"]["durationMs"] -= 100
        annotation["elements"][1]["reveal"]["startMs"] -= 100
        p.save("scenes/scene-003/annotation.json", annotation)
        with self.assertRaises(WorkflowError):
            w.render(p, False)
        second = w.render(p, True, size=[320, 180])
        self.assertEqual(second["rendered"], ["scene-003"])
        w.compose(p, True)
        approve(p, "preview")
        third = w.render(p, False)
        self.assertEqual(third["rendered"], ["scene-003"])
        self.assertEqual(hashes[0], p.hash("scenes/scene-001/final.mp4"))

    def test_agent_asset_protocol_and_full_resolution_path_cache(self):
        p = prepare_plans(prepare_audio(prepare_images(fixture(self.temp.name, mode="agent", width=640, height=360), mode="agent")))
        w.render(p, True, size=[320, 180])
        cache = p.load("render/cache/scene-001-paths.json")
        self.assertEqual(cache["canonical_size"], [640, 360])
        before = p.hash("render/cache/scene-001-paths.json")
        w.compose(p, True)
        approve(p, "preview")
        w.render(p, False)
        self.assertEqual(before, p.hash("render/cache/scene-001-paths.json"))

    def test_path_cache_tampering_blocks_old_preview_approval(self):
        p = prepare_plans(prepare_audio(prepare_images(fixture(self.temp.name))))
        w.render(p, True, size=[320, 180])
        w.compose(p, True)
        approve(p, "preview")
        cached = p.load("render/cache/scene-001-paths.json")
        cached["paths"] = [[], []]
        p.save("render/cache/scene-001-paths.json", cached)
        with self.assertRaises(WorkflowError):
            w.render(p, False)
        w.render(p, True, size=[320, 180])
        self.assertNotEqual(p.load("render/cache/scene-001-paths.json")["paths"], [[], []])

    def test_fully_occluded_region_still_emits_full_duration(self):
        p = prepare_plans(prepare_audio(prepare_images(fixture(self.temp.name)), seconds=8))
        annotation = p.load("scenes/scene-001/annotation.json")
        for element in annotation["elements"]:
            element["region"] = {"x": 0, "y": 0, "width": 320, "height": 180}
        p.save("scenes/scene-001/annotation.json", annotation)
        self.assertEqual(w.render(p, True, size=[320, 180])["rendered"], ["scene-001"])

    def test_interrupted_render_recovers_persisted_scene_receipts(self):
        p = prepare_plans(prepare_audio(prepare_images(fixture(self.temp.name, count=3))))
        original = w.media.render_scene
        calls = []
        def interrupted(*args, **kwargs):
            calls.append(args[1])
            if len(calls) == 2:
                raise WorkflowError("模拟第二镜渲染中断", 5)
            return original(*args, **kwargs)
        with patch.object(w.media, "render_scene", side_effect=interrupted):
            with self.assertRaises(WorkflowError):
                w.render(p, True, size=[320, 180])
        recovered = Project(p.root)
        result = w.render(recovered, True, size=[320, 180])
        self.assertEqual(result["cached"], ["scene-001"])
        self.assertEqual(result["rendered"], ["scene-002", "scene-003"])

    def test_image_replacement_only_rebuilds_affected_scene(self):
        p = prepare_plans(prepare_audio(prepare_images(fixture(self.temp.name, count=2))))
        w.render(p, True, size=[320, 180])
        import cv2
        import numpy as np
        image = w.media._imread_any(p.path("scenes/scene-002/image.png"))
        cv2.circle(image, (220, 90), 10, (10, 50, 200), 2)
        cv2.imencode(".png", image)[1].tofile(str(p.path("scenes/scene-002/image.png")))
        with self.assertRaises(WorkflowError):
            w.images_ready(p)
        w.review_image(p, "scene-002", w.image_target(p, "scene-002"), "新增测试圆形，重新看图验收")
        w.validate_images(p)
        plan = p.load("scenes/scene-002/drawing-plan.json")
        plan["image_sha256"] = p.hash("scenes/scene-002/image.png")
        p.save("scenes/scene-002/drawing-plan.json", plan)
        self.assertEqual(w.annotation_build(p)["built"], ["scene-002"])
        self.assertEqual(w.render(p, True, size=[320, 180])["rendered"], ["scene-002"])

    def test_crf_and_subtitles_do_not_invalidate_drawing_preview(self):
        p = prepare_plans(prepare_audio(prepare_images(fixture(self.temp.name))))
        w.render(p, True, size=[320, 180]); w.compose(p, True); approve(p, "preview")
        target = w.preview_target(p)
        w.render(p, False)
        p.data["config"]["crf"] += 1
        p.data["config"]["subtitles"] = False
        w.preview_ready(p)
        self.assertEqual(target, w.preview_target(p))
        w.render(p, False)
        w.compose(p, False)
        self.assertTrue(w.validate_final(p)["passed"])

    def test_mixed_preview_resolutions_cannot_pass_composition(self):
        p = prepare_plans(prepare_audio(prepare_images(fixture(self.temp.name, count=2, width=640, height=360))))
        w.render(p, True, "scene-001", [320, 180])
        w.render(p, True, "scene-002", [640, 360])
        with self.assertRaisesRegex(WorkflowError, "分辨率不一致"):
            w.compose(p, True)
        self.assertFalse(p.path("previews/full-preview.mp4").exists())
        w.render(p, True, "scene-002", [320, 180])
        self.assertTrue(w.compose(p, True)["passed"])
