"""SSH-only setup entrypoint. The website uses the same write-only service.
Read JSON from stdin; never accept a key in argv or print exception details.
"""
import json
import os
from pathlib import Path
import sys

from mahjong_api.external_sync import ExternalSync, validate_endpoint, validate_private_key
from mahjong_api.store import Store, Conflict


def configure(data):
    key = validate_private_key(data.get("key"))
    endpoint = validate_endpoint(str(data.get("endpoint", "")).strip())
    store = Store(Path(os.getenv("NFC_DATABASE_PATH", "data/nfc_matches.sqlite3")),
                  os.getenv("NFC_DATABASE_URL", ""))
    try:
        external = ExternalSync(store)
        external.save_config({"endpoint": endpoint, "adapter": "narts", "enabled": True,
                              "api_key": key}, "ssh-admin")
        result = external.test("ssh-admin")
        return {"ok": True, "key_configured": True, "test_code": result["code"]}
    finally:
        store.close()


def main():
    try:
        data = json.loads(sys.stdin.read(16385))
        if not isinstance(data, dict):
            raise ValueError("invalid_input")
        print(json.dumps(configure(data)))
        return 0
    except Conflict as exc:
        print(json.dumps({"ok": False, "code": exc.detail["code"]}))
    except (ValueError, TypeError):
        print(json.dumps({"ok": False, "code": "invalid_input"}))
    except Exception:
        print(json.dumps({"ok": False, "code": "setup_failed"}))
    return 1


if __name__ == "__main__":
    sys.exit(main())
