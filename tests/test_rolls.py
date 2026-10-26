"""Optional narrative coverage, exact cutbacks, inset composition and invalidation."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from cs_board_video import bridge, media, rolls, workflow as w
from cs_board_video.project import WorkflowError
from helpers import fixture, prepare_images, prepare_audio, prepare_plans, approve


def board(p):
    scenes = p.scenes()
    specs = [
        {'type':'a','mode':'draw','reason':'建立人物与场景'},
        {'type':'b','mode':'hold','a_scene':'scene-001','reason':'展示具体物品'},
        {'type':'a','mode':'return','a_scene':'scene-001','reason':'返回主叙事'},
        {'type':'b','mode':'draw','layout':'inset','box':[.55,.05,.4,.4],
         'a_scene':'scene-001','reason':'主场景中补充细节'},
        {'type':'a','mode':'return','a_scene':'scene-001','reason':'继续主线'}]
    for scene, spec in zip(scenes,specs):
        scene['roll'] = spec
    p.save('narration/storyboard.json',{'scenes':scenes})
    return p


class RollTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_validation_is_optional_and_rejects_invalid_references_and_geometry(self):
        p = fixture(self.temp.name,count=6)
        self.assertTrue(w.validate_storyboard(p)['passed'])
        board(p)
        self.assertTrue(w.validate_storyboard(p)['passed'])
        original = p.scenes()
        for bad in (None, {}, {'type':'b','reason':'细节'},
                    {'type':'b','reason':'细节','a_scene':'scene-006'},
                    {'type':'b','reason':'细节','a_scene':'scene-002'},
                    {'type':'b','reason':'细节','a_scene':'scene-001','mode':'return'},
                    {'type':'b','reason':'细节','a_scene':'scene-001','layout':'inset','box':[0,0,1,.5]},
                    {'type':'b','reason':'细节','a_scene':'scene-001','layout':'inset','box':[0,0,float('nan'),.4]},
                    {'type':'a','reason':'','mode':'hold'}):
            scenes = deepcopy(original);scenes[1]['roll'] = bad
            with self.subTest(roll=bad), patch.object(p,'scenes',return_value=scenes):
                with self.assertRaises(WorkflowError):w.validate_storyboard(p)
        with self.assertRaisesRegex(WorkflowError,'白板'):
            rolls.validate(original,'remotion')

    def test_planner_preserves_optional_roles_and_does_not_force_them(self):
        p = fixture(self.temp.name,count=3)
        bridge.plan(p,6)
        prompt = p.load('narration/plan-request.json')['prompt']
        self.assertIn('不强制每段使用',prompt)
        texts = [s['narration'] for s in p.scenes()]
        raw = [{'title':'镜头','concept':'递物','text':text,'elements':['人物','物品']} for text in texts]
        raw[0]['roll'] = {'type':'a','reason':'主场景'}
        raw[1]['roll'] = {'type':'b','mode':'hold','a_scene':'scene-001','reason':'物品特写'}
        bridge.plan(p,6,raw)
        self.assertEqual(p.scenes()[1]['roll'],raw[1]['roll'])
        self.assertNotIn('roll',p.scenes()[2])
        before = p.hash('narration/storyboard.json')
        raw[1]['roll']['a_scene'] = 'scene-999'
        with self.assertRaises(WorkflowError):bridge.plan(p,6,raw)
        self.assertEqual(before,p.hash('narration/storyboard.json'))

    def prepared(self):
        p = prepare_images(board(fixture(self.temp.name,count=6)))
        bridge.prompts(p)
        for scene in p.scenes():
            sid = scene['scene_id']
            if rolls.settings(scene)['mode']=='return':
                p.path(f'scenes/{sid}/image.png').unlink()
                p.path(f'scenes/{sid}/image-metadata.json').unlink()
                continue
            if rolls.settings(scene)['type']=='b':
                im = np.full((180,320,3),(70,130,190),np.uint8)
                cv2.circle(im,(160,90),45,(25,25,25),3)
                cv2.imencode('.png',im)[1].tofile(str(p.path(f'scenes/{sid}/image.png')))
            w.review_image(p,sid,w.image_target(p,sid),'测试素材内容匹配、颜色有明确区别、可描线')
        w.validate_images(p)
        prepare_plans(prepare_audio(p))
        return p

    def test_return_reuses_assets_and_full_pipeline_keeps_audio_and_gates(self):
        p = self.prepared()
        self.assertFalse(p.load('scenes/scene-003/prompt-context.json')['generation_required'])
        self.assertEqual(p.load('scenes/scene-003/annotation.json')['elements'],[])
        self.assertIn('B-roll',p.path('scenes/scene-002/prompt.md').read_text(encoding='utf-8'))
        self.assertEqual(len(w.render(p,True,size=[160,90])['rendered']),6)
        expected = rolls.completed_frame(p,'scene-001')
        cap = cv2.VideoCapture(str(p.path('scenes/scene-003/preview.mp4')))
        ok,first = cap.read();cap.release()
        self.assertTrue(ok)
        self.assertLess(float(cv2.absdiff(first,cv2.resize(expected,(160,90))).mean()),6)
        cap = cv2.VideoCapture(str(p.path('scenes/scene-004/preview.mp4')))
        cap.set(cv2.CAP_PROP_POS_FRAMES,18);ok,frame=cap.read();cap.release()
        self.assertTrue(ok)
        self.assertLess(float(cv2.absdiff(frame[:,:70],cv2.resize(expected,(160,90))[:,:70]).mean()),6)
        self.assertGreater(float(cv2.absdiff(frame[8:35,95:140],cv2.resize(expected,(160,90))[8:35,95:140]).mean()),20)
        w.compose(p,True)
        self.assertTrue(p.load('reports/preview-validation.json')['passed'])
        with self.assertRaises(WorkflowError):w.render(p,False)

        approve(p,'preview')  # isolated test fixture only
        self.assertEqual(len(w.render(p,False)['rendered']),6)
        w.compose(p,False)
        self.assertTrue(w.validate_final(p)['passed'])
        self.assertEqual(w.render(p,True,size=[160,90])['rendered'],[])
        old = [w.scene_inputs(p,s['scene_id']) for s in p.scenes()]
        annotation = p.load('scenes/scene-001/annotation.json')
        annotation['elements'][0]['reveal']['durationMs'] -= 50
        p.save('scenes/scene-001/annotation.json',annotation)
        new = [w.scene_inputs(p,s['scene_id']) for s in p.scenes()]
        self.assertTrue(all(a!=b for a,b in zip(old[:5],new[:5])))
        self.assertEqual(old[5],new[5])
        with self.assertRaises(WorkflowError):w.render(p,False)

    def test_cli_image_operations_and_annotation_preview_support_return_without_image(self):
        from cs_board_video.cli import dispatch, parser
        p = self.prepared()
        for action in ('fit','key-text'):
            args=parser().parse_args(['images',action,'--project',str(p.root),'--scene','scene-003'])
            result=dispatch(p,args)
            self.assertEqual(result['changed'],[])
            self.assertEqual(result['reused'],['scene-003'])
        args=parser().parse_args(['annotation','preview','--project',str(p.root),'--scene','scene-003'])
        result=dispatch(p,args)
        self.assertEqual(result['scenes'],['scene-003'])
        self.assertTrue(p.path('scenes/scene-003/annotation-preview.png').is_file())

    def test_inset_hold_and_layered_a_completed_state(self):
        p = self.prepared()
        # Direct renderer integration, without altering production approval records.
        scenes = p.scenes();scenes[3]['roll']['mode']='hold'
        p.save('narration/storyboard.json',{'scenes':scenes})
        width,height=320,180
        bg=np.full((height,width,4),(160,130,90,255),np.uint8)
        fg=np.zeros_like(bg);fg[40:150,100:200]=(40,170,210,255)
        for name,pixels in [('back',bg),('front',fg)]:
            cv2.imencode('.png',pixels)[1].tofile(str(p.path(f'scenes/scene-001/{name}.png')))
        ann={'canvas':{'width':width,'height':height},'sceneDurationMs':2000,
             'layers':[{'id':k,'image':f'{k}.png'} for k in ('back','front')],
             'elements':[{'id':k,'layer_id':k,'region':{'x':0,'y':0,'width':width,'height':height},
                         'reveal':{'startMs':i*700,'durationMs':700}} for i,k in enumerate(('back','front'))]}
        p.save('scenes/scene-001/annotation.json',ann)
        expected=bg[:,:,:3].copy();expected[40:150,100:200]=fg[40:150,100:200,:3]
        np.testing.assert_array_equal(rolls.completed_frame(p,'scene-001'),expected)
        static_ann={'canvas':{'width':320,'height':180},'sceneDurationMs':2000,'elements':[]}
        _,quality=media.render_scene(p,'scene-004',static_ann,'test',[160,90])
        self.assertTrue(quality['passed'])
        self.assertTrue(quality['intentional_hold'])
        a=w.scene_inputs(p,'scene-003')
        fg[55,120]=(80,80,80,255)
        cv2.imencode('.png',fg)[1].tofile(str(p.path('scenes/scene-001/front.png')))
        self.assertNotEqual(a,w.scene_inputs(p,'scene-003'))

    def test_return_to_text_only_a_reuses_blank_background_and_finished_text(self):
        from cs_board_video import typography
        from test_typography import item
        p = fixture(self.temp.name,count=2)
        scenes = p.scenes()
        scenes[0].update(visual_mode='text_only',visual_text=[item('核心观点')],
                         roll={'type':'a','mode':'hold','reason':'概念主镜头'})
        scenes[1]['roll']={'type':'a','mode':'return','a_scene':'scene-001','reason':'返回概念页'}
        p.save('narration/storyboard.json',{'scenes':scenes})
        typography.choose_font(p,'tiejili');typography.sample(p,'scene-001')
        approve(p,'typography')
        prepare_images(p)
        image=np.full((180,320,3),255,np.uint8)
        cv2.imencode('.png',image)[1].tofile(str(p.path('scenes/scene-001/image.png')))
        p.path('scenes/scene-002/image.png').unlink()
        p.path('scenes/scene-002/image-metadata.json').unlink()
        w.review_image(p,'scene-001',w.image_target(p,'scene-001'),'纯白背景，文字由本地排版产生')
        self.assertTrue(w.validate_images(p)['passed'])
        prepare_plans(prepare_audio(p))
        self.assertEqual(len(w.render(p,True,size=[320,180])['rendered']),2)
        expected=rolls.completed_frame(p,'scene-001')
        self.assertGreater(len(np.unique(expected.reshape(-1,3),axis=0)),5)
        cap=cv2.VideoCapture(str(p.path('scenes/scene-002/preview.mp4')))
        ok,first=cap.read();cap.release()
        self.assertTrue(ok)
        self.assertLess(float(cv2.absdiff(first,expected).mean()),6)

    def test_cutback_and_inset_preserve_actual_tail_without_unrevealed_source_content(self):
        p=board(fixture(self.temp.name,count=3))
        scenes=p.scenes();scenes[1]['roll']['layout']='inset'
        p.save('narration/storyboard.json',{'scenes':scenes})
        prepare_images(p)
        source=np.full((180,320,3),255,np.uint8)
        cv2.circle(source,(60,80),25,(30,30,30),2)
        source[110:150,240:270]=0  # Deliberately outside the authored drawing region.
        cv2.imencode('.png',source)[1].tofile(str(p.path('scenes/scene-001/image.png')))
        w.review_image(p,'scene-001',w.image_target(p,'scene-001'),'测试图含一个不安排绘制的右下小物件')
        w.validate_images(p);prepare_plans(prepare_audio(p))
        ann=p.load('scenes/scene-001/annotation.json')
        ann['elements']=ann['elements'][:1]
        ann['elements'][0]['reveal'].update(startMs=0,durationMs=1200)
        p.save('scenes/scene-001/annotation.json',ann)
        w.annotation_validate(p,'scene-001',ann)
        w.render(p,True,size=[320,180])
        def frame(sid,last=False):
            cap=cv2.VideoCapture(str(p.path(f'scenes/{sid}/preview.mp4')))
            if last:cap.set(cv2.CAP_PROP_POS_FRAMES,cap.get(cv2.CAP_PROP_FRAME_COUNT)-1)
            ok,value=cap.read();cap.release();self.assertTrue(ok);return value
        tail=frame('scene-001',True)
        returned=frame('scene-003')
        inset=frame('scene-002')
        self.assertLess(float(cv2.absdiff(tail,returned).mean()),3)
        self.assertGreater(float(returned[115:145,245:265].mean()),200)
        self.assertGreater(float(inset[115:145,245:265].mean()),200)
        expected=rolls.completed_frame(p,'scene-001')
        p.path('render/cache/scene-001-completed.png').unlink()
        replay=rolls.completed_frame(p,'scene-001')
        np.testing.assert_array_equal(replay,expected)
        ann['elements'][0]['region']['width']=320
        p.save('scenes/scene-001/annotation.json',ann)
        refreshed=rolls.completed_frame(p,'scene-001')
        self.assertLess(float(refreshed[115:145,245:265].mean()),5)


if __name__ == '__main__':
    unittest.main()
