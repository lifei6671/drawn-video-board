"use client";

import {FormEvent,useEffect,useState} from "react";
import Link from "next/link";
import styles from "./page.module.css";

const API=process.env.NEXT_PUBLIC_API_BASE||"";
const backendUrl=(path:string)=>`${API}${path}`;
type Quality="medium"|"high";
type GeneratedImage={
  image:string;
  prompt:string;
  model:string;
  styleName:string|null;
  size:string;
  quality:Quality;
  time:string;
};

type StyleOption={
  id:string;
  name:string;
  image:string;
  description:string;
  recipe:string;
  badge?:string;
  builtin?:boolean;
};

const builtinStyles:StyleOption[]=[
  {id:"builtin-minimal-whiteboard",name:"极简粗线简笔白板风",image:"/styles/minimal-whiteboard.webp",description:"粗黑线 · 少量配色 · 清爽留白",recipe:"minimal whiteboard illustration, bold black outlines, generous white space, restrained color accents, clean hand-drawn educational visual",builtin:true},
  {id:"builtin-business-doodle",name:"极简商务涂鸦风",image:"/styles/business-doodle.webp",description:"几何图表 · 蓝绿配色 · 专业克制",recipe:"minimal business doodle illustration, geometric diagrams, blue and green accent palette, clean editorial layout, restrained professional visual language",builtin:true},
  {id:"builtin-warm-pencil",name:"暖米黄素描白板风",image:"/styles/warm-pencil.webp",description:"铅笔排线 · 纸张质感 · 温暖细腻",recipe:"warm cream paper, graphite pencil hatching, soft hand-drawn contours, subtle paper grain, intimate editorial sketchbook feeling",builtin:true},
  {id:"builtin-guofeng-flat",name:"粗线扁平国风卡通",image:"/styles/guofeng-flat.webp",description:"朱红玉绿 · 国风纹样 · 生动平涂",recipe:"bold outlined Chinese flat illustration, vermilion red and jade green palette, elegant traditional motifs, lively simplified shapes",builtin:true},
  {id:"builtin-viral-pop",name:"爆款高热吸睛风",image:"/styles/viral-pop.webp",description:"高饱和 · 强对比 · 短视频冲击力",recipe:"high-energy social media illustration, saturated colors, sharp contrast, punchy composition, expressive shapes, immediate visual impact",badge:"热门",builtin:true},
  {id:"builtin-black-gold-tech",name:"黑金科技发布会风",image:"/styles/black-gold-tech.webp",description:"黑金光效 · 科技舞台 · 高级权威",recipe:"black and gold technology keynote aesthetic, cinematic stage lighting, polished metallic accents, deep shadows, premium authoritative composition",builtin:true},
  {id:"builtin-healing-journal",name:"清新治愈手账风",image:"/styles/healing-journal.webp",description:"柔和水彩 · 治愈配色 · 生活手账",recipe:"gentle healing journal illustration, soft watercolor washes, muted pastel palette, handwritten warmth, delicate everyday details",builtin:true},
  {id:"builtin-retro-collage",name:"复古报纸拼贴风",image:"/styles/retro-collage.webp",description:"撕纸拼贴 · 半色调 · 编辑视觉",recipe:"retro newspaper collage, torn paper edges, halftone print texture, limited ink colors, bold editorial composition, analog imperfections",builtin:true},
  {id:"builtin-paper-metaphor",name:"纸感隐喻拼贴风",image:"/styles/paper-metaphor.png",description:"手工剪纸 · 观点隐喻 · 高级克制",recipe:"tactile paper metaphor collage, layered cut paper shapes, thoughtful conceptual symbolism, quiet palette, refined negative space",badge:"新增",builtin:true},
  {id:"builtin-oil-visual",name:"漫画墨线解释风",image:"/styles/oil-visual.png",description:"漫画墨线 · 半调网点 · 概念机制",recipe:"ink comic explainer illustration, expressive black linework, halftone dots, clear visual metaphors, conceptual mechanism shown with playful precision",badge:"新增",builtin:true},
  {id:"builtin-clay-3d",name:"3D黏土趣味风",image:"/styles/clay-3d.webp",description:"黏土材质 · 玩具比例 · 温暖可爱",recipe:"whimsical 3D clay illustration, tactile modeling-clay texture, toy-like proportions, soft studio lighting, warm playful colors",builtin:true},
  {id:"builtin-cyber-neon",name:"赛博霓虹漫画风",image:"/styles/cyber-neon.webp",description:"霓虹青紫 · 漫画速度线 · 未来感",recipe:"cyber neon comic illustration, electric cyan and violet lighting, dramatic speed lines, futuristic urban atmosphere, bold graphic contrast",builtin:true},
];

