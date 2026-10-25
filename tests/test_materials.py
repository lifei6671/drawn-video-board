"""Material exports stay independent, transparent and usable by text layout."""
import json
from pathlib import Path
import tempfile
import unittest
from xml.etree.ElementTree import fromstring

import numpy as np
from PIL import Image

from cs_board_video import materials as m, typography as t
from cs_board_video.cli import dispatch, parser
from cs_board_video.project import WorkflowError, file_hash
from helpers import fixture


class MaterialTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.p=fixture(self.temp.name)

    def test_catalog_and_packaged_previews_are_complete(self):
        items=m.catalog();self.assertEqual(len(items),51)
        self.assertEqual(len({i['id'] for i in items}),51)
        self.assertEqual({c:len(m.catalog(c)) for c in ('bubble','emphasis','paper','object','person','animal','scene')},
                         {'bubble':10,'emphasis':5,'paper':5,'object':11,'person':6,'animal':10,'scene':4})
        for item in items:
            self.assertTrue(item['styles']);self.assertIn(item['depth'],('overlay','background','middle','foreground'))
            if item.get('raster'):
                with Image.open(m.ROOT/item['raster']) as png:
                    self.assertEqual(png.mode,'RGBA')
                    self.assertGreaterEqual(min(png.size),1024)
                    alpha=np.asarray(png.getchannel('A'))
                    self.assertEqual(alpha[0,0],0)
                    self.assertGreater((alpha == 0).mean(),.05)
                    self.assertGreater((alpha > 240).mean(),.05)
                continue
            self.assertEqual((m.ROOT/(item['id']+'.svg')).read_text(encoding='utf-8'),m.svg(item))
            for shape in m.shapes(item):
                points=shape.get('points') or [shape['box'][:2],shape['box'][2:]]
                self.assertTrue(all(0 <= x <= 600 and 0 <= y <= 400 for x,y in points), item['id'])
            with Image.open(m.ROOT/(item['id']+'.png')) as png:
                self.assertEqual(png.mode,'RGBA');self.assertEqual(png.size,(600,400))
                alpha=np.asarray(png.getchannel('A'));self.assertEqual(alpha[0,0],0);self.assertGreater(alpha.max(),0)
        self.assertEqual(len(dispatch(None,parser().parse_args(['materials','list','--category','emphasis']))['materials']),5)

    def test_raster_exports_keep_transparency_aspect_ratio_and_identity(self):
        people=dispatch(None,parser().parse_args(['materials','list','--category','person']))['materials']
        self.assertEqual(len(people),6)
        self.assertTrue(all(item['svg'] is None and Path(item['preview']).is_file() for item in people))
        result=dispatch(self.p,parser().parse_args(['materials','export','--project',str(self.p.root),
            '--id','collage-cn-student','--width','400','--height','400','--flip']))
        self.assertEqual(set(result['files']),{'png','json'})
        self.assertIsNone(result['material']['colors'])
        self.assertIsNone(result['material']['character_identity'])
        self.assertEqual(result['material']['direction'],'left')
        self.assertEqual(result['material']['png_sha256'],file_hash(Path(result['files']['png'])))
        normal=np.asarray(m.render(m.select('collage-cn-student'),(400,400)))
        with Image.open(result['files']['png']) as png:
            self.assertEqual(png.size,(400,400))
            self.assertTrue(np.array_equal(np.asarray(png),normal[:,::-1]))
            self.assertFalse(np.asarray(png)[:60,:,3].any())
        self.assertFalse(self.p.data.get('visual_references',{}).get('characters'))
        with self.assertRaises(WorkflowError):m.export(self.p,'collage-cn-student')
        m.export(self.p,'collage-cn-student',replace=True)

    def test_animals_and_scenes_can_be_selected_and_exported_as_separate_layers(self):
        for category,count,depth in [('animal',10,'foreground'),('scene',4,'background')]:
            items=dispatch(None,parser().parse_args(['materials','list','--category',category]))['materials']
            self.assertEqual(len(items),count)
            for item in items:
                self.assertEqual(item['depth'],depth)
                self.assertIn('layered-paper-collage',item['styles'])
                self.assertIsNone(item['svg'])
                result=m.export(self.p,item['id'],size=(900,600))
                self.assertEqual(set(result['files']),{'png','json'})
                self.assertEqual(result['material']['category'],category)
                with Image.open(result['files']['png']) as png:
                    self.assertEqual(png.size,(900,600))
                    self.assertEqual(png.getpixel((0,0))[3],0)
                    self.assertGreater(np.asarray(png.getchannel('A')).max(),240)

    def test_raster_recolor_is_rejected_without_writing(self):
        with self.assertRaisesRegex(WorkflowError,'保留原色'):
            m.export(self.p,'collage-kettle',colors={'accent':'#FF0000'})
        self.assertFalse(self.p.path('materials').exists())
        with self.assertRaisesRegex(WorkflowError,'不提供矢量'):
            m.svg(m.select('collage-kettle'))

    def test_export_colors_flip_size_and_project_snapshot(self):
        result=dispatch(self.p,parser().parse_args(['materials','export','--project',str(self.p.root),'--id','speech-right',
                        '--width','900','--height','600','--paper','#ABCDEF','--ink','#123456','--flip']))
        metadata=result['material'];self.assertEqual(metadata['direction'],'left')
        self.assertIsNone(metadata['character_identity'])
        with Image.open(result['files']['png']) as png:
            self.assertEqual(png.size,(900,600));self.assertEqual(png.getpixel((450,250)),(171,205,239,255))
        svg=Path(result['files']['svg']).read_text(encoding='utf-8')
        self.assertIn('#ABCDEF',svg);self.assertIn('scale(-1 1)',svg);fromstring(svg)
        self.assertEqual(metadata['png_sha256'],file_hash(Path(result['files']['png'])))
        self.assertFalse(self.p.data.get('visual_references',{}).get('characters'))
        original=file_hash(Path(result['files']['png']))
        with self.assertRaises(WorkflowError):m.export(self.p,'speech-right')
        self.assertEqual(original,file_hash(Path(result['files']['png'])))
        m.export(self.p,'speech-right',replace=True)
        self.assertNotEqual(original,file_hash(Path(result['files']['png'])))

    def test_bad_export_inputs_do_not_write_assets(self):
        for name,size,colors in [('missing',(600,400),None),('moon',(0,400),None),('moon',(600,400),{'ink':'red'})]:
            with self.assertRaises(WorkflowError):m.export(self.p,name,size,colors)
        self.assertFalse(self.p.path('materials').exists())

    def test_new_bubbles_work_in_text_layout_and_borderless_has_no_outline(self):
        t.choose_font(self.p,'tiejili')
        for key in ('speech-soft','cloud-hand','shout','sticky-note','torn-note'):
            self.assertIn(key,t.PRESENTATIONS)
            scene={**self.p.scene('scene-001'),'visual_text':[{'text':'先行动','purpose':'行动提示',
                    'presentation':key,'box':[.05,.05,.9,.9],'font_scale':.08}]}
            layers=t.layout(self.p,scene,(600,400))
            self.assertEqual(len(layers[0]['glyphs']),3)
        bubble=np.asarray(t.bubble_image('speech-soft',(600,400),'#FFFFFF','#000000'))
        self.assertTrue(np.all(bubble[bubble[:,:,3]>0,:3]==255))

    def test_frame_centers_remain_transparent_and_accent_is_separate(self):
        for key in ('photo-frame','circle-mark','bracket'):
            self.assertEqual(m.render(m.select(key)).getpixel((300,200))[3],0)
        moon=m.render(m.select('moon'),colors={'accent':'#C93344'})
        self.assertEqual(moon.getpixel((300,50)),(201,51,68,255))
        with Image.open(m.ROOT/'moon.png') as default:
            self.assertNotEqual(default.getpixel((300,50)),moon.getpixel((300,50)))


if __name__=='__main__':unittest.main()
