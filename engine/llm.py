import json
import os
import re
import time
import urllib.error
import urllib.request

TIERS = {
    "light": "google/gemma-4-31b-it:free",
    "heavy": "google/gemma-4-31b-it:free",
    "peak": "google/gemma-4-31b-it:free",
}

def route(scene_weight):
    try:
        weight = float(scene_weight)
    except (TypeError, ValueError):
        weight = 3

    if weight >= 8:
        return TIERS["peak"]
    if weight >= 5:
        return TIERS["heavy"]
    return TIERS["light"]


def complete(system, user, scene_weight=3, max_tokens=None):
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()

    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set."
        )

    model = route(scene_weight)

    if max_tokens is None:
        try:
            weight = float(scene_weight)
        except (TypeError, ValueError):
            weight = 3

        max_tokens = 7000 if weight >= 8 else 4000 if weight >= 5 else 1800

   payload = {
    "model": model,
    "messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ],
    "max_tokens": max_tokens,
    "temperature": 0.7,
    "response_format": {
        "type": "json_object"
    },
    "provider": {
        "order": ["Google AI Studio"],
        "allow_fallbacks": False,
    },
}

    data = json.dumps(
        payload,
        ensure_ascii=False
    ).encode("utf-8")

    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://github.com/yolanda418/open-souls",
            "X-Title": "Open Souls",
        },
    )

    for attempt in range(3):
        try:
            with urllib.request.urlopen(
                request,
                timeout=180
            ) as response:
                raw = response.read().decode("utf-8")

            result = json.loads(raw)
            choices = result.get("choices", [])

            if not choices:
                raise RuntimeError(
                    f"OpenRouter returned no choices: {raw[:1500]}"
                )

            content = choices[0].get("message", {}).get("content", "")

            if isinstance(content, list):
                content = "".join(
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict)
                )

            content = str(content).strip()

            if not content:
                raise RuntimeError(
                    f"OpenRouter returned empty content: {raw[:1500]}"
                )

            print(
                f"LLM OK | model={model} | "
                f"output_chars={len(content)}"
            )

            return content

        except urllib.error.HTTPError as e:
            body = e.read().decode(
                "utf-8",
                errors="replace"
            )

            if e.code not in {408, 429, 500, 502, 503, 504}:
                raise RuntimeError(
                    f"OpenRouter HTTP {e.code}: {body[:1500]}"
                ) from e

            last_error = body

        except Exception as e:
            last_error = str(e)

        if attempt < 2:
            time.sleep(2 ** attempt)

    raise RuntimeError(
        f"OpenRouter request failed: {last_error}"
    )


def parse_json(text):
    if not isinstance(text, str):
        raise ValueError("LLM response is not text.")

    text = text.strip().lstrip("\ufeff")

    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"\s*```$",
        "",
        text,
        flags=re.IGNORECASE
    ).strip()

    start = text.find("{")

    if start < 0:
        raise ValueError(
            f"LLM did not return JSON:\n{text[:1500]}"
        )

    depth = 0
    in_string = False
    escaped = False

    for i in range(start, len(text)):
        c = text[i]

        if in_string:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_string = False
            continue

        if c == '"':
            in_string = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1

            if depth == 0:
                obj = text[start:i + 1]

                try:
                    result = json.loads(obj)
                except json.JSONDecodeError as e:
                    raise ValueError(
                        f"Invalid JSON from LLM:\n{text[:1500]}"
                    ) from e

                if not isinstance(result, dict):
                    raise ValueError(
                        "LLM JSON is not an object."
                    )

                return result

    raise ValueError(
        f"Incomplete JSON from LLM:\n{text[:1500]}"
    )
