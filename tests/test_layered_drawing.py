"""Real occlusion: complete each layer before drawing the next one."""
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from cs_board_video.bridge import Config, RegionStreamRenderer, load_layer_images
from cs_board_video import media, workflow
from cs_board_video.project import WorkflowError
from test_subject_contours import Frames
from helpers import fixture, prepare_images, prepare_audio, prepare_plans


def assets():
    background = np.full((100,100,4), (160,100,60,255), np.uint8)
    person = np.zeros((100,100,4), np.uint8)
    person[15:90,30:60] = (20,180,210,255)
    person[20:30,30:35,3] = 128
    plant = np.zeros((100,100,4), np.uint8)
    plant[30:85,55:90] = (40,140,30,255)
    plant[45:55,65:75] = 0  # An opening through the foliage must show the wall.
    return dict(background=background, person=person, plant=plant)


def annotation():
    ids = ['background','person','plant']
    return {'canvas': {'width':100,'height':100}, 'sceneDurationMs':3500,
            'layers':[{'id':key,'image':f'layers/{key}.png'} for key in ids],
            'elements':[{'id':key,'layer_id':key,'sequence':index+1,'narrativeRole':key,'subtitle':key,
                         'region':{'x':0,'y':0,'width':100,'height':100},
                         'reveal':{'startMs':index*1000,'durationMs':1000,'phase':'both'}}
                        for index,key in enumerate(ids)]}


def composite(images, keys):
    result = np.full((100,100,3),255,np.float32)
    for key in keys:
        rgba = images[key]
        alpha = rgba[:,:,3:4]/255
        result = rgba[:,:,:3]*alpha + result*(1-alpha)
    return result


