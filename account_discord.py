"""Discord OAuth uses the existing account fields; tokens are never persisted."""
import hashlib
import os
import re
import secrets
import time
from urllib.parse import urlencode
import requests
import registered_names as names
from account_registration import safe_return

_states = {}


def avatar(account):
    return account.get("avatar", "") or account.get("discord_avatar", "")


def bind(path, account_id, discord_id, discord_name, image=""):
    if not re.fullmatch(r"\d{15,22}", str(discord_id)):
        raise ValueError("Invalid Discord account.")
    with names.account_lock(path):
        directory = names.read_accounts(path)
        user = next((a for a in directory["users"].values() if str(a.get("account_id")) == str(account_id)), None)
        if not user or user.get("disabled") or user.get("is_active") is False or user.get("status") in {"pending_claim", "banned", "disabled", "deleted"}:
            raise ValueError("This account is unavailable.")
        if any(a is not user and str(a.get("discord_id", "")) == str(discord_id) for a in directory["users"].values()):
            raise ValueError("This Discord account is already bound. Unbind it from the original account first.")
        user.update(discord_id=str(discord_id), discord_name=str(discord_name), discord_avatar=image)
        names.write_accounts(path, directory)
        return user["name"]


def unbind(user):
    for key in ("discord_id", "discord_name", "discord_avatar"):
        user.pop(key, None)


def configured():
    return all(os.getenv(k) for k in ("DISCORD_CLIENT_ID", "DISCORD_CLIENT_SECRET", "DISCORD_REDIRECT_URI"))


def start(account_id, session_cookie, destination):
    if not configured():
        raise ValueError("Discord binding is currently unavailable. You can skip it and bind later in Account Settings.")
    now = time.time()
    for old in list(_states):
        if _states[old]["expires"] < now:
            _states.pop(old, None)
    nonce = secrets.token_urlsafe(32)
    _states[nonce] = {"id": account_id, "session": hashlib.sha256(session_cookie.encode()).hexdigest(),
                      "return_to": safe_return(destination), "expires": now + 600}
    return "https://discord.com/oauth2/authorize?" + urlencode({"client_id": os.environ["DISCORD_CLIENT_ID"],
        "redirect_uri": os.environ["DISCORD_REDIRECT_URI"], "response_type": "code", "scope": "identify", "state": nonce})


def complete(path, query, account_id, session_cookie):
    state = _states.pop(query.get("state", ""), None)
    if (not state or state["expires"] < time.time() or state["id"] != account_id
            or not secrets.compare_digest(state["session"], hashlib.sha256(session_cookie.encode()).hexdigest())):
        raise ValueError("Discord authorization expired or is invalid. Please try again.")
    if query.get("error") or not query.get("code"):
        return state["return_to"], False
    try:
        response = requests.post("https://discord.com/api/oauth2/token", data={"grant_type": "authorization_code",
            "code": query["code"], "redirect_uri": os.environ["DISCORD_REDIRECT_URI"]},
            auth=(os.environ["DISCORD_CLIENT_ID"], os.environ["DISCORD_CLIENT_SECRET"]), timeout=10, allow_redirects=False)
        response.raise_for_status()
        token = response.json()["access_token"]
        response = requests.get("https://discord.com/api/v10/users/@me", headers={"Authorization": "Bearer " + token}, timeout=10, allow_redirects=False)
        response.raise_for_status()
        person = response.json()
        uid, image_hash = str(person["id"]), person.get("avatar")
        image = "https://cdn.discordapp.com/avatars/" + uid + "/" + image_hash + ".png?size=128" if image_hash and re.fullmatch(r"[a-zA-Z0-9_]+", image_hash) else ""
        bind(path, account_id, uid, person.get("global_name") or person.get("username", "Discord"), image)
    except (requests.RequestException, KeyError, ValueError):
        return state["return_to"], False
    return state["return_to"], True
