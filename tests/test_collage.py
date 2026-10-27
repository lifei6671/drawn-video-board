"""Collage's independent timeline, approval and cache contracts."""
from copy import deepcopy
from pathlib import Path
import os
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

from cs_board_video import collage, cli
from cs_board_video.project import Project, WorkflowError, initialize, file_hash, validate_config


class CollageTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        script = root / 'source.txt'
        script.write_text('等待。寻找答案。', encoding='utf-8')
        self.p = initialize(root/'content', 'test', script, {
            'composition_type':'collage', 'render_engine':'remotion', 'width':320, 'height':180})
        self.p.path('audio/test.wav').write_bytes(b'test-audio')
        self.p.path('style/font.ttf').write_bytes(b'test-font')
        Image.new('RGBA', (100,100), (200,180,140,255)).save(self.p.path('style/paper.png'))
        self.plan = {'schema_version':1, 'duration_ms':2000, 'audio':'audio/test.wav', 'font':'style/font.ttf',
            'alignment':{'source':'test fixture', 'evidence':'synthetic times', 'audio_sha256':file_hash(self.p.path('audio/test.wav'))},
            'assets':{'paper':{'path':'style/paper.png','description':'paper','source':'test'}}, 'background':'paper',
            'beats':[{'id':'wait','start_ms':0,'end_ms':1000,'text':'等待。','visual_goal':'等待'},
                     {'id':'answer','start_ms':1000,'end_ms':2000,'text':'寻找答案。','visual_goal':'答案'}],
            'groups':[{'id':'first','start_ms':0,'end_ms':1500,'exit':{'type':'fade','duration_ms':500}},
                      {'id':'second','start_ms':1000,'end_ms':2000,'enter':{'type':'fade','duration_ms':500}}],
            'elements':[{'id':'clock','kind':'image','asset':'paper','start_ms':0,'end_ms':1500,
                         'group':'first','width':100,'height':100,'z':2,'motion':{'type':'sway'}},
                        {'id':'answer','kind':'text','text':'答案','anchor':'answer','end_ms':2000,
                         'group':'second','width':120,'height':60,'z':1,'enter':{'type':'pop','duration_ms':200}}]}
        for name, value in [('duration',2),('probe',{'streams':[{'codec_type':'audio'}]})]:
            mocked = patch.object(collage.media, name, return_value=value)
            mocked.start()
            self.addCleanup(mocked.stop)

    def compile(self):
        return collage.compile_plan(self.p,self.plan)

    def test_request_works_before_assets_or_audio_exist(self):
        self.p.path('audio/test.wav').unlink()
        self.p.path('style/paper.png').unlink()
        args = cli.parser().parse_args(['collage', 'request', '--project', str(self.p.root)])
        result = cli.dispatch(self.p, args)
        request = self.p.load(result['request'])
        self.assertEqual(request['narration'], '等待。寻找答案。')
        self.assertIn('visual_plan', request['prompt'])
        self.assertFalse(self.p.path(collage.PLAN).exists())

    def test_expression_metadata_export_digest_and_failed_import(self):
        from test_direction import visual_plan
        self.plan['beats'][0]['visual_plan'] = visual_plan()
        before = self.save_approved_plan()
        result = collage.dispatch(self.p, SimpleNamespace(command='collage', action='prompts'))
        self.assertEqual(result['beats'][0]['visual_plan'], visual_plan())
        self.assertEqual(result, self.p.load('render/collage-assets.json'))
        self.plan['beats'][0]['visual_plan']['reason'] = '用时钟表达等待'
        self.assertNotEqual(before, self.compile()[2])
        saved = self.p.load(collage.PLAN)
        self.plan['beats'][0]['visual_plan']['assets'][0]['source'] = 'unknown'
        self.p.save('bad.json', self.plan)
        with self.assertRaises(WorkflowError):
            collage.dispatch(self.p, SimpleNamespace(command='collage', action='import', file=self.p.path('bad.json')))
        self.assertEqual(saved, self.p.load(collage.PLAN))

    def save_approved_plan(self):
        inputs = self.compile()[2]
        self.p.save(collage.PLAN,self.plan)
        self.p.approvals['collage']={'digest':inputs,'user_message':'isolated test fixture'}
        return inputs

    def save_preview(self):
        inputs = self.save_approved_plan()
        self.p.path('previews/full-preview.mp4').write_bytes(b'synthetic video')
        self.p.save('previews/review.json',{'passed':True})
        self.p.data['collage_preview_size']=[320,180]
        self.p.receipt('collage:preview',collage.render_inputs(self.p,inputs,[320,180],True),
                       ['previews/full-preview.mp4','previews/review.json'])
        return collage.preview_target(self.p)

    def test_overlapping_elements_groups_and_absolute_anchor(self):
        props, _, _ = self.compile()
        self.assertEqual(props['totalDurationFrames'],60)
        self.assertEqual([x['id'] for x in props['elements']],['answer','clock'])
        self.assertEqual(props['elements'][0]['startFrame'],30)
        self.assertEqual(props['elements'][1]['endFrame'],45)
        self.assertEqual(props['background'],'style/paper.png')

    def test_missing_original_text_or_reordered_beats_rejected(self):
        self.plan['beats'][0]['text']='删掉原话'
        with self.assertRaisesRegex(WorkflowError,'完整覆盖原文'): self.compile()

    def test_audio_edit_requires_alignment_refresh(self):
        self.p.path('audio/test.wav').write_bytes(b'changed')
        with self.assertRaisesRegex(WorkflowError,'重新对齐'): self.compile()

    def test_real_audio_duration_required(self):
        with patch.object(collage.media,'duration',return_value=3):
            with self.assertRaisesRegex(WorkflowError,'真实音频'): self.compile()

    def test_group_bounds_and_same_frame_keyframes_rejected(self):
        self.plan['elements'][0]['end_ms']=1600
        with self.assertRaisesRegex(WorkflowError,'所属组'): self.compile()
        self.plan['elements'][0]['end_ms']=1500
        self.plan['elements'][0]['keyframes']={'x':[{'at_ms':0,'value':0},{'at_ms':1,'value':100}]}
        with self.assertRaisesRegex(WorkflowError,'同一帧'): self.compile()

    def test_effect_timing_and_nan_rejected(self):
        self.plan['elements'][1]['enter']['duration_ms']=1100
        with self.assertRaisesRegex(WorkflowError,'动画时长'): self.compile()
        self.plan['elements'][1]['enter']['duration_ms']=200
        self.plan['elements'][1]['x']=float('nan')
        with self.assertRaisesRegex(WorkflowError,'有限数字'): self.compile()

    def test_asset_path_confined_to_project(self):
        self.plan['assets']['paper']['path']='../escape.png'
        with self.assertRaises(WorkflowError): self.compile()

    def test_inputs_bind_font_image_script_and_subtitle_setting(self):
        old = self.compile()[2]
        self.p.path('style/font.ttf').write_bytes(b'changed font')
        self.assertNotEqual(old,self.compile()[2])
        old = self.compile()[2]
        self.p.data['config']['subtitles']=False
        props,_,target=self.compile()
        self.assertNotEqual(old,target)
        self.assertEqual(props['captions'],[])
        old = target
        Image.new('RGB',(100,100),'red').save(self.p.path('style/paper.png'))
        self.assertNotEqual(old,self.compile()[2])

    def test_final_needs_current_preview_approval_before_external_render(self):
        self.save_preview()
        with patch.object(collage.media,'run') as run:
            with self.assertRaisesRegex(WorkflowError,'preview'): collage.render(self.p,False)
            run.assert_not_called()

    def test_changed_preview_output_or_engine_invalidates_approval(self):
        target = self.save_preview()
        self.p.approvals['preview']={'digest':target}
        with patch.object(collage,'engine_hash',return_value='new-engine'):
            with self.assertRaisesRegex(WorkflowError,'失效'): collage.preview_target(self.p)
        self.p.path('previews/full-preview.mp4').write_bytes(b'changed pixels')
        with self.assertRaisesRegex(WorkflowError,'失效'): collage.preview_target(self.p)

    def test_failed_import_preserves_old_plan(self):
        self.save_approved_plan()
        wrong=deepcopy(self.plan)
        wrong['elements'][0]['asset']='missing'
        self.p.save('bad.json',wrong)
        args=SimpleNamespace(command='collage',action='import',file=self.p.path('bad.json'))
        with self.assertRaises(WorkflowError): collage.dispatch(self.p,args)
        self.assertEqual(self.p.load(collage.PLAN),self.plan)

    def test_resume_keeps_portrait_ratio(self):
        self.p.data['config'].update(width=1080,height=1920)
        self.save_approved_plan()
        with patch.object(collage,'render',return_value={}) as render:
            collage.dispatch(self.p,SimpleNamespace(command='resume'))
            render.assert_called_once_with(self.p,True,[1080,1920])

    def test_standard_project_defaults_and_mode_dispatch(self):
        config=dict(self.p.data['config'])
        config.pop('composition_type')
        config['render_engine']='whiteboard'
        config['fps']=10
        validate_config(config)
        self.p.data['config']=config
        self.assertFalse(collage.enabled(self.p))
        with patch.object(cli.w,'status',return_value={'standard':True}) as status:
            self.assertEqual(cli.dispatch(self.p,SimpleNamespace(command='status')),{'standard':True})
            status.assert_called_once_with(self.p)

    def test_draw_commands_rejected_without_mutating_collage(self):
        with self.assertRaisesRegex(WorkflowError,'手绘命令'):
            cli.dispatch(self.p,SimpleNamespace(command='annotation',action='build'))

    def test_revision_revokes_approval_on_disk(self):
        self.save_approved_plan()
        self.p.persist()
        collage.dispatch(self.p,SimpleNamespace(command='revise',stage='collage',scene=None,feedback='改变转场'))
        reloaded=Project(self.p.root)
        self.assertNotIn('collage',reloaded.approvals)
        self.assertEqual(reloaded.data['revision']['feedback'],'改变转场')

    @unittest.skipUnless(os.name == 'nt', 'Windows path normalization')
    def test_windows_paths_become_browser_urls(self):
        self.plan['audio']='audio\\test.wav'
        self.plan['font']='style\\font.ttf'
        self.plan['assets']['paper']['path']='style\\paper.png'
        props,files,_=self.compile()
        self.assertEqual(props['font'],'style/font.ttf')
        self.assertEqual(props['background'],'style/paper.png')
        self.assertIn('audio/test.wav',files)


if __name__ == '__main__':
    unittest.main()
