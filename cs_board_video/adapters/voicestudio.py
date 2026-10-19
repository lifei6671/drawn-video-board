"""Discover local OpenAPI, then use a configured synchronous audio endpoint.

VoiceStudio distributions differ: no guessed port, model, or voice is embedded.
For a local model without HTTP, use the configured argv template instead.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from ..project import WorkflowError, require


def request(url, payload=None, timeout=30):
    req = Request(url, data=None if payload is None else json.dumps(payload).encode(),
                  headers={"Content-Type": "application/json"} if payload is not None else {})
    try:
        with urlopen(req, timeout=timeout) as response:
            return response.headers.get("Content-Type", ""), response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise WorkflowError(f"本地语音服务请求失败: {error}", 3) from error


def local_url(url):
    parsed = urlsplit(url)
    require(parsed.scheme in ("http", "https") and parsed.hostname in ("localhost", "127.0.0.1", "::1"),
            "VoiceStudio 必须配置为本机 loopback 地址")
    require(not parsed.username and not parsed.password and not parsed.query and not parsed.fragment,
            "本地服务 URL 不应包含凭据、查询或片段")
    return url.rstrip("/")


def discover(url):
    base = local_url(url)
    _, raw = request(base + "/openapi.json")
    try:
        schema = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise WorkflowError("本地服务未返回可识别 OpenAPI", 3) from error
    require(isinstance(schema.get("paths"), dict), "本地接口缺少 OpenAPI paths", 3)
    models = {}
    for path, operations in schema["paths"].items():
        if "get" in operations and path.rstrip("/").split("/")[-1] == "models":
            try:
                _, raw_models = request(base + path)
                models[path] = json.loads(raw_models)
            except WorkflowError as error:
                models[path] = {"status": "UNAVAILABLE", "error": str(error)}
    return {"status": "PASS", "base_url": base, "paths": schema["paths"],
            "components": schema.get("components", {}), "models": models}


def synthesize(project):
    config = project.load("audio/voice-config.json", {})
    require(config, "先配置 audio/voice-config.json")
    output = project.path("audio/generated.wav")
    from ..bridge import project_context
    original = project.path("narration/original.txt").read_text(encoding="utf-8-sig")
    with project_context(project) as module:
        text = module.preprocess_tts_text(original)
        project.path("audio/tts-input.txt").write_text(text, encoding="utf-8")
        if config.get("adapter") == "upstream":
            reference = project.path(config["reference"])
            require(reference.is_file(), "原语音接口需要项目内参考音频")
            download_dir = project.path("audio/cache/gradio")
            download_dir.mkdir(parents=True, exist_ok=True)
            module.synthesize_voice({**module.DEFAULT_CONFIG, **config.get("payload", {})}, reference, original, output,
                                    download_dir=download_dir)
            return output, {"adapter": "upstream.synthesize_voice", "config_sha256": project.hash("audio/voice-config.json")}
    if config.get("command"):
        argv = config["command"]
        require(isinstance(argv, list) and all(isinstance(x, str) for x in argv), "本地模型 command 必须是 argv 数组")
        require(any("{output}" in x for x in argv) and any("{text_file}" in x for x in argv),
                "command 必须含 {output} 和 {text_file}")
        command = [x.replace("{output}", str(output)).replace("{text_file}", str(project.path("audio/tts-input.txt")))
                   for x in argv]
        from ..media import run
        run(command, cwd=project.root)
        return output, {"adapter": "local-command", "config_sha256": project.hash("audio/voice-config.json")}
    info = discover(config.get("base_url", ""))
    endpoint = config.get("endpoint", "")
    require(endpoint in info["paths"] and "post" in info["paths"][endpoint],
            "配置的 POST endpoint 不在实际 OpenAPI 中；请先 doctor 查看接口")
    payload = dict(config.get("payload", {}))
    field = config.get("text_field")
    require(isinstance(field, str) and field, "必须按实际接口配置 text_field")
    payload[field] = text
    model_field = config.get("model_field", "model")
    model = payload.get(model_field)
    if info["models"] and model:
        # Model catalogs may contain nested data; require the selected id to be present.
        def strings(value):
            if isinstance(value, str):
                return [value]
            if isinstance(value, dict):
                return [s for v in value.values() for s in strings(v)]
            if isinstance(value, list):
                return [s for v in value for s in strings(v)]
            return []
        require(model in strings(info["models"]), f"所选模型未出现在实际可用模型中: {model}")
    content_type, raw = request(info["base_url"] + endpoint, payload, timeout=300)
    if "json" in content_type:
        data = json.loads(raw)
        field = config.get("audio_base64_field")
        require(field and isinstance(data.get(field), str),
                "JSON 音频响应需配置 audio_base64_field；异步任务协议不支持，请改用本地 command", 3)
        raw = base64.b64decode(data[field], validate=True)
    require(raw[:4] == b"RIFF" and raw[8:12] == b"WAVE", "语音接口必须返回 WAV 数据", 3)
    output.write_bytes(raw)
    return output, {"adapter": "openapi-wav", "config_sha256": project.hash("audio/voice-config.json"),
                    "endpoint": endpoint, "model": model}
