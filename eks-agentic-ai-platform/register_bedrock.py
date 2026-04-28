import urllib.request
import json
import subprocess
import base64

# Get credentials
ak = subprocess.run(['kubectl', 'get', 'secret', 'bedrock-credentials', '-n', 'ai-inference',
                     '-o', 'jsonpath={.data.aws-access-key-id}'], capture_output=True, text=True).stdout
sk = subprocess.run(['kubectl', 'get', 'secret', 'bedrock-credentials', '-n', 'ai-inference',
                     '-o', 'jsonpath={.data.aws-secret-access-key}'], capture_output=True, text=True).stdout
ak = base64.b64decode(ak).decode()
sk = base64.b64decode(sk).decode()

# Get all bifrost pod names
pods = subprocess.run(['kubectl', 'get', 'pods', '-n', 'ai-inference', '-l', 'app.kubernetes.io/name=bifrost',
                       '-o', 'jsonpath={.items[*].metadata.name}'], capture_output=True, text=True).stdout.split()

print(f"Found {len(pods)} bifrost pods: {pods}")

for pod in pods:
    print(f"\nRegistering bedrock on {pod}...")
    # Port-forward to this specific pod
    import time
    
    # Use kubectl exec to register via localhost inside the pod
    payload = json.dumps({
        "provider": "bedrock",
        "keys": [{
            "name": "bedrock-key-1",
            "models": ["anthropic.claude-haiku-4-5-20251001-v1:0", "global.anthropic.claude-haiku-4-5-20251001-v1:0"],
            "weight": 1.0,
            "bedrock_key_config": {
                "access_key": ak,
                "secret_key": sk,
                "region": "ap-northeast-2"
            }
        }]
    })
    
    # First try to delete existing
    result = subprocess.run([
        'kubectl', 'exec', '-n', 'ai-inference', pod, '--',
        'wget', '-q', '-O', '-', '--method=DELETE', 'http://localhost:8080/api/providers/bedrock'
    ], capture_output=True, text=True, timeout=10)
    print(f"  Delete: {result.stdout[:50] if result.stdout else result.stderr[:50]}")
    
    time.sleep(1)
    
    # Register
    result = subprocess.run([
        'kubectl', 'exec', '-n', 'ai-inference', pod, '--',
        'wget', '-q', '-O', '-', '--post-data', payload,
        '--header', 'Content-Type: application/json',
        'http://localhost:8080/api/providers'
    ], capture_output=True, text=True, timeout=10)
    
    if 'active' in result.stdout:
        print(f"  SUCCESS: provider_status=active")
    else:
        print(f"  Result: {result.stdout[:100]}")
        print(f"  Stderr: {result.stderr[:100]}")
