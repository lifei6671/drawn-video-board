"""Outline tracing and direct horizontal painting across all entry points."""
from pathlib import Path
import subprocess
import sys
import unittest

import cv2
import numpy as np

from cs_board_video.bridge import Config, RegionStreamRenderer
from cs_board_video.upstream.scripts.stream_render import _paint_strokes, StreamBoardRenderer
from test_subject_contours import Frames


class ContourDrawingTests(unittest.TestCase):
    def source(self):
        image = np.full((100, 100, 3), 255, np.uint8)
        cv2.circle(image, (50, 50), 32, (90, 140, 170), -1)
        cv2.circle(image, (50, 50), 32, (0, 0, 0), 2)
        return image

    def renderer(self, **options):
        annotation = {"canvas": {"width": 100, "height": 100}, "elements": [
            {"id": "circle", "region": {"x": 5, "y": 5, "width": 90, "height": 90},
             "reveal": {"startMs": 0, "durationMs": 2000}}]}
        cfg = Config(fps=10, cap_long_edge=100, canvas_hex="#FFFFFF", pause_mode="off", **options)
        return RegionStreamRenderer(self.source(), annotation, cfg, None, True)

    def test_legacy_grid_and_fill_options_use_the_same_contour_frames(self):
        expected = Frames()
        self.renderer().render_to(Path("unused.mp4"), 2500, writer=expected)
        for mode in ("contour", "paint", "brush", "contour-wipe"):
            renderer = self.renderer(ink_path_mode="grid", color_fill=mode)
            self.assertEqual(renderer.cfg.ink_path_mode, "skeleton")
            self.assertEqual(renderer.cfg.color_fill, "paint")
            actual = Frames()
            renderer.render_to(Path("unused.mp4"), 2500, writer=actual)
            self.assertEqual(len(actual.frames), 25)
            for a, b in zip(actual.frames, expected.frames):
                np.testing.assert_array_equal(a, b)

    def test_color_moves_top_to_bottom_without_blending_or_final_patch(self):
        renderer = self.renderer()
        allowed = np.ones((100, 100), bool)
        writer = Frames()
        renderer._wash_subject(writer, 20, allowed)
        y, x = np.indices((100, 100))
        early = np.any(writer.frames[2] != 255, axis=2)
        self.assertTrue(early.any())
        self.assertLess(y[early].max(), 50)
        exact_target = np.all(writer.frames[2] == renderer.color_img, axis=2)
        self.assertTrue(np.all(exact_target[early]))
        self.assertTrue(np.all(writer.frames[2][45:55,45:55] == 255))
        np.testing.assert_array_equal(writer.frames[-1], renderer.color_img)
        self.assertFalse(np.array_equal(writer.frames[-2], writer.frames[-1]))

    def test_paint_routes_preserve_holes_thin_lines_and_isolated_pixels(self):
        mask = np.zeros((70, 90), np.uint8)
        cv2.circle(mask, (35, 35), 25, 1, -1)
        cv2.circle(mask, (35, 35), 10, 0, -1)
        mask[2,2:20] = 1
        mask[65,80] = 1
        strokes = _paint_strokes(mask > 0, 4)
        painted = np.zeros_like(mask)
        for stroke in strokes:
            for a,b in zip(stroke,stroke[1:]):
                cv2.line(painted,a,b,1,9,cv2.LINE_8)
        self.assertTrue(np.all(painted[mask > 0] == 1))
        self.assertEqual(_paint_strokes(np.zeros((3,3), bool), 4), [])

    def test_color_appears_only_on_the_continuous_pen_path_each_frame(self):
        renderer=self.renderer()
        renderer.color_img_float[:]=[70,120,190]
        allowed=np.zeros((100,100),bool);allowed[15:85,15:85]=True
        allowed[42:58,40:60]=False
        tips=[]
        coverage=np.zeros((100,100),np.uint8)
        original=renderer._reveal_color_segment
        def reveal(a,b,mask):
            cv2.line(coverage,a,b,1,renderer.cfg.ink_reveal_radius*2+1,cv2.LINE_8)
            original(a,b,mask)
        def snapshot(x,y):
            tips.append((x,y))
            return renderer._snapshot()
        renderer._reveal_color_segment=reveal
        renderer._snapshot_with_tip=snapshot
        class CheckedFrames(Frames):
            def write(self,frame):
                expected=np.full((100,100,3),255,np.uint8)
                touched=(coverage>0)&allowed
                expected[touched]=[70,120,190]
                np.testing.assert_array_equal(frame,expected)
                super().write(frame)
        writer=CheckedFrames()
        renderer._wash_subject(writer,160,allowed)
        moves=np.diff(np.asarray(tips),axis=0)
        self.assertTrue((moves[:,0]>0).any())
        self.assertTrue((moves[:,0]<0).any())
        self.assertLess(np.hypot(moves[:,0],moves[:,1]).max(),30)
        np.testing.assert_array_equal(writer.frames[-1][allowed],renderer.color_img_float[allowed])
        self.assertTrue(np.all(writer.frames[-1][~allowed]==255))

    def test_color_stroke_has_round_end_and_does_not_reveal_a_rectangle(self):
        renderer=self.renderer();renderer.color_img_float[:]=[70,120,190]
        renderer._reveal_color_segment((25,50),(55,50),np.ones((100,100),bool))
        np.testing.assert_array_equal(renderer.drawn[46,25],[70,120,190])
        np.testing.assert_array_equal(renderer.drawn[45,20],[255,255,255])
        np.testing.assert_array_equal(renderer.drawn[70,40],[255,255,255])

    def test_one_frame_ink_traces_the_entire_stroke_and_lifts_between_strokes(self):
        renderer = self.renderer()
        renderer.ink_pixels[:] = True
        renderer.ink_paint[:] = 0
        writer = Frames()
        renderer._lay_ink(writer, 1, [(10,10),(25,10),(75,75),(90,75)], {2},
                          np.ones((100,100), bool))
        self.assertEqual(len(writer.frames), 1)
        self.assertTrue(np.all(writer.frames[0][10,10:26] == 0))
        self.assertTrue(np.all(writer.frames[0][75,75:91] == 0))
        self.assertTrue(np.all(writer.frames[0][40,40] == 255))

    def test_standalone_entry_has_exact_duration_and_uses_contour_rendering(self):
        for milliseconds in (1000, 6000):
            cfg = Config(fps=10, cap_long_edge=100, canvas_hex="#FFFFFF", pause_mode="off",
                         ink_path_mode="grid", color_fill="paint")
            renderer = StreamBoardRenderer(self.source(), cfg, None, True)
            writer = Frames()
            renderer.render_to(Path("unused.mp4"), milliseconds, writer=writer)
            self.assertEqual(len(writer.frames), milliseconds // 100)
            np.testing.assert_array_equal(writer.frames[-1], renderer.renderer.color_img)
            self.assertFalse(np.array_equal(writer.frames[0], writer.frames[-1]))

    def test_standalone_renderer_imports_without_bridge_initialization(self):
        code = (
            "import numpy as np; "
            "from cs_board_video.upstream.scripts.stream_render import StreamBoardRenderer,Config; "
            "r=StreamBoardRenderer(np.full((100,100,3),255,np.uint8),Config(cap_long_edge=100),None,True); "
            "assert (r.out_w,r.out_h)==(100,100)"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                                cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
