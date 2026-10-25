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
        items=m.catalog();self.assertEqual(len(items),25)
        self.assertEqual(len({i['id'] for i in items}),25)
        self.assertEqual({c:len(m.catalog(c)) for c in ('bubble','emphasis','paper','object')},
                         {'bubble':10,'emphasis':5,'paper':5,'object':5})
        for item in items:
            self.assertTrue(item['styles']);self.assertIn(item['depth'],('overlay','background','middle','foreground'))
            self.assertEqual((m.ROOT/(item['id']+'.svg')).read_text(encoding='utf-8'),m.svg(item))
            for shape in m.shapes(item):
                points=shape.get('points') or [shape['box'][:2],shape['box'][2:]]
                self.assertTrue(all(0 <= x <= 600 and 0 <= y <= 400 for x,y in points), item['id'])
            with Image.open(m.ROOT/(item['id']+'.png')) as png:
                self.assertEqual(png.mode,'RGBA');self.assertEqual(png.size,(600,400))
                alpha=np.asarray(png.getchannel('A'));self.assertEqual(alpha[0,0],0);self.assertGreater(alpha.max(),0)
        self.assertEqual(len(dispatch(None,parser().parse_args(['materials','list','--category','emphasis']))['materials']),5)

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
