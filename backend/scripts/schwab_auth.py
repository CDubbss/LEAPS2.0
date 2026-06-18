"""
One-time Schwab OAuth authentication script.

Run this once from the project root to generate the token file.
After that, the backend loads the token automatically on every startup.

Usage (from project root, with backend venv activated):
    backend/.venv/Scripts/python.exe -m backend.scripts.schwab_auth

What it does:
    1. Opens a browser tab to Schwab's OAuth login page.
    2. You log in with your Schwab account (use the secondary developer account).
    3. Schwab redirects to https://127.0.0.1:8182/ — schwab-py captures the code
       automatically via a local HTTP server.
    4. Token is saved to SCHWAB_TOKEN_PATH (backend/.schwab_token.json by default).
    5. schwab-py handles token refresh automatically; you don't need to re-run this
       unless you revoke the app's access or delete the token file.

Prerequisite:
    In your Schwab developer app settings, the Redirect URI must be set to:
        https://127.0.0.1:8182/
    (Exact match required — no trailing path, include the trailing slash.)
"""

import sys
from pathlib import Path

# Ensure project root is on sys.path so `backend.config` is importable
_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def main() -> None:
    try:
        import schwab
    except ImportError:
        print("ERROR: schwab-py is not installed.")
        print("Run:  backend/.venv/Scripts/pip.exe install schwab-py")
        sys.exit(1)

    from backend.config.settings import get_settings

    settings = get_settings()

    if not settings.SCHWAB_APP_KEY or not settings.SCHWAB_APP_SECRET:
        print("ERROR: SCHWAB_APP_KEY and SCHWAB_APP_SECRET must be set in backend/.env")
        sys.exit(1)

    # Resolve token path relative to project root
    token_path = Path(settings.SCHWAB_TOKEN_PATH)
    if not token_path.is_absolute():
        token_path = _project_root / token_path
    token_path.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Schwab OAuth Login")
    print("=" * 60)
    print(f"  App Key   : {settings.SCHWAB_APP_KEY[:8]}...")
    print(f"  Token file: {token_path}")
    print(f"  Callback  : {settings.SCHWAB_CALLBACK_URL}")
    print()
    print("IMPORTANT — your Schwab developer app must have this exact")
    print("redirect URI registered (Settings → Redirect URIs):")
    print(f"    {settings.SCHWAB_CALLBACK_URL}")
    print()
    print("A browser window will open. Log in with your Schwab account.")
    print("After authorising, schwab-py captures the callback automatically.")
    print()
    input("Press Enter to open the browser...")

    try:
        schwab.auth.client_from_login_flow(
            api_key=settings.SCHWAB_APP_KEY,
            app_secret=settings.SCHWAB_APP_SECRET,
            callback_url=settings.SCHWAB_CALLBACK_URL,
            token_path=str(token_path),
        )
    except Exception as e:
        print(f"\nAuthentication failed: {e}")
        sys.exit(1)

    # Encrypt the token file at rest if a key is configured.
    if settings.SCHWAB_TOKEN_KEY:
        try:
            from cryptography.fernet import Fernet
            fernet = Fernet(settings.SCHWAB_TOKEN_KEY.encode())
            encrypted = fernet.encrypt(token_path.read_bytes())
            enc_path = token_path.parent / (token_path.stem + ".enc")
            enc_path.write_bytes(encrypted)
            token_path.unlink()  # delete plaintext
            print()
            print(f"Success!  Token encrypted and saved to: {enc_path}")
        except Exception as e:
            print(f"\nWarning: encryption failed ({e}). Plaintext token kept at {token_path}.")
    else:
        print()
        print(f"Success!  Token saved to: {token_path}")
        print()
        print("Tip: set SCHWAB_TOKEN_KEY in backend/.env to encrypt the token at rest.")
        print("     Generate a key with:")
        print('     python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"')

    print()
    print("Restart the backend (start.bat) — SchwabClient will load automatically.")


if __name__ == "__main__":
    main()
