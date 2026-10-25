"""Migration contracts; approvals/tokens here are engineering fixtures only."""
import ast
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np
from PIL import Image

from cs_board_video import bridge, media, workflow as w
from cs_board_video.adapters.voicestudio import synthesize
from cs_board_video.cli import dispatch, parser
from cs_board_video.project import WorkflowError, file_hash
from helpers import approve, fixture, prepare_audio, prepare_images

REPO = Path(__file__).parents[1]


def invoke(p, *args):
    return dispatch(p, parser().parse_args([*args, "--project", str(p.root)]))


def prepare_deck(p):
    p.data["config"].update(render_engine="remotion", fps=30)
    p.persist()
    prepare_images(p)
    bridge.prompts(p)
    for scene in p.scenes():
        sid = scene["scene_id"]
        w.review_image(p, sid, w.image_target(p, sid), "测试几何图符合原提示词人物/物品，统一画风与边界")
    w.validate_images(p)
    prepare_audio(p)
    text = p.path("narration/original.txt").read_text(encoding="utf-8")
    chars = [c for c in text if c.isalnum()]
    step = 2000 / len(chars)
    p.save("audio/alignment.tokens.json", {"captions": [
        {"text": c, "startMs": i * step, "endMs": (i + 1) * step, "confidence": .95}
        for i, c in enumerate(chars)]})
    from scripts.semantic_timeline import build_phrase_timeline
    phrases = build_phrase_timeline(text, p.load("audio/alignment.tokens.json"), 2000, fps=30)
    ids = [x["id"] for x in phrases["phrases"]]
    candidate = [{"source_phrase_ids": ids, "page_title": "人物递物", "nodes": ["人物", "物品"],
                  "illustration_elements": ["人物", "物品"], "layout_type": "focus"}]
    bridge.plan(p, 2, candidate, deck_only=True)
    return p


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_complete_source_tree_and_all_original_symbols_retained(self):
        manifest = json.loads((REPO / "references/upstream-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["files"]), 133)
        source = Path(os.environ.get("CS_BOARD_SOURCE", "D:/wx_lifeilin/github.com/cs-board"))
        modified = set()
        for item in manifest["files"]:
            migrated = bridge.ROOT / item["path"]
            self.assertTrue(migrated.is_file(), item["path"])
            self.assertEqual(file_hash(migrated), item["migrated_sha256"], item["path"])
            if item["source_sha256"] != item["migrated_sha256"]:
                modified.add(item["path"])
                self.assertTrue(item["adaptation"])
            if source.is_dir():
                original = source / item["path"]
                self.assertEqual(file_hash(original), item["source_sha256"])
                if original.suffix == ".py":
                    def symbols(path):
                        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
                        return {(type(n).__name__, n.name) for n in ast.walk(tree)
                                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
                    self.assertFalse(symbols(original) - symbols(migrated), item["path"])
        self.assertEqual(modified, {"webapp/server.py", "scripts/render_stream_whiteboard.py",
                                  "scripts/merge_scenes.py", "video_renderer/align.mjs", "video_renderer/render.mjs"})
        self.assertFalse((REPO / "cs_board_video/engine/stream_render.py").exists())

    def test_original_presets_references_prompts_and_planning(self):
        styles = bridge.presets()
        self.assertEqual(len(styles), 16)
        self.assertTrue(all(Path(s["image_path"]).is_file() and s["recipe"] for s in styles))
        p = prepare_images(fixture(self.temp.name))
        module = bridge.server()
        bridge.prompts(p)
        with bridge.project_context(p):
            expected = module.build_board_prompt(bridge.native_scenes(p), bridge.style_name(p, module), "", False, False, "16:9")
        self.assertEqual(p.path("scenes/scene-001/prompt.md").read_text(encoding="utf-8"), expected)
        with patch.object(module, "provider_post", side_effect=AssertionError("must not call API")):
            bridge.plan(p, 2)
            bridge.plan(p, 2, [{"title": "递出", "concept": "递物", "elements": ["人物", "物品"]}])
        self.assertEqual(w.validate_storyboard(p)["scene_count"], 1)
        self.assertIn("固定分幕", p.load("narration/plan-request.json")["prompt"])
        self.assertFalse(module.VOICE_WORKER_THREADS or module.MODEL_WORKER_THREADS or module.RENDER_THREADS)

    def test_original_timing_annotation_editor_keytext_and_subtitles(self):
        p = prepare_audio(prepare_images(fixture(self.temp.name, count=2)))
        expected = deepcopy(bridge.native_scenes(p))
        with bridge.project_context(p) as module:
            module.fit_scene_durations(expected, 4)
            module.write_subtitles(expected, p.path("audio/expected.srt"))
        w.timeline_build(p)
        self.assertEqual(p.path("audio/subtitles.srt").read_bytes(), p.path("audio/expected.srt").read_bytes())
        w.annotation_build(p)
        invoke(p, "annotation", "preview")
        self.assertEqual(p.path("previews/editor.html").read_bytes(), (bridge.ROOT / "assets/preview.html").read_bytes())
        self.assertTrue(p.path("scenes/scene-001/annotation-preview.png").is_file())
        # Raw square source: fit then key text must preserve the raw bytes and the target aspect.
        source = p.path("scenes/scene-001/image.png")
        Image.new("RGB", (400, 400), "white").save(source)
        before = file_hash(source)
        invoke(p, "images", "fit", "--scene", "scene-001")
        invoke(p, "images", "key-text", "--scene", "scene-001")
        self.assertEqual(before, p.hash("scenes/scene-001/image.source.png"))
        info = media.image_info(source)
        self.assertAlmostEqual(info["width"] / info["height"], 16 / 9, places=2)
        self.assertGreater(info["contrast_std"], 3)

    def test_upstream_gradio_downloads_are_project_local(self):
        p = prepare_images(fixture(self.temp.name))
        reference = p.path("audio/original/reference.wav")
        reference.write_bytes(b"reference fixture")
        produced = p.path("audio/cache/result.wav")
        produced.parent.mkdir(parents=True)
        produced.write_bytes(b"output fixture")
        p.save("audio/voice-config.json", {"adapter": "upstream", "reference": "audio/original/reference.wav",
                                         "payload": {"tts_mode": "gradio"}})
        module = bridge.server()
        client = Mock()
        client.view_api.return_value = {"named_endpoints": {"/gen_single": {"parameters": [{}]}}}
        client.submit.return_value.result.return_value = str(produced)
        with patch.object(module, "Client", return_value=client) as factory, patch.object(module, "handle_file", return_value=str(reference)):
            output, provenance = synthesize(p)
        self.assertEqual(output.read_bytes(), b"output fixture")
        self.assertEqual(Path(factory.call_args.kwargs["download_files"]), p.path("audio/cache/gradio"))
        self.assertEqual(provenance["adapter"], "upstream.synthesize_voice")

    def test_remotion_uses_original_deck_planning_and_invalidates_props(self):
        p = fixture(self.temp.name)
        p.data["config"].update(render_engine="remotion", fps=30)
        with self.assertRaises(WorkflowError):
            bridge.plan(p, 2)
        bridge.plan(p, 2, narrative_only=True)
        prepare_deck(p)
        prompt = p.path("scenes/scene-001/prompt.md").read_text(encoding="utf-8")
        self.assertIn("画面只画以下具象内容：人物、物品", prompt)
        bridge.prompts(p)
        self.assertEqual(p.load("scenes/scene-001/prompt-context.json")["panels"][0]["page_title"], "人物递物")
        w.review_image(p, "scene-001", w.image_target(p, "scene-001"), "原PPT页插图仍为人物/物品，实际夹具对应")
        w.validate_images(p)
        bridge.plan(p, 2, deck_only=True)
        self.assertTrue(p.load("render/deck-request.json")["prompt"])
        w.timeline_build(p)
        w.annotation_build(p)
        props = p.load("render/remotion-props.json")
        self.assertEqual(props["pages"][0]["pageTitle"], "人物递物")
        self.assertEqual(p.load("reports/alignment-report.json")["estimated_fallback_used"], False)
        before = w.scene_inputs(p, "scene-001")
        deck = p.load("render/deck-plan.json")
        deck[0]["page_title"] = "新的页面标题"
        p.save("render/deck-plan.json", deck)
        self.assertNotIn("cached", w.timeline_build(p))
        self.assertNotEqual(before, w.scene_inputs(p, "scene-001"))
        p.data["config"]["subtitles"] = False
        self.assertNotIn("cached", w.timeline_build(p))
        self.assertFalse(p.load("render/remotion-props.json")["subtitlesEnabled"])

    def test_original_pyav_merge_and_pillow_burned_subtitles(self):
        p = fixture(self.temp.name)
        plain = p.path("render/cache/plain.mp4")
        writer = cv2.VideoWriter(str(plain), cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 180))
        for _ in range(10):
            writer.write(np.full((180, 320, 3), 225, np.uint8))
        writer.release()
        from scripts.merge_scenes import _pyav_concat
        merged = p.path("render/cache/merged.mp4")
        self.assertTrue(_pyav_concat([plain, plain], merged))
        self.assertTrue(media.video_check(merged, [320, 180], 10, 2, audio=False)["passed"])
        srt = p.path("audio/subtitles.srt")
        srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n原生字幕\n", encoding="utf-8")
        burned = p.path("render/cache/burned.mp4")
        with bridge.project_context(p) as module, patch.object(bridge.server(), "_ffmpeg_has_filter", return_value=False):
            result, vf = module._subtitle_video_input(plain, srt, burned)
        self.assertEqual(result, burned)
        self.assertIsNone(vf)
        a, b = cv2.VideoCapture(str(plain)), cv2.VideoCapture(str(burned))
        try:
            _, af = a.read(); _, bf = b.read()
            self.assertGreater(np.abs(af[100:].astype(float) - bf[100:].astype(float)).mean(), 2)
        finally:
            a.release(); b.release()

    @unittest.skipUnless(os.environ.get("CS_BOARD_REMOTION_TEST") == "1", "显式开启本机浏览器真实渲染")
    def test_real_remotion_preview_gate_and_formal_video(self):
        p = prepare_deck(fixture(self.temp.name, width=640, height=360))
        w.timeline_build(p)
        w.annotation_build(p)
        w.render(p, True, size=[320, 180])
        w.compose(p, True)
        with self.assertRaises(WorkflowError):
            w.render(p, False)
        approve(p, "preview")
        w.render(p, False)
        self.assertEqual(p.load("render/cache/scene-001-preview-remotion.json"),
                         p.load("render/cache/scene-001-final-remotion.json"))
        preview = cv2.VideoCapture(str(p.path("scenes/scene-001/preview.mp4")))
        formal = cv2.VideoCapture(str(p.path("scenes/scene-001/final.mp4")))
        try:
            for frame in (0, 15, 30, 45, 59):
                preview.set(cv2.CAP_PROP_POS_FRAMES, frame)
                formal.set(cv2.CAP_PROP_POS_FRAMES, frame)
                ar, a = preview.read(); br, b = formal.read()
                self.assertTrue(ar and br)
                b = cv2.resize(b, (320, 180), interpolation=cv2.INTER_AREA)
                self.assertLess(float(np.abs(a.astype(float)-b.astype(float)).mean()), 5)
        finally:
            preview.release(); formal.release()
        w.compose(p, False)
        self.assertTrue(w.validate_final(p)["passed"])


if __name__ == "__main__":
    unittest.main()