class LayeredDrawingTests(unittest.TestCase):
    def renderer(self, ann=None, images=None, size=100):
        images = assets() if images is None else images
        return RegionStreamRenderer(np.zeros((100,100,3),np.uint8), annotation() if ann is None else ann,
                                    Config(fps=10,cap_long_edge=size,canvas_hex='#FFFFFF',pause_mode='off'),
                                    None,True,layer_images=images)

    def test_background_and_person_finish_before_plant_without_white_cutout(self):
        images = assets()
        renderer = self.renderer(images=images)
        writer = Frames()
        renderer.render_to(Path('unused.mp4'),3500,writer=writer)
        self.assertEqual(len(writer.frames),35)
        np.testing.assert_array_equal(writer.frames[9],images['background'][:,:,:3])
        beneath = composite(images,['background','person']).astype(np.uint8)
        np.testing.assert_allclose(writer.frames[19],beneath,atol=1)
        mask = renderer._allowed_mask(annotation()['elements'][2],[])
        unpainted = mask & ~renderer.ink_pixels
        self.assertTrue(unpainted.any())
        np.testing.assert_allclose(writer.frames[24][unpainted],beneath[unpainted],atol=1)
        np.testing.assert_allclose(writer.frames[29],composite(images,list(images)),atol=1)
        np.testing.assert_array_equal(writer.frames[29],writer.frames[-1])
        np.testing.assert_array_equal(writer.frames[-1][48:52,68:72],beneath[48:52,68:72])

    def test_cached_paths_use_each_layers_own_contours(self):
        renderer = self.renderer(size=200)
        ann = annotation()
        paths = []
        for e in ann['elements']:
            renderer.prepare_element(e)
            paths.append(renderer._region_skeleton_strokes(renderer._allowed_mask(e,[])))
        cached, live = Frames(), Frames()
        renderer.render_to(Path('unused.mp4'),3500,writer=cached,paths=paths)
        self.renderer(size=200).render_to(Path('unused.mp4'),3500,writer=live)
        for a,b in zip(cached.frames,live.frames):
            np.testing.assert_array_equal(a,b)

    def test_arbitrary_layer_names_and_four_depths_complete_in_order(self):
        original=assets()
        images=dict(skyline=original['background'],furniture=original['person'],vehicle=original['plant'])
        animal=np.zeros((100,100,4),np.uint8);animal[65:95,15:80]=(100,20,190,128)
        images['animal']=animal
        ann=annotation()
        ann['layers']=[{'id':key,'image':f'layers/{key}.png'} for key in images]
        ann['elements']=[{'id':key,'layer_id':key,'region':{'x':0,'y':0,'width':100,'height':100},
                          'reveal':{'startMs':index*1000,'durationMs':1000}}
                         for index,key in enumerate(images)]
        ann['sceneDurationMs']=4500
        renderer=self.renderer(ann,images);writer=Frames()
        renderer.render_to(Path('unused.mp4'),4500,writer=writer)
        keys=list(images)
        for index in range(4):
            np.testing.assert_allclose(writer.frames[(index+1)*10-1],composite(images,keys[:index+1]),atol=1)

    def test_partial_out_of_order_or_missing_layers_are_rejected(self):
        invalid = []
        ann=annotation();ann['elements'][0]['reveal']['phase']='ink';invalid.append(ann)
        ann=annotation();ann['elements'][1]['layer_id']='plant';invalid.append(ann)
        ann=annotation();ann['elements'][1]['reveal']['startMs']=900;invalid.append(ann)
        ann=annotation();ann['elements'][1]['reveal']['protectedRegions']=[{'x':0,'y':0,'width':1,'height':1}];invalid.append(ann)
        ann=annotation();ann['elements'][0]['reveal']['durationMs']=10;invalid.append(ann)
        for ann in invalid:
            with self.subTest(annotation=ann), self.assertRaises(ValueError):self.renderer(ann)
        with self.assertRaisesRegex(ValueError,'独立图层'):
            RegionStreamRenderer(np.zeros((100,100,3),np.uint8),annotation(),Config(),None,True)

    def write_assets(self, directory, images=None):
        images = assets() if images is None else images
        folder=Path(directory)/'layers';folder.mkdir(parents=True,exist_ok=True)
        for key,image in images.items():cv2.imencode('.png',image)[1].tofile(str(folder/f'{key}.png'))

    def test_layer_loader_validates_alpha_size_missing_files_and_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_assets(tmp)
            loaded=load_layer_images(annotation(),Path(tmp))
            np.testing.assert_array_equal(loaded['plant'],assets()['plant'])
            for name in ('../outside.png',str(Path(tmp).resolve()/'absolute.png')):
                ann=annotation();ann['layers'][1]['image']=name
                with self.assertRaisesRegex(ValueError,'相对路径'):load_layer_images(ann,Path(tmp))
            broken=assets();broken['plant'][:,:]=255;self.write_assets(tmp,broken)
            with self.assertRaisesRegex(ValueError,'透明区域'):load_layer_images(annotation(),Path(tmp))
            self.write_assets(tmp,assets());(Path(tmp)/'layers/plant.png').unlink()
            with self.assertRaisesRegex(ValueError,'缺失'):load_layer_images(annotation(),Path(tmp))

    def test_real_project_layer_edits_invalidate_drawing_cache_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            project=prepare_plans(prepare_audio(prepare_images(fixture(tmp,width=100,height=100))))
            ann=project.load('scenes/scene-001/annotation.json')
            ann['layers']=annotation()['layers'][:2]
            for e,key in zip(ann['elements'],('background','person')):e['layer_id']=key
            self.write_assets(project.path('scenes/scene-001'))
            project.save('scenes/scene-001/annotation.json',ann)
            before=workflow.scene_inputs(project,'scene-001')
            media.native_renderer(project,'scene-001',ann)
            images=assets();images['person'][20,40,:3]=[200,30,40]
            self.write_assets(project.path('scenes/scene-001'),images)
            self.assertNotEqual(before,workflow.scene_inputs(project,'scene-001'))
            (project.path('scenes/scene-001/layers/person.png')).unlink()
            with self.assertRaises(WorkflowError):workflow.scene_inputs(project,'scene-001')

    def test_quality_check_accepts_visible_background_and_detects_early_foreground(self):
        with tempfile.TemporaryDirectory() as tmp:
            renderer=self.renderer();writer=Frames()
            renderer.render_to(Path('unused.mp4'),3500,writer=writer)
            path=Path(tmp)/'clip.mp4'
            def encode(frames):
                output=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'mp4v'),10,(100,100))
                for frame in frames:output.write(frame)
                output.release()
            encode(writer.frames)
            check=media.drawing_checks(path,renderer,annotation())
            self.assertTrue(check['passed'],check)
            writer.frames[15][30:85,65:90]=[40,140,30]
            encode(writer.frames)
            check=media.drawing_checks(path,renderer,annotation())
            self.assertEqual(check['mask_check'],'FAIL')
            self.assertTrue(check['mask_leakage'])


if __name__=='__main__':unittest.main()
