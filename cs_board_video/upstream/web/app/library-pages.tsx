"use client";

import {FormEvent, useEffect, useState} from "react";

const API = process.env.NEXT_PUBLIC_API_BASE || "";
const PAGE_SIZE = 8;

type Voice = {
  id: string;
  name: string;
  filename: string;
  content_type?: string;
  size?: number;
  created_at?: number;
};

type Style = {
  id: string;
  name: string;
  aliases: string[];
  description: string;
  recipe: string;
  image_filename: string;
  image_url: string;
  builtin: boolean;
  custom: boolean;
  deleted: boolean;
  type: string;
  created_at: number;
  updated_at: number;
};

type ListResponse<T> = {
  items: T[];
  page: number;
  pages: number;
  page_size: number;
  total: number;
};

type TtsConfig = {
  tts_url: string;
  tts_url_2: string;
  tts_mode: string;
  tts_emotion_mode: number;
  tts_emotion_weight: number;
  tts_emotion_vectors: number[];
  tts_emotion_text: string;
  tts_emotion_random: boolean;
  tts_do_sample: boolean;
  tts_top_p: number;
  tts_top_k: number;
  tts_temperature: number;
  tts_length_penalty: number;
  tts_num_beams: number;
  tts_repetition_penalty: number;
  tts_max_mel_tokens: number;
  tts_max_text_tokens_per_segment: number;
};

const defaultTtsConfig: TtsConfig = {
  tts_url: "http://127.0.0.1:7860",
  tts_url_2: "",
  tts_mode: "gradio",
  tts_emotion_mode: 0,
  tts_emotion_weight: 0.65,
  tts_emotion_vectors: [0, 0, 0, 0, 0, 0, 0, 0],
  tts_emotion_text: "",
  tts_emotion_random: false,
  tts_do_sample: true,
  tts_top_p: 0.8,
  tts_top_k: 30,
  tts_temperature: 0.8,
  tts_length_penalty: 0,
  tts_num_beams: 3,
  tts_repetition_penalty: 10,
  tts_max_mel_tokens: 1500,
  tts_max_text_tokens_per_segment: 120,
};

const emotionModes = [
  "与音色参考音频相同",
  "使用情感参考音频",
  "使用情感向量控制",
  "使用情感描述文本控制",
];

const vectorLabels = ["喜", "怒", "哀", "惧", "厌恶", "低落", "惊喜", "平静"];

function imageSource(path: string) {
  if (path.startsWith("http") || path.startsWith("/styles/")) return path;
  return API ? `${API}${path}` : path;
}

function formatDate(value?: number) {
  return value ? new Date(value * 1000).toLocaleString("zh-CN") : "—";
}

