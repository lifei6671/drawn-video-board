"""Real local fonts, approval freshness and the encoded rendering boundary."""
from pathlib import Path
import tempfile
import unittest
import numpy as np
from PIL import Image

from cs_board_video import typography as t, workflow as w, media, bridge, styles
from cs_board_video.text_render import TextOverlay
from cs_board_video.project import WorkflowError
from helpers import fixture, approve, prepare_images, prepare_audio, prepare_plans


def item(text="自我塑造", **extra):
    return {"text": text, "purpose": "提炼行动的含义", "box": [.05,.05,.9,.4],
            "font_scale": .10, "start": .5, "duration": .3, **extra}


class TypographyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.p = fixture(self.temp.name)

    def text(self, *items, mode="illustration"):
        scenes = self.p.scenes()
        scenes[0].update(visual_text=list(items), visual_mode=mode)
        self.p.save("narration/storyboard.json", {"scenes": scenes})
        w.validate_storyboard(self.p)

    def select(self):
        t.choose_font(self.p, "tiejili")

    def test_legacy_needs_no_font_but_text_requires_real_sample_approval(self):
        approve(self.p, "storyboard")
        w.board_ready(self.p)
        self.text(item())
        with self.assertRaises(WorkflowError):
            approve(self.p, "storyboard")
        self.select()
        t.sample(self.p, "scene-001")
        with self.assertRaises(WorkflowError):
            w.board_ready(self.p)
        approve(self.p, "typography")
        approve(self.p, "storyboard")
        w.board_ready(self.p)
        self.assertEqual(t.font_path(self.p).suffix, ".ttf")
        self.text(item("改变从现在开始"))
        with self.assertRaises(WorkflowError):
            t.ready(self.p)

    def test_font_copy_and_sample_bytes_are_bound_to_approval(self):
        self.text(item()); self.select(); t.sample(self.p, "scene-001")
        approve(self.p, "typography")
        font = t.font_path(self.p)
        raw = font.read_bytes()
        font.write_bytes(raw + b"changed")
        with self.assertRaises(WorkflowError): t.ready(self.p)
        font.write_bytes(raw)
        t.ready(self.p)
        self.p.path("previews/typography-sample.png").write_bytes(b"changed")
        with self.assertRaises(WorkflowError): t.ready(self.p)

    def test_missing_glyph_and_overflow_are_errors_not_truncation(self):
        self.text(item()); t.choose_font(self.p, "anton")
        with self.assertRaisesRegex(WorkflowError, "缺少字符"):
            t.layout(self.p, self.p.scene("scene-001"), (320,180))
        self.select(); self.text(item("文字"*45))
        with self.assertRaisesRegex(WorkflowError, "溢出"):
            t.layout(self.p, self.p.scene("scene-001"), (320,180))

    def test_glyph_progress_final_sample_and_transparent_bubbles(self):
        self.text(item("改变行动", presentation="speech-right")); self.select()
        layers = t.layout(self.p, self.p.scene("scene-001"), (320,180))
        overlay = TextOverlay(layers, 2000, 10)
        blank = np.full((180,320,3),255,np.uint8)
        np.testing.assert_array_equal(overlay.paint(blank.copy(), 900), blank)
        partial = overlay.paint(blank.copy(), 1130)
        final = overlay.paint(blank.copy(), 1999)
        self.assertFalse(np.array_equal(partial, final))
        # Second glyph is still untouched while the first fades in.
        g=layers[0]["glyphs"][1]; h,ww=g["mask"].shape
        self.assertFalse(np.array_equal(partial[g["y"]:g["y"]+h,g["x"]:g["x"]+ww],
                                       final[g["y"]:g["y"]+h,g["x"]:g["x"]+ww]))
        for kind in t.PRESENTATIONS[1:]:
            im=np.asarray(t.bubble_image(kind,(320,180),"#FFFFFF","#202020"))
            self.assertEqual(im[0,0,3],0)
            self.assertGreater(np.count_nonzero(im[:,:,3]),100)

    def test_schema_rejects_invalid_geometry_timing_and_empty_text_page(self):
        for bad in (item(box=[.8,0,.3,.4]),item(start=.8,duration=.3),item(purpose=""),item(presentation="unknown"),item(animation="strokes")):
            with self.assertRaises(WorkflowError): self.text(bad)
        with self.assertRaises(WorkflowError): self.text(mode="text_only")

    def test_shared_baseline_keeps_horizontal_stroke_and_punctuation_in_place(self):
        self.text(item("先一，aA",box=[.05,.05,.9,.8],font_scale=.2));self.select()
        glyphs=t.layout(self.p,self.p.scene("scene-001"),(1000,600))[0]["glyphs"]
        tops={g["char"]:g["y"]+int(np.where(g["mask"]>0)[0].min()) for g in glyphs}
        self.assertGreater(tops["一"],tops["先"]+15)
        self.assertGreater(tops["，"],tops["一"]+15)
        self.assertGreater(tops["a"],tops["A"]+5)

    def test_italic_overhang_is_contained_or_explicitly_rejected(self):
        t.choose_font(self.p,"instrument-italic")
        for kind in ("plain","speech-left"):
            self.text(item("fff",box=[0,.1,.17,.8],font_scale=.3,presentation=kind))
            try:
                layers=t.layout(self.p,self.p.scene("scene-001"),(300,200))
            except WorkflowError as error:
                self.assertRegex(str(error),"墨迹|溢出")
                continue
            for g in layers[0]["glyphs"]:
                ys,xs=np.where(g["mask"]>0)
                self.assertGreaterEqual(g["x"]+xs.min(),0)
                self.assertLess(g["x"]+xs.max(),51)
        # A large box must render: rejecting every italic run is not a solution.
        self.text(item("fff",box=[0,0,1,1],font_scale=.3))
        self.assertEqual(len(t.layout(self.p,self.p.scene("scene-001"),(300,200))[0]["glyphs"]),3)

    def test_native_video_with_text_and_cache_invalidation(self):
        self.text(item()); self.select(); t.sample(self.p,"scene-001")
        approve(self.p,"typography"); prepare_images(self.p); prepare_audio(self.p); prepare_plans(self.p)
        w.render(self.p, True, size=[320,180])
        report=self.p.load("reports/scene-001-preview.json")
        self.assertTrue(report["text_overlay"])
        self.assertTrue(report["passed"], report)
        before=w.scene_inputs(self.p,"scene-001")
        self.text(item("行动"))
        self.assertNotEqual(before,w.scene_inputs(self.p,"scene-001"))
        with self.assertRaises(WorkflowError): w.render(self.p,True,size=[320,180])

    def test_text_only_background_and_planning_request(self):
        self.text(item(),mode="text_only"); self.select(); t.sample(self.p,"scene-001")
        with self.assertRaises(WorkflowError): t.create_background(self.p,"scene-001")
        approve(self.p,"typography")
        result=t.create_background(self.p,"scene-001")
        self.assertTrue(Path(result["path"]).is_file())
        bridge.plan(self.p,2)
        self.assertIn("visual_text",str(self.p.load("narration/plan-request.json")))

    def test_planner_adapts_optional_text_and_image_prompt_reserves_space(self):
        text=self.p.scene("scene-001")["narration"]
        candidate=[{"title":"行动", "text":text,"concept":"行动提示", "elements":["人物","物品"],
                    "visual_text":[item()]}]
        bridge.plan(self.p,2,candidate)
        self.assertEqual(self.p.scene("scene-001")["visual_text"],[item()])
        self.select();t.sample(self.p,"scene-001");approve(self.p,"typography")
        prepare_images(self.p);bridge.prompts(self.p)
        self.assertIn("预留干净空间",self.p.path("scenes/scene-001/prompt.md").read_text(encoding="utf-8"))

    def test_blank_text_page_uses_real_video_path(self):
        self.text(item(animation="fade"),mode="text_only");self.select();t.sample(self.p,"scene-001")
        approve(self.p,"typography");prepare_images(self.p)
        Image.new("RGB",(320,180),self.p.data["config"]["canvas_hex"]).save(self.p.path("scenes/scene-001/image.png"))
        w.review_image(self.p,"scene-001",w.image_target(self.p,"scene-001"),"测试纯文字底图，排字来自独立文字层")
        w.validate_images(self.p);prepare_audio(self.p);prepare_plans(self.p)
        w.render(self.p,True,size=[320,180])
        self.assertTrue(self.p.load("reports/scene-001-preview.json")["passed"])

    def test_entrances_reveal_whole_glyphs_without_stroke_masks(self):
        mask=np.array([[255,0,255],[255,255,255]],np.uint8)
        def overlay(animation):
            return TextOverlay([{"glyphs":[{"mask":mask,"x":1,"y":1},{"mask":mask,"x":6,"y":1}],
                "bubble":np.zeros((4,10,4),np.uint8),"x":0,"y":0,"color":(0,0,0),
                "start":.2,"duration":.4,"animation":animation}],1000,25)
        blank=np.full((4,10,3),255,np.uint8)
        characters=overlay("characters")
        at_start=characters.paint(blank.copy(),200)
        np.testing.assert_array_equal(at_start,blank)
        partial=characters.paint(blank.copy(),300)
        # Every ink pixel of the first glyph appears together, with identical opacity.
        ink=partial[1:3,1:4][mask>0]
        self.assertTrue(np.all(ink==ink[0]))
        self.assertTrue(np.all((ink>0)&(ink<255)))
        self.assertTrue(np.all(partial[1:3,6:9]==255))
        whole=overlay("fade")
        middle=whole.paint(blank.copy(),400)
        np.testing.assert_array_equal(middle[1:3,1:4],middle[1:3,6:9])
        self.assertTrue(np.all((middle[1:3,1:4][mask>0]>0)&(middle[1:3,1:4][mask>0]<255)))
        np.testing.assert_array_equal(characters.paint(blank.copy(),700),whole.paint(blank.copy(),700))

    def test_new_style_presets_have_independent_identity_and_real_assets(self):
        for name in ("builtin-vintage-paper-people","builtin-layered-paper-collage"):
            preset=styles.select(name)
            self.assertTrue(preset["use_as_reference"])
            self.assertNotIn("characters",preset)
            with Image.open(preset["image_path"]) as im:
                self.assertEqual(im.size,(1536,1024)); im.verify()


if __name__ == "__main__": unittest.main()
