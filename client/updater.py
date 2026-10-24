"""In-session auto-update for the packaged hexbot executable.

The release workflow publishes a rolling GitHub release "latest". Its notes contain the build's git sha, and
the binary embeds its own sha (client/_build.py, written by CI). While no game is in progress, the bot polls
the GitHub API about every 2 minutes (unauthenticated, If-None-Match/ETag, honouring rate-limit resets).
When the sha changes it downloads the new asset next to the running one, checks that it runs (--version
prints the new sha), swaps it in (Windows: running exe -> .old, then new -> exe) and re-executes with the same
arguments. The token travels to the new process only through the environment, never on the command line.
"""
import json
import os
import platform
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

try:
    from _build import BUILD_SHA  # written by CI before packaging
except ImportError:
    BUILD_SHA = "dev"

REPO = "srikdhruv/hex-capture"
API = f"https://api.github.com/repos/{REPO}/releases/tags/latest"
DOWNLOAD = f"https://github.com/{REPO}/releases/download/latest/"
FROZEN = getattr(sys, "frozen", False)
SHA_RE = re.compile(r"\b[0-9a-f]{40}\b")


def asset_name():
    if sys.platform == "win32":
        return "hexbot-windows-x64.exe"
    if sys.platform == "darwin":
        return "hexbot-macos-arm64" if platform.machine().lower() in ("arm64", "aarch64") else "hexbot-macos-x64"
    return "hexbot-linux-x64"


class Updater:
    def __init__(self, log):
        self.log = log
        self.etag = None
        self.latest_sha = None
        self.not_before = 0.0  # rate-limit / failure backoff (epoch seconds)
        self.failed_sha = None

    def enabled(self):
        return FROZEN and BUILD_SHA != "dev" and not os.environ.get("HEXBOT_NO_UPDATE")

    def check(self):
        """Return the latest release sha (cached via ETag), or None if unknown/rate limited."""
        if time.time() < self.not_before:
            return self.latest_sha
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "hexbot-updater"}
        if self.etag:
            headers["If-None-Match"] = self.etag
        try:
            with urllib.request.urlopen(urllib.request.Request(API, headers=headers), timeout=15) as r:
                self.etag = r.headers.get("ETag") or self.etag
                data = json.load(r)
            m = SHA_RE.search(data.get("body") or "") or SHA_RE.search(data.get("name") or "")
            if m:
                self.latest_sha = m.group(0)
        except urllib.error.HTTPError as e:
            if e.code == 304:
                return self.latest_sha
            if e.code in (403, 429):
                reset = e.headers.get("X-RateLimit-Reset") or ""
                retry = e.headers.get("Retry-After") or ""
                wait = float(retry) if retry.isdigit() else (max(60.0, float(reset) - time.time()) if reset.isdigit() else 900.0)
                self.not_before = time.time() + min(wait, 3600)
                self.log(f"update check rate limited; next check in {int(min(wait, 3600))}s")
            else:
                self.not_before = time.time() + 600
        except Exception:  # noqa: BLE001 - network hiccup: try again later
            self.not_before = time.time() + 300
        return self.latest_sha

    def newer_available(self):
        sha = self.check()
        return sha if sha and sha != BUILD_SHA and sha != self.failed_sha else None

    def install(self, sha):
        """Download + verify + swap. Returns the path of the (new) executable, or None on failure."""
        cur = os.path.abspath(sys.executable)
        new = cur + ".new"
        try:
            self.log(f"downloading update {sha[:12]} ({asset_name()}) ...")
            req = urllib.request.Request(DOWNLOAD + asset_name(), headers={"User-Agent": "hexbot-updater"})
            with urllib.request.urlopen(req, timeout=180) as r, open(new, "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
            os.chmod(new, 0o755)
            if sys.platform == "darwin":
                subprocess.run(["xattr", "-d", "com.apple.quarantine", new], capture_output=True)
            env = clean_env(os.environ)
            env.pop("STRATEGYJAM_TOKEN", None)
            out = subprocess.run([new, "--version"], capture_output=True, text=True, timeout=120, env=env)
            got = (out.stdout or "").strip().split()
            if out.returncode != 0 or not got or got[0] != sha:
                raise RuntimeError(f"new binary reports {got[:1]} (exit {out.returncode}), expected {sha[:12]}")
            if os.name == "nt":
                old = cur + ".old"
                try:
                    os.remove(old)
                except OSError:
                    pass
                os.replace(cur, old)  # a running exe can be renamed, not overwritten
                os.replace(new, cur)
            else:
                os.replace(new, cur)  # atomic; the running process keeps its inode
            return cur
        except Exception as e:  # noqa: BLE001
            self.log(f"update to {sha[:12]} failed: {e}; staying on {BUILD_SHA[:12]}")
            self.failed_sha = sha
            self.not_before = time.time() + 600
            try:
                os.remove(new)
            except OSError:
                pass
            return None


def clean_env(env):
    """Environment for a fresh PyInstaller instance (don't reuse the old extraction dir)."""
    e = {k: v for k, v in env.items() if not k.startswith("_PYI") and k != "_MEIPASS2"}
    e["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return e


def reexec(exe, argv, token, updated_from):
    """Replace this process with `exe argv...`; the token goes through the environment only."""
    env = clean_env(os.environ)
    if token:
        env["STRATEGYJAM_TOKEN"] = token
    env["HEXBOT_UPDATED_FROM"] = updated_from
    args = [exe] + list(argv)
    sys.stdout.flush()
    sys.stderr.flush()
    if os.name == "nt":
        rc = subprocess.call(args, env=env)
        os._exit(rc)
    os.execve(exe, args, env)


def cleanup_old():
    if FROZEN and os.name == "nt":
        try:
            os.remove(os.path.abspath(sys.executable) + ".old")
        except OSError:
            pass
