"""
QGISPythonDetector
==================
Detecta todas as instalações de Python standalone e QGIS na máquina,
incluindo o Python embutido em cada QGIS.

Suporte: Windows · Linux · macOS
Autor   : gerado via Anthropic Claude
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
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class PythonInfo:
    name: str
    version: str
    executable: str
    source: str                   # registry | path_scan | qgis_embedded | conda | venv
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
        "/opt/local/bin",                     # MacPorts
        "/home/linuxbrew/.linuxbrew/bin",      # Linuxbrew
        "/opt/conda/bin", "/opt/miniconda*/bin",
        "/opt/anaconda*/bin",
        "/root/miniconda*/bin",
        "/root/anaconda*/bin",
    ]
    # também o PATH corrente
    for p in os.environ.get("PATH", "").split(":"):
        if p not in search_dirs:
            search_dirs.append(p)

    candidates: list[str] = []
    for d in search_dirs:
        for exp in glob.glob(d):
            for py in glob.glob(os.path.join(exp, "python*")):
                candidates.append(py)
    # pyenv
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

    Suporta todos os layouts conhecidos:
      - Standalone installer : <root>/apps/Python3XX/python.exe
      - OSGeo4W raiz         : <root>/apps/Python3XX/python.exe
      - Muito antigos (< 3.0): <root>/apps/Python27/python.exe
      - Fallback             : <root>/bin/python3.exe  ou  <root>/bin/python.exe
    """
    # Prioridade 1 – pasta apps/Python* (standalone e OSGeo4W)
    # glob retorna todas as versões; sorted() reverse garante a maior versão primeiro
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

    # Prioridade 2 – python3.exe / python.exe direto em bin/
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

    # Prioridade 3 – qualquer python*.exe em qualquer subpasta (busca ampla)
    for exe in sorted(qgis_root.rglob("python3*.exe"), reverse=True):
        # ignora pythonw.exe, python3X-config.exe etc.
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

    # 1) Chave direta QGIS
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

    # 2) Uninstall keys (captura standalone installers)
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
    """
    Varredura de diretórios comuns no Windows.

    Cenários cobertos
    -----------------
    1. Standalone installer  → C:\\Program Files\\QGIS 3.34.12\\
                               C:\\Program Files\\QGIS 3.40.0\\
                               C:\\Program Files\\QGIS 4.0.0\\  etc.
    2. OSGeo4W raiz única    → C:\\OSGeo4W\\ com apps/qgis-ltr, apps/qgis, etc.
       Cada subpasta qgis* dentro de apps/ é tratada como instalação separada,
       com seu PRÓPRIO executável Python em apps/Python3XX/.
    3. Drives alternativos   → D:\\, E:\\, … mesmo padrão acima.
    4. Program Files (x86)   → instaladores 32-bit legados.
    5. Instalações em C:\\ raiz (ex: C:\\QGIS3.16).
    """
    seen_paths: set[str] = set()
    results = []

    # ── 1. Coletar raízes candidatas ─────────────────────────────────────────

    pf_dirs = []
    # Program Files em todos os drives
    for drive_letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        drive = f"{drive_letter}:\\"
        if not os.path.exists(drive):
            continue
        pf_dirs += [
            os.path.join(drive, "Program Files"),
            os.path.join(drive, "Program Files (x86)"),
            drive,  # instalações direto na raiz do drive
        ]

    standalone_roots: list[str] = []
    osgeo_roots: list[str] = []

    for pf in pf_dirs:
        if not os.path.isdir(pf):
            continue
        # QGIS standalone: "QGIS 3.34.12", "QGIS 4.0.0", "QGIS3.16" etc.
        standalone_roots += glob.glob(os.path.join(pf, "QGIS*"))
        standalone_roots += glob.glob(os.path.join(pf, "qgis*"))
        # OSGeo4W: "OSGeo4W", "OSGeo4W64", "OSGeo4W3" etc.
        osgeo_roots += glob.glob(os.path.join(pf, "OSGeo4W*"))

    # ── 2. Processar standalone (uma versão por pasta) ────────────────────────

    for install_dir in standalone_roots:
        install_dir = install_dir.rstrip("\\")
        if not os.path.isdir(install_dir):
            continue
        if _seen(seen_paths, install_dir):
            continue
        root = Path(install_dir)

        # Executável principal do QGIS
        exe: Optional[Path] = None
        for candidate_name in ("qgis-bin.exe", "qgis.exe", "qgis-ltr-bin.exe"):
            c = root / "bin" / candidate_name
            if c.exists():
                exe = c
                break
        if exe is None:
            continue  # não é uma instalação QGIS válida

        # Versão: preferir --version, fallback ao nome da pasta
        ver_out = _run([str(exe), "--version"])
        if ver_out:
            version = _normalize_version(ver_out.split("\n")[0])
        else:
            version = _normalize_version(root.name)

        # Python desta instalação específica (root é a raiz do standalone)
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

    # ── 3. Processar OSGeo4W (múltiplas versões DENTRO da mesma raiz) ─────────
    #
    # Estrutura típica:
    #   C:\OSGeo4W\
    #     apps\
    #       qgis\          ← versão latest
    #       qgis-ltr\      ← versão LTR
    #       qgis-3.16\     ← versão legada (raro)
    #       Python312\     ← Python compartilhado OU por versão
    #     bin\
    #       qgis-bin.exe        ← aponta para apps/qgis
    #       qgis-ltr-bin.exe    ← aponta para apps/qgis-ltr
    #
    # Cada apps/qgis* é uma instalação independente.

    for osgeo_dir in osgeo_roots:
        osgeo_dir = osgeo_dir.rstrip("\\")
        if not os.path.isdir(osgeo_dir):
            continue
        osgeo_root = Path(osgeo_dir)
        apps_dir = osgeo_root / "apps"
        if not apps_dir.is_dir():
            # OSGeo4W sem apps/ — tenta como standalone
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

        # Itera sobre cada subpasta qgis* dentro de apps/
        qgis_app_dirs = sorted(apps_dir.glob("qgis*"), reverse=True)
        if not qgis_app_dirs:
            # Sem subpastas: trata OSGeo4W inteiro como instalação única
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

            # Cada apps/qgis* pode ter bin/qgis-bin.exe próprio...
            local_exe = qgis_app_dir / "bin" / "qgis-bin.exe"
            # ...ou o executável fica em <osgeo_root>/bin/ com sufixo
            # Mapeamento: apps/qgis-ltr → bin/qgis-ltr-bin.exe
            #             apps/qgis     → bin/qgis-bin.exe
            suffix = qgis_app_dir.name  # "qgis", "qgis-ltr", "qgis-3.34" …
            root_bin_exe = osgeo_root / "bin" / f"{suffix}-bin.exe"
            if not root_bin_exe.exists():
                root_bin_exe = osgeo_root / "bin" / "qgis-bin.exe"

            exe = local_exe if local_exe.exists() else (root_bin_exe if root_bin_exe.exists() else None)

            # Chave de deduplicação: combina osgeo_root + nome do app
            dedup_key = str(osgeo_root) + "|" + suffix
            if dedup_key in seen_paths:
                continue
            seen_paths.add(dedup_key)

            # Versão: tenta executável, fallback ao package_version.txt do app
            version = None
            if exe and exe.exists():
                ver_out = _run([str(exe), "--version"])
                if ver_out:
                    version = _normalize_version(ver_out.split("\n")[0])

            if not version:
                # Tenta ler versão de arquivos de metadados internos
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
                version = suffix  # último recurso: nome da pasta

            # Python desta versão específica
            # Primeiro busca Python na subpasta do app, depois na raiz OSGeo4W
            py = _win_qgis_python(qgis_app_dir) or _win_qgis_python(osgeo_root)
            if py:
                py.qgis_version = version

            results.append(QGISInfo(
                name=f"QGIS {version}",
                version=version,
                install_path=str(qgis_app_dir),   # aponta para a versão específica
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
    """Localiza o Python usado pelo QGIS no Linux."""
    root = Path(install_path)

    # Snap / Flatpak têm Python interno
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

    # instalação via apt: usa o Python do sistema
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

    # ── 1. apt / sistema
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

    # ── 2. Snap
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

    # ── 3. Flatpak
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

    # ── 4. Custom / manual em /opt ou /usr/local
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
    """Localiza Python dentro de um .app bundle do QGIS."""
    root = Path(app_bundle)
    for exe in sorted(root.glob("**/bin/python3"), reverse=True):
        ver = _python_version(str(exe))
        if ver:
            return PythonInfo(name=f"Python {ver}", version=ver,
                              executable=str(exe), source="qgis_embedded",
                              os_name="macos", architecture=_python_arch(str(exe)),
                              is_qgis_python=True, qgis_version=version)
    # Homebrew: Python linkado fora do bundle
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

    # ── 1. /Applications/*.app
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

    # ── 2. Homebrew (brew info qgis)
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
# Classe principal
# ──────────────────────────────────────────────────────────────────────────────

class QGISPythonDetector:
    """
    Detecta todas as instalações de Python e QGIS na máquina atual.

    Uso rápido
    ----------
    >>> detector = QGISPythonDetector()
    >>> result = detector.detect()
    >>> print(result.to_json())

    Parâmetros
    ----------
    include_venvs : bool
        Se True, inclui ambientes virtuais encontrados em diretórios comuns.
        (padrão: False — costumam ser muitos)
    include_conda_envs : bool
        Se True, lista também os envs conda/mamba individuais.
        (padrão: False)
    extra_search_paths : list[str]
        Caminhos adicionais para varrer em busca de Python ou QGIS.
    """

    def __init__(
        self,
        include_venvs: bool = False,
        include_conda_envs: bool = False,
        extra_search_paths: Optional[list[str]] = None,
    ):
        self.include_venvs = include_venvs
        self.include_conda_envs = include_conda_envs
        self.extra_search_paths = extra_search_paths or []

    # ── Detecção de Python standalone ────────────────────────────────────────

    def _detect_pythons(self) -> list[PythonInfo]:
        pythons: list[PythonInfo] = []

        if OS_NAME == "Windows":
            pythons += _win_pythons_from_registry()
            pythons += _win_pythons_from_paths()
        else:
            pythons += _unix_pythons_from_paths()

        # Python atual (pode não estar nos paths acima)
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

        # Venvs opcionais
        if self.include_venvs:
            pythons += self._scan_venvs()

        # Conda envs opcionais
        if self.include_conda_envs:
            pythons += self._scan_conda_envs()

        # Extra paths
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
        """Varre diretórios comuns em busca de venvs (.venv, venv, env)."""
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
        """Lista envs conda/mamba via `conda env list`."""
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

    # ── Detecção de QGIS ─────────────────────────────────────────────────────

    def _detect_qgis(self) -> list[QGISInfo]:
        if OS_NAME == "Windows":
            reg_items = _win_qgis_from_registry()
            path_items = _win_qgis_from_paths()
            # mescla sem duplicar install_path
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

    # ── Ponto de entrada ─────────────────────────────────────────────────────

    def detect(self) -> DetectionResult:
        """
        Executa toda a detecção e retorna um DetectionResult.

        O DetectionResult expõe:
          .system_pythons        → List[PythonInfo]
          .qgis_installations    → List[QGISInfo]   (cada um com .python embutido)
          .to_dict()             → dict serializável
          .to_json(indent=2)     → str JSON
        """
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
# CLI simples
# ──────────────────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Detecta todas as instalações de Python e QGIS na máquina."
    )
    parser.add_argument("--venvs",       action="store_true", help="Incluir venvs locais")
    parser.add_argument("--conda-envs",  action="store_true", help="Incluir envs conda/mamba")
    parser.add_argument("--extra-paths", nargs="*", default=[], metavar="PATH",
                        help="Caminhos extras para varrer")
    parser.add_argument("--output", default=None, metavar="FILE",
                        help="Salvar resultado em arquivo JSON")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    detector = QGISPythonDetector(
        include_venvs=args.venvs,
        include_conda_envs=args.conda_envs,
        extra_search_paths=args.extra_paths,
    )
    result = detector.detect()
    output = result.to_json()

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Resultado salvo em: {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()