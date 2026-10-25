"""Subject ownership, phased drawing and legacy compatibility at frame level."""
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from cs_board_video.bridge import Config, RegionStreamRenderer
from cs_board_video import media
from cs_board_video.upstream.scripts.render_stream_whiteboard import validate_subject_contours


class Frames:
    def __init__(self):
        self.frames = []

    def isOpened(self):
        return True

    def write(self, frame):
        self.frames.append(frame.copy())

    def release(self):
        pass


def event(key, phase, start):
    return {"id": key, "region": {"x": 10, "y": 10, "width": 80, "height": 80},
            "contours": [[[10, 10], [90, 10], [50, 90]]],
            "holes": [[[43, 25], [57, 25], [57, 40], [43, 40]]],
            "reveal": {"startMs": start, "durationMs": 1000, "phase": phase}}


class SubjectContourTests(unittest.TestCase):
    def renderer(self, annotation, size=100):
        source = np.full((100, 100, 3), 255, np.uint8)
        cv2.fillPoly(source, [np.array([[10, 10], [90, 10], [50, 90]])], (150, 150, 150))
        cv2.polylines(source, [np.array([[10, 10], [90, 10], [50, 90]])], True, (0, 0, 0), 2)
        source[26:40, 44:57] = (0, 0, 255)  # Another object inside the hole.
        source[90:98, 0:8] = 0  # Unannotated content must not flash in at the end.
        return RegionStreamRenderer(source, annotation,
                                    Config(fps=10, cap_long_edge=size, canvas_hex="#FFFFFF",
                                           ink_path_mode="skeleton", pause_mode="off"), None, True)

    def annotation(self):
        return {"canvas": {"width": 100, "height": 100}, "sceneDurationMs": 2500,
                "elements": [event("outline", "ink", 0), event("fill", "color", 1000)]}

    def test_later_color_does_not_steal_outline_and_holes_stay_clear(self):
        ann = self.annotation()
        r = self.renderer(ann)
        mask = r._allowed_mask(ann["elements"][0], ann["elements"][1:])
        self.assertTrue(mask[20, 30])
        self.assertFalse(mask[80, 15])  # Inside the old rectangle, outside the triangle.
        self.assertFalse(mask[32, 50])
        np.testing.assert_array_equal(mask, r._allowed_mask(ann["elements"][1], []))

    def test_gray_fill_is_progressive_and_no_final_whole_image_reveal(self):
        ann = self.annotation()
        r = self.renderer(ann)
        writer = Frames()
        r.render_to(Path("unused.mp4"), 2500, writer=writer)
        self.assertEqual(len(writer.frames), 25)
        mask = r._allowed_mask(ann["elements"][0], [])
        interior = mask & ~r.ink_pixels
        self.assertTrue(np.all(writer.frames[9][interior] == 255))
        filled = [np.count_nonzero(np.any(f[interior] != 255, axis=1)) for f in writer.frames[10:20]]
        self.assertGreater(filled[-1], filled[0])
        self.assertEqual(filled, sorted(filled))
        np.testing.assert_array_equal(writer.frames[-1][mask], r.color_img[mask])
        self.assertTrue(np.all(writer.frames[-1][~mask] == 255))
        np.testing.assert_array_equal(writer.frames[19], writer.frames[-1])

    def test_cached_strokes_and_scaled_masks(self):
        ann = self.annotation()
        r = self.renderer(ann, 200)
        mask = r._allowed_mask(ann["elements"][0], [])
        self.assertTrue(mask[40, 60])
        self.assertFalse(mask[64, 100])
        paths = [r._region_skeleton_strokes(mask), []]
        cached, live = Frames(), Frames()
        r.render_to(Path("unused.mp4"), 2500, writer=cached, paths=paths)
        self.renderer(ann, 200).render_to(Path("unused.mp4"), 2500, writer=live)
        for a, b in zip(cached.frames, live.frames):
            np.testing.assert_array_equal(a, b)

    def test_rectangular_annotations_keep_later_region_exclusion(self):
        ann = self.annotation()
        for e in ann["elements"]:
            e.pop("contours")
            e.pop("holes")
            e["reveal"].pop("phase")
        r = self.renderer(ann)
        self.assertFalse(r.subject_mode)
        self.assertFalse(r._allowed_mask(ann["elements"][0], ann["elements"][1:]).any())

    def test_empty_ink_phase_preserves_duration(self):
        ann = self.annotation()
        r = self.renderer(ann)
        writer = Frames()
        r.render_to(Path("unused.mp4"), 2500, writer=writer, paths=[[], []])
        self.assertEqual(len(writer.frames), 25)
        self.assertTrue(np.all(writer.frames[9] == 255))

    def test_fractional_frame_events_do_not_accumulate_timing_drift(self):
        for phase in ("ink", "color", "both"):
            with self.subTest(phase=phase):
                ann = self.annotation()
                ann["sceneDurationMs"] = 7500
                ann["elements"] = []
                for index in range(20):
                    e = event(str(index), phase, index * 350)
                    e["reveal"]["durationMs"] = 350
                    ann["elements"].append(e)
                writer = Frames()
                self.renderer(ann).render_to(Path("unused.mp4"), 7500, writer=writer, paths=[[]] * 20)
                self.assertEqual(len(writer.frames), 75)

    def test_quality_check_does_not_flag_outline_as_early_color(self):
        ann = self.annotation()
        r = self.renderer(ann)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "preview.mp4"
            r.render_to(path, 2500)
            check = media.drawing_checks(path, r, ann)
            self.assertEqual(check["decoded_frames"], 25)
            self.assertEqual(check["mask_check"], "PASS")
            self.assertEqual(check["mask_leakage"], [])

    def test_invalid_subject_annotations_are_rejected(self):
        invalid = []
        ann = self.annotation(); ann["elements"][0]["contours"][0][0] = [-1, 10]; invalid.append(ann)
        ann = self.annotation(); ann["elements"][1].pop("contours"); invalid.append(ann)
        ann = self.annotation(); ann["elements"][0]["reveal"]["phase"] = "unknown"; invalid.append(ann)
        ann = self.annotation(); ann["elements"][0]["contours"] = [[[1, 1], [2, 2], [3, 3]]]; invalid.append(ann)
        for ann in invalid:
            with self.subTest(ann=ann), self.assertRaises(ValueError):
                validate_subject_contours(ann)
