import json
import subprocess
import sys
import time
import urllib.request

def poll_run(run_id: str, interval: int = 30, max_minutes: int = 120):
    cmd = ['git', 'credential', 'fill']
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    out, _ = proc.communicate('protocol=https\nhost=github.com\n')
    token = None
    for line in out.splitlines():
        if line.startswith('password='):
            token = line.split('=', 1)[1]

    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': 'TestTeller-Bot'
    }

    url = f'https://api.github.com/repos/agooll/ai-test-automation-platform/actions/runs/{run_id}'
    start_time = time.time()
    max_seconds = max_minutes * 60

    print(f"Starting poll for run {run_id} every {interval}s (max {max_minutes}m)...")
    last_status = None
    while time.time() - start_time < max_seconds:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode())
                status = data.get('status')
                conclusion = data.get('conclusion')
                elapsed = int(time.time() - start_time)
                if status != last_status or elapsed % 120 < interval:
                    print(f"[{elapsed//60}m {elapsed%60}s] Status: {status}, Conclusion: {conclusion}")
                    last_status = status
                if status == 'completed':
                    print(f"Run {run_id} finished with conclusion: {conclusion}")
                    return conclusion == 'success'
        except Exception as e:
            print(f"Poll error: {e}")
        time.sleep(interval)

    print("Poll timed out.")
    return False

if __name__ == '__main__':
    run_id = sys.argv[1] if len(sys.argv) > 1 else '33987821152'
    success = poll_run(run_id)
    sys.exit(0 if success else 1)
