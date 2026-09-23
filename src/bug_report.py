"""Bug report packaging and upload for TechReader.

The Tools -> "Report a problem" menu entry uses this module to package the
reader's log together with minimal system info and hand the user a link
they can paste into Telegram, e-mail, or a GitHub issue.

Design rules:

* Blind-first: the whole flow is speakable, and the only thing the user
  must handle is a link -- which is also copied to the clipboard.
* Keyless upload: no accounts, no API keys. The report text is posted to
  a public paste service with a 7-day expiry (dpaste.com first,
  paste.rs as fallback) so nothing is stored permanently anywhere.
* Everything the app writes (the report zip included) lives under
  %APPDATA%\\TechReader, never in the program folder.
* The network call never runs on the wx main thread, so a slow or dead
  connection cannot freeze the reader.
"""

import os
import platform
import sys
import zipfile
from datetime import datetime

import config

DAYS = "7"  # paste expiry, in days

_UPLOAD_TIMEOUT_S = 20

# dpaste.com API v2: form POST "content", optional "expiry_days".
_DPASTE_URL = "https://dpaste.com/api/v2/"
# paste.rs: raw body POST, response is the paste URL.
_PASTERs_URL = "https://paste.rs/"


def collect_report_text():
    """The report body: system info header plus the reader's log."""
    lines = []
    lines.append("TechReader bug report")
    lines.append("generated: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    lines.append("python: " + sys.version.replace("\n", " "))
    lines.append("frozen exe: " + ("yes" if getattr(sys, "frozen", False) else "no"))
    lines.append("os: " + platform.platform())
    lines.append("machine: " + platform.machine())
    lines.append("--- log ---")
    try:
        log_path = config.log_path()
        with open(log_path, "rb") as f:
            raw = f.read()
        if raw.startswith(b"\xff\xfe") or b"\x00" in raw[:128]:
            text = raw.decode("utf-16-le", errors="replace")
        else:
            text = raw.decode("utf-8", errors="replace")
        lines.append(text.strip() or "(log is empty)")
    except Exception as exc:
        lines.append(f"(log could not be read: {exc})")
    return "\n".join(lines)


def make_report_zip(dest_dir=None):
    """Write bug_report_<timestamp>.zip (log + system info); return path.

    The zip is the offline fallback: if the upload fails the user still
    has a single file to attach to a message.
    """
    if dest_dir is None:
        dest_dir = config.data_dir()
    os.makedirs(dest_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(dest_dir, f"bug_report_{stamp}.zip")
    report = collect_report_text()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("report.txt", report)
    return path


def upload_report_text(text):
    """Upload report text; return the paste URL, or None on failure.

    Tries dpaste.com (7-day expiry) first, then paste.rs. Both need no
    account or key. Runs on a worker thread -- never the UI thread.
    """
    import urllib.error
    import urllib.parse
    import urllib.request

    ua = "TechReader-bugreport/1.0"
    # 1. dpaste.com
    try:
        data = urllib.parse.urlencode(
            {"content": text, "expiry_days": DAYS}).encode("utf-8")
        req = urllib.request.Request(
            _DPASTE_URL, data=data,
            headers={"User-Agent": ua,
                     "Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=_UPLOAD_TIMEOUT_S) as resp:
            url = resp.read().decode("utf-8", "replace").strip()
        if url.startswith("http"):
            return url
    except Exception:
        pass
    # 2. paste.rs
    try:
        req = urllib.request.Request(
            _PASTERs_URL, data=text.encode("utf-8"),
            headers={"User-Agent": ua})
        with urllib.request.urlopen(req, timeout=_UPLOAD_TIMEOUT_S) as resp:
            url = resp.read().decode("utf-8", "replace").strip()
        if url.startswith("http"):
            return url
    except Exception:
        pass
    return None
