"""Editorial intent survives planning, prompts and approval boundaries."""
from tempfile import TemporaryDirectory
import unittest

from cs_board_video import bridge, direction, workflow as w
from cs_board_video.project import WorkflowError
from helpers import fixture, prepare_images


def visual_plan():
    return {'devices': ['metaphor', 'contrast'], 'reason': '用遥控海浪表达控制的徒劳',
            'assets': [{'subject': '人物', 'source': 'user', 'brief': '待补用户人物照片', 'cutout': True},
                       {'subject': '海浪', 'source': 'web', 'brief': '海岸浪花，横向视角，来源明确', 'cutout': False}]}


class DirectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.p = fixture(self.temp.name, count=3)

    def test_optional_for_old_projects_and_rejects_malformed_plans(self):
        self.assertTrue(w.validate_storyboard(self.p)['passed'])
        for key, value in [('devices', []), ('devices', ['unknown']), ('reason', ''), ('assets', None)]:
            plan = visual_plan(); plan[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(WorkflowError):
                direction.validate({'visual_plan': plan})
        for key, value in [('source', 'local-model'), ('cutout', 'yes'), ('brief', ''), ('reference', '')]:
            plan = visual_plan(); plan['assets'][0][key] = value
            with self.subTest(key=key), self.assertRaises(WorkflowError):
                direction.validate({'visual_plan': plan})

    def test_adapt_preserves_plan_and_bad_update_preserves_storyboard(self):
        bridge.plan(self.p, 6)
        segments = self.p.load('narration/plan-request.json')['segments']
        raw = [{'title': '镜头', 'concept': '递物', 'elements': ['人物', '物品', '双手']}
               for _ in segments]
        raw[0]['visual_plan'] = visual_plan()
        bridge.plan(self.p, 6, raw)
        self.assertEqual(self.p.scenes()[0]['visual_plan'], raw[0]['visual_plan'])
        for scene in self.p.scenes()[1:]:
            self.assertNotIn('visual_plan', scene)
        old = self.p.hash('narration/storyboard.json')
        raw[0]['visual_plan']['assets'][0]['cutout'] = 'yes'
        with self.assertRaises(WorkflowError):
            bridge.plan(self.p, 6, raw)
        self.assertEqual(old, self.p.hash('narration/storyboard.json'))

    def test_approved_intent_reaches_image_prompt_and_changes_approval_digest(self):
        scenes = self.p.scenes(); scenes[0]['visual_plan'] = visual_plan()
        self.p.save('narration/storyboard.json', {'scenes': scenes})
        prepare_images(self.p)
        bridge.prompts(self.p)
        context = self.p.load('scenes/scene-001/prompt-context.json')
        self.assertEqual(context['visual_plan'], visual_plan())
        prompt = self.p.path('scenes/scene-001/prompt.md').read_text(encoding='utf-8')
        self.assertIn(visual_plan()['reason'], prompt)
        self.assertIn('AI 图像编辑', prompt)
        old = w.board_target(self.p, scenes[0])
        scenes[0]['visual_plan']['assets'][0]['source'] = 'generate'
        self.assertNotEqual(old, w.board_target(self.p, scenes[0]))

    def test_request_includes_source_and_expression_planning(self):
        bridge.plan(self.p, 6)
        request = self.p.load('narration/plan-request.json')
        self.assertIn('visual_plan', request['prompt'])
        self.assertIn('metaphor', request['prompt'])
        self.assertIn('不安装或调用本地抠图模型', request['prompt'])
        self.assertNotIn('禁止加入原文没有的童年', request['prompt'])


if __name__ == '__main__':
    unittest.main()
