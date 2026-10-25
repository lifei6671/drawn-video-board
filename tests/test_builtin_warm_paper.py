"""Warm-paper style registration, packaged assets and generation references."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from PIL import Image

from cs_board_video import bridge, styles, workflow as w
from cs_board_video.cli import dispatch, parser
from cs_board_video.project import WorkflowError, file_hash
from helpers import approve, fixture


STYLE_ID = "builtin-warm-paper-line"
STYLE_NAME = "暖纸松弛线描风"
IMAGE_SHA256 = "da412e50f9a60379e167883b86810b015d71703f46258f103208dc0e15c575a3"
REPO = Path(__file__).parents[1]


class GenerationCaptured(BaseException):
    """Stop at the provider boundary without making a real API request."""


class WarmPaperStyleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch.object(styles, "LIBRARY_DIR", Path(self.temp.name) / "styles")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.p = fixture(self.temp.name)
        approve(self.p, "storyboard")

    def test_listing_asset_and_package_manifest(self):
        selected = styles.select(STYLE_ID)
        self.assertEqual(selected, styles.select(STYLE_NAME))
        self.assertEqual(selected["source"], "builtin")
        self.assertTrue(selected["use_as_reference"])
        image = Path(selected["image_path"])
        self.assertEqual(file_hash(image), IMAGE_SHA256)
        with Image.open(image) as sample:
            self.assertEqual(sample.size, (1536, 1024))
            sample.verify()
        config = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn(image.relative_to(REPO / "cs_board_video").as_posix(),
                      config["tool"]["setuptools"]["package-data"]["cs_board_video"])
        manifest = json.loads((REPO / "references/upstream-manifest.json").read_text(encoding="utf-8"))
        entry = next(item for item in manifest["additions"] if item["path"] == "web/public/styles/warm-paper-line.png")
        self.assertEqual(entry["sha256"], IMAGE_SHA256)

    def test_selected_reference_and_recipe_reach_scene_with_approval(self):
        p = self.p
        result = dispatch(p, parser().parse_args(["style", "set", "--preset", STYLE_NAME, "--project", str(p.root)]))
        self.assertTrue(result["approval_required"])
        self.assertEqual(p.load("style/style.json")["preset"], STYLE_ID)
        self.assertEqual(p.data["config"]["canvas_hex"], "#FFFCF0")
        self.assertEqual(styles.reference_path(p), p.path("style/preset-preview.png"))
        self.assertEqual(p.hash("style/preset-preview.png"), IMAGE_SHA256)
        with self.assertRaises(WorkflowError):
            w.style_ready(p)
        approve(p, "style")
        p.data["image_mode"] = "manual"
        approve(p, "image_mode")
        bridge.prompts(p)
        context = p.load("scenes/scene-001/prompt-context.json")
        self.assertEqual(context["style"], STYLE_NAME)
        self.assertEqual(len(context["references"]), 1)
        self.assertEqual(p.hash(context["references"][0]), IMAGE_SHA256)
        prompt = p.path("scenes/scene-001/prompt.md").read_text(encoding="utf-8")
        self.assertIn(styles.select(STYLE_ID)["recipe"], prompt)
        self.assertIn("不得被替换", prompt)
        self.assertNotIn("同一主角固定为：中国青年男性", prompt)

    def test_web_regeneration_and_renaming_keep_reference(self):
        p = self.p
        p.save("plan.json", bridge.native_scenes(p))
        with bridge.project_context(p) as module, ExitStack() as stack:
            snapshot = module.update_style(STYLE_ID, {"name": "暖纸生活线描"})
            self.assertEqual(snapshot["image_url"], "/styles/warm-paper-line.png")
            stack.enter_context(patch.object(module, "load_config", return_value={}))
            stack.enter_context(patch.object(module, "probe_duration", return_value=2))
            stack.enter_context(patch.object(module, "begin_phase"))
            stack.enter_context(patch.object(module, "update_job"))
            generator = stack.enter_context(patch.object(module, "generate_image", side_effect=GenerationCaptured))
            for name in (STYLE_NAME, "暖纸生活线描"):
                module.JOBS[p.root.name]["style"] = name
                prompt = module.build_board_prompt(bridge.native_scenes(p), name)
                for operation in (lambda: module.model_stage(p.root.name, "人物递出物品。", name, p.path("unused.wav"), 1, "", False, False, "detailed"),
                                  lambda: module.regenerate_board_image(p.root.name, 1, prompt)):
                    with self.assertRaises(GenerationCaptured):
                        operation()
                    references = generator.call_args.args[3]
                    self.assertEqual(len(references), 1)
                    self.assertEqual(file_hash(references[0]), IMAGE_SHA256)
                    self.assertIn(module.STYLE_PRESETS[STYLE_NAME], generator.call_args.args[1])
