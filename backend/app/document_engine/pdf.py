"""DOCX -> PDF through LibreOffice headless, isolated per call.

Each conversion gets its own throw-away user profile and working directory, a
hard timeout, and a stripped environment. Output is rendered by LibreOffice,
so it can differ slightly from Word; always say so in the UI.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional


class PdfExportError(RuntimeError):
    pass


_WINDOWS_DIRS = [os.path.join(os.environ.get(v, ""), "LibreOffice", "program", "soffice.exe")
                 for v in ("ProgramFiles", "ProgramFiles(x86)") if os.environ.get(v)]


def soffice_path() -> Optional[str]:
    """SMARTDOC_SOFFICE, then PATH, then the standard Windows install folders."""
    explicit = os.environ.get("SMARTDOC_SOFFICE")
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    return next((p for p in _WINDOWS_DIRS if os.path.isfile(p)), None)


def _kill_tree(proc: subprocess.Popen) -> None:
    """Stop LibreOffice and every process it started."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=15)
        else:
            import signal
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        pass
    try:
        proc.kill()
        proc.communicate(timeout=10)
    except Exception:
        pass


def docx_to_pdf(docx_path: str, out_path: str, timeout: int = 120) -> str:
    exe = soffice_path()
    if exe is None:
        raise PdfExportError("LibreOffice is not installed on the server, so PDF export is unavailable.")
    with tempfile.TemporaryDirectory(prefix="smartdoc-lo-", ignore_cleanup_errors=True) as work:
        profile = os.path.join(work, "profile")
        src = os.path.join(work, "in.docx")
        shutil.copyfile(docx_path, src)
        env = {"PATH": os.environ.get("PATH", ""), "HOME": work, "LANG": "C.UTF-8",
               "TEMP": work, "TMP": work}
        if os.name == "nt" and os.environ.get("SYSTEMROOT"):
            env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]   # Windows processes cannot start without it
        # own process group, so a timeout can stop soffice.bin as well as the launcher in front of it
        group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
                 else {"start_new_session": True})
        proc = subprocess.Popen(
            [exe, f"-env:UserInstallation={Path(profile).as_uri()}", "--headless", "--norestore",
             "--nologo", "--nodefault", "--nolockcheck", "--convert-to", "pdf", "--outdir", work, src],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=work, **group)
        try:
            proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            raise PdfExportError("PDF conversion timed out.")
        produced = os.path.join(work, "in.pdf")
        if not os.path.exists(produced) or os.path.getsize(produced) == 0:
            raise PdfExportError("PDF conversion failed.")
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        shutil.move(produced, out_path)
    return out_path
