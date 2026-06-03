"""
QGIS Package Manager v1.0.1 — Gerenciador de pacotes Python para o QGIS
Arquivo único com detector embutido.
Requer: PySide6  → pip install PySide6
Uso: rode com o Python interno do QGIS ou qualquer Python com PySide6 instalado.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import pathlib
import datetime
import tempfile
import re as _re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional


def _ensure_pyside6() -> None:
    try:
        import PySide6  # type: ignore
    except ModuleNotFoundError:
        print("PySide6 não encontrado. Instalando via pip...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "PySide6"])
        print("PySide6 instalado. Reiniciando importações...")
    else:
        version = getattr(PySide6, "__version__", "0.0.0")
        try:
            major, minor, *_ = map(int, version.split("."))
        except Exception:
            return
        if (major, minor) < (6, 4):
            print(f"Versão do PySide6 ({version}) é inferior à 6.4. Atualizando...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "PySide6"])
            print("PySide6 atualizado.")


_ensure_pyside6()

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QRadioButton, QButtonGroup, QPushButton, QTextEdit,
    QLabel, QScrollArea, QCheckBox, QFrame, QLineEdit,
    QProgressBar, QMessageBox, QStackedWidget,
    QSizePolicy, QComboBox, QFileDialog
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QTextCursor, QDesktopServices
from PySide6.QtCore import QUrl

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class PythonInfo:
    name: str
    version: str
    executable: str
    source: str                   # registry | path_scan | qgis_embedded | conda | venv | extra_path | current_process
    os_name: str
    architecture: str
    is_qgis_python: bool = False
    qgis_version: Optional[str] = None   # preenchido quando is_qgis_python=True

@dataclass
class QGISInfo:
    name: str
    version: str
    install_path: str
    executable: str
    os_name: str
    source: str                   # registry | path_scan | osgeo4w | flatpak | snap | homebrew | app_bundle
    python: Optional[PythonInfo] = None


@dataclass
class DetectionResult:
    system_pythons: List[PythonInfo] = field(default_factory=list)
    qgis_installations: List[QGISInfo] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "system_pythons": [asdict(p) for p in self.system_pythons],
            "qgis_installations": [asdict(q) for q in self.qgis_installations],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _run(cmd: list[str], timeout: int = 10) -> Optional[str]:
    """Executa um comando e retorna stdout, ou None em caso de erro."""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            text=True,
        )
        return result.stdout.strip() or result.stderr.strip()
    except Exception as exc:
        logger.debug("_run(%s) falhou: %s", cmd, exc)
        return None


def _python_version(exe: str) -> Optional[str]:
    """Retorna a versão de um executável Python (ex.: '3.11.4')."""
    out = _run([exe, "--version"])
    if out and out.lower().startswith("python"):
        return out.split()[1]
    return None


def _python_arch(exe: str) -> str:
    out = _run([exe, "-c", "import platform; print(platform.architecture()[0])"])
    return out if out else "unknown"


def _normalize_version(raw: str) -> str:
    """Remove prefixos como 'QGIS ' ou 'v' e retorna apenas números."""
    for prefix in ("QGIS ", "QGIS-", "qgis ", "v", "V"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
    return raw.strip()


def _seen(exes: set, exe: str) -> bool:
    """Desduplicação simples por caminho resolvido."""
    try:
        real = str(Path(exe).resolve())
    except Exception:
        real = exe
    if real in exes:
        return True
    exes.add(real)
    return False


OS_NAME = platform.system()   # 'Windows' | 'Linux' | 'Darwin'


# ──────────────────────────────────────────────────────────────────────────────
# Python standalone – Windows
# ──────────────────────────────────────────────────────────────────────────────

def _win_pythons_from_registry() -> list[PythonInfo]:
    """Lê HKLM e HKCU para encontrar Pythons instalados via instalador oficial."""
    results = []
    try:
        import winreg  # type: ignore
    except ImportError:
        return results

    hives = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Python"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Python"),
        (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Python"),
    ]

    seen: set[str] = set()
    for hive, base_key in hives:
        try:
            base = winreg.OpenKey(hive, base_key)
        except FileNotFoundError:
            continue

        i = 0
        while True:
            try:
                company = winreg.EnumKey(base, i); i += 1
            except OSError:
                break
            try:
                comp_key = winreg.OpenKey(base, company)
            except OSError:
                continue

            j = 0
            while True:
                try:
                    ver_tag = winreg.EnumKey(comp_key, j); j += 1
                except OSError:
                    break
                try:
                    ver_key = winreg.OpenKey(comp_key, ver_tag + r"\InstallPath")
                    exe_path, _ = winreg.QueryValueEx(ver_key, "ExecutablePath")
                    exe_path = str(exe_path)
                    if not exe_path or not Path(exe_path).exists():
                        continue
                    if _seen(seen, exe_path):
                        continue
                    version = _python_version(exe_path) or ver_tag
                    results.append(PythonInfo(
                        name=f"Python {version}",
                        version=version,
                        executable=exe_path,
                        source="registry",
                        os_name="windows",
                        architecture=_python_arch(exe_path),
                    ))
                except OSError:
                    pass
    return results


def _win_pythons_from_paths() -> list[PythonInfo]:
    """Varre paths comuns no Windows em busca de python.exe."""
    patterns = [
        r"C:\Python*\python.exe",
        r"C:\Python*\python3*.exe",
        r"C:\Users\*\AppData\Local\Programs\Python\Python*\python.exe",
        r"C:\Program Files\Python*\python.exe",
        r"C:\Program Files (x86)\Python*\python.exe",
        r"C:\ProgramData\Miniconda*\python.exe",
        r"C:\ProgramData\Anaconda*\python.exe",
        r"C:\Users\*\Miniconda*\python.exe",
        r"C:\Users\*\Anaconda*\python.exe",
        r"C:\Users\*\AppData\Local\Programs\Python\*\python.exe",
        r"C:\msys64\usr\bin\python*.exe",
        r"C:\msys64\mingw64\bin\python*.exe",
    ]
    seen: set[str] = set()
    results = []
    for pattern in patterns:
        for exe in glob.glob(pattern, recursive=False):
            if not Path(exe).is_file():
                continue
            if _seen(seen, exe):
                continue
            version = _python_version(exe)
            if version is None:
                continue
            source = "conda" if "conda" in exe.lower() else "path_scan"
            results.append(PythonInfo(
                name=f"Python {version}",
                version=version,
                executable=exe,
                source=source,
                os_name="windows",
                architecture=_python_arch(exe),
            ))
    return results


# ──────────────────────────────────────────────────────────────────────────────
# Python standalone – Linux / macOS
# ──────────────────────────────────────────────────────────────────────────────

def _unix_pythons_from_paths() -> list[PythonInfo]:
    """Varre paths conhecidos e PATH do sistema em Linux/macOS."""
    os_name = "macos" if OS_NAME == "Darwin" else "linux"

    search_dirs = [
        "/usr/bin", "/usr/local/bin", "/opt/homebrew/bin",
        "/usr/local/opt/python*/bin",
        "/opt/local/bin",
        "/home/linuxbrew/.linuxbrew/bin",
        "/opt/conda/bin", "/opt/miniconda*/bin",
        "/opt/anaconda*/bin",
        "/root/miniconda*/bin",
        "/root/anaconda*/bin",
    ]
    for p in os.environ.get("PATH", "").split(":"):
        if p not in search_dirs:
            search_dirs.append(p)

    candidates: list[str] = []
    for d in search_dirs:
        for exp in glob.glob(d):
            for py in glob.glob(os.path.join(exp, "python*")):
                candidates.append(py)
    pyenv_root = Path.home() / ".pyenv" / "versions"
    if pyenv_root.exists():
        for py in pyenv_root.glob("*/bin/python"):
            candidates.append(str(py))

    seen: set[str] = set()
    results = []
    for exe in candidates:
        p = Path(exe)
        if not p.is_file():
            continue
        if p.name in ("python", "python2", "python3") or p.name.startswith("python3.") or p.name.startswith("python2."):
            if _seen(seen, exe):
                continue
            version = _python_version(exe)
            if version is None:
                continue
            source = "conda" if "conda" in exe else "path_scan"
            results.append(PythonInfo(
                name=f"Python {version}",
                version=version,
                executable=exe,
                source=source,
                os_name=os_name,
                architecture=_python_arch(exe),
            ))
    return results


# ──────────────────────────────────────────────────────────────────────────────
# QGIS – Windows
# ──────────────────────────────────────────────────────────────────────────────

def _win_qgis_python(qgis_root: Path) -> Optional[PythonInfo]:
    """
    Encontra o Python embutido numa instalação QGIS Windows.
    """
    apps_candidates = sorted(
        qgis_root.glob("apps/Python*/python.exe"),
        key=lambda p: p.parts,
        reverse=True,
    )
    for exe in apps_candidates:
        if exe.is_file():
            ver = _python_version(str(exe))
            if ver:
                return PythonInfo(
                    name=f"Python {ver}",
                    version=ver,
                    executable=str(exe),
                    source="qgis_embedded",
                    os_name="windows",
                    architecture=_python_arch(str(exe)),
                    is_qgis_python=True,
                )

    for name in ("python3.exe", "python.exe"):
        exe = qgis_root / "bin" / name
        if exe.is_file():
            ver = _python_version(str(exe))
            if ver:
                return PythonInfo(
                    name=f"Python {ver}",
                    version=ver,
                    executable=str(exe),
                    source="qgis_embedded",
                    os_name="windows",
                    architecture=_python_arch(str(exe)),
                    is_qgis_python=True,
                )

    for exe in sorted(qgis_root.rglob("python3*.exe"), reverse=True):
        if exe.name.lower() in ("python.exe",) or (
            exe.name.lower().startswith("python3") and exe.name.lower().endswith(".exe")
            and len(exe.name) <= len("python3XX.exe")
        ):
            ver = _python_version(str(exe))
            if ver:
                return PythonInfo(
                    name=f"Python {ver}",
                    version=ver,
                    executable=str(exe),
                    source="qgis_embedded",
                    os_name="windows",
                    architecture=_python_arch(str(exe)),
                    is_qgis_python=True,
                )
    return None


def _win_qgis_from_registry() -> list[QGISInfo]:
    r"""HKLM\SOFTWARE\QGIS e chaves de desinstalação."""
    results = []
    try:
        import winreg  # type: ignore
    except ImportError:
        return results

    seen_paths: set[str] = set()

    hives = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\QGIS"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\QGIS"),
    ]
    for hive, key_path in hives:
        try:
            base = winreg.OpenKey(hive, key_path)
        except FileNotFoundError:
            continue
        i = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(base, i); i += 1
            except OSError:
                break
            try:
                sub = winreg.OpenKey(base, subkey_name)
                install_dir, _ = winreg.QueryValueEx(sub, "InstallPath")
                install_dir = str(install_dir).rstrip("\\")
                if _seen(seen_paths, install_dir):
                    continue
                root = Path(install_dir)
                exe = root / "bin" / "qgis-bin.exe"
                if not exe.exists():
                    exe = root / "bin" / "qgis.exe"
                version = _normalize_version(subkey_name)
                py = _win_qgis_python(root)
                if py:
                    py.qgis_version = version
                results.append(QGISInfo(
                    name=f"QGIS {version}",
                    version=version,
                    install_path=install_dir,
                    executable=str(exe),
                    os_name="windows",
                    source="registry",
                    python=py,
                ))
            except OSError:
                pass

    uninstall_keys = [
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    ]
    for key_path in uninstall_keys:
        try:
            base = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
        except FileNotFoundError:
            continue
        i = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(base, i); i += 1
            except OSError:
                break
            try:
                sub = winreg.OpenKey(base, subkey_name)
                display_name, _ = winreg.QueryValueEx(sub, "DisplayName")
                if "qgis" not in str(display_name).lower():
                    continue
                install_dir, _ = winreg.QueryValueEx(sub, "InstallLocation")
                install_dir = str(install_dir).rstrip("\\")
                if not install_dir or _seen(seen_paths, install_dir):
                    continue
                root = Path(install_dir)
                exe = root / "bin" / "qgis-bin.exe"
                if not exe.exists():
                    exe = root / "bin" / "qgis.exe"
                try:
                    raw_ver, _ = winreg.QueryValueEx(sub, "DisplayVersion")
                    version = _normalize_version(str(raw_ver))
                except OSError:
                    version = _normalize_version(str(display_name))
                py = _win_qgis_python(root)
                if py:
                    py.qgis_version = version
                results.append(QGISInfo(
                    name=f"QGIS {version}",
                    version=version,
                    install_path=install_dir,
                    executable=str(exe),
                    os_name="windows",
                    source="registry",
                    python=py,
                ))
            except OSError:
                pass
    return results


def _win_qgis_from_paths() -> list[QGISInfo]:
    seen_paths: set[str] = set()
    results = []

    pf_dirs = []
    for drive_letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        drive = f"{drive_letter}:\\"
        if not os.path.exists(drive):
            continue
        pf_dirs += [
            os.path.join(drive, "Program Files"),
            os.path.join(drive, "Program Files (x86)"),
            drive,
        ]

    standalone_roots: list[str] = []
    osgeo_roots: list[str] = []

    for pf in pf_dirs:
        if not os.path.isdir(pf):
            continue
        standalone_roots += glob.glob(os.path.join(pf, "QGIS*"))
        standalone_roots += glob.glob(os.path.join(pf, "qgis*"))
        osgeo_roots += glob.glob(os.path.join(pf, "OSGeo4W*"))

    for install_dir in standalone_roots:
        install_dir = install_dir.rstrip("\\")
        if not os.path.isdir(install_dir):
            continue
        if _seen(seen_paths, install_dir):
            continue
        root = Path(install_dir)

        exe: Optional[Path] = None
        for candidate_name in ("qgis-bin.exe", "qgis.exe", "qgis-ltr-bin.exe"):
            c = root / "bin" / candidate_name
            if c.exists():
                exe = c
                break
        if exe is None:
            continue

        ver_out = _run([str(exe), "--version"])
        if ver_out:
            version = _normalize_version(ver_out.split("\n")[0])
        else:
            version = _normalize_version(root.name)

        py = _win_qgis_python(root)
        if py:
            py.qgis_version = version

        results.append(QGISInfo(
            name=f"QGIS {version}",
            version=version,
            install_path=str(root),
            executable=str(exe),
            os_name="windows",
            source="path_scan",
            python=py,
        ))

    for osgeo_dir in osgeo_roots:
        osgeo_dir = osgeo_dir.rstrip("\\")
        if not os.path.isdir(osgeo_dir):
            continue
        osgeo_root = Path(osgeo_dir)
        apps_dir = osgeo_root / "apps"
        if not apps_dir.is_dir():
            if not _seen(seen_paths, osgeo_dir):
                exe_c = osgeo_root / "bin" / "qgis-bin.exe"
                if exe_c.exists():
                    ver_out = _run([str(exe_c), "--version"])
                    version = _normalize_version(ver_out.split("\n")[0]) if ver_out else osgeo_root.name
                    py = _win_qgis_python(osgeo_root)
                    if py:
                        py.qgis_version = version
                    results.append(QGISInfo(
                        name=f"QGIS {version}",
                        version=version,
                        install_path=osgeo_dir,
                        executable=str(exe_c),
                        os_name="windows",
                        source="osgeo4w",
                        python=py,
                    ))
            continue

        qgis_app_dirs = sorted(apps_dir.glob("qgis*"), reverse=True)
        if not qgis_app_dirs:
            if not _seen(seen_paths, osgeo_dir):
                exe_c = osgeo_root / "bin" / "qgis-bin.exe"
                if exe_c.exists():
                    ver_out = _run([str(exe_c), "--version"])
                    version = _normalize_version(ver_out.split("\n")[0]) if ver_out else osgeo_root.name
                    py = _win_qgis_python(osgeo_root)
                    if py:
                        py.qgis_version = version
                    results.append(QGISInfo(
                        name=f"QGIS {version}",
                        version=version,
                        install_path=osgeo_dir,
                        executable=str(exe_c),
                        os_name="windows",
                        source="osgeo4w",
                        python=py,
                    ))
            continue

        for qgis_app_dir in qgis_app_dirs:
            if not qgis_app_dir.is_dir():
                continue

            local_exe = qgis_app_dir / "bin" / "qgis-bin.exe"
            suffix = qgis_app_dir.name
            root_bin_exe = osgeo_root / "bin" / f"{suffix}-bin.exe"
            if not root_bin_exe.exists():
                root_bin_exe = osgeo_root / "bin" / "qgis-bin.exe"

            exe = local_exe if local_exe.exists() else (root_bin_exe if root_bin_exe.exists() else None)

            dedup_key = str(osgeo_root) + "|" + suffix
            if dedup_key in seen_paths:
                continue
            seen_paths.add(dedup_key)

            version = None
            if exe and exe.exists():
                ver_out = _run([str(exe), "--version"])
                if ver_out:
                    version = _normalize_version(ver_out.split("\n")[0])

            if not version:
                for meta in [
                    qgis_app_dir / "VERSION",
                    qgis_app_dir / "version.txt",
                    qgis_app_dir / "package_version.txt",
                ]:
                    if meta.exists():
                        raw = meta.read_text(encoding="utf-8", errors="ignore").strip().splitlines()[0]
                        version = _normalize_version(raw)
                        break

            if not version:
                version = suffix

            py = _win_qgis_python(qgis_app_dir) or _win_qgis_python(osgeo_root)
            if py:
                py.qgis_version = version

            results.append(QGISInfo(
                name=f"QGIS {version}",
                version=version,
                install_path=str(qgis_app_dir),
                executable=str(exe) if exe else str(osgeo_root / "bin" / "qgis-bin.exe"),
                os_name="windows",
                source="osgeo4w",
                python=py,
            ))

    return results


# ──────────────────────────────────────────────────────────────────────────────
# QGIS – Linux
# ──────────────────────────────────────────────────────────────────────────────

def _linux_qgis_python(install_path: str, source: str) -> Optional[PythonInfo]:
    root = Path(install_path)

    if source == "snap":
        for exe in sorted(root.glob("**/python3"), reverse=True):
            ver = _python_version(str(exe))
            if ver:
                return PythonInfo(name=f"Python {ver}", version=ver,
                                  executable=str(exe), source="qgis_embedded",
                                  os_name="linux", architecture=_python_arch(str(exe)),
                                  is_qgis_python=True)
    if source == "flatpak":
        for exe in sorted(root.glob("**/python3"), reverse=True):
            ver = _python_version(str(exe))
            if ver:
                return PythonInfo(name=f"Python {ver}", version=ver,
                                  executable=str(exe), source="qgis_embedded",
                                  os_name="linux", architecture=_python_arch(str(exe)),
                                  is_qgis_python=True)

    sys_py = shutil.which("python3") or shutil.which("python")
    if sys_py:
        ver = _python_version(sys_py)
        if ver:
            return PythonInfo(name=f"Python {ver}", version=ver,
                              executable=sys_py, source="qgis_embedded",
                              os_name="linux", architecture=_python_arch(sys_py),
                              is_qgis_python=True)
    return None


def _linux_qgis() -> list[QGISInfo]:
    results = []
    seen_paths: set[str] = set()

    qgis_exe = shutil.which("qgis")
    if qgis_exe:
        ver_out = _run([qgis_exe, "--version"])
        version = _normalize_version(ver_out.split("\n")[0]) if ver_out else "unknown"
        install_path = str(Path(qgis_exe).parent.parent)
        if not _seen(seen_paths, install_path):
            py = _linux_qgis_python(install_path, "apt")
            if py:
                py.qgis_version = version
            results.append(QGISInfo(
                name=f"QGIS {version}",
                version=version,
                install_path=install_path,
                executable=qgis_exe,
                os_name="linux",
                source="apt",
                python=py,
            ))

    for snap_dir in glob.glob("/snap/qgis*/current"):
        if _seen(seen_paths, snap_dir):
            continue
        exe_candidates = list(Path(snap_dir).glob("**/qgis"))
        exe = str(exe_candidates[0]) if exe_candidates else snap_dir + "/bin/qgis"
        ver_out = _run([exe, "--version"]) if Path(exe).exists() else None
        version = _normalize_version(ver_out.split("\n")[0]) if ver_out else Path(snap_dir).parts[-2]
        py = _linux_qgis_python(snap_dir, "snap")
        if py:
            py.qgis_version = version
        results.append(QGISInfo(
            name=f"QGIS {version}",
            version=version,
            install_path=snap_dir,
            executable=exe,
            os_name="linux",
            source="snap",
            python=py,
        ))

    flatpak_dirs = glob.glob(os.path.expanduser(
        "~/.local/share/flatpak/app/org.qgis.qgis/current/active/files"
    )) + glob.glob(
        "/var/lib/flatpak/app/org.qgis.qgis/current/active/files"
    )
    for fp_dir in flatpak_dirs:
        if _seen(seen_paths, fp_dir):
            continue
        exe = os.path.join(fp_dir, "bin", "qgis")
        ver_out = _run(["flatpak", "run", "--command=qgis", "org.qgis.qgis", "--version"])
        version = _normalize_version(ver_out.split("\n")[0]) if ver_out else "unknown"
        py = _linux_qgis_python(fp_dir, "flatpak")
        if py:
            py.qgis_version = version
        results.append(QGISInfo(
            name=f"QGIS {version}",
            version=version,
            install_path=fp_dir,
            executable=exe,
            os_name="linux",
            source="flatpak",
            python=py,
        ))

    for base in ["/opt", "/usr/local"]:
        for entry in glob.glob(os.path.join(base, "qgis*")):
            if _seen(seen_paths, entry):
                continue
            exe = os.path.join(entry, "bin", "qgis")
            if not Path(exe).exists():
                continue
            ver_out = _run([exe, "--version"])
            version = _normalize_version(ver_out.split("\n")[0]) if ver_out else Path(entry).name
            py = _linux_qgis_python(entry, "custom")
            if py:
                py.qgis_version = version
            results.append(QGISInfo(
                name=f"QGIS {version}",
                version=version,
                install_path=entry,
                executable=exe,
                os_name="linux",
                source="path_scan",
                python=py,
            ))

    return results


# ──────────────────────────────────────────────────────────────────────────────
# QGIS – macOS
# ──────────────────────────────────────────────────────────────────────────────

def _macos_qgis_python(app_bundle: str, version: str) -> Optional[PythonInfo]:
    root = Path(app_bundle)
    for exe in sorted(root.glob("**/bin/python3"), reverse=True):
        ver = _python_version(str(exe))
        if ver:
            return PythonInfo(name=f"Python {ver}", version=ver,
                              executable=str(exe), source="qgis_embedded",
                              os_name="macos", architecture=_python_arch(str(exe)),
                              is_qgis_python=True, qgis_version=version)
    homebrew_python = shutil.which("python3")
    if homebrew_python:
        ver = _python_version(homebrew_python)
        if ver:
            return PythonInfo(name=f"Python {ver}", version=ver,
                              executable=homebrew_python, source="qgis_embedded",
                              os_name="macos", architecture=_python_arch(homebrew_python),
                              is_qgis_python=True, qgis_version=version)
    return None


def _macos_qgis() -> list[QGISInfo]:
    results = []
    seen_paths: set[str] = set()

    for app in glob.glob("/Applications/QGIS*.app"):
        if _seen(seen_paths, app):
            continue
        exe = os.path.join(app, "Contents", "MacOS", "QGIS")
        ver_out = _run([exe, "--version"]) if Path(exe).exists() else None
        version = _normalize_version(ver_out.split("\n")[0]) if ver_out else Path(app).stem
        py = _macos_qgis_python(app, version)
        results.append(QGISInfo(
            name=f"QGIS {version}",
            version=version,
            install_path=app,
            executable=exe,
            os_name="macos",
            source="app_bundle",
            python=py,
        ))

    brew_prefix = _run(["brew", "--prefix", "qgis"])
    if brew_prefix:
        brew_prefix = brew_prefix.strip()
        if not _seen(seen_paths, brew_prefix):
            exe = os.path.join(brew_prefix, "bin", "qgis")
            ver_out = _run([exe, "--version"]) if Path(exe).exists() else None
            version = _normalize_version(ver_out.split("\n")[0]) if ver_out else "unknown"
            py = _macos_qgis_python(brew_prefix, version)
            results.append(QGISInfo(
                name=f"QGIS {version}",
                version=version,
                install_path=brew_prefix,
                executable=exe,
                os_name="macos",
                source="homebrew",
                python=py,
            ))

    return results


# ──────────────────────────────────────────────────────────────────────────────
# Classe principal do detector
# ──────────────────────────────────────────────────────────────────────────────
class QGISPythonDetector:
    def __init__(
        self,
        include_venvs: bool = False,
        include_conda_envs: bool = False,
        extra_search_paths: Optional[list[str]] = None,
    ):
        self.include_venvs = include_venvs
        self.include_conda_envs = include_conda_envs
        self.extra_search_paths = extra_search_paths or []

    def _detect_pythons(self) -> list[PythonInfo]:
        pythons: list[PythonInfo] = []

        if OS_NAME == "Windows":
            pythons += _win_pythons_from_registry()
            pythons += _win_pythons_from_paths()
        else:
            pythons += _unix_pythons_from_paths()

        self_exe = sys.executable
        seen_exes: set[str] = {str(Path(p.executable).resolve()) for p in pythons if Path(p.executable).exists()}
        try:
            real_self = str(Path(self_exe).resolve())
        except Exception:
            real_self = self_exe
        if real_self not in seen_exes:
            ver = _python_version(self_exe) or platform.python_version()
            pythons.append(PythonInfo(
                name=f"Python {ver}",
                version=ver,
                executable=self_exe,
                source="current_process",
                os_name=OS_NAME.lower() if OS_NAME != "Darwin" else "macos",
                architecture=platform.architecture()[0],
            ))

        if self.include_venvs:
            pythons += self._scan_venvs()

        if self.include_conda_envs:
            pythons += self._scan_conda_envs()

        seen_extra: set[str] = set()
        for sp in self.extra_search_paths:
            for exe in glob.glob(os.path.join(sp, "python*")):
                if not Path(exe).is_file():
                    continue
                if _seen(seen_extra, exe):
                    continue
                ver = _python_version(exe)
                if ver:
                    pythons.append(PythonInfo(
                        name=f"Python {ver}",
                        version=ver,
                        executable=exe,
                        source="extra_path",
                        os_name=OS_NAME.lower() if OS_NAME != "Darwin" else "macos",
                        architecture=_python_arch(exe),
                    ))

        return self._deduplicate_pythons(pythons)

    def _scan_venvs(self) -> list[PythonInfo]:
        results = []
        search_roots = [Path.home(), Path.cwd()]
        exe_name = "python.exe" if OS_NAME == "Windows" else "python"
        seen: set[str] = set()
        for root in search_roots:
            for venv_name in [".venv", "venv", "env", ".env"]:
                bin_dir = "Scripts" if OS_NAME == "Windows" else "bin"
                exe = root / venv_name / bin_dir / exe_name
                if exe.is_file() and not _seen(seen, str(exe)):
                    ver = _python_version(str(exe))
                    if ver:
                        results.append(PythonInfo(
                            name=f"Python {ver}",
                            version=ver,
                            executable=str(exe),
                            source="venv",
                            os_name=OS_NAME.lower() if OS_NAME != "Darwin" else "macos",
                            architecture=_python_arch(str(exe)),
                        ))
        return results

    def _scan_conda_envs(self) -> list[PythonInfo]:
        results = []
        conda_exe = shutil.which("conda") or shutil.which("mamba")
        if not conda_exe:
            return results
        out = _run([conda_exe, "env", "list", "--json"])
        if not out:
            return results
        try:
            data = json.loads(out)
            envs: list[str] = data.get("envs", [])
        except json.JSONDecodeError:
            return results
        seen: set[str] = set()
        for env_path in envs:
            bin_dir = "Scripts" if OS_NAME == "Windows" else "bin"
            exe_name = "python.exe" if OS_NAME == "Windows" else "python"
            exe = os.path.join(env_path, bin_dir, exe_name)
            if not Path(exe).is_file():
                continue
            if _seen(seen, exe):
                continue
            ver = _python_version(exe)
            if ver:
                results.append(PythonInfo(
                    name=f"Python {ver} [conda:{Path(env_path).name}]",
                    version=ver,
                    executable=exe,
                    source="conda",
                    os_name=OS_NAME.lower() if OS_NAME != "Darwin" else "macos",
                    architecture=_python_arch(exe),
                ))
        return results

    @staticmethod
    def _deduplicate_pythons(pythons: list[PythonInfo]) -> list[PythonInfo]:
        seen: set[str] = set()
        out = []
        for p in pythons:
            try:
                key = str(Path(p.executable).resolve())
            except Exception:
                key = p.executable
            if key not in seen:
                seen.add(key)
                out.append(p)
        return out

    def _detect_qgis(self) -> list[QGISInfo]:
        if OS_NAME == "Windows":
            reg_items = _win_qgis_from_registry()
            path_items = _win_qgis_from_paths()
            seen: set[str] = set()
            merged = []
            for q in reg_items + path_items:
                try:
                    key = str(Path(q.install_path).resolve())
                except Exception:
                    key = q.install_path
                if key not in seen:
                    seen.add(key)
                    merged.append(q)
            return merged
        elif OS_NAME == "Linux":
            return _linux_qgis()
        elif OS_NAME == "Darwin":
            return _macos_qgis()
        return []

    def detect(self) -> DetectionResult:
        logger.info("Iniciando detecção em %s", OS_NAME)
        result = DetectionResult(
            system_pythons=self._detect_pythons(),
            qgis_installations=self._detect_qgis(),
        )
        logger.info(
            "Detecção concluída: %d Python(s), %d QGIS",
            len(result.system_pythons),
            len(result.qgis_installations),
        )
        return result


# ──────────────────────────────────────────────────────────────────────────────
# Gerenciador de pacotes QGIS
# ──────────────────────────────────────────────────────────────────────────────

_CUSTOM_PYTHONS_DIR = pathlib.Path(tempfile.gettempdir()) / "qgis_pkg_manager"
_CUSTOM_PYTHONS_DIR.mkdir(exist_ok=True)
_CUSTOM_PYTHONS_FILE = _CUSTOM_PYTHONS_DIR / "custom_pythons.json"


def _load_custom_pythons() -> list[dict]:
    """Carrega Pythons personalizados salvos em temp."""
    if _CUSTOM_PYTHONS_FILE.exists():
        try:
            with open(_CUSTOM_PYTHONS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_custom_python(exe: str, version: str):
    """Salva um novo Python personalizado no arquivo JSON de temp."""
    data = _load_custom_pythons()
    for entry in data:
        if entry.get("exe") == exe:
            return
    data.append({
        "exe": exe,
        "version": version,
        "label": f"Python {version} (personalizado)",
        "added": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    with open(_CUSTOM_PYTHONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _load_python_options() -> list[tuple[str, str]]:
    """Retorna lista de (label, executable) para todos os Pythons detectados."""
    detector = QGISPythonDetector()
    result = detector.detect()
    options: list[tuple[str, str]] = []

    for py in result.system_pythons:
        label = py.name
        if py.source == "current_process":
            label += " (atual)"
        elif py.source == "conda":
            label += " (conda)"
        options.append((label, py.executable))

    for qgis in result.qgis_installations:
        if qgis.python and qgis.python.executable:
            label = f"{qgis.python.name} [embutido: {qgis.name}]"
            options.append((label, qgis.python.executable))

    for entry in _load_custom_pythons():
        options.append((entry["label"], entry["exe"]))

    return options


_ALL_PYTHON_OPTIONS = _load_python_options()


class PipWorker(QThread):
    log_line = Signal(str)
    finished = Signal(bool)

    def __init__(self, cmd: list[str]):
        super().__init__()
        self.cmd = cmd

    def run(self):
        try:
            proc = subprocess.Popen(
                self.cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            for line in proc.stdout:
                self.log_line.emit(line.rstrip())
            proc.wait()
            self.finished.emit(proc.returncode == 0)
        except Exception as e:
            self.log_line.emit(f"[ERRO] {e}")
            self.finished.emit(False)


class ListPackagesWorker(QThread):
    packages_loaded = Signal(list)
    log_line = Signal(str)

    def __init__(self, python_exe: str):
        super().__init__()
        self.python_exe = python_exe

    def run(self):
        try:
            code = (
                "import importlib.metadata, json; "
                "pkgs = sorted(importlib.metadata.distributions(), "
                "key=lambda d: d.metadata.get('Name','').lower()); "
                "print(json.dumps([(d.metadata.get('Name','?'), "
                "d.metadata.get('Version','?')) for d in pkgs]))"
            )
            proc = subprocess.Popen(
                [self.python_exe, "-c", code],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            stdout, _ = proc.communicate(timeout=30)
            if proc.returncode == 0:
                data = json.loads(stdout.strip())
                self.packages_loaded.emit(data)
            else:
                self.log_line.emit(f"[ERRO] Falha ao listar pacotes: {stdout.strip()}")
                self.packages_loaded.emit([])
        except Exception as e:
            self.log_line.emit(f"[ERRO] {e}")
            self.packages_loaded.emit([])


class QGISPkgManager(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QGIS · Gerenciador de Pacotes Python")
        self.setMinimumSize(880, 620)
        self._worker = None
        self._list_worker = None
        self._current_python_exe: str = sys.executable
        self._build_ui()
        self._apply_style()

    @property
    def python_exe(self) -> str:
        return self._current_python_exe

    @python_exe.setter
    def python_exe(self, value: str):
        self._current_python_exe = value
        version_str = self._get_python_version(value) or "?"
        self.py_info_label.setText(f"Python {version_str}  📁")
        self.py_info_label.setToolTip(
            f"Clique para abrir a pasta do executável no explorer\n{value}"
        )

    @staticmethod
    def _get_python_version(exe: str) -> str | None:
        try:
            result = subprocess.run(
                [exe, "--version"],
                capture_output=True, text=True, timeout=5
            )
            out = result.stdout.strip() or result.stderr.strip()
            if out.lower().startswith("python"):
                return out.split()[1]
        except Exception:
            pass
        return None

    @staticmethod
    def _find_python_in_folder(folder: str) -> str | None:
        """Procura por executável Python dentro de uma pasta (suporte a QGIS)."""
        candidates = [
            "python.exe", "python3.exe",
            "python", "python3",
            "bin/python.exe", "bin/python3.exe",
            "bin/python", "bin/python3",
            "apps/Python312/python.exe",
            "apps/Python311/python.exe",
            "apps/Python310/python.exe",
            "apps/Python39/python.exe",
        ]
        root = pathlib.Path(folder)
        for c in candidates:
            p = root / c
            if p.exists():
                return str(p)
        for depth in range(1, 5):
            pattern = "/".join(["*"] * depth)
            for name in ("python.exe", "python3.exe", "python", "python3"):
                for found in root.glob(f"{pattern}/{name}"):
                    if found.is_file():
                        return str(found)
        return None

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        header = QFrame()
        header.setObjectName("header")
        h_lay = QVBoxLayout(header)
        h_lay.setContentsMargins(20, 8, 20, 8)
        h_lay.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        title_lbl = QLabel("⚙  QGIS Package Manager")
        title_lbl.setObjectName("title")
        version_lbl = QLabel("v1.0.1")
        version_lbl.setObjectName("version")

        title_row.addWidget(title_lbl)
        title_row.addWidget(version_lbl)
        title_row.addStretch()
        h_lay.addLayout(title_row)

        py_row = QHBoxLayout()
        py_row.setSpacing(6)

        py_lbl = QLabel("Python:")
        py_lbl.setObjectName("pyLbl")
        py_lbl.setToolTip(
            "Selecione qual interpretador Python usar para instalar/remover pacotes.\n"
            "Você pode escolher um Python do sistema, embutido no QGIS,\n"
            "ou localizar manualmente com o botão 📂 Procurar."
        )
        py_row.addWidget(py_lbl)

        self.py_selector = QComboBox()
        self.py_selector.setObjectName("pySelector")
        self.py_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.py_selector.setToolTip(
            "Lista de interpretadores Python detectados no sistema.\n"
            "Inclui Pythons standalone, ambientes conda e Pythons\n"
            "embutidos nas instalações do QGIS encontradas.\n\n"
            "Para adicionar um Python não listado, use o botão 📂 Procurar."
        )

        current_exe_lower = sys.executable.lower().replace("\\", "/")
        selected_index = 0
        for i, (label, exe) in enumerate(_ALL_PYTHON_OPTIONS):
            self.py_selector.addItem(label, exe)
            if exe.lower().replace("\\", "/") == current_exe_lower:
                selected_index = i

        self.py_selector.setCurrentIndex(selected_index)
        self.py_selector.currentIndexChanged.connect(self._on_python_changed)
        py_row.addWidget(self.py_selector, stretch=1)

        self.btn_browse = QPushButton("📂  Procurar…")
        self.btn_browse.setObjectName("btnSecondary")
        self.btn_browse.setToolTip(
            "Localizar manualmente um executável Python ou pasta do QGIS.\n\n"
            "• Selecione python.exe / python diretamente, OU\n"
            "• Selecione a pasta raiz do QGIS — o executável\n"
            "  Python embutido será localizado automaticamente.\n\n"
            "O Python encontrado será salvo em temp para uso futuro."
        )
        self.btn_browse.clicked.connect(self._on_browse_python)
        py_row.addWidget(self.btn_browse)

        self.py_info_label = QLabel()
        self.py_info_label.setObjectName("pyinfo")
        self.py_info_label.setCursor(Qt.PointingHandCursor)
        self.py_info_label.mousePressEvent = lambda e: self._open_python_path()
        py_row.addWidget(self.py_info_label)

        h_lay.addLayout(py_row)
        self.python_exe = self.py_selector.currentData() or sys.executable

        root.addWidget(header)

        mode_frame = QFrame()
        mode_frame.setObjectName("modeBar")
        mode_lay = QHBoxLayout(mode_frame)
        mode_lay.setContentsMargins(20, 8, 20, 8)
        mode_lay.setSpacing(24)

        mode_lay.addWidget(QLabel("Modo:"))

        self.rb_install = QRadioButton("  Instalar")
        self.rb_uninstall = QRadioButton("  Desinstalar")
        self.rb_install.setChecked(True)
        self.rb_install.setObjectName("rb")
        self.rb_uninstall.setObjectName("rb")

        group = QButtonGroup(self)
        group.addButton(self.rb_install)
        group.addButton(self.rb_uninstall)
        self.rb_install.toggled.connect(self._on_mode_change)

        mode_lay.addWidget(self.rb_install)
        mode_lay.addWidget(self.rb_uninstall)
        mode_lay.addStretch()

        self.btn_refresh = QPushButton("↻  Atualizar lista")
        self.btn_refresh.setObjectName("btnSecondary")
        self.btn_refresh.setToolTip("Recarrega a lista de pacotes instalados no Python selecionado.")
        self.btn_refresh.clicked.connect(self._load_installed)
        self.btn_refresh.setVisible(False)
        mode_lay.addWidget(self.btn_refresh)

        root.addWidget(mode_frame)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_install_panel())
        self.stack.addWidget(self._build_uninstall_panel())
        root.addWidget(self.stack, stretch=1)

        log_frame = QFrame()
        log_frame.setObjectName("logFrame")
        log_lay = QVBoxLayout(log_frame)
        log_lay.setContentsMargins(12, 6, 12, 6)
        log_lay.setSpacing(4)

        log_header = QHBoxLayout()
        log_header.addWidget(QLabel("📋  Saída do pip"))
        log_header.addStretch()
        self.btn_clear_log = QPushButton("Limpar")
        self.btn_clear_log.setObjectName("btnTiny")
        self.btn_clear_log.setToolTip("Limpa o conteúdo do log de saída.")
        self.btn_clear_log.clicked.connect(lambda: self.log.clear())
        log_header.addWidget(self.btn_clear_log)
        log_lay.addLayout(log_header)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setObjectName("logBox")
        self.log.setFixedHeight(136)
        log_lay.addWidget(self.log)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedHeight(3)
        self.progress.setObjectName("pbar")
        self.progress.setVisible(False)
        log_lay.addWidget(self.progress)

        root.addWidget(log_frame)

    def _build_install_panel(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(10)

        lbl = QLabel(
            "Digite os pacotes que deseja instalar. "
            "Separe por vírgula, espaço ou nova linha. "
            "Versões aceitas:  numpy>=1.24  opencv-python==4.8.0"
        )
        lbl.setObjectName("hint")
        lbl.setWordWrap(True)
        lay.addWidget(lbl)

        self.txt_pkgs = QTextEdit()
        self.txt_pkgs.setObjectName("inputBox")
        self.txt_pkgs.setPlaceholderText(
            "Ex:\nopencv-python\nnumpy>=1.24\nscipy\ngeopandas"
        )
        lay.addWidget(self.txt_pkgs, stretch=1)

        opt_lay = QHBoxLayout()
        opt_lay.setSpacing(20)
        self.chk_upgrade = QCheckBox("--upgrade  (atualizar se já instalado)")
        self.chk_upgrade.setObjectName("optCheck")
        self.chk_upgrade.setToolTip("Passa --upgrade ao pip: reinstala mesmo que já esteja na versão mais recente.")
        self.chk_no_deps = QCheckBox("--no-deps  (ignorar dependências)")
        self.chk_no_deps.setObjectName("optCheck")
        self.chk_no_deps.setToolTip("Passa --no-deps ao pip: instala apenas o pacote, sem instalar suas dependências.")
        opt_lay.addWidget(self.chk_upgrade)
        opt_lay.addWidget(self.chk_no_deps)
        opt_lay.addStretch()
        lay.addLayout(opt_lay)

        self.btn_install = QPushButton("▶  Instalar pacotes")
        self.btn_install.setObjectName("btnPrimary")
        self.btn_install.setToolTip("Executa pip install com os pacotes listados no Python selecionado.")
        self.btn_install.clicked.connect(self._run_install)
        lay.addWidget(self.btn_install)

        return w

    def _build_uninstall_panel(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 12, 20, 12)
        lay.setSpacing(8)

        top_lay = QHBoxLayout()
        top_lay.setSpacing(8)
        hint = QLabel("Marque os pacotes que deseja remover:")
        hint.setObjectName("hint")
        top_lay.addWidget(hint)
        top_lay.addStretch()

        self.lbl_selected = QLabel("0 selecionados")
        self.lbl_selected.setObjectName("badge")
        top_lay.addWidget(self.lbl_selected)

        self.btn_sel_all = QPushButton("Selecionar todos")
        self.btn_sel_all.setObjectName("btnTiny")
        self.btn_sel_all.setToolTip("Seleciona todos os pacotes visíveis na lista.")
        self.btn_sel_all.clicked.connect(lambda: self._select_all(True))

        self.btn_sel_none = QPushButton("Limpar seleção")
        self.btn_sel_none.setObjectName("btnTiny")
        self.btn_sel_none.setToolTip("Desmarca todos os pacotes selecionados.")
        self.btn_sel_none.clicked.connect(lambda: self._select_all(False))

        top_lay.addWidget(self.btn_sel_all)
        top_lay.addWidget(self.btn_sel_none)
        lay.addLayout(top_lay)

        self.search = QLineEdit()
        self.search.setObjectName("searchBox")
        self.search.setPlaceholderText("🔍  Filtrar pacotes…")
        self.search.setToolTip("Digite parte do nome do pacote para filtrar a lista abaixo.")
        self.search.textChanged.connect(self._filter_packages)
        lay.addWidget(self.search)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("pkgScroll")
        self.pkg_container = QWidget()
        self.pkg_layout = QVBoxLayout(self.pkg_container)
        self.pkg_layout.setSpacing(4)
        self.pkg_layout.setContentsMargins(6, 6, 6, 6)
        self.pkg_layout.addStretch()
        scroll.setWidget(self.pkg_container)
        lay.addWidget(scroll, stretch=1)

        self.btn_uninstall = QPushButton("🗑  Desinstalar selecionados")
        self.btn_uninstall.setObjectName("btnDanger")
        self.btn_uninstall.setToolTip(
            "Remove permanentemente os pacotes selecionados do Python alvo.\n"
            "Uma confirmação será solicitada antes de prosseguir."
        )
        self.btn_uninstall.clicked.connect(self._run_uninstall)
        lay.addWidget(self.btn_uninstall)

        self._checkboxes: list[QCheckBox] = []
        return w

    def _on_mode_change(self, checked: bool):
        if self.rb_install.isChecked():
            self.stack.setCurrentIndex(0)
            self.btn_refresh.setVisible(False)
        else:
            self.stack.setCurrentIndex(1)
            self.btn_refresh.setVisible(True)
            if not self._checkboxes:
                self._load_installed()

    def _on_browse_python(self):
        if sys.platform == "win32":
            file_filter = "Python (python.exe python3.exe);;Todos (*)"
        else:
            file_filter = "Python (python python3);;Todos (*)"

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar executável Python ou pasta do QGIS",
            "",
            file_filter
        )

        if not file_path:
            folder = QFileDialog.getExistingDirectory(
                self,
                "Ou selecione a pasta raiz do QGIS / Python",
                ""
            )
            if not folder:
                return
            found = self._find_python_in_folder(folder)
            if not found:
                QMessageBox.warning(
                    self, "Python não encontrado",
                    f"Não foi possível encontrar um executável Python na pasta:\n{folder}\n\n"
                    "Tente apontar diretamente para o python.exe."
                )
                return
            file_path = found

        version = self._get_python_version(file_path)
        if not version:
            QMessageBox.warning(
                self, "Python inválido",
                f"O arquivo selecionado não parece ser um Python válido:\n{file_path}"
            )
            return

        for i in range(self.py_selector.count()):
            if self.py_selector.itemData(i) == file_path:
                self.py_selector.setCurrentIndex(i)
                self._log(f"[INFO] Python já listado, selecionado: {file_path}", "#a78bfa")
                return

        _save_custom_python(file_path, version)
        self._log(
            f"[INFO] Python personalizado salvo em: {_CUSTOM_PYTHONS_FILE}",
            "#a78bfa"
        )

        label = f"Python {version} (personalizado)"
        self.py_selector.addItem(label, file_path)
        self.py_selector.setCurrentIndex(self.py_selector.count() - 1)
        self._log(f"[INFO] Python adicionado: {file_path} ({version})", "#34d399")

    def _open_python_path(self):
        p = pathlib.Path(self.python_exe)
        folder = str(p.parent)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        self._log(f"[INFO] Abrindo pasta: {folder}", "#60a5fa")

    def _on_python_changed(self, index: int):
        exe = self.py_selector.itemData(index)
        if not exe:
            return
        self.python_exe = exe
        self._log(f"[INFO] Python alterado para: {exe}", "#60a5fa")
        if hasattr(self, '_checkboxes') and self.rb_uninstall.isChecked():
            self._load_installed()

    def _load_installed(self):
        for cb in self._checkboxes:
            cb.setParent(None)
        self._checkboxes.clear()

        self._log(f"[INFO] Carregando pacotes de: {self.python_exe}", "#60a5fa")
        self._set_busy(True)

        self._list_worker = ListPackagesWorker(self.python_exe)
        self._list_worker.packages_loaded.connect(self._on_packages_loaded)
        self._list_worker.log_line.connect(lambda l: self._log(l))
        self._list_worker.start()

    def _on_packages_loaded(self, packages: list):
        self._set_busy(False)

        while self.pkg_layout.count() > 0:
            item = self.pkg_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        for name, version in packages:
            cb = QCheckBox(f"{name}  ({version})")
            cb.setObjectName("pkgCheck")
            cb.stateChanged.connect(self._update_selected_count)
            self.pkg_layout.addWidget(cb)
            self._checkboxes.append(cb)
        self.pkg_layout.addStretch()
        self._update_selected_count()
        self._log(
            f"[INFO] {len(self._checkboxes)} pacotes encontrados em {self.python_exe}.",
            "#34d399"
        )

        if hasattr(self, 'search') and self.search.text():
            self._filter_packages(self.search.text())

    def _filter_packages(self, text: str):
        for cb in self._checkboxes:
            cb.setVisible(text.lower() in cb.text().lower())

    def _select_all(self, state: bool):
        for cb in self._checkboxes:
            if cb.isVisible():
                cb.setChecked(state)

    def _update_selected_count(self):
        n = sum(1 for cb in self._checkboxes if cb.isChecked())
        self.lbl_selected.setText(f"{n} selecionados")

    def _run_install(self):
        raw = self.txt_pkgs.toPlainText()
        pkgs = [p.strip() for p in _re.split(r"[\s,]+", raw) if p.strip()]
        if not pkgs:
            self._log("[AVISO] Nenhum pacote informado.", "#f59e0b")
            return

        cmd = [self.python_exe, "-m", "pip", "install"] + pkgs
        if self.chk_upgrade.isChecked():
            cmd.append("--upgrade")
        if self.chk_no_deps.isChecked():
            cmd.append("--no-deps")

        self._log(f"[CMD] {' '.join(cmd)}", "#818cf8")
        self._run_cmd(cmd, post_action=self._on_install_done)

    def _on_install_done(self):
        if self.rb_uninstall.isChecked():
            self._load_installed()

    def _run_uninstall(self):
        selected = [
            cb.text().split("  (")[0].strip()
            for cb in self._checkboxes if cb.isChecked()
        ]
        if not selected:
            self._log("[AVISO] Nenhum pacote selecionado.", "#f59e0b")
            return

        confirm = QMessageBox.question(
            self, "Confirmar remoção",
            f"Desinstalar {len(selected)} pacote(s)?\n\n" + "\n".join(selected),
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return

        cmd = [self.python_exe, "-m", "pip", "uninstall", "-y"] + selected
        self._log(f"[CMD] {' '.join(cmd)}", "#818cf8")
        self._run_cmd(cmd, post_action=self._load_installed)

    def _run_cmd(self, cmd: list[str], post_action=None):
        self._set_busy(True)
        self._worker = PipWorker(cmd)
        self._worker.log_line.connect(lambda l: self._log(l))
        self._worker.finished.connect(lambda ok: self._on_done(ok, post_action))
        self._worker.start()

    def _on_done(self, ok: bool, post_action=None):
        self._set_busy(False)
        color = "#34d399" if ok else "#f87171"
        self._log("✔  Concluído com sucesso." if ok else "✖  Falhou.", color)
        if ok and post_action:
            post_action()

    def _set_busy(self, busy: bool):
        self.progress.setVisible(busy)
        self.btn_install.setEnabled(not busy)
        self.btn_uninstall.setEnabled(not busy)
        self.rb_install.setEnabled(not busy)
        self.rb_uninstall.setEnabled(not busy)
        self.py_selector.setEnabled(not busy)
        self.btn_refresh.setEnabled(not busy)

    def _log(self, text: str, color: str = "#94a3b8"):
        self.log.setTextColor(QColor(color))
        self.log.append(text)
        self.log.moveCursor(QTextCursor.End)

    def _apply_style(self):
        self.setStyleSheet("""
            QWidget {
                background: #202024;
                color: #E8E6E0;
                font-family: 'Segoe UI Variable', 'Segoe UI', 'Inter', sans-serif;
                font-size: 12px;
            }
            QFrame#header {
                background: #18171A;
                border-bottom: 1px solid #36332E;
            }
            QLabel#title {
                font-size: 15px;
                font-weight: 700;
                color: #E8E6E0;
                letter-spacing: 0.2px;
            }
            QLabel#version {
                font-size: 10px;
                font-weight: 600;
                color: #A38F00;
                letter-spacing: 1.5px;
                padding-left: 2px;
            }
            QLabel#pyLbl {
                color: #9A978F;
                font-size: 12px;
            }
            QLabel#pyinfo {
                font-size: 11px;
                color: #5C5A55;
                padding: 3px 8px;
                border-radius: 4px;
                border: 1px solid transparent;
            }
            QLabel#pyinfo:hover {
                color: #A38F00;
                background: #2C2A26;
                border: 1px solid #A38F00;
            }
            QComboBox#pySelector {
                background: #242220;
                border: 1px solid #36332E;
                border-radius: 4px;
                padding: 4px 10px;
                color: #E8E6E0;
                font-size: 12px;
                min-width: 240px;
                max-height: 26px;
            }
            QComboBox#pySelector:hover {
                border-color: #021BA3;
                background: #2A2825;
            }
            QComboBox#pySelector:focus {
                border-color: #021BA3;
            }
            QComboBox#pySelector::drop-down {
                border: none;
                width: 18px;
            }
            QComboBox#pySelector::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #9A978F;
                margin-right: 6px;
            }
            QComboBox#pySelector QAbstractItemView {
                background: #242320;
                border: 1px solid #36332E;
                border-radius: 4px;
                selection-background-color: #021BA3;
                selection-color: #E8E6E0;
                color: #E8E6E0;
                font-size: 12px;
                padding: 2px;
                outline: none;
            }
            QFrame#modeBar {
                background: #1C1B1F;
                border-bottom: 1px solid #36332E;
            }
            QRadioButton#rb {
                font-size: 12px;
                spacing: 7px;
                color: #9A978F;
            }
            QRadioButton#rb::indicator {
                width: 13px; height: 13px;
                border-radius: 7px;
                border: 2px solid #36332E;
                background: #202024;
            }
            QRadioButton#rb::indicator:hover {
                border-color: #021BA3;
            }
            QRadioButton#rb::indicator:checked {
                border-color: #021BA3;
                background: #021BA3;
            }
            QRadioButton#rb:checked {
                color: #E8E6E0;
                font-weight: 600;
            }
            QTextEdit#inputBox, QLineEdit#searchBox {
                background: #242220;
                border: 1px solid #36332E;
                border-radius: 4px;
                padding: 7px 10px;
                color: #E8E6E0;
                font-size: 12px;
            }
            QTextEdit#inputBox:focus, QLineEdit#searchBox:focus {
                border: 1px solid #021BA3;
            }
            QFrame#logFrame {
                background: #18171A;
                border-top: 1px solid #36332E;
            }
            QTextEdit#logBox {
                background: #0E0D10;
                border: 1px solid #2A2825;
                border-radius: 3px;
                color: #9A978F;
                font-family: 'Cascadia Code', 'Consolas', 'JetBrains Mono', monospace;
                font-size: 11px;
                padding: 6px 8px;
            }
            QProgressBar#pbar {
                border: none;
                background: #36332E;
                border-radius: 1px;
            }
            QProgressBar#pbar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #021BA3, stop:1 #1A3FD4);
                border-radius: 1px;
            }
            QPushButton#btnPrimary {
                background: #021BA3;
                color: #E8E6E0;
                font-size: 13px;
                font-weight: 600;
                border: none;
                border-radius: 4px;
                padding: 7px 20px;
            }
            QPushButton#btnPrimary:hover {
                background: #1A3FD4;
            }
            QPushButton#btnPrimary:pressed {
                background: #011278;
            }
            QPushButton#btnPrimary:disabled {
                background: #36332E;
                color: #5C5A55;
            }
            QPushButton#btnDanger {
                background: #242220;
                color: #D94040;
                font-size: 13px;
                font-weight: 700;
                border: 1px solid #36332E;
                border-radius: 4px;
                padding: 7px 20px;
            }
            QPushButton#btnDanger:hover {
                background: #2E2220;
                border-color: #D94040;
                color: #F06060;
            }
            QPushButton#btnDanger:pressed {
                background: #1E1615;
            }
            QPushButton#btnDanger:disabled {
                background: #36332E;
                color: #5C5A55;
                border-color: #36332E;
            }
            QPushButton#btnSecondary {
                background: transparent;
                color: #9A978F;
                border: 1px solid #36332E;
                border-radius: 4px;
                padding: 4px 12px;
                font-weight: 500;
                font-size: 12px;
                max-height: 26px;
            }
            QPushButton#btnSecondary:hover {
                background: #2A2825;
                border-color: #A38F00;
                color: #E8E6E0;
            }
            QPushButton#btnSecondary:pressed {
                background: #1C1B1F;
            }
            QPushButton#btnSecondary:disabled {
                color: #5C5A55;
            }
            QPushButton#btnTiny {
                background: transparent;
                color: #5C5A55;
                border: 1px solid #36332E;
                border-radius: 3px;
                padding: 3px 10px;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton#btnTiny:hover {
                background: #2A2825;
                color: #E8E6E0;
                border-color: #5C5A55;
            }
            QCheckBox#pkgCheck {
                spacing: 8px;
                color: #9A978F;
                padding: 4px 6px;
                border-radius: 3px;
            }
            QCheckBox#pkgCheck:hover {
                background: #2A2825;
                color: #E8E6E0;
            }
            QCheckBox#pkgCheck::indicator {
                width: 13px; height: 13px;
                border-radius: 2px;
                border: 1px solid #36332E;
                background: #202024;
            }
            QCheckBox#pkgCheck::indicator:hover {
                border-color: #021BA3;
            }
            QCheckBox#pkgCheck::indicator:checked {
                background: #021BA3;
                border-color: #021BA3;
            }
            QCheckBox#optCheck {
                spacing: 7px;
                color: #5C5A55;
                font-size: 12px;
            }
        """)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = QGISPkgManager()
    win.show()
    sys.exit(app.exec())
