"""
QGIS Package Manager v1.0.1 — Gerenciador de pacotes Python para o QGIS
Requer: PySide6  →  pip install PySide6
Uso: rode com o Python interno do QGIS ou qualquer Python com PySide6 instalado.
"""

import sys
import subprocess
import json
import pathlib
import datetime
import tempfile
import re as _re
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QRadioButton, QButtonGroup, QPushButton, QTextEdit,
    QLabel, QScrollArea, QCheckBox, QFrame, QLineEdit,
    QProgressBar, QMessageBox, QStackedWidget,
    QSizePolicy, QComboBox, QFileDialog
)
from PySide6.QtCore import Qt, QThread, Signal, QDir
from PySide6.QtGui import QFont, QColor, QTextCursor, QDesktopServices
from PySide6.QtCore import QUrl

# ── Importa o detector do dep2.py ─────────────────────────────────────────────
from dep2 import QGISPythonDetector

# ── Pasta temp para salvar Pythons personalizados ─────────────────────────────
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
    # Não duplica
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


# ── Detecta todos os Pythons disponíveis (standalone + QGIS embutidos) ────────
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

    # Adiciona os personalizados salvos em temp
    for entry in _load_custom_pythons():
        options.append((entry["label"], entry["exe"]))

    return options


_ALL_PYTHON_OPTIONS = _load_python_options()


