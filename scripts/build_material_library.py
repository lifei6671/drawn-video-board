"""Regenerate the original vector material library and default PNG/SVG previews."""
from pathlib import Path
import json
import math
import random

from cs_board_video import materials as m

ROOT = Path(__file__).resolve().parents[1]
BUBBLES = ROOT/'cs_board_video/assets/bubbles'


def poly(points, fill='paper', stroke='ink', width=3, opacity=1):
    return dict(type='polygon',points=points,fill=fill,stroke=stroke,width=width,opacity=opacity)


def line(points, stroke='ink', width=4, opacity=1):
    return dict(type='line',points=points,stroke=stroke,width=width,opacity=opacity)


def ellipse(box, fill='paper', stroke='ink', width=3, opacity=1):
    return dict(type='ellipse',box=box,fill=fill,stroke=stroke,width=width,opacity=opacity)


def rect(box, fill='paper', stroke='none', width=3, opacity=1):
    return dict(type='rect',box=box,fill=fill,stroke=stroke,width=width,opacity=opacity)


def main():
    data=json.loads((BUBBLES/'templates.json').read_text(encoding='utf-8'))
    data['speech-soft']={**data['speech-right'],'stroke':False}
    cloud=[]
    for i in range(100):
        angle=i*2*math.pi/100;wave=1+.055*math.cos(angle*9)
        cloud.append([round(.5+.47*wave*math.cos(angle),5),round(.42+.36*wave*math.sin(angle),5)])
    data['cloud-hand']={'outline':cloud,'dots':[[.24,.87,.025,.03],[.19,.95,.013,.017]],'text_box':[.16,.20,.68,.40]}
    shout=[]
    for i in range(36):
        a=i*2*math.pi/36;r=(1 if i%2==0 else .78)*(1+.035*math.sin(i*2.4))
        shout.append([round(.5+.47*r*math.cos(a),5),round(.46+.43*r*math.sin(a),5)])
    data['shout']={'outline':shout,'text_box':[.22,.24,.56,.40]}
    data['sticky-note']={'outline':[[.08,.04],[.96,.08],[.91,.80],[.75,.96],[.05,.91]],'text_box':[.17,.17,.63,.55]}
    rough=[[.04,.06],[.15,.09],[.27,.04],[.39,.08],[.51,.035],[.65,.08],[.79,.04],[.96,.075],[.94,.30],[.97,.51],[.94,.73],[.96,.94],[.81,.90],[.68,.96],[.52,.91],[.37,.95],[.21,.90],[.035,.94],[.06,.72],[.03,.50],[.06,.28]]
    data['torn-note']={'outline':rough,'text_box':[.15,.20,.70,.60]}
    (BUBBLES/'templates.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    items=[]
    def add(key,name,category,geometry=None,styles=None,direction='none',depth='overlay',text_box=None,bubble=None):
        item={'id':key,'name':name,'category':category,'styles':styles or ['line','comic','paper-collage'],
              'direction':direction,'depth':depth,'text_box':text_box,'view_box':[600,400],
              'description':name+'，独立透明素材，可改色、缩放或水平翻转。', 'origin':'original-project-vector'}
        if bubble:item['bubble']=bubble
        else:item['shapes']=geometry
        items.append(item)
    names={'speech-left':'左向对话','speech-right':'右向对话','thought':'思考气泡','burst':'强调气泡','caption':'说明框',
           'speech-soft':'无边框对话','cloud-hand':'手绘云朵气泡','shout':'喊话框','sticky-note':'便签','torn-note':'撕纸条'}
    for key,name in names.items():
        add(key,name,'bubble',direction='left' if key in ('speech-left','thought','cloud-hand') else 'right' if key in ('speech-right','speech-soft') else 'none',
            text_box=data[key]['text_box'],bubble=key)
    oval=[[300+245*math.cos(i*2*math.pi/90),200+133*math.sin(i*2*math.pi/90)+3*math.sin(i)] for i in range(91)]
    add('circle-mark','手绘圈线','emphasis',[line(oval,width=5),line([[55,208],[75,234],[120,255]],width=2)])
    add('underline','双道下划线','emphasis',[line([[45,210],[150,204],[250,211],[370,205],[555,212]],width=7),line([[75,235],[220,231],[420,237],[520,232]],width=3)])
    add('highlighter','荧光笔底色','emphasis',[poly([[50,154],[552,143],[541,246],[39,251]],'accent','none',opacity=.60),poly([[63,159],[562,155],[551,233],[55,242]],'accent','none',opacity=.22)])
    arrow=[[65+i*4.7,290-150*math.sin(i/100*math.pi*.65)] for i in range(101)]
    add('curved-arrow','弧形箭头','emphasis',[line(arrow,width=7),poly([[482,108],[546,147],[490,183]],'ink','none')],direction='right')
    add('bracket','重点括号','emphasis',[line([[120,65],[75,65],[75,335],[120,335]],width=6),line([[480,65],[525,65],[525,335],[480,335]],width=6)])
    rng=random.Random(20261025)
    texture=[rect([12,12,588,388])]
    for _ in range(115):
        x,y=rng.uniform(20,575),rng.uniform(20,380)
        texture.append(line([[x,y],[min(582,x+rng.uniform(3,13)),y+rng.uniform(-2,2)]],width=1,opacity=.10))
    add('paper-fiber','浅纤维纸','paper',texture,styles=['paper-collage','line'],depth='background')
    news=[rect([12,12,588,388]),line([[38,55],[562,55]],width=4),rect([38,25,220,38],'ink',opacity=.65)]
    for col in range(3):
        for row in range(24):
            x=38+col*180;y=80+row*12
            news.append(line([[x,y],[x+rng.uniform(105,155),y]],width=2,opacity=.24))
    add('paper-newsprint','旧报纸纹理','paper',news,styles=['paper-collage'],depth='background')
    add('torn-paper','撕边纸张','paper',[poly([[x*600,y*400] for x,y in rough],'paper','none')],styles=['paper-collage'],depth='middle')
    add('photo-frame','照片白边','paper',[rect([25,20,575,55]),rect([25,55,65,330]),rect([535,55,575,330]),rect([25,330,575,385])],styles=['paper-collage'],depth='foreground')
    add('tape-strip','半透明胶带','paper',[poly([[55,145],[75,135],[90,144],[108,135],[545,143],[534,164],[546,184],[533,204],[542,238],[60,247],[70,226],[56,205],[68,183]],'accent','none',opacity=.66)],styles=['paper-collage'],depth='foreground')
    moon=[ellipse([130,30,470,370],'accent','none')]
    for box in ([180,85,235,140],[325,72,380,127],[315,240,400,325],[215,215,246,246],[267,153,340,226],[157,179,189,211]):
        moon.append(ellipse(box,'ink','none',opacity=.12))
    add('moon','月亮剪贴','object',moon,styles=['paper-collage','comic'],depth='background')
    outline=[]
    for i in range(120):
        a=i*2*math.pi/120;r=1+.08*math.sin(a*7)
        outline.append([300+245*r*math.cos(a),210+95*r*math.sin(a)])
    add('cloud','云朵剪贴','object',[poly(outline)],depth='middle')
    add('window-frame','窗框','object',[rect([75,30,525,58],'ink'),rect([75,342,525,370],'ink'),rect([75,58,100,342],'ink'),rect([500,58,525,342],'ink'),rect([289,58,311,342],'ink'),rect([100,193,500,211],'ink')],direction='none',depth='foreground')
    leaves=[line([[80,350],[190,285],[310,210],[425,115],[515,45]],width=7)]
    for x,y in [(180,290),(275,235),(370,160),(445,115)]:
        leaves.extend([poly([[x,y],[x-85,y-20],[x-105,y-100],[x-25,y-80]],'accent','ink',2),poly([[x,y],[x+90,y+32],[x+135,y-10],[x+55,y-38]],'accent','ink',2)])
    add('leafy-branch','前景枝叶','object',leaves,direction='right',depth='foreground')
    silhouette=[ellipse([268,28,332,92],'ink','none'),poly([[275,98],[325,98],[354,194],[345,260],[255,260],[246,194]],'ink','none'),poly([[258,240],[291,240],[286,362],[239,368]],'ink','none'),poly([[307,240],[340,240],[360,365],[318,365]],'ink','none'),line([[263,116],[223,199],[250,238]],width=22),line([[337,116],[380,195],[352,230]],width=22)]
    add('person-silhouette','通用人物剪影','object',silhouette,depth='foreground')
    m.ROOT.mkdir(parents=True,exist_ok=True)
    (m.ROOT/'catalog.json').write_text(json.dumps({'version':1,'items':items},ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    for item in items:
        m.render(item).save(m.ROOT/(item['id']+'.png'))
        (m.ROOT/(item['id']+'.svg')).write_text(m.svg(item),encoding='utf-8',newline='\n')
        if item.get('bubble') in ('speech-soft','cloud-hand','shout','sticky-note','torn-note'):
            (BUBBLES/(item['id']+'.svg')).write_text(m.svg(item),encoding='utf-8',newline='\n')
    print(f'Generated {len(items)} independent materials')


if __name__=='__main__':main()
