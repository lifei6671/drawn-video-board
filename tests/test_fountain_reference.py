"""Reference-engine pen behavior: source ink, pressure, whole strokes and lifts."""
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from cs_board_video import bridge
from scripts import fountain_pen as fp
from scripts import sweety_stroke_paths as paths
from test_subject_contours import Frames
from helpers import fixture, prepare_images


class FountainReferenceTests(unittest.TestCase):
    def renderer(self, source=None):
        if source is None:
            source = np.full((100, 100, 3), 255, np.uint8)
        return bridge.RegionStreamRenderer(source, {"canvas": {"width": 100, "height": 100}, "elements": []},
            bridge.Config(fps=20, cap_long_edge=100, pen_type="fountain", canvas_hex="#FFFFFF", match_bg=False), None, True)

    def test_reference_taper_and_motion_start_and_finish_gently(self):
        points = np.c_[np.linspace(0, 100, 201), np.zeros(201)]
        taper = fp.taper(points)
        self.assertAlmostEqual(taper[0], .3)
        self.assertAlmostEqual(taper[-1], .3)
        self.assertEqual(taper[100], 1.)
        self.assertLess(fp.distance_fraction(.1, "minjerk"), .03)
        for profile in ("minjerk", "plateau"):
            progress = fp.distance_fraction(np.linspace(0, 1, 31), profile)
            np.testing.assert_allclose(fp.time_fraction(progress, profile), np.linspace(0, 1, 31), atol=.002)
            self.assertTrue(np.all(np.diff(progress) >= 0))

    def test_reference_thinning_retains_free_diagonal_endpoint(self):
        mask = np.zeros((100, 100), np.uint8)
        cv2.line(mask, (15, 70), (85, 70), 1, 3)
        cv2.line(mask, (45, 70), (78, 37), 1, 3)
        skeleton = paths.thin_ink(mask > 0)
        self.assertTrue(skeleton[35:40, 76:81].any())
        extracted = fp.extract_paths(mask > 0)
        self.assertTrue(any(np.linalg.norm(np.asarray(stroke) - [78, 37], axis=1).min() < 3 for stroke in extracted))

    def test_pressure_ink_stays_on_strokes_and_lift_moves_without_drawing(self):
        renderer = self.renderer()
        renderer.ink_pixels[:] = True
        renderer.ink_paint[:] = 0
        tips = []
        def snapshot(x, y):
            tips.append((x, y))
            return renderer._snapshot()
        renderer._snapshot_with_tip = snapshot
        writer = Frames()
        renderer._lay_ink_strokes(writer, 60, [[(10, 25), (85, 25)], [(85, 75), (15, 75)]],
                                  np.ones((100, 100), bool))
        self.assertEqual(len(writer.frames), 60)
        self.assertTrue(np.all(writer.frames[-1][40:60] == 255))
        self.assertGreater((writer.frames[-1][:, 45, 0] < 180).sum(),
                           (writer.frames[-1][:, 10, 0] < 180).sum())
        travelling = [i for i in range(1, 60) if 30 < tips[i][1] < 70]
        self.assertTrue(travelling)
        for index in travelling:
            np.testing.assert_array_equal(writer.frames[index], writer.frames[index-1])
        self.assertLessEqual(np.linalg.norm(np.diff(tips, axis=0), axis=1).max(), 120)

    def test_short_window_fails_without_bulk_completion(self):
        renderer = self.renderer()
        writer = Frames()
        with self.assertRaisesRegex(ValueError, "延长描线时间或简化线稿"):
            renderer._lay_ink_strokes(writer, 1, [[(10, 25), (85, 25)], [(85, 75), (15, 75)]],
                                      np.ones((100, 100), bool))
        self.assertEqual(writer.frames, [])
        self.assertTrue(np.all(renderer.drawn == 255))

    def test_quick_contours_skip_small_details_but_full_mode_keeps_them(self):
        strokes = [[(10, 20), (90, 20)]] + [[(10, y), (18, y)] for y in range(30, 90, 4)]
        allowed = np.ones((100, 100), bool)
        quick = self.renderer()
        quick.ink_pixels[:] = True
        quick.ink_paint[:] = 0
        frames = Frames()
        quick._lay_ink_strokes(frames, 5, strokes, allowed)
        self.assertEqual(len(frames.frames), 5)
        self.assertLess(frames.frames[-1][20, 50, 0], 80)
        self.assertTrue(np.all(frames.frames[-1][30:] == 255))
        full = self.renderer()
        full.max_skeleton_strokes = 0
        full.ink_pixels[:] = True
        full.ink_paint[:] = 0
        with self.assertRaisesRegex(ValueError, "延长描线时间"):
            full._lay_ink_strokes(Frames(), 5, strokes, allowed)
        full_frames = Frames()
        full._lay_ink_strokes(full_frames, 100, strokes, allowed)
        self.assertLess(full_frames.frames[-1][30, 14, 0], 100)

    def test_quick_layers_begin_color_early_and_finish_before_next_layer(self):
        from test_layered_drawing import assets, annotation, composite
        images, ann = assets(), annotation()
        for image in images.values():
            cv2.line(image, (35, 35), (50, 35), (25, 25, 25, 255), 1)
        for index, element in enumerate(ann['elements']):
            element['reveal'].update(startMs=index * 3000, durationMs=3000)
        ann['sceneDurationMs'] = 9500
        cfg = bridge.Config(fps=20, cap_long_edge=100, pen_type='fountain', canvas_hex='#FFFFFF')
        def render(cached):
            r = bridge.RegionStreamRenderer(np.full((100,100,3),255,np.uint8), ann, cfg,
                None, True, layer_images=images)
            paths = None
            if cached:
                paths = []
                for element in ann['elements']:
                    r.prepare_element(element)
                    paths.append(r._region_skeleton_strokes(r._allowed_mask(element, [])))
            writer = Frames()
            r.render_to(Path('unused.mp4'), 9500, writer=writer, paths=paths)
            return writer.frames
        live, cached = render(False), render(True)
        self.assertTrue(np.any(live[25][:,:,0] == images['background'][0,0,0]))
        for index in range(3):
            np.testing.assert_allclose(live[(index+1)*60-1], composite(images, list(images)[:index+1]), atol=1)
        for actual, expected in zip(live, cached):
            np.testing.assert_array_equal(actual, expected)
        np.testing.assert_array_equal(live[-1][48:52,68:72], images['background'][48:52,68:72,:3])

    def test_quick_low_fps_scene_has_time_to_complete_long_contour(self):
        source = np.full((480, 720, 3), 255, np.uint8)
        cv2.line(source, (20, 240), (700, 240), (25, 25, 25), 1)
        ann = {'canvas': {'width':720, 'height':480}, 'elements':[
            {'id':'line','region':{'x':0,'y':0,'width':720,'height':480},
             'reveal':{'startMs':0,'durationMs':30000,'phase':'both'}}]}
        r = bridge.RegionStreamRenderer(source, ann,
            bridge.Config(fps=2,cap_long_edge=720,pen_type='fountain',canvas_hex='#FFFFFF',match_bg=False),None,True)
        frames = Frames()
        r.render_to(Path('unused.mp4'), 30000, writer=frames)
        self.assertEqual(len(frames.frames), 60)
        self.assertLess(frames.frames[5][240, 698, 0], 220)
        np.testing.assert_array_equal(frames.frames[-1], source)

    def test_dark_colored_fill_is_not_used_as_pen_ink(self):
        source = np.full((100, 100, 3), 255, np.uint8)
        source[30:60, 20:80] = [30, 65, 105]
        renderer = self.renderer(source)
        self.assertFalse(renderer.ink_pixels[25:65, 15:85].any())

    def test_layer_silhouette_remains_recognizable_without_source_black_ink(self):
        background = np.full((100,100,4), (210,170,130,255), np.uint8)
        person = np.zeros((100,100,4), np.uint8)
        cv2.circle(person, (50,18), 9, (90,170,220,255), -1)
        cv2.fillPoly(person, [np.array([(43,27),(57,27),(77,40),(73,46),(60,38),
            (59,60),(65,88),(56,90),(49,65),(43,90),(35,87),(41,60),(40,38),
            (23,23),(27,17),(44,32)])], (90,170,220,255))
        ann = {'canvas':{'width':100,'height':100},'layers':[{'id':'back','image':'back.png'},
            {'id':'actor','image':'actor.png'}], 'elements':[
            {'id':key,'layer_id':key,'region':{'x':0,'y':0,'width':100,'height':100},
             'reveal':{'startMs':i*6000,'durationMs':6000}} for i,key in enumerate(('back','actor'))]}
        r = bridge.RegionStreamRenderer(background[:,:,:3],ann,
            bridge.Config(fps=30,cap_long_edge=100,pen_type='fountain',canvas_hex='#FFFFFF'),
            None,True,max_skeleton_strokes=1,layer_images={'back':background,'actor':person})
        r.drawn[:] = background[:,:,:3]
        r.prepare_element(ann['elements'][1])
        allowed = r._allowed_mask(ann['elements'][1],[])
        strokes = r._region_skeleton_strokes(allowed)
        frames = Frames()
        r._lay_ink_strokes(frames,120,strokes,allowed)
        border = allowed & ~(cv2.erode(allowed.astype(np.uint8),np.ones((3,3),np.uint8)) > 0)
        ink = np.any(frames.frames[-1] != background[:,:,:3],axis=2)
        nearby = cv2.dilate(ink.astype(np.uint8),np.ones((3,3),np.uint8)) > 0
        self.assertGreater(np.mean(nearby[border]), .95)
        np.testing.assert_array_equal(frames.frames[-1][~allowed], background[:,:,:3][~allowed])
        np.testing.assert_array_equal(frames.frames[-1][50,50], background[50,50,:3])
        r._wash_subject(Frames(),30,allowed)
        np.testing.assert_array_equal(r.drawn,r.color_img_float)

    def test_symbolic_color_finishes_in_four_fast_passes_without_filling_holes(self):
        r = self.renderer()
        r.color_img_float[:] = [70,130,190]
        allowed = np.zeros((100,100),bool)
        allowed[10:90,15:85] = True
        allowed[40:60,40:60] = False
        allowed[2,2] = True
        tips = []
        def snapshot(x,y):
            tips.append((x,y))
            return r._snapshot()
        r._snapshot_with_tip = snapshot
        frames = Frames()
        r._wash_subject(frames,100,allowed)
        self.assertEqual(len(frames.frames),100)
        self.assertEqual(len(tips),12)  # 0.6 s at 20 fps, then no moving hand.
        self.assertGreaterEqual(np.count_nonzero(np.diff(np.sign(np.diff(np.array(tips)[:,0])))),3)
        np.testing.assert_array_equal(frames.frames[11][allowed],r.color_img_float[allowed])
        self.assertTrue(np.all(frames.frames[11][~allowed] == 255))
        np.testing.assert_array_equal(frames.frames[11],frames.frames[-1])
        self.assertFalse(np.array_equal(frames.frames[0],frames.frames[11]))

    def test_color_preserves_clean_source_art_without_restylizing_or_inpainting(self):
        source = np.full((100, 100, 3), 255, np.uint8)
        cv2.line(source, (15, 25), (85, 25), (30, 30, 30), 2, cv2.LINE_AA)
        source[50:85, 20:80] = [160, 210, 180]
        cv2.rectangle(source, (20, 50), (80, 85), (30, 30, 30), 1, cv2.LINE_AA)
        renderer = self.renderer(source)
        np.testing.assert_array_equal(renderer.color_img, source)
        renderer.ann["elements"] = [{"id": "plant", "region": {"x": 0, "y": 0, "width": 100, "height": 100},
                                     "reveal": {"startMs": 0, "durationMs": 6000}}]
        writer = Frames()
        renderer.render_to(Path("unused.mp4"), 6500, writer=writer)
        self.assertEqual(len(writer.frames), 130)
        np.testing.assert_array_equal(writer.frames[-1], source)

    def test_fountain_prompts_require_real_fine_ink_artwork(self):
        with tempfile.TemporaryDirectory() as directory:
            project = prepare_images(fixture(directory))
            project.data["config"]["pen_type"] = "fountain"
            project.persist()
            bridge.prompts(project)
            prompt = project.path("scenes/scene-001/prompt.md").read_text(encoding="utf-8")
            self.assertIn("细而流畅", prompt)
            self.assertIn("不要粗马克笔描边", prompt)
            self.assertEqual(project.load("scenes/scene-001/prompt-context.json")["pen_type"], "fountain")

    def test_layered_fountain_keeps_background_alpha_holes_and_cached_paths(self):
        from test_layered_drawing import assets, annotation, composite
        images, ann = assets(), annotation()
        cv2.rectangle(images["plant"], (56, 32), (87, 82), (25, 25, 25, 255), 1)
        for index, element in enumerate(ann["elements"]):
            element["reveal"].update(startMs=index*6000, durationMs=6000)
        ann["sceneDurationMs"] = 18500
        cfg = bridge.Config(fps=10, cap_long_edge=100, pen_type="fountain", canvas_hex="#FFFFFF")
        def renderer():
            return bridge.RegionStreamRenderer(np.full((100, 100, 3), 255, np.uint8), ann, cfg,
                None, True, max_skeleton_strokes=0, layer_images=images)
        live = renderer()
        frames = Frames()
        live.render_to(Path("unused.mp4"), 18500, writer=frames)
        np.testing.assert_array_equal(frames.frames[59], images["background"][:, :, :3])
        np.testing.assert_allclose(frames.frames[-1], composite(images, list(images)), atol=1)
        np.testing.assert_array_equal(frames.frames[-1][48:52, 68:72], images["background"][48:52, 68:72, :3])
        cached = renderer()
        paths = []
        for element in ann["elements"]:
            cached.prepare_element(element)
            paths.append(cached._region_skeleton_strokes(cached._allowed_mask(element, [])))
        cached_frames = Frames()
        cached.render_to(Path("unused.mp4"), 18500, writer=cached_frames, paths=paths)
        for a, b in zip(frames.frames, cached_frames.frames):
            np.testing.assert_array_equal(a, b)


if __name__ == "__main__":
    unittest.main()
