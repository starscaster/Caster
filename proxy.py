from flask import Flask, request, Response, jsonify
import requests, json, os

app = Flask(__name__)

# ===== User-configurable parameters =====
CONFIG = {
    "model": "deepseek-v4-flash",          # Pro or Flash?
    "temperature": 0.7,                   # creativity (0~2)
    "top_p": 1,                        # sampling range
    "max_tokens": 256000,                   # max output length
    "thinking_enabled": True,               # enable thinking by default
    "thinking_mode": "max",                # None / "low" / "medium" / "high"
    "api_key": os.getenv("DEEPSEEK_KEY"),
    "api_base": "https://api.deepseek.com"
}

MODEL_MAP = {
    "deepseek-v4-flash-thinking": {"model": "deepseek-v4-flash", "thinking_mode": "high"},
    "deepseek-v4-flash-max": {"model": "deepseek-v4-flash", "thinking_mode": "max"},
    "deepseek-v4-pro-thinking": {"model": "deepseek-v4-pro", "thinking_mode": "high"},
    "deepseek-v4-pro-max": {"model": "deepseek-v4-pro", "thinking_mode": "max"},
}

class ReasoningCache:
    def __init__(self):
        self._tool_reasoning = {}  # tool_call_id -> reasoning_content
        self._last_reasoning = None

    def save(self, tool_calls, reasoning_content):
        if not reasoning_content:
            return
        self._last_reasoning = reasoning_content
        if tool_calls:
            for tc in tool_calls:
                tc_id = tc.get("id")
                if tc_id:
                    self._tool_reasoning[tc_id] = reasoning_content

    def get_reasoning(self, messages):
        has_tool_call_round = any(
            msg.get("role") == "assistant" and "tool_calls" in msg
            for msg in messages
        )
        if not has_tool_call_round:
            return {}
        result = {}
        for i, msg in enumerate(messages):
            if msg.get("role") == "assistant" and not msg.get("reasoning_content"):
                reasoning = None
                for tc in msg.get("tool_calls", []):
                    tc_id = tc.get("id")
                    if tc_id and tc_id in self._tool_reasoning:
                        reasoning = self._tool_reasoning[tc_id]
                        break
                if reasoning is None:
                    reasoning = self._last_reasoning
                if reasoning:
                    result[i] = reasoning
        return result


cache = ReasoningCache()

def get_api_key():
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    body_key = request.json.get("api_key") if request.is_json else None
    if body_key:
        return body_key
    return CONFIG["api_key"] or None

def build_cors_response(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return resp

@app.route('/v1/models', methods=['GET', 'OPTIONS'])
def list_models():
    if request.method == 'OPTIONS':
        return build_cors_response(Response())
    models = [
        {
            "id": model_id,
            "object": "model",
            "created": 1745800000,
            "owned_by": "deepseek"
        }
        for model_id in MODEL_MAP
    ]
    return build_cors_response(jsonify({"object": "list", "data": models}))

@app.route('/v1/chat/completions', methods=['POST'])
def proxy():
    data = request.json
    
    if not data or not data.get("messages"):
        return build_cors_response(jsonify({"error": {"message": "messages is required"}})), 400
    
    api_key = get_api_key()
    if not api_key:
        return build_cors_response(jsonify({"error": {"message": "API key is required"}})), 401

    client_model = data.get("model", CONFIG["model"])
    mapping = MODEL_MAP.get(client_model)
    if mapping:
        data["model"] = mapping["model"]
        thinking_mode = mapping["thinking_mode"]
    else:
        data["model"] = client_model
        thinking_mode = CONFIG["thinking_mode"]

    data["temperature"] = data.get("temperature", CONFIG["temperature"])
    data["top_p"] = data.get("top_p", CONFIG["top_p"])
    data["max_tokens"] = data.get("max_tokens", CONFIG["max_tokens"])

    has_tools = bool(data.get("tools")) or (data.get("tool_choice") not in (None, "none"))

    if "thinking" not in data:
        if CONFIG["thinking_enabled"] and thinking_mode:
            data["thinking"] = {"type": "enabled"}
        elif not CONFIG["thinking_enabled"]:
            data["thinking"] = {"type": "disabled"}
    if "reasoning_effort" not in data and thinking_mode and CONFIG["thinking_enabled"]:
        data["reasoning_effort"] = thinking_mode
    thinking_enabled = (
        data.get("thinking", {}).get("type") == "enabled"
        or "reasoning_effort" in data
    )
    if thinking_enabled:
        reasoning_map = cache.get_reasoning(data.get("messages", []))
        for idx, rt in reasoning_map.items():
            data["messages"][idx]["reasoning_content"] = rt

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    extra_kwargs = data.pop("extra_kwargs", {})
    if not isinstance(extra_kwargs, dict):
        extra_kwargs = {}

    try:
        resp = requests.post(
            f"{CONFIG['api_base']}/chat/completions",
            headers=headers,
            json=data,
            stream=data.get("stream", True),
            timeout=extra_kwargs.get("timeout", 360),
            proxies=extra_kwargs.get("proxies", None)
        )
        if resp.status_code >= 400:
            detail = resp.text
            print(f"[proxy] upstream returned {resp.status_code}, body: {detail}")
            print(f"[proxy] request body: {json.dumps(data, ensure_ascii=False, indent=2)}")
            return build_cors_response(jsonify({"error": {"message": f"upstream error: {detail}"}})), resp.status_code
    except requests.exceptions.RequestException as e:
        status = e.response.status_code if e.response else 502
        detail = e.response.text if e.response else str(e)
        print(f"[proxy] request failed: {status}, {detail}")
        return build_cors_response(jsonify({"error": {"message": f"upstream error: {detail}"}})), status

    if not data.get("stream", True):
        return build_cors_response(Response(resp.content, content_type=resp.headers.get("content-type", "application/json")))

    def generate():
        current_reasoning = []
        stream_tool_calls = []
        for chunk in resp.iter_lines():
            if chunk:
                line = chunk.decode()
                if line.startswith("data: "):
                    payload = line[6:].strip()
                    if payload == "[DONE]":
                        yield f"data: [DONE]\n\n"
                        if current_reasoning or stream_tool_calls:
                            cache.save(stream_tool_calls, "".join(current_reasoning))
                        return
                    try:
                        ch = json.loads(payload)
                    except json.JSONDecodeError:
                        yield f"data: {payload}\n\n"
                        continue
                    delta = ch.get("choices", [{}])[0].get("delta", {})
                    rt = delta.get("reasoning_content")
                    if rt:
                        current_reasoning.append(rt)
                    tcs = delta.get("tool_calls")
                    if tcs:
                        for tc in tcs:
                            idx = tc.get("index")
                            while len(stream_tool_calls) <= idx:
                                stream_tool_calls.append({})
                            stream_tool_calls[idx] = {
                                **stream_tool_calls[idx],
                                **{k: v for k, v in tc.items() if k != "index"}
                            }
                    yield f"data: {json.dumps(ch)}\n\n"
        if current_reasoning or stream_tool_calls:
            cache.save(stream_tool_calls, "".join(current_reasoning))

    return build_cors_response(Response(generate(), content_type='text/event-stream'))

if __name__ == '__main__':
    port = int(os.getenv("PROXY_PORT", "20262"))
    print(f"proxy started: http://localhost:{port}")
    print(f"config: model={CONFIG['model']}, temperature={CONFIG['temperature']}, "
          f"thinking={CONFIG['thinking_mode']}")
    app.run(port=port, debug=True)
