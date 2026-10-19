# 本地配音与原时间轴

用户音频先实际试听或本地 ASR 比对，再 `audio import --source <文件> --content-evidence ...`。
保留原件并转 mono 48kHz WAV 到 audio/voice.wav；用户提供的匹配音频无需再次批准。

新配音配置 audio/voice-config.json。先 `doctor --voice-url http://127.0.0.1:13900` 查询实际
OpenAPI/模型，按当前可用模型及音色设置；服务地址不写死到代码，不能猜测配置。

```json
{"base_url":"http://127.0.0.1:13900","endpoint":"/v1/audio/speech","text_field":"input","payload":{"model":"实际模型","voice":"实际音色","response_format":"wav"}}
```

同步接口支持 WAV 或配置 audio_base64_field 的 base64 JSON。原 TTS 同样保留：

```json
{"adapter":"upstream","reference":"audio/original/reference.wav","payload":{"tts_mode":"gradio","tts_url":"实际原服务地址"}}
```

payload 沿用原 DEFAULT_CONFIG 的全部 TTS 参数/双节点设置；Gradio 缓存强制在本项目
 audio/cache/gradio。原 FastAPI 模式用 tts_mode=fastapi。发音预处理直接调用原规则，
项目保存 audio/pronunciation.yaml 与 audio/tts-input.txt。也支持本地 argv：
`{"command":["解释器","本地脚本","--text-file","{text_file}","--output","{output}"]}`。
本地程序也应遵循项目资源边界。新生成配音必须实际试听、audio verify、用户明确确认，
才能记录 audio 批准。技术探针和 ASR 结果不能代替用户听觉验收。

普通白板 timeline build 直接使用原 fit_scene_durations 和 write_subtitles，不使用另写
分镜预估权重分配器。原普通字幕按字符分配句内时间，属于估计，需要完整预览审核。
可导入已有精确镜头时间 audio/alignment.json：
`{"scenes":[{"scene_id":"scene-001","start_ms":0,"end_ms":8000}]}`，连续覆盖全音频。

Remotion 必须 `audio align` 调原 video_renderer/align.mjs，或 `audio align --tokens <文件>`
导入同格式实际词边界（captions 的 text/startMs/endMs/confidence）。原 Whisper 使用
原模型与语音活动检测；缓存绑定项目。禁止将测试合成词边界用于真实视频。
随后 `deck request/adapt` 使用原 PPT 提示词/归一，timeline build 直接调用原
build_phrase_timeline/build_deck_timeline/remotion_infographic_props；低覆盖匹配明确失败。
音频、词边界、页面、画风、字幕布局变化都使相关 props/预览/批准失效。