function formatBytes(value?: number) {
  if (!value) return "—";
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

export function LibraryPageShell({
  eyebrow,
  title,
  subtitle,
  children,
}: {
  eyebrow: string;
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <main className="libraryShell">
      <header className="libraryTopbar">
        <a className="libraryBrand" href="/">
          <span className="brandMark"><img src="/brand-mark.png" alt="" /></span>
          <span>有温度出品</span>
        </a>
        <nav className="libraryNav" aria-label="页面导航">
          <a href="/">制作台</a>
          <a href="/voices">音色库</a>
          <a href="/styles">画风库</a>
          <a href="/tts">IndexTTS 设置</a>
        </nav>
      </header>
      <section className="libraryHero">
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="subtitle">{subtitle}</p>
      </section>
      {children}
    </main>
  );
}

function LibraryPager({
  page,
  pages,
  total,
  onPageChange,
}: {
  page: number;
  pages: number;
  total: number;
  onPageChange: (page: number) => void;
}) {
  return (
    <div className="libraryPager">
      <span>共 {total} 项 · 第 {page} / {pages} 页</span>
      <div>
        <button type="button" className="secondary small" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>上一页</button>
        <button type="button" className="secondary small" disabled={page >= pages} onClick={() => onPageChange(page + 1)}>下一页</button>
      </div>
    </div>
  );
}

export function VoiceLibraryPage() {
  const [voices, setVoices] = useState<Voice[]>([]);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [meta, setMeta] = useState({ pages: 1, total: 0 });
  const [name, setName] = useState("");
  const [audio, setAudio] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const load = async (signal?: AbortSignal) => {
    try {
      const params = new URLSearchParams({ search, page: String(page), page_size: String(PAGE_SIZE) });
      const response = await fetch(`${API}/api/voices?${params}`, { signal });
      if (!response.ok) throw new Error("读取音色库失败");
      const data: ListResponse<Voice> = await response.json();
      setVoices(data.items || []);
      setMeta({ pages: data.pages || 1, total: data.total || 0 });
      if (data.page !== page) setPage(data.page || 1);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setMessage(error instanceof Error ? error.message : "读取音色库失败");
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => load(controller.signal), 220);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [search, page]);

  const addVoice = async (event: FormEvent) => {
    event.preventDefault();
    if (!audio) return setMessage("请先选择音频文件");
    setBusy(true);
    setMessage("");
    try {
      const body = new FormData();
      body.append("name", name);
      body.append("audio", audio);
      const response = await fetch(`${API}/api/voices`, { method: "POST", body });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "新增音色失败");
      setName("");
      setAudio(null);
      setPage(1);
      setMessage(`已新增音色“${data.name}”`);
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "新增音色失败");
    } finally {
      setBusy(false);
    }
  };

  const renameVoice = async (voice: Voice) => {
    const nextName = window.prompt("请输入新的音色名称", voice.name)?.trim();
    if (!nextName || nextName === voice.name) return;
    setBusy(true);
    try {
      const response = await fetch(`${API}/api/voices/${voice.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: nextName }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "重命名失败");
      setMessage(`已重命名为“${data.name}”`);
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "重命名失败");
    } finally {
      setBusy(false);
    }
  };

  const deleteVoice = async (voice: Voice) => {
    if (!window.confirm(`确定删除音色“${voice.name}”吗？`)) return;
    setBusy(true);
    try {
      const response = await fetch(`${API}/api/voices/${voice.id}`, { method: "DELETE" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "删除音色失败");
      setMessage(`已删除音色“${voice.name}”`);
      if (voices.length === 1 && page > 1) setPage(page - 1);
      else await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "删除音色失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <LibraryPageShell eyebrow="VOICE LIBRARY" title="音色库" subtitle="集中管理本机参考音频，新建任务时可以直接选择已经上传的音色。">
      <section className="libraryPanel panel">
        <div className="libraryToolbar"><label className="librarySearch"><span>搜索音色</span><input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="按名称、文件名或格式搜索" /></label><span className="libraryHint">音频只保存在本机</span></div>
        <form className="libraryAddForm" onSubmit={addVoice}>
          <label>音色名称<input maxLength={30} value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：我的解说音色" /></label>
          <label>参考音频<input type="file" accept="audio/*,.wav,.mp3,.m4a,.aac,.flac,.ogg,.webm" onChange={(event) => setAudio(event.target.files?.[0] || null)} /><small>{audio ? audio.name : "建议使用 10–30 秒的清晰单人音频"}</small></label>
          <button className="primary small" type="submit" disabled={busy}>{busy ? "处理中…" : "新增音色"}</button>
        </form>
        {voices.length ? <div className="libraryCardGrid voiceCardGrid">{voices.map((voice) => <article className="libraryCard" key={voice.id}><div className="libraryCardHeading"><div><strong>{voice.name}</strong><span>{voice.filename}</span></div><em>{formatBytes(voice.size)}</em></div><audio controls preload="metadata" src={`${API}/api/voices/${voice.id}/audio`}><track kind="captions" /></audio><p>{voice.content_type || "音频"} · 上传于 {formatDate(voice.created_at)}</p><div className="cardActions"><button type="button" className="secondary small" onClick={() => renameVoice(voice)} disabled={busy}>重命名</button><button type="button" className="deleteHistory" onClick={() => deleteVoice(voice)} disabled={busy}>删除</button></div></article>)}</div> : <div className="libraryEmpty">{search ? "没有匹配的音色。" : "音色库还没有音色，请先上传一条参考音频。"}</div>}
        <LibraryPager page={page} pages={meta.pages} total={meta.total} onPageChange={setPage} />
        {message && <p className="message">{message}</p>}
      </section>
    </LibraryPageShell>
  );
}

function StyleDetails({ style, onClose }: { style: Style; onClose: () => void }) {
  const fields: [string, string][] = [
    ["id", style.id],
    ["name", style.name],
    ["aliases", style.aliases.length ? style.aliases.join("、") : "[]"],
    ["type", style.type],
    ["builtin", String(style.builtin)],
    ["custom", String(style.custom)],
    ["deleted", String(style.deleted)],
    ["description", style.description || ""],
    ["recipe", style.recipe || ""],
    ["image_filename", style.image_filename || ""],
    ["image_url", style.image_url || ""],
    ["created_at", formatDate(style.created_at)],
    ["updated_at", formatDate(style.updated_at)],
  ];
  return <div className="styleDetailOverlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><section className="styleDetailDialog" role="dialog" aria-modal="true" aria-label={`${style.name}详情`}><header><div><span className="eyebrow">STYLE DETAIL</span><h2>{style.name}</h2></div><button type="button" className="detailClose" onClick={onClose}>×</button></header><div className="styleDetailContent"><img src={imageSource(style.image_url)} alt={`${style.name}预览`} /><dl>{fields.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || "—"}</dd></div>)}</dl></div></section></div>;
}

export function StyleLibraryPage() {
  const [styles, setStyles] = useState<Style[]>([]);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [meta, setMeta] = useState({ pages: 1, total: 0 });
  const [selected, setSelected] = useState<Style | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [recipe, setRecipe] = useState("");
  const [image, setImage] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const load = async (signal?: AbortSignal) => {
    try {
      const params = new URLSearchParams({ search, page: String(page), page_size: String(PAGE_SIZE) });
      const response = await fetch(`${API}/api/styles?${params}`, { signal });
      if (!response.ok) throw new Error("读取画风库失败");
      const data: ListResponse<Style> = await response.json();
      setStyles(data.items || []);
      setMeta({ pages: data.pages || 1, total: data.total || 0 });
      if (data.page !== page) setPage(data.page || 1);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setMessage(error instanceof Error ? error.message : "读取画风库失败");
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => load(controller.signal), 220);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [search, page]);

  const addStyle = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const body = new FormData();
      body.append("name", name);
      body.append("description", description);
      body.append("recipe", recipe);
      if (image) body.append("image", image);
      const response = await fetch(`${API}/api/styles`, { method: "POST", body });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "新增画风失败");
      setName(""); setDescription(""); setRecipe(""); setImage(null); setPage(1);
      setMessage(`已新增画面风格“${data.name}”`);
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "新增画风失败");
    } finally {
      setBusy(false);
    }
  };

  const editStyle = async (style: Style) => {
    const nextName = window.prompt("风格名称", style.name)?.trim();
    if (!nextName) return;
    const nextDescription = window.prompt("风格简介", style.description)?.trim();
    if (nextDescription === undefined) return;
    const nextRecipe = window.prompt("生成配方", style.recipe)?.trim();
    if (!nextRecipe) return;
    setBusy(true);
    try {
      const response = await fetch(`${API}/api/styles/${style.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: nextName, description: nextDescription, recipe: nextRecipe }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "编辑画风失败");
      setMessage(`已更新画面风格“${data.name}”`);
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "编辑画风失败");
    } finally {
      setBusy(false);
    }
  };

  const deleteStyle = async (style: Style) => {
    if (style.builtin || !window.confirm(`确定删除画面风格“${style.name}”吗？`)) return;
    setBusy(true);
    try {
      const response = await fetch(`${API}/api/styles/${style.id}`, { method: "DELETE" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "删除画风失败");
      setMessage(`已删除画面风格“${style.name}”`);
      if (selected?.id === style.id) setSelected(null);
      if (styles.length === 1 && page > 1) setPage(page - 1);
      else await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "删除画风失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <LibraryPageShell eyebrow="STYLE LIBRARY" title="画风库" subtitle="内置和自定义画风统一展示、搜索和分页管理；详情可以查看后端保存的全部字段。">
      <section className="libraryPanel panel">
        <div className="libraryToolbar"><label className="librarySearch"><span>搜索画风</span><input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="按名称、别名、简介或配方搜索" /></label><span className="libraryHint">内置画风可编辑但不可删除</span></div>
        <form className="libraryAddForm styleAddForm" onSubmit={addStyle}><label>风格名称<input maxLength={40} value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：复古胶片科普风" /></label><label>风格简介<input maxLength={100} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="例如：颗粒胶片 · 暖色调 · 纪录片感" /></label><label className="wideField">生成配方<textarea value={recipe} onChange={(event) => setRecipe(event.target.value)} placeholder="描述背景、线条、材质、配色、构图和禁止项" /></label><label>预览图<input type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => setImage(event.target.files?.[0] || null)} /><small>{image ? image.name : "可选"}</small></label><button className="primary small" type="submit" disabled={busy}>{busy ? "处理中…" : "新增画风"}</button></form>
        {styles.length ? <div className="libraryCardGrid styleCardGrid">{styles.map((style) => <article className="libraryCard styleLibraryCard" key={style.id}><img src={imageSource(style.image_url)} alt={`${style.name}预览`} /><div className="libraryCardHeading"><div><strong>{style.name}</strong><span>{style.type} · {style.description || "暂无简介"}</span></div></div><p>{style.recipe || "暂无配方"}</p><div className="cardActions"><button type="button" className="secondary small" onClick={() => setSelected(style)}>查看详情</button><button type="button" className="editHistory" onClick={() => editStyle(style)} disabled={busy}>编辑</button>{!style.builtin && <button type="button" className="deleteHistory" onClick={() => deleteStyle(style)} disabled={busy}>删除</button>}</div></article>)}</div> : <div className="libraryEmpty">{search ? "没有匹配的画风。" : "画风库没有可展示的画风。"}</div>}
        <LibraryPager page={page} pages={meta.pages} total={meta.total} onPageChange={setPage} />
        {message && <p className="message">{message}</p>}
      </section>
      {selected && <StyleDetails style={selected} onClose={() => setSelected(null)} />}
    </LibraryPageShell>
  );
}

export function TtsSettingsPage() {
  const [config, setConfig] = useState<TtsConfig>(defaultTtsConfig);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    fetch(`${API}/api/config`).then(async (response) => {
      if (!response.ok) throw new Error("读取 IndexTTS 设置失败");
      const data = await response.json();
      setConfig({ ...defaultTtsConfig, ...data, tts_emotion_vectors: data.tts_emotion_vectors || defaultTtsConfig.tts_emotion_vectors });
    }).catch((error) => setMessage(error instanceof Error ? error.message : "读取 IndexTTS 设置失败")).finally(() => setLoading(false));
  }, []);

  const update = <K extends keyof TtsConfig>(key: K, value: TtsConfig[K]) => setConfig((current) => ({ ...current, [key]: value }));
  const updateNumber = (key: keyof TtsConfig, value: string) => update(key, Number(value) as never);
  const updateVector = (index: number, value: string) => update("tts_emotion_vectors", config.tts_emotion_vectors.map((item, vectorIndex) => vectorIndex === index ? Number(value) : item));

  const save = async () => {
    setSaving(true);
    setMessage("");
    try {
      const response = await fetch(`${API}/api/config`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(config) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "保存 IndexTTS 设置失败");
      setConfig((current) => ({ ...current, ...data }));
      setMessage("IndexTTS 参数已保存，下一次生成时生效。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存 IndexTTS 设置失败");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <LibraryPageShell eyebrow="INDEXTTS CONTROL" title="IndexTTS 设置" subtitle="正在读取本机语音节点配置…"><section className="libraryPanel panel libraryEmpty">正在加载…</section></LibraryPageShell>;
  return <LibraryPageShell eyebrow="INDEXTTS CONTROL" title="IndexTTS 设置" subtitle="这些参数只会作用于发送给 IndexTTS 的文本和推理请求，不会改变字幕、页面文案或历史原文。">
    <section className="libraryPanel panel ttsSettingsPanel">
      <div className="sectionTitle"><div><span>01</span><h2>语音节点</h2></div><p>支持 Gradio 与旧版 FastAPI 适配器</p></div>
      <div className="settingsGrid"><label>语音节点 1<input value={config.tts_url} onChange={(event) => update("tts_url", event.target.value)} /></label><label>语音节点 2<input value={config.tts_url_2} onChange={(event) => update("tts_url_2", event.target.value)} placeholder="可留空" /></label><label>接口类型<select value={config.tts_mode} onChange={(event) => update("tts_mode", event.target.value)}><option value="gradio">IndexTTS Gradio（7860）</option><option value="fastapi">IndexTTS FastAPI（8000）</option></select></label></div>
      <div className="sectionTitle ttsSectionTitle"><div><span>02</span><h2>情绪控制</h2></div><p>按当前 IndexTTS 2.x 的 gen_single 参数传递</p></div>
      <div className="settingsGrid"><label>情绪控制方式<select value={config.tts_emotion_mode} onChange={(event) => updateNumber("tts_emotion_mode", event.target.value)}>{emotionModes.map((mode, index) => <option value={index} key={mode}>{mode}</option>)}</select><small>情感参考音频模式需要服务端同时提供情绪参考音频；未提供时建议使用音色相同或情感向量。</small></label><label>情绪权重<input type="number" min="0" max="1" step="0.01" value={config.tts_emotion_weight} onChange={(event) => updateNumber("tts_emotion_weight", event.target.value)} /></label><label className="wideField">情绪描述文本<input maxLength={120} value={config.tts_emotion_text} onChange={(event) => update("tts_emotion_text", event.target.value)} placeholder="例如：委屈巴巴、危险在悄悄逼近" /></label></div>
      <div className="checkboxSetting"><input id="tts-emotion-random" type="checkbox" checked={config.tts_emotion_random} onChange={(event) => update("tts_emotion_random", event.target.checked)} /><label htmlFor="tts-emotion-random"><strong>情绪随机采样</strong><small>允许 IndexTTS 在情绪控制下增加采样变化</small></label></div>
      <div className="ttsVectorGrid">{vectorLabels.map((label, index) => <label key={label}>{label}<input type="number" min="0" max="1" step="0.05" value={config.tts_emotion_vectors[index] || 0} onChange={(event) => updateVector(index, event.target.value)} /></label>)}</div>
      <div className="sectionTitle ttsSectionTitle"><div><span>03</span><h2>采样与长度</h2></div><p>数值会在后端保存时自动限制到安全范围</p></div>
      <div className="settingsGrid"><div className="checkboxSetting"><input id="tts-do-sample" type="checkbox" checked={config.tts_do_sample} onChange={(event) => update("tts_do_sample", event.target.checked)} /><label htmlFor="tts-do-sample"><strong>do_sample</strong><small>开启采样通常更有表现力</small></label></div><label>top_p<input type="number" min="0" max="1" step="0.01" value={config.tts_top_p} onChange={(event) => updateNumber("tts_top_p", event.target.value)} /></label><label>top_k<input type="number" min="0" max="1000" step="1" value={config.tts_top_k} onChange={(event) => updateNumber("tts_top_k", event.target.value)} /></label><label>temperature<input type="number" min="0" max="2" step="0.01" value={config.tts_temperature} onChange={(event) => updateNumber("tts_temperature", event.target.value)} /></label><label>length_penalty<input type="number" min="-2" max="2" step="0.01" value={config.tts_length_penalty} onChange={(event) => updateNumber("tts_length_penalty", event.target.value)} /></label><label>num_beams<input type="number" min="1" max="20" step="1" value={config.tts_num_beams} onChange={(event) => updateNumber("tts_num_beams", event.target.value)} /></label><label>repetition_penalty<input type="number" min="0" max="20" step="0.1" value={config.tts_repetition_penalty} onChange={(event) => updateNumber("tts_repetition_penalty", event.target.value)} /></label><label>max_mel_tokens<input type="number" min="100" max="10000" step="10" value={config.tts_max_mel_tokens} onChange={(event) => updateNumber("tts_max_mel_tokens", event.target.value)} /></label><label>分句最大 Token 数<input type="number" min="20" max="500" step="2" value={config.tts_max_text_tokens_per_segment} onChange={(event) => updateNumber("tts_max_text_tokens_per_segment", event.target.value)} /></label></div>
      <div className="actions"><button type="button" className="primary" onClick={save} disabled={saving}>{saving ? "保存中…" : "保存 IndexTTS 设置"}</button></div>{message && <p className="message">{message}</p>}
    </section>
  </LibraryPageShell>;
}