# ─────────────────────────────────────────────────────────────────────────────
# Worker thread – roda pip sem travar a UI
# ─────────────────────────────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────────────────────
# Worker thread – lista pacotes instalados de um Python específico
# ─────────────────────────────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────────────────────
# Janela principal
# ─────────────────────────────────────────────────────────────────────────────
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

    # ── Propriedade para o executável Python atual ────────────────────────────
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
            "python.exe", "python3.exe",           # Windows
            "python", "python3",                    # Linux/macOS
            "bin/python.exe", "bin/python3.exe",
            "bin/python", "bin/python3",
            # Caminhos típicos do QGIS Windows
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
        # Busca recursiva limitada (profundidade 4) para qualquer python.exe / python3
        for depth in range(1, 5):
            pattern = "/".join(["*"] * depth)
            for name in ("python.exe", "python3.exe", "python", "python3"):
                for found in root.glob(f"{pattern}/{name}"):
                    if found.is_file():
                        return str(found)
        return None

    # ── UI ───────────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # ══ CABEÇALHO: Título + versão ═══════════════════════════════════════
        header = QFrame()
        header.setObjectName("header")
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(20, 10, 20, 10)
        h_lay.setSpacing(0)

        # Bloco título + versão (coluna esquerda)
        title_col = QVBoxLayout()
        title_col.setSpacing(1)

        title_lbl = QLabel("⚙  QGIS Package Manager")
        title_lbl.setObjectName("title")
        version_lbl = QLabel("v1.0.1")
        version_lbl.setObjectName("version")

        title_col.addWidget(title_lbl)
        title_col.addWidget(version_lbl)
        h_lay.addLayout(title_col)
        h_lay.addStretch()

        # ── Seletor Python + botões (coluna direita) ──────────────────────
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

        # ══ BARRA DE MODO ════════════════════════════════════════════════════
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

        # ══ STACK: INSTALAR / DESINSTALAR ════════════════════════════════════
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_install_panel())
        self.stack.addWidget(self._build_uninstall_panel())
        root.addWidget(self.stack, stretch=1)

        # ══ LOG ══════════════════════════════════════════════════════════════
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

    # ── Painel INSTALAR ───────────────────────────────────────────────────────
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

    # ── Painel DESINSTALAR ────────────────────────────────────────────────────
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

    # ── Lógica de modo ────────────────────────────────────────────────────────
    def _on_mode_change(self, checked: bool):
        if self.rb_install.isChecked():
            self.stack.setCurrentIndex(0)
            self.btn_refresh.setVisible(False)
        else:
            self.stack.setCurrentIndex(1)
            self.btn_refresh.setVisible(True)
            if not self._checkboxes:
                self._load_installed()

    # ── Procurar Python / Pasta QGIS ─────────────────────────────────────────
    def _on_browse_python(self):
        """
        Permite selecionar:
          1. Um executável Python diretamente (python.exe / python)
          2. Uma pasta (e.g. raiz do QGIS) — busca python automaticamente
        """
        # Primeiro tenta como arquivo executável
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
            # Tenta seleção de pasta (caso o usuário cancele o diálogo de arquivo)
            folder = QFileDialog.getExistingDirectory(
                self,
                "Ou selecione a pasta raiz do QGIS / Python",
                ""
            )
            if not folder:
                return
            # Busca o python na pasta
            found = self._find_python_in_folder(folder)
            if not found:
                QMessageBox.warning(
                    self, "Python não encontrado",
                    f"Não foi possível encontrar um executável Python na pasta:\n{folder}\n\n"
                    "Tente apontar diretamente para o python.exe."
                )
                return
            file_path = found

        # Valida o executável encontrado
        version = self._get_python_version(file_path)
        if not version:
            QMessageBox.warning(
                self, "Python inválido",
                f"O arquivo selecionado não parece ser um Python válido:\n{file_path}"
            )
            return

        # Verifica se já está no combo
        for i in range(self.py_selector.count()):
            if self.py_selector.itemData(i) == file_path:
                self.py_selector.setCurrentIndex(i)
                self._log(f"[INFO] Python já listado, selecionado: {file_path}", "#a78bfa")
                return

        # Salva em temp (JSON com nome + versão + data)
        _save_custom_python(file_path, version)
        self._log(
            f"[INFO] Python personalizado salvo em: {_CUSTOM_PYTHONS_FILE}",
            "#a78bfa"
        )

        label = f"Python {version} (personalizado)"
        self.py_selector.addItem(label, file_path)
        self.py_selector.setCurrentIndex(self.py_selector.count() - 1)
        self._log(f"[INFO] Python adicionado: {file_path} ({version})", "#34d399")

    # ── Abrir local do Python no explorer ─────────────────────────────────────
    def _open_python_path(self):
        p = pathlib.Path(self.python_exe)
        folder = str(p.parent)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        self._log(f"[INFO] Abrindo pasta: {folder}", "#60a5fa")

    # ── Troca de Python selecionado ───────────────────────────────────────────
    def _on_python_changed(self, index: int):
        exe = self.py_selector.itemData(index)
        if not exe:
            return
        self.python_exe = exe
        self._log(f"[INFO] Python alterado para: {exe}", "#60a5fa")
        if hasattr(self, '_checkboxes') and self.rb_uninstall.isChecked():
            self._load_installed()

    # ── Carrega pacotes instalados ────────────────────────────────────────────
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

    # ── Instalar ──────────────────────────────────────────────────────────────
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

    # ── Desinstalar ───────────────────────────────────────────────────────────
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

    # ── Executa pip em thread ─────────────────────────────────────────────────
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

    # ── Estilo QSS ────────────────────────────────────────────────────────────
    def _apply_style(self):
        self.setStyleSheet("""
            /* ═══════════════════════════════════════════════════════════════
               QGIS PKG MANAGER — PALETA ZINC / INDIGO / EMERALD
               Background profundo  · Acentos índigo vivos · Verde p/ sucesso
               ═══════════════════════════════════════════════════════════════ */

            /* ── Base ── */
            QWidget {
                background: #18181b;
                color: #e4e4e7;
                font-family: 'Segoe UI Variable', 'Segoe UI', 'Inter', 'Roboto', sans-serif;
                font-size: 12px;
            }

            /* ── Cabeçalho ── */
            QFrame#header {
                background: #09090b;
                border-bottom: 1px solid #27272a;
                padding: 0;
            }
            QLabel#title {
                font-size: 15px;
                font-weight: 700;
                color: #fafafa;
                letter-spacing: 0.3px;
            }
            QLabel#version {
                font-size: 10px;
                font-weight: 500;
                color: #6366f1;
                letter-spacing: 1px;
                text-transform: uppercase;
            }

            /* ── Label "Python:" ── */
            QLabel#pyLbl {
                color: #a1a1aa;
                font-size: 12px;
            }

            /* ── Info clicável do python ── */
            QLabel#pyinfo {
                font-size: 11px;
                color: #71717a;
                padding: 4px 8px;
                border-radius: 4px;
                border: 1px solid transparent;
            }
            QLabel#pyinfo:hover {
                color: #818cf8;
                background: #1e1e2e;
                border: 1px solid #3730a3;
            }

            /* ── Seletor de Python ── */
            QComboBox#pySelector {
                background: #27272a;
                border: 1px solid #3f3f46;
                border-radius: 5px;
                padding: 5px 10px;
                color: #e4e4e7;
                font-size: 12px;
                min-width: 260px;
                max-height: 28px;
            }
            QComboBox#pySelector:hover {
                border-color: #6366f1;
                background: #2a2a2e;
            }
            QComboBox#pySelector:focus {
                border-color: #6366f1;
            }
            QComboBox#pySelector::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox#pySelector::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #71717a;
                margin-right: 6px;
            }
            QComboBox#pySelector QAbstractItemView {
                background: #1c1c1f;
                border: 1px solid #3f3f46;
                border-radius: 5px;
                selection-background-color: #4f46e5;
                selection-color: #fff;
                color: #e4e4e7;
                font-size: 12px;
                padding: 3px;
                outline: none;
            }

            /* ── Barra de modo ── */
            QFrame#modeBar {
                background: #09090b;
                border-bottom: 1px solid #27272a;
            }
            QRadioButton#rb {
                font-size: 12px;
                spacing: 7px;
                color: #a1a1aa;
            }
            QRadioButton#rb::indicator {
                width: 14px; height: 14px;
                border-radius: 7px;
                border: 2px solid #3f3f46;
                background: #18181b;
            }
            QRadioButton#rb::indicator:hover {
                border-color: #6366f1;
            }
            QRadioButton#rb::indicator:checked {
                border-color: #6366f1;
                background: #6366f1;
            }
            QRadioButton#rb:checked {
                color: #e4e4e7;
                font-weight: 600;
            }

            /* ── Inputs ── */
            QTextEdit#inputBox, QLineEdit#searchBox {
                background: #27272a;
                border: 1px solid #3f3f46;
                border-radius: 5px;
                padding: 8px 10px;
                color: #e4e4e7;
                font-size: 12px;
            }
            QTextEdit#inputBox:focus, QLineEdit#searchBox:focus {
                border: 1px solid #6366f1;
            }

            /* ── Log ── */
            QFrame#logFrame {
                background: #09090b;
                border-top: 1px solid #27272a;
            }
            QTextEdit#logBox {
                background: #000000;
                border: 1px solid #27272a;
                border-radius: 4px;
                color: #71717a;
                font-family: 'Cascadia Code', 'Consolas', 'JetBrains Mono', monospace;
                font-size: 11px;
                padding: 6px 8px;
            }

            /* ── Progress bar ── */
            QProgressBar#pbar {
                border: none;
                background: #27272a;
                border-radius: 1px;
            }
            QProgressBar#pbar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4f46e5, stop:1 #818cf8);
                border-radius: 1px;
            }

            /* ── Botão Primário (Instalar) ── */
            QPushButton#btnPrimary {
                background: #4f46e5;
                color: #fff;
                font-size: 13px;
                font-weight: 600;
                border: none;
                border-radius: 5px;
                padding: 8px 20px;
            }
            QPushButton#btnPrimary:hover {
                background: #6366f1;
            }
            QPushButton#btnPrimary:pressed {
                background: #3730a3;
            }
            QPushButton#btnPrimary:disabled {
                background: #3f3f46;
                color: #52525b;
            }

            /* ── Botão Destrutivo (Desinstalar) — fonte vermelha, negrito, sem fundo colorido ── */
            QPushButton#btnDanger {
                background: #27272a;
                color: #f87171;
                font-size: 13px;
                font-weight: 700;
                border: 1px solid #7f1d1d;
                border-radius: 5px;
                padding: 8px 20px;
            }
            QPushButton#btnDanger:hover {
                background: #3f1515;
                border-color: #ef4444;
                color: #fca5a5;
            }
            QPushButton#btnDanger:pressed {
                background: #500b0b;
            }
            QPushButton#btnDanger:disabled {
                background: #3f3f46;
                color: #52525b;
                border-color: #3f3f46;
            }

            /* ── Botão Secundário ── */
            QPushButton#btnSecondary {
                background: transparent;
                color: #a1a1aa;
                border: 1px solid #3f3f46;
                border-radius: 5px;
                padding: 5px 12px;
                font-weight: 500;
                font-size: 12px;
                max-height: 28px;
            }
            QPushButton#btnSecondary:hover {
                background: #27272a;
                border-color: #6366f1;
                color: #e4e4e7;
            }
            QPushButton#btnSecondary:pressed {
                background: #1c1c1f;
            }

            /* ── Botão Pequeno ── */
            QPushButton#btnTiny {
                background: transparent;
                color: #71717a;
                border: 1px solid #3f3f46;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton#btnTiny:hover {
                background: #27272a;
                color: #e4e4e7;
                border-color: #52525b;
            }

            /* ── Checkboxes de pacotes ── */
            QCheckBox#pkgCheck {
                spacing: 8px;
                color: #a1a1aa;
                padding: 4px 6px;
                border-radius: 3px;
            }
            QCheckBox#pkgCheck:hover {
                background: #27272a;
                color: #e4e4e7;
            }
            QCheckBox#pkgCheck::indicator {
                width: 14px; height: 14px;
                border-radius: 3px;
                border: 1px solid #3f3f46;
                background: #18181b;
            }
            QCheckBox#pkgCheck::indicator:hover {
                border-color: #6366f1;
            }
            QCheckBox#pkgCheck::indicator:checked {
                background: #4f46e5;
                border-color: #4f46e5;
            }

            /* ── Checkboxes de opções ── */
            QCheckBox#optCheck {
                spacing: 7px;
                color: #71717a;
                font-size: 12px;
            }
            QCheckBox#optCheck::indicator {
                width: 13px; height: 13px;
                border-radius: 3px;
                border: 1px solid #3f3f46;
                background: #27272a;
            }
            QCheckBox#optCheck::indicator:hover {
                border-color: #6366f1;
            }
            QCheckBox#optCheck::indicator:checked {
                background: #4f46e5;
                border-color: #4f46e5;
            }

            /* ── Badge contador ── */
            QLabel#badge {
                background: #27272a;
                color: #a1a1aa;
                border-radius: 10px;
                padding: 3px 10px;
                font-size: 11px;
                font-weight: 600;
            }

            /* ── Hints ── */
            QLabel#hint {
                color: #52525b;
                font-size: 11px;
            }

            /* ── Scroll ── */
            QScrollArea#pkgScroll {
                border: 1px solid #27272a;
                border-radius: 5px;
                background: #18181b;
            }
            QScrollBar:vertical {
                background: #18181b;
                width: 7px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: #3f3f46;
                border-radius: 3px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: #52525b;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }

            /* ── Tooltips ── */
            QToolTip {
                background: #1c1c1f;
                color: #d4d4d8;
                border: 1px solid #3f3f46;
                border-radius: 4px;
                padding: 6px 8px;
                font-size: 11px;
            }
        """)


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = QGISPkgManager()
    win.show()
    sys.exit(app.exec())