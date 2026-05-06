import urllib.request
import json

data = json.dumps({
    "model": "bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0",
    "messages": [{"role": "user", "content": "EKS 클러스터에서 OOM 에러가 발생했을 때 어떻게 대응해야 하나요? 간단히 답해주세요."}],
    "max_tokens": 200
}).encode()

req = urllib.request.Request(
    "http://localhost:8080/v1/chat/completions",
    data=data,
    headers={"Content-Type": "application/json"}
)

try:
    resp = urllib.request.urlopen(req, timeout=30)
    result = json.loads(resp.read())
    print("SUCCESS!")
    msg = result["choices"][0]["message"]["content"]
    print(f"Response: {msg}")
    print(f"Model: {result.get('model')}")
    usage = result.get("usage", {})
    print(f"Tokens - prompt: {usage.get('prompt_tokens')}, completion: {usage.get('completion_tokens')}")
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}: {e.read().decode()}")
