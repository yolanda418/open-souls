"""Anthropic call with scene-weighted model routing, adapted for OpenRouter. Mock mode disabled."""
import os, json, re, time, urllib.error, urllib.request

TIERS = {"light": "claude-haiku-4-5", "heavy": "claude-sonnet-4-6", "peak": "claude-opus-4-8"}

def route(w):
    return TIERS["peak"] if w >= 8 else TIERS["heavy"] if w >= 5 else TIERS["light"]

def complete(system, user, scene_weight=3, max_tokens=1100):
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("未检测到 OPENROUTER_API_KEY 环境变量，请检查 GitHub Secrets 设置。")
    
    raw_model = route(scene_weight)
    if not raw_model.startswith("anthropic/") and not "/" in raw_model:
        model_name = f"anthropic/{raw_model}"
    else:
        model_name = raw_model

    body = json.dumps({
        "model": model_name,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ],
    }).encode()

    base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    req = urllib.request.Request(
        f"{base_url}/chat/completions", data=body,
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://github.com/yolanda418/open-souls",
            "X-Title": "Open Souls"
        })

    retries = int(os.environ.get("LLM_RETRIES", "2"))
    retries = max(1, min(retries, 3))
    data = None
    last_error = None

    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.load(r)
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.load(r)
            print(f"DEBUG_RAW_DATA: {data}") # 
            break
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in {408, 429, 500, 502, 503, 504}:
                raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(0.25 * (2 ** attempt))

    if data is None:
        raise RuntimeError(f"LLM 请求失败（重试 {retries} 次）: {last_error}") from last_error

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise ValueError(f"OpenRouter 返回的数据结构不符: {data}") from e

def parse_json(text):
    text = re.sub(r"```(json)?", "", text).strip().lstrip("\ufeff")
    if text.startswith("["):
        raise ValueError(f"LLM 返回的不是 JSON 对象:\n{text[:300]}")
    start = text.find("{")
    if start == -1:
        raise ValueError(f"LLM 没返回 JSON:\n{text[:300]}")
    depth = 0
    in_string = False
    escape = False
    end = -1
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == "\"":
                in_string = False
            continue
        if ch == "\"":
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end == -1:
        raise ValueError(f"LLM 没返回完整 JSON 对象:\n{text[:300]}")
    obj = text[start:end + 1]
    try:
        parsed = json.loads(obj)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM 返回的 JSON 解析失败: {str(e)}\n{text[:300]}")
    if not isinstance(parsed, dict):
        raise ValueError(f"LLM 返回的不是 JSON 对象:\n{text[:300]}")
    return parsed

def _mock(user):
    raise RuntimeError(f"Mock 模式已被禁用。用户输入: {user[:50]}...")
