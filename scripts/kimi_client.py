"""
Shared Kimi (Moonshot) client.

Uses the OpenAI-compatible endpoint at https://api.moonshot.ai/v1.
Requires MOONSHOT_API_KEY in env.
"""
import os
import sys
import base64
import json
from pathlib import Path

DEFAULT_BASE_URL = "https://api.moonshot.ai/v1"
# kimi-k2-turbo-preview = K2 family, no invisible reasoning, ~5x cheaper +
# faster than kimi-k2.6 for text-only JSON / chat tasks. Vision tasks fall
# back to kimi-k2.6 (the only K2 model with reliable vision input).
DEFAULT_MODEL        = os.environ.get("KIMI_MODEL",        "kimi-k2-turbo-preview")
DEFAULT_VISION_MODEL = os.environ.get("KIMI_VISION_MODEL", "kimi-k2.6")


def get_client():
    try:
        from openai import OpenAI
    except ImportError:
        print("openai SDK missing. Run: pip install openai", file=sys.stderr)
        sys.exit(2)
    key = os.environ.get("MOONSHOT_API_KEY") or os.environ.get("KIMI_API_KEY")
    if not key:
        print("MOONSHOT_API_KEY not set in env.", file=sys.stderr)
        sys.exit(2)
    return OpenAI(api_key=key,
                  base_url=os.environ.get("KIMI_BASE_URL", DEFAULT_BASE_URL))


def _resolve_temperature(model, requested):
    """`kimi-k2.X` thinking models reject any temperature except 1.0; others
    pass through what the caller asked for."""
    if _is_thinking_model(model):
        return 1.0
    return requested


# kimi-k2.6 (and any future k2.X without "turbo" / "0905") does invisible
# reasoning before producing output. Empirically they need ~1500-2500 tokens
# of thinking budget for moderately structured prompts. Floor max_tokens
# at 3000 to avoid finish_reason='length' returning empty content.
# kimi-k2-turbo-preview / kimi-k2-0905-preview do NOT think, no floor needed.
_THINKING_MIN_TOKENS = 3000


def _is_thinking_model(model_name):
    m = (model_name or "").lower()
    if "turbo" in m or "0905" in m or "0711" in m:
        return False
    return m.startswith("kimi-k2.") or m == "kimi-k2-thinking"


def _resolve_max_tokens(model, requested):
    if _is_thinking_model(model):
        return max(requested, _THINKING_MIN_TOKENS)
    return requested


def chat(messages, *, model=None, temperature=0.7, max_tokens=800,
         response_format=None):
    """Plain chat completion. Returns the assistant text content."""
    client = get_client()
    use_model = model or DEFAULT_MODEL
    kw = dict(model=use_model,
              messages=messages,
              temperature=_resolve_temperature(use_model, temperature),
              max_tokens=_resolve_max_tokens(use_model, max_tokens))
    if response_format is not None:
        kw["response_format"] = response_format
    resp = client.chat.completions.create(**kw)
    return resp.choices[0].message.content


def chat_json(system, user, *, model=None, temperature=0.5, max_tokens=800):
    """Chat-completion that returns parsed JSON. Tolerates ```json``` fences."""
    raw = chat(
        [{"role": "system", "content": system},
         {"role": "user",   "content": user}],
        model=model, temperature=temperature, max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    return _coerce_json(raw)


def _coerce_json(text):
    text = text.strip()
    if text.startswith("```"):
        # strip ``` fences
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # last-resort: find the first {...} block
        s = text.find("{"); e_idx = text.rfind("}")
        if s >= 0 and e_idx > s:
            return json.loads(text[s:e_idx + 1])
        raise


def vision_pick(prompt, image_paths, *, model=None, temperature=0.3,
                max_tokens=200):
    """Send N images + a prompt; return the assistant text. Each image must
    be a path to a local file (jpg/png/webp). Defaults to DEFAULT_VISION_MODEL
    (kimi-k2.6) since text models don't accept image input."""
    content = [{"type": "text", "text": prompt}]
    for p in image_paths:
        b64 = base64.b64encode(Path(p).read_bytes()).decode()
        ext = Path(p).suffix.lower().lstrip(".") or "jpeg"
        if ext == "jpg":
            ext = "jpeg"
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/{ext};base64,{b64}"},
        })
    return chat([{"role": "user", "content": content}],
                model=model or DEFAULT_VISION_MODEL,
                temperature=temperature, max_tokens=max_tokens)
