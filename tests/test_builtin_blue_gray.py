"""Blue-gray builtin style: source preservation, selection and generation routing."""
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


STYLE_ID = "builtin-blue-gray-story"
STYLE_NAME = "灰蓝写实叙事漫画风"
IMAGE_SHA256 = "b495487306b01b9a4ae4da2c2443d281d037ccc2fdb8d7ba71be9407c902b9f3"
REPO = Path(__file__).parents[1]


class GenerationCaptured(BaseException):
    """Stop before provider I/O; fixture approval is never production approval."""


class BlueGrayStyleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch.object(styles, "LIBRARY_DIR", Path(self.temp.name) / "styles")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.p = fixture(self.temp.name)
        approve(self.p, "storyboard")

    def test_builtin_asset_manifest_and_package_data(self):
        selected = styles.select(STYLE_ID)
        self.assertEqual(selected, styles.select(STYLE_NAME))
        self.assertEqual(selected["source"], "builtin")
        self.assertTrue(selected["use_as_reference"])
        image = Path(selected["image_path"])
        self.assertEqual(file_hash(image), IMAGE_SHA256)
        with Image.open(image) as original:
            self.assertEqual(original.size, (1672, 941))
            original.verify()
        config = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn(image.relative_to(REPO / "cs_board_video").as_posix(),
                      config["tool"]["setuptools"]["package-data"]["cs_board_video"])
        manifest = json.loads((REPO / "references/upstream-manifest.json").read_text(encoding="utf-8"))
        addition = next(item for item in manifest["additions"] if item["path"] == "web/public/styles/blue-gray-story.png")
        self.assertEqual(addition["sha256"], IMAGE_SHA256)

    def test_selected_preview_and_recipe_reach_project_scene(self):
        p = self.p
        result = dispatch(p, parser().parse_args(["style", "set", "--preset", STYLE_NAME, "--project", str(p.root)]))
        self.assertTrue(result["approval_required"])
        self.assertEqual(p.load("style/style.json")["preset"], STYLE_ID)
        self.assertEqual(p.data["config"]["canvas_hex"], "#A7B9B9")
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
        self.assertIn(p.load("style/style.json")["recipe"], prompt)
        self.assertIn("不得被替换", prompt)
        self.assertNotIn("同一主角固定为：中国青年男性", prompt)

    def test_renamed_style_keeps_recipe_and_story_characters_in_all_prompt_modes(self):
        with bridge.project_context(self.p) as module:
            snapshot = module.update_style(STYLE_ID, {"name": "灰蓝生活漫画"})
            self.assertEqual(snapshot["image_url"], "/styles/blue-gray-story.png")
            scene = {"title": "修车", "concept": "女孩在户外修自行车", "elements": ["女孩", "自行车"],
                     "text": "女孩高兴地修好自行车。", "illustration_elements": ["女孩", "自行车"]}
            for name in (STYLE_NAME, "灰蓝生活漫画"):
                paths, instruction = module.builtin_style_reference_context(name)
                self.assertEqual(file_hash(paths[0]), IMAGE_SHA256)
                for prompt in (module.build_board_prompt([scene], name, instruction),
                               module.build_board_prompt([scene], name, instruction, infographic=True),
                               module.build_image_prompt(scene, name)):
                    self.assertIn(module.STYLE_PRESETS[STYLE_NAME], prompt)
                    self.assertIn("女孩", prompt)
                    self.assertNotIn("同一主角固定为：中国青年男性", prompt)
                prompt = module.build_board_prompt([scene], name, instruction + "输入图2定义女孩。", True)
                self.assertIn("只使用人物参考组中定义的角色", prompt)
                self.assertIn("输入图2定义女孩", prompt)

    def test_web_initial_and_regeneration_send_reference_and_recipe(self):
        p = self.p
        p.save("plan.json", bridge.native_scenes(p))
        with bridge.project_context(p) as module, ExitStack() as stack:
            module.update_style(STYLE_ID, {"name": "灰蓝生活漫画"})
            stack.enter_context(patch.object(module, "load_config", return_value={}))
            stack.enter_context(patch.object(module, "probe_duration", return_value=2))
            stack.enter_context(patch.object(module, "begin_phase"))
            stack.enter_context(patch.object(module, "update_job"))
            generator = stack.enter_context(patch.object(module, "generate_image", side_effect=GenerationCaptured))
            for name in (STYLE_NAME, "灰蓝生活漫画"):
                module.JOBS[p.root.name]["style"] = name
                edited_prompt = module.build_board_prompt(bridge.native_scenes(p), name) + "\n突出人物动作。"
                for operation in (lambda: module.model_stage(p.root.name, "人物递出物品。", name, p.path("unused.wav"), 1, "", False, False, "detailed"),
                                  lambda: module.regenerate_board_image(p.root.name, 1, edited_prompt)):
                    with self.assertRaises(GenerationCaptured):
                        operation()
                    references = generator.call_args.args[3]
                    self.assertEqual(len(references), 1)
                    self.assertEqual(file_hash(references[0]), IMAGE_SHA256)
                    self.assertIn(module.STYLE_PRESETS[STYLE_NAME], generator.call_args.args[1])
                self.assertEqual(generator.call_args.args[1], edited_prompt)

    def test_standalone_original_and_renamed_style_send_reference_and_recipe(self):
        with bridge.project_context(self.p) as module, ExitStack() as stack:
            module.update_style(STYLE_ID, {"name": "灰蓝生活漫画"})
            stack.enter_context(patch.object(module, "load_config", return_value={}))
            stack.enter_context(patch.object(module, "image_provider_config", return_value={"api_key": "test-fixture"}))
            generator = stack.enter_context(patch.object(module, "generate_image", side_effect=GenerationCaptured))
            for name in (STYLE_NAME, "灰蓝生活漫画"):
                with self.assertRaises(GenerationCaptured):
                    module.generate_standalone_image({"prompt": "女孩在户外修自行车。", "style_name": name})
                references = generator.call_args.kwargs["reference_images"]
                self.assertEqual(len(references), 1)
                self.assertEqual(file_hash(references[0]), IMAGE_SHA256)
                self.assertIn(module.STYLE_PRESETS[STYLE_NAME], generator.call_args.args[1])
