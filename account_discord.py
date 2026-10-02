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
_admin_setup_grants = {}


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


def _authorization_url(nonce):
    return "https://discord.com/oauth2/authorize?" + urlencode({
        "client_id": os.environ["DISCORD_CLIENT_ID"],
        "redirect_uri": os.environ["DISCORD_REDIRECT_URI"],
        "response_type": "code", "scope": "identify", "state": nonce,
    })


def _clean_expired_states(now):
    for old in list(_states):
        if _states[old]["expires"] < now:
            _states.pop(old, None)
    for old in list(_admin_setup_grants):
        if _admin_setup_grants[old]["expires"] < now:
            _admin_setup_grants.pop(old, None)


def start(account_id, session_cookie, destination):
    if not configured():
        raise ValueError("Discord binding is currently unavailable. You can skip it and bind later in Account Settings.")
    now = time.time()
    _clean_expired_states(now)
    nonce = secrets.token_urlsafe(32)
    _states[nonce] = {"id": account_id, "purpose": "bind",
                      "session": hashlib.sha256(session_cookie.encode()).hexdigest(),
                      "return_to": safe_return(destination), "expires": now + 600}
    return _authorization_url(nonce)


def start_admin_password_setup(account_id, expected_discord_id):
    if not configured():
        raise ValueError("Discord verification is currently unavailable. Please try again later.")
    if not re.fullmatch(r"\d{15,22}", str(expected_discord_id or "")):
        raise ValueError("This administrator account has no verified recovery method. Contact FuYun.")
    now = time.time()
    _clean_expired_states(now)
    nonce = secrets.token_urlsafe(32)
    _states[nonce] = {
        "id": str(account_id), "purpose": "admin_password_setup",
        "discord_id": str(expected_discord_id),
        "return_to": "/login#admin-password-setup", "expires": now + 600,
    }
    return _authorization_url(nonce)


def is_admin_password_setup_state(nonce):
    state = _states.get(str(nonce or ""))
    return bool(state and state.get("purpose") == "admin_password_setup")


def _discord_person(query):
    response = requests.post("https://discord.com/api/oauth2/token", data={
        "grant_type": "authorization_code", "code": query["code"],
        "redirect_uri": os.environ["DISCORD_REDIRECT_URI"],
    }, auth=(os.environ["DISCORD_CLIENT_ID"], os.environ["DISCORD_CLIENT_SECRET"]),
       timeout=10, allow_redirects=False)
    response.raise_for_status()
    token = response.json()["access_token"]
    response = requests.get("https://discord.com/api/v10/users/@me",
        headers={"Authorization": "Bearer " + token}, timeout=10, allow_redirects=False)
    response.raise_for_status()
    return response.json()


def complete_admin_password_setup(path, query, is_admin_account):
    state = _states.pop(query.get("state", ""), None)
    if (not state or state.get("purpose") != "admin_password_setup"
            or state["expires"] < time.time()):
        raise ValueError("Administrator verification expired. Please start again.")
    if query.get("error") or not query.get("code"):
        raise ValueError("Discord verification was not completed.")
    try:
        person = _discord_person(query)
        discord_id = str(person["id"])
    except (requests.RequestException, KeyError, ValueError):
        raise ValueError("Discord verification could not be completed. Please try again.") from None
    if not secrets.compare_digest(discord_id, state["discord_id"]):
        raise ValueError("This Discord account is not linked to that administrator.")

    with names.account_lock(path):
        directory = names.read_accounts(path)
        account = next((item for item in directory["users"].values()
                        if str(item.get("account_id")) == state["id"]), None)
        if (not account or not is_admin_account(account) or account.get("password_hash")
                or str(account.get("discord_id") or "") != discord_id
                or account.get("disabled") or account.get("is_active") is False
                or account.get("status") in {"pending_claim", "disabled", "deleted", "banned"}):
            raise ValueError("This administrator account changed. Please start again or use password recovery.")
        raw = secrets.token_urlsafe(32)
        digest = hashlib.sha256(raw.encode("ascii")).hexdigest()
        _clean_expired_states(time.time())
        _admin_setup_grants[digest] = {
            "account_id": state["id"], "discord_id": discord_id,
            "expires": time.time() + 600,
        }
        return raw


def take_admin_password_setup_grant(raw):
    if not isinstance(raw, str) or len(raw) > 128:
        return None
    digest = hashlib.sha256(raw.encode("ascii", errors="ignore")).hexdigest()
    grant = _admin_setup_grants.pop(digest, None)
    if not grant or grant["expires"] < time.time():
        return None
    return dict(grant)


def complete(path, query, account_id, session_cookie):
    state = _states.pop(query.get("state", ""), None)
    if (not state or state.get("purpose") != "bind" or state["expires"] < time.time() or state["id"] != account_id
            or not secrets.compare_digest(state["session"], hashlib.sha256(session_cookie.encode()).hexdigest())):
        raise ValueError("Discord authorization expired or is invalid. Please try again.")
    if query.get("error") or not query.get("code"):
        return state["return_to"], False
    try:
        person = _discord_person(query)
        uid, image_hash = str(person["id"]), person.get("avatar")
        image = "https://cdn.discordapp.com/avatars/" + uid + "/" + image_hash + ".png?size=128" if image_hash and re.fullmatch(r"[a-zA-Z0-9_]+", image_hash) else ""
        bind(path, account_id, uid, person.get("global_name") or person.get("username", "Discord"), image)
    except (requests.RequestException, KeyError, ValueError):
        return state["return_to"], False
    return state["return_to"], True