const sizes=[
  {value:"1536x1024",name:"横向",ratio:"3 : 2",hint:"场景 / 海报"},
  {value:"1024x1024",name:"方形",ratio:"1 : 1",hint:"头像 / 社媒"},
  {value:"1024x1536",name:"竖向",ratio:"2 : 3",hint:"封面 / 手机"},
];

const inspirations=[
  "A solitary astronaut tending a tiny greenhouse inside an abandoned orbital station, warm sodium lights, cinematic sci-fi still",
  "A night market floating above a sleeping city, paper lanterns reflected in rainwater, editorial photography, rich texture",
  "A porcelain fox crossing a brutalist museum at dawn, long shadows, soft dust in the air, surreal fine art",
];

function ArrowIcon(){
  return <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h9M8.5 4.5 12 8l-3.5 3.5" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.4"/></svg>;
}

function SparkIcon(){
  return <svg viewBox="0 0 20 20" aria-hidden="true"><path d="m10 1.8 1.55 5.7L17.2 10l-5.65 1.55L10 17.2l-1.55-5.65L2.8 10l5.65-2.5L10 1.8Z" fill="none" stroke="currentColor" strokeLinejoin="round" strokeWidth="1.2"/><path d="m16.2 2.5.55 1.75 1.7.55-1.7.55-.55 1.7-.55-1.7-1.7-.55 1.7-.55.55-1.75Z" fill="currentColor"/></svg>;
}

function DownloadIcon(){
  return <svg viewBox="0 0 18 18" aria-hidden="true"><path d="M9 2.5v8.2m0 0 3-3m-3 3-3-3M3 13.6v1.1c0 .45.35.8.8.8h10.4c.45 0 .8-.35.8-.8v-1.1" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.35"/></svg>;
}

