import multiprocessing
import os
from dotenv import load_dotenv
import subprocess
import sys
import time


def supervise(name, command, restart_delay=5):
    while True:
        print(f"[entrypoint] starting {name}: {' '.join(command)}", flush=True)
        completed = subprocess.run(command)
        print(f"[entrypoint] {name} exited with code {completed.returncode}; restarting in {restart_delay}s", flush=True)
        time.sleep(restart_delay)


def run_web():
    supervise(
        "web",
        [sys.executable, "web_server.py", "--host", "0.0.0.0", "--port", "5000"],
    )


def run_score_api():
    # Cookie introspection goes back to the original account-owning process.
    os.environ.setdefault("NFC_AUTH_PROFILE_URL", "http://127.0.0.1:5000/api/session")
    os.environ.setdefault("NFC_VISION_ENABLED", "true")
    os.environ.setdefault("NFC_MOCK_AUTH_ENABLED", "false")
    supervise("score-api", [sys.executable, "-m", "uvicorn", "mahjong_api.main:app",
                           "--host", "127.0.0.1", "--port", "8001", "--workers", "1"])


def run_bot():
    supervise("discord-bot", [sys.executable, "main.py"])


def main():
    load_dotenv(os.getenv("NFC_ENV_FILE", ".env.nfc"))
    processes = [
        multiprocessing.Process(target=run_web, name="web"),
        multiprocessing.Process(target=run_bot, name="discord-bot"),
        multiprocessing.Process(target=run_score_api, name="score-api"),
    ]

    for process in processes:
        process.start()

    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
