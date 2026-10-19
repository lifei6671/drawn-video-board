import unittest
from types import SimpleNamespace

from scripts.render_stream_whiteboard import (
    RegionStreamRenderer,
    _allocate_weighted_frames,
    _stroke_turn_score,
    _stroke_weight,
)


class WhiteboardTimingTests(unittest.TestCase):
    def test_turning_stroke_gets_more_complexity_than_straight_stroke(self):
        straight = [(0, 0), (10, 0), (20, 0)]
        turning = [(0, 0), (10, 0), (10, 10)]

        self.assertAlmostEqual(_stroke_turn_score(straight), 0.0)
        self.assertGreater(_stroke_turn_score(turning), 0.0)
        self.assertGreater(_stroke_weight(turning, 0.75), _stroke_weight(straight, 0.75))

    def test_weighted_frame_allocation_preserves_total(self):
        allocation = _allocate_weighted_frames([1.0, 2.0, 4.0], 17)

        self.assertEqual(sum(allocation), 17)
        self.assertTrue(all(value >= 1 for value in allocation))

    def test_stroke_plan_preserves_order_and_total_frames(self):
        renderer = RegionStreamRenderer.__new__(RegionStreamRenderer)
        renderer.cfg = SimpleNamespace(
            pause_mode="heavy",
            stroke_pause_ratio_heavy=0.10,
            stroke_pause_ratio_light=0.04,
            stroke_pause_max_frames=3,
            stroke_turn_weight=0.75,
        )
        strokes = [
            [(0, 0), (10, 0)],
            [(30, 0), (30, 10)],
            [(60, 0), (70, 10)],
        ]

        plans = renderer._plan_stroke_groups(strokes, 30)
        planned_strokes = [stroke for plan in plans for stroke in plan.strokes]

        self.assertEqual(planned_strokes, strokes)
        self.assertEqual(
            sum(plan.draw_frames + plan.pause_frames for plan in plans),
            30,
        )
        self.assertGreater(sum(plan.pause_frames for plan in plans), 0)

    def test_nearby_strokes_stay_in_one_object_group(self):
        renderer = RegionStreamRenderer.__new__(RegionStreamRenderer)
        renderer.cfg = SimpleNamespace(brush_radius=40, stroke_turn_weight=0.75)
        strokes = [
            [(0, 0), (20, 0)],
            [(18, 2), (28, 2)],
            [(120, 80), (140, 80)],
        ]

        groups = renderer._group_strokes_for_budget(strokes, 3)

        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0], strokes[:2])
        self.assertEqual(groups[1], strokes[2:])


if __name__ == "__main__":
    unittest.main()