export default function ImageGeneratorPage(){
  const[configModel,setConfigModel]=useState("读取中…");
  const[styleOptions,setStyleOptions]=useState<StyleOption[]>(builtinStyles);
  const[selectedStyleId,setSelectedStyleId]=useState<string|null>(null);
  const[prompt,setPrompt]=useState("");
  const[size,setSize]=useState("1536x1024");
  const[quality,setQuality]=useState<Quality>("high");
  const[result,setResult]=useState<GeneratedImage|null>(null);
  const[history,setHistory]=useState<GeneratedImage[]>([]);
  const[isGenerating,setIsGenerating]=useState(false);
  const[error,setError]=useState("");
  const[copyState,setCopyState]=useState("复制提示词");
  const selectedStyle=styleOptions.find(item=>item.id===selectedStyleId)||null;

  useEffect(()=>{
    let active=true;
    fetch(backendUrl("/api/config"))
      .then(response=>response.ok?response.json():null)
      .then(data=>{
        if(active&&data?.image_model)setConfigModel(String(data.image_model));
      })
      .catch(()=>{if(active)setConfigModel("未连接 API 设置")});
    return()=>{active=false};
  },[]);

  useEffect(()=>{
    let active=true;
    fetch(backendUrl("/api/styles?page_size=100"))
      .then(response=>response.ok?response.json():null)
      .then(data=>{
        if(!active||!data?.items)return;
        const items=data.items as Array<{id?:string;name?:string;description?:string;recipe?:string;image_url?:string;builtin?:boolean;badge?:string}>;
        const mergedBuiltins=builtinStyles.map(style=>{
          const remote=items.find(item=>item.id===style.id);
          return remote?{...style,name:remote.name||style.name,description:remote.description||style.description,recipe:remote.recipe||style.recipe,image:remote.image_url||style.image}:style;
        });
        const customStyles=items
          .filter(item=>item.name&&item.id&&!builtinStyles.some(style=>style.id===item.id))
          .map(item=>({
            id:item.id as string,
            name:item.name as string,
            image:item.image_url||"/styles/minimal-whiteboard.webp",
            description:item.description||"自定义画面风格",
            recipe:item.recipe||item.description||"custom visual style",
            badge:item.badge,
            builtin:item.builtin,
          }));
        if(customStyles.length||mergedBuiltins.some((style,index)=>style!==builtinStyles[index]))setStyleOptions([...mergedBuiltins,...customStyles]);
      })
      .catch(()=>{});
    return()=>{active=false};
  },[]);

  const generate=async(event:FormEvent<HTMLFormElement>)=>{
    event.preventDefault();
    const cleanPrompt=prompt.trim();
    if(!cleanPrompt){setError("先写下你想看到的画面。");return}
    if(configModel==="读取中…"||configModel==="未连接 API 设置"){setError("请先在白板工程的 API 设置中配置图片模型。");return}
    setError("");
    setIsGenerating(true);
    try{
      const response=await fetch(backendUrl("/api/image-generate"),{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({prompt:cleanPrompt,style_name:selectedStyle?.name||"",style_recipe:selectedStyle?.recipe||"",aspect_ratio:size==="1536x1024"?"16:9":size==="1024x1536"?"9:16":"1:1",quality}),
      });
      const data=await response.json().catch(()=>({})) as {image?:string;model?:string;style_name?:string|null;error?:string;detail?:string};
      if(!response.ok||!data.image)throw new Error(data.error||data.detail||"图片生成失败，请稍后重试。");
      const next:GeneratedImage={image:data.image,prompt:cleanPrompt,model:data.model||configModel,styleName:data.style_name||selectedStyle?.name||null,size,quality,time:new Date().toLocaleTimeString("zh-CN",{hour:"2-digit",minute:"2-digit"})};
      setResult(next);
      setHistory(previous=>[next,...previous.filter(item=>item.image!==next.image)].slice(0,4));
    }catch(caught){
      setError(caught instanceof Error?caught.message:"图片生成失败，请稍后重试。");
    }finally{
      setIsGenerating(false);
    }
  };

  const copyPrompt=async()=>{
    if(!prompt.trim())return;
    try{
      await navigator.clipboard.writeText(prompt.trim());
      setCopyState("已复制");
      window.setTimeout(()=>setCopyState("复制提示词"),1600);
    }catch{
      setCopyState("复制失败");
    }
  };

  const useInspiration=()=>{
    const next=inspirations[Math.floor(Math.random()*inspirations.length)];
    setPrompt(next);
    setError("");
  };

  const download=()=>{
    if(!result)return;
    const link=document.createElement("a");
    link.href=result.image;
    link.download=`image-lab-${result.model}-${Date.now()}.png`;
    link.click();
  };

  return <main className={styles.page}>
    <div className={styles.ambientGlow}/>
    <header className={styles.topbar}>
      <Link className={styles.brand} href="/image-generator" aria-label="Image Lab 首页">
        <span className={styles.brandMark}><span/></span>
        <span><strong>IMAGE LAB</strong><small>GENERATIVE STUDIO</small></span>
      </Link>
      <div className={styles.topbarMeta}>
        <span className={styles.liveDot}/>
        <span>{configModel.startsWith("未连接")?"API OFFLINE":"API SETTINGS LINKED"}</span>
        <span className={styles.topbarDivider}/>
        <span>V 01.02</span>
      </div>
    </header>

    <section className={styles.intro}>
      <p className={styles.kicker}><span>01</span> PROMPT → PIXEL</p>
      <h1>把脑海里的<br/><em>下一帧</em>，显影。</h1>
      <p className={styles.introCopy}>模型来自白板工程的 API 设置，<br/>写下画面，让它负责显影。</p>
    </section>

    <div className={styles.workspace}>
      <section className={styles.controlPanel}>
        <div className={styles.sectionHeading}>
          <span className={styles.sectionNumber}>A</span>
          <div><p>API IMAGE MODEL</p><span>使用白板工程 API 设置中的图片模型</span></div>
        </div>
        <div className={styles.configModelCard}>
          <span className={styles.configModelOrb}><span/></span>
          <span><small>CURRENT IMAGE MODEL</small><strong>{configModel}</strong><em>API 设置同步 · 生成时锁定</em></span>
          <Link href="/#api-settings">修改设置 ↗</Link>
        </div>

        <div className={`${styles.sectionHeading} ${styles.styleHeading}`}>
          <span className={styles.sectionNumber}>B</span>
          <div><p>STYLE LIBRARY <b>OPTIONAL</b></p><span>沿用项目画风库，也可以保持原始风格</span></div>
        </div>
        <div className={styles.styleToolbar}>
          <button type="button" className={`${styles.styleOff} ${!selectedStyle?styles.styleOffActive:""}`} onClick={()=>setSelectedStyleId(null)} aria-pressed={!selectedStyle}><span className={styles.noStyleIcon}>∅</span><span><strong>不指定画风</strong><small>交给模型自由发挥</small></span></button>
          <span className={styles.styleCount}>{selectedStyle?`已选：${selectedStyle.name}`:`共 ${styleOptions.length} 个可选风格`}</span>
        </div>
        <div className={styles.styleGrid} role="radiogroup" aria-label="画风库">
          {styleOptions.map(item=><button key={item.id} type="button" className={`${styles.styleCard} ${selectedStyleId===item.id?styles.styleCardActive:""}`} onClick={()=>setSelectedStyleId(item.id)} role="radio" aria-checked={selectedStyleId===item.id}>
            <span className={styles.styleImageWrap}><img src={item.image} alt=""/>{item.badge&&<em>{item.badge}</em>}<i>{selectedStyleId===item.id?"✓":""}</i></span>
            <strong>{item.name}</strong>
            <small>{item.description}</small>
          </button>)}
        </div>

        <div className={`${styles.sectionHeading} ${styles.promptHeading}`}>
          <span className={styles.sectionNumber}>C</span>
          <div><p>YOUR SCENE</p><span>越具体，越接近你想象的画面</span></div>
        </div>
        <form onSubmit={generate}>
          <div className={styles.promptWrap}>
            <textarea value={prompt} onChange={event=>{setPrompt(event.target.value);setError("")}} placeholder="描述人物、动作、光线、材质与氛围……" maxLength={4000} aria-label="画面提示词"/>
            <div className={styles.promptFooter}><span>{prompt.length.toLocaleString()} / 4,000</span><button type="button" onClick={useInspiration}><SparkIcon/> 灵感</button></div>
          </div>
          <div className={styles.settingGrid}>
            <div><span className={styles.settingLabel}>CANVAS</span><div className={styles.optionRow}>{sizes.map(item=><button key={item.value} type="button" className={`${styles.option} ${size===item.value?styles.optionActive:""}`} onClick={()=>setSize(item.value)}><strong>{item.ratio}</strong><span>{item.name}</span></button>)}</div></div>
            <div><span className={styles.settingLabel}>QUALITY</span><div className={styles.qualityRow}>{(["medium","high"] as Quality[]).map(item=><button key={item} type="button" className={`${styles.qualityButton} ${quality===item?styles.qualityActive:""}`} onClick={()=>setQuality(item)}><span>{item==="high"?"HIGH":"MEDIUM"}</span>{item==="high"&&<em>细节优先</em>}</button>)}</div></div>
          </div>
          {error&&<p className={styles.error} role="alert">{error}</p>}
          <button className={styles.generateButton} type="submit" disabled={isGenerating}>
            <span>{isGenerating?"正在显影":"开始生成"}</span>
            <span className={styles.generateArrow}>{isGenerating?<i className={styles.spinner}/>:<ArrowIcon/>}</span>
          </button>
        </form>
        <p className={styles.securityNote}><span>✦</span> 图片模型、接口地址与 API Key 均复用白板工程设置。</p>
      </section>

      <section className={styles.outputPanel} aria-live="polite">
        <div className={styles.outputHeader}><div><p className={styles.kicker}><span>02</span> OUTPUT FRAME</p><h2>{result?"画面已显影":"等待下一帧"}</h2></div><span className={styles.frameMeta}>{result?`${result.model} · ${result.size}${result.styleName?` · ${result.styleName}`:""}`:"NO IMAGE YET"}</span></div>
        <div className={`${styles.canvas} ${result?styles.canvasFilled:""}`}>
          {result?<img src={result.image} alt={result.prompt}/>:<div className={styles.emptyCanvas}><div className={styles.frameMark}><span/><span/><span/><span/></div><strong>NO FRAME LOADED</strong><p>你的第一张图会在这里出现</p><div className={styles.emptyLine}/></div>}
          {isGenerating&&<div className={styles.generatingOverlay}><div className={styles.scanLine}/><span><i className={styles.spinner}/>正在渲染 {configModel}</span></div>}
        </div>
        <div className={styles.outputFooter}>
          {result?<><div className={styles.resultInfo}><span className={styles.resultBadge}>READY</span><span>{result.time} · {result.quality.toUpperCase()}</span></div><div className={styles.resultActions}><button type="button" onClick={copyPrompt}>{copyState}</button><button type="button" onClick={download} className={styles.downloadButton}><DownloadIcon/> 下载 PNG</button></div></>:<p className={styles.outputHint}>提示：左侧选择模型并输入描述，然后点击开始生成。</p>}
        </div>
        {history.length>0&&<div className={styles.history}><div className={styles.historyHeader}><span>RECENT FRAMES</span><span>{history.length.toString().padStart(2,"0")}</span></div><div className={styles.historyGrid}>{history.map((item,index)=><button key={`${item.time}-${index}`} type="button" className={`${styles.historyItem} ${result?.image===item.image?styles.historyActive:""}`} onClick={()=>setResult(item)}><img src={item.image} alt=""/><span>{item.model}</span></button>)}</div></div>}
      </section>
    </div>

    <footer className={styles.footer}><span>IMAGE LAB / 2026</span><span>USE API SETTINGS · WRITE A SCENE · MAKE IT REAL</span><Link href="/#api-settings">API SETTINGS ↗</Link></footer>
  </main>;
}
