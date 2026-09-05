"""Manage GitHub Actions Benchmark runs via REST API."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import urllib.error

import nacl.encoding
import nacl.public

REPO = "agooll/ai-test-automation-platform"

def get_github_token() -> str:
    """Retrieve GitHub token from env var or git credential helper."""
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token

    # Query git credential helper
    try:
        proc = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n",
            capture_output=True,
            text=True,
            check=True,
        )
        for line in proc.stdout.splitlines():
            if line.startswith("password="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass

    raise RuntimeError("No GitHub token found in GITHUB_TOKEN or git credentials.")

def get_headers() -> dict[str, str]:
    token = get_github_token()
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "TestTeller-Agent",
    }

def set_secret(secret_name: str, secret_value: str) -> bool:
    """Encrypt and set a secret in the GitHub repository."""
    headers = get_headers()

    # 1. Get public key
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/actions/secrets/public-key",
        headers=headers,
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    key_id = data["key_id"]
    public_key_b64 = data["key"]

    # 2. Encrypt secret with libsodium
    public_key_bytes = base64.b64decode(public_key_b64)
    pubkey = nacl.public.PublicKey(public_key_bytes)
    box = nacl.public.SealedBox(pubkey)
    encrypted = box.encrypt(secret_value.encode("utf-8"))
    encrypted_b64 = base64.b64encode(encrypted).decode("utf-8")

    # 3. PUT secret
    payload = json.dumps({"encrypted_value": encrypted_b64, "key_id": key_id}).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/actions/secrets/{secret_name}",
        data=payload,
        headers={**headers, "Content-Type": "application/json"},
        method="PUT",
    )
    with urllib.request.urlopen(req) as resp:
        if resp.status in (201, 204):
            print(f"✅ Secret '{secret_name}' successfully set on GitHub Actions.")
            return True
    return False

def trigger_workflow(mode: str = "smoke", model: str = "gemini-2.5-pro") -> int | None:
    """Trigger the Stage 3 Benchmark workflow on GitHub Actions."""
    headers = get_headers()
    payload = json.dumps({
        "ref": "main",
        "inputs": {
            "mode": mode,
            "model": model,
        }
    }).encode("utf-8")

    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/actions/workflows/stage3_benchmark.yml/dispatches",
        data=payload,
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        if resp.status == 204:
            print(f"🚀 Triggered Stage 3 Benchmark workflow (mode={mode}, model={model}).")

    # Wait for the run to appear
    time.sleep(5)
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/actions/runs?per_page=5",
        headers=headers,
    )
    with urllib.request.urlopen(req) as resp:
        runs = json.loads(resp.read().decode("utf-8")).get("workflow_runs", [])
    for r in runs:
        if r.get("name") == f"Stage 3 Benchmark ({mode})" or "Benchmark" in r.get("name", ""):
            print(f"📋 Found Workflow Run ID: {r['id']} (URL: {r['html_url']})")
            return r["id"]
    return None

if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "help"
    if action == "set-secret":
        key_val = sys.argv[2]
        set_secret("GOOGLE_API_KEY", key_val)
    elif action == "trigger":
        mode = sys.argv[2] if len(sys.argv) > 2 else "smoke"
        trigger_workflow(mode)
    else:
        print("Usage: python manage_github_benchmark.py [set-secret <KEY> | trigger <smoke|dry-run|baseline>]")
