"""Run the existing website plus its private score API, without the Discord bot."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

from dotenv import load_dotenv


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--api-port", type=int, default=8001)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / os.getenv("NFC_ENV_FILE", ".env.nfc"))
    env = os.environ.copy()
    env["NFC_API_URL"] = f"http://127.0.0.1:{args.api_port}"
    env["NFC_AUTH_PROFILE_URL"] = f"http://127.0.0.1:{args.port}/api/session"
    env.setdefault("NFC_VISION_ENABLED", "true")
    env.setdefault("NFC_MOCK_AUTH_ENABLED", "false")
    children = []
    try:
        for command in (
            [sys.executable, "-m", "uvicorn", "mahjong_api.main:app", "--host", "127.0.0.1", "--port", str(args.api_port), "--workers", "1"],
            [sys.executable, "web_server.py", "--host", args.host, "--port", str(args.port)],
        ):
            children.append(subprocess.Popen(command, cwd=root, env=env))
        print(f"Website and photo scoring: http://{args.host}:{args.port}/score?table=1", flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(.5)
    except KeyboardInterrupt:
        pass
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    main()
