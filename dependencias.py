"""
QGIS Package Manager — Gerenciador de pacotes Python para o QGIS
Requer: PySide6  →  pip install PySide6
Uso: rode com o Python interno do QGIS ou qualquer Python com PySide6 instalado.
"""

import sys
import subprocess
import importlib.metadata
import re as _re
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QRadioButton, QButtonGroup, QPushButton, QTextEdit,
    QLabel, QScrollArea, QCheckBox, QFrame, QLineEdit,
    QSplitter, QProgressBar, QMessageBox, QStackedWidget,
    QSizePolicy, QComboBox, QFileDialog
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QColor, QPalette, QIcon, QTextCursor, QDesktopServices
from PySide6.QtCore import QUrl

# ── Importa o detector do dep2.py ─────────────────────────────────────────────
from dep2 import QGISPythonDetector

# ── Detecta todos os Pythons disponíveis (standalone + QGIS embutidos) ────────
_PYTHON_OPTIONS: list[tuple[str, str]] = []  # (rótulo, executável)
def _load_python_options() -> list[tuple[str, str]]:
    """Retorna lista de (label, executable) para todos os Pythons detectados."""
    detector = QGISPythonDetector()
    result = detector.detect()
    options: list[tuple[str, str]] = []

    # Pythons standalone
    for py in result.system_pythons:
        label = py.name
        if py.source == "current_process":
            label += " (atual)"
        elif py.source == "conda":
            label += " (conda)"
        options.append((label, py.executable))

    # Pythons embutidos no QGIS
    for qgis in result.qgis_installations:
        if qgis.python and qgis.python.executable:
            label = f"{qgis.python.name} [embutido: {qgis.name}]"
            options.append((label, qgis.python.executable))

    return options

# Carrega cache de opções (executado apenas uma vez na importação)
_ALL_PYTHON_OPTIONS = _load_python_options()

# ── Python atualmente selecionado ─────────────────────────────────────────────
_CURRENT_PYTHON_EXE: str = sys.executable  # fallback: o que está rodando

# ─────────────────────────────────────────────────────────────────────────────
# Worker thread – roda pip sem travar a UI
# ─────────────────────────────────────────────────────────────────────────────
class PipWorker(QThread):
    log_line  = Signal(str)   # linha de output
    finished  = Signal(bool)  # True = sucesso

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
    packages_loaded = Signal(list)  # list[tuple[nome, versão]]
    log_line        = Signal(str)

    def __init__(self, python_exe: str):
        super().__init__()
        self.python_exe = python_exe

    def run(self):
        try:
            # Usa importlib.metadata via subprocess para pegar os pacotes do Python alvo
            code = """
import importlib.metadata, json
pkgs = sorted(importlib.metadata.distributions(), key=lambda d: d.metadata.get('Name', '').lower())
out = [(d.metadata.get('Name', '?'), d.metadata.get('Version', '?')) for d in pkgs]
print(json.dumps(out))
"""
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
                import json
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
        self.setMinimumSize(920, 680)
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
        # Atualiza o label de info com caminho clicável
        version_str = self._get_python_version(value) or "?"
        self.py_info_label.setText(
            f"Python {version_str}  ·  📎 {value}"
        )
        self.py_info_label.setToolTip(f"Clique para abrir o local\n{value}")

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

    # ── UI ───────────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # ── Cabeçalho ─────────────────────────────────────────────────────
        header = QFrame()
        header.setObjectName("header")
        header.setFixedHeight(72)
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(24, 0, 24, 0)

        title = QLabel("⚙  QGIS Package Manager")
        title.setObjectName("title")
        h_lay.addWidget(title)
        h_lay.addStretch()

        # ── Seletor de Python ─────────────────────────────────────────────
        selector_frame = QFrame()
        selector_frame.setObjectName("selectorFrame")
        sel_lay = QHBoxLayout(selector_frame)
        sel_lay.setContentsMargins(0, 0, 0, 0)
        sel_lay.setSpacing(8)

        sel_lay.addWidget(QLabel("Python:"))

        self.py_selector = QComboBox()
        self.py_selector.setObjectName("pySelector")
        self.py_selector.setMinimumWidth(320)
        self.py_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        # Preenche o combo com as opções detectadas
        current_exe_lower = sys.executable.lower().replace("\\", "/")
        selected_index = 0
        for i, (label, exe) in enumerate(_ALL_PYTHON_OPTIONS):
            self.py_selector.addItem(label, exe)
            # Marca o Python atual como selecionado por padrão
            if exe.lower().replace("\\", "/") == current_exe_lower:
                selected_index = i

        self.py_selector.setCurrentIndex(selected_index)
        self.py_selector.currentIndexChanged.connect(self._on_python_changed)
        sel_lay.addWidget(self.py_selector, stretch=1)

        # ── Botão "Procurar..." ─────────────────────────────────────────
        self.btn_browse = QPushButton("📂  Procurar…")
        self.btn_browse.setObjectName("btnSecondary")
        self.btn_browse.clicked.connect(self._on_browse_python)
        sel_lay.addWidget(self.btn_browse)

        h_lay.addWidget(selector_frame)

        # ── Info do Python selecionado (caminho clicável) ─────────────────
        self.py_info_label = QLabel()
        self.py_info_label.setObjectName("pyinfo")
        self.py_info_label.setCursor(Qt.PointingHandCursor)
        self.py_info_label.mousePressEvent = lambda e: self._open_python_path()
        h_lay.addWidget(self.py_info_label)

        # Inicializa com o Python atual
        self.python_exe = self.py_selector.currentData() or sys.executable

        root.addWidget(header)

        # ── Seletor de modo ───────────────────────────────────────────────
        mode_frame = QFrame()
        mode_frame.setObjectName("modeBar")
        mode_lay = QHBoxLayout(mode_frame)
        mode_lay.setContentsMargins(24, 12, 24, 12)
        mode_lay.setSpacing(32)

        self.rb_install   = QRadioButton("  Instalar")
        self.rb_uninstall = QRadioButton("  Desinstalar")
        self.rb_install.setChecked(True)
        self.rb_install.setObjectName("rb")
        self.rb_uninstall.setObjectName("rb")

        group = QButtonGroup(self)
        group.addButton(self.rb_install)
        group.addButton(self.rb_uninstall)

        self.rb_install.toggled.connect(self._on_mode_change)

        mode_lay.addWidget(QLabel("Modo:"))
        mode_lay.addWidget(self.rb_install)
        mode_lay.addWidget(self.rb_uninstall)
        mode_lay.addStretch()

        # botão atualizar lista (só visível no modo desinstalar)
        self.btn_refresh = QPushButton("↻  Atualizar lista")
        self.btn_refresh.setObjectName("btnSecondary")
        self.btn_refresh.clicked.connect(self._load_installed)
        self.btn_refresh.setVisible(False)
        mode_lay.addWidget(self.btn_refresh)

        root.addWidget(mode_frame)

        # ── Área central (stack) ──────────────────────────────────────────
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_install_panel())   # índice 0
        self.stack.addWidget(self._build_uninstall_panel()) # índice 1
        root.addWidget(self.stack, stretch=1)

        # ── Log ───────────────────────────────────────────────────────────
        log_frame = QFrame()
        log_frame.setObjectName("logFrame")
        log_lay = QVBoxLayout(log_frame)
        log_lay.setContentsMargins(12, 8, 12, 8)
        log_lay.setSpacing(4)

        log_header = QHBoxLayout()
        log_header.addWidget(QLabel("📋  Saída do pip"))
        log_header.addStretch()
        self.btn_clear_log = QPushButton("Limpar")
        self.btn_clear_log.setObjectName("btnTiny")
        self.btn_clear_log.clicked.connect(lambda: self.log.clear())
        log_header.addWidget(self.btn_clear_log)
        log_lay.addLayout(log_header)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setObjectName("logBox")
        self.log.setFixedHeight(160)
        log_lay.addWidget(self.log)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.setFixedHeight(4)
        self.progress.setObjectName("pbar")
        self.progress.setVisible(False)
        log_lay.addWidget(self.progress)

        root.addWidget(log_frame)

    # ── Painel INSTALAR ───────────────────────────────────────────────────────
    def _build_install_panel(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)

        lbl = QLabel(
            "Digite os pacotes que deseja instalar.\n"
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

        # opções extras
        opt_lay = QHBoxLayout()
        self.chk_upgrade = QCheckBox("--upgrade  (atualizar se já instalado)")
        self.chk_upgrade.setObjectName("optCheck")
        self.chk_no_deps = QCheckBox("--no-deps  (ignorar dependências)")
        self.chk_no_deps.setObjectName("optCheck")
        opt_lay.addWidget(self.chk_upgrade)
        opt_lay.addWidget(self.chk_no_deps)
        opt_lay.addStretch()
        lay.addLayout(opt_lay)

        self.btn_install = QPushButton("▶  Instalar pacotes")
        self.btn_install.setObjectName("btnPrimary")
        self.btn_install.clicked.connect(self._run_install)
        lay.addWidget(self.btn_install)

        return w

    # ── Painel DESINSTALAR ────────────────────────────────────────────────────
    def _build_uninstall_panel(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(10)

        top_lay = QHBoxLayout()
        hint = QLabel("Marque os pacotes que deseja remover:")
        hint.setObjectName("hint")
        top_lay.addWidget(hint)
        top_lay.addStretch()

        self.lbl_selected = QLabel("0 selecionados")
        self.lbl_selected.setObjectName("badge")
        top_lay.addWidget(self.lbl_selected)

        self.btn_sel_all  = QPushButton("Selecionar todos")
        self.btn_sel_all.setObjectName("btnTiny")
        self.btn_sel_all.clicked.connect(lambda: self._select_all(True))
        self.btn_sel_none = QPushButton("Limpar seleção")
        self.btn_sel_none.setObjectName("btnTiny")
        self.btn_sel_none.clicked.connect(lambda: self._select_all(False))
        top_lay.addWidget(self.btn_sel_all)
        top_lay.addWidget(self.btn_sel_none)
        lay.addLayout(top_lay)

        # busca
        self.search = QLineEdit()
        self.search.setObjectName("searchBox")
        self.search.setPlaceholderText("🔍  Filtrar pacotes…")
        self.search.textChanged.connect(self._filter_packages)
        lay.addWidget(self.search)

        # lista com scroll
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("pkgScroll")
        self.pkg_container = QWidget()
        self.pkg_layout    = QVBoxLayout(self.pkg_container)
        self.pkg_layout.setSpacing(2)
        self.pkg_layout.setContentsMargins(8, 8, 8, 8)
        self.pkg_layout.addStretch()
        scroll.setWidget(self.pkg_container)
        lay.addWidget(scroll, stretch=1)

        self.btn_uninstall = QPushButton("🗑  Desinstalar selecionados")
        self.btn_uninstall.setObjectName("btnDanger")
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

    # ── Buscar Python em uma pasta ─────────────────────────────────────────
    def _on_browse_python(self):
        """Abre diálogo para selecionar um executável Python (python.exe) de qualquer pasta."""
        exe_name = "python.exe" if sys.platform == "win32" else "python"
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar executável Python",
            "",
            f"Python ({exe_name});;Todos (*)"
        )
        if not file_path:
            return

        # Verifica se é um Python válido
        version = self._get_python_version(file_path)
        if not version:
            QMessageBox.warning(
                self, "Python inválido",
                f"O arquivo selecionado não parece ser um Python válido:\n{file_path}"
            )
            return

        # Adiciona ao combo (se já não existe) e seleciona
        for i in range(self.py_selector.count()):
            if self.py_selector.itemData(i) == file_path:
                self.py_selector.setCurrentIndex(i)
                return

        label = f"Python {version} (personalizado)"
        self.py_selector.addItem(label, file_path)
        self.py_selector.setCurrentIndex(self.py_selector.count() - 1)
        self._log(f"[INFO] Python personalizado adicionado: {file_path}", "#6ee7b7")

    # ── Abrir local do Python no explorador ────────────────────────────────
    def _open_python_path(self):
        """Abre a pasta do executável Python no explorador de arquivos."""
        import pathlib
        p = pathlib.Path(self.python_exe)
        folder = str(p.parent)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        self._log(f"[INFO] Abrindo pasta: {folder}", "#93c5fd")

    # ── Troca de Python selecionado ───────────────────────────────────────────
    def _on_python_changed(self, index: int):
        exe = self.py_selector.itemData(index)
        if not exe:
            return
        self.python_exe = exe
        self._log(
            f"[INFO] Python alterado para: {exe}",
            "#93c5fd"
        )
        # Recarrega a lista de pacotes se estiver no modo desinstalar
        if hasattr(self, '_checkboxes') and self.rb_uninstall.isChecked():
            self._load_installed()

    # ── Carrega pacotes instalados (agora via subprocess para o Python alvo) ──
    def _load_installed(self):
        # limpa lista anterior
        for cb in self._checkboxes:
            cb.setParent(None)
        self._checkboxes.clear()

        self._log(f"[INFO] Carregando pacotes de: {self.python_exe}", "#93c5fd")
        self._set_busy(True)

        self._list_worker = ListPackagesWorker(self.python_exe)
        self._list_worker.packages_loaded.connect(self._on_packages_loaded)
        self._list_worker.log_line.connect(lambda l: self._log(l))
        self._list_worker.start()

    def _on_packages_loaded(self, packages: list):
        self._set_busy(False)

        # Remove o stretch antigo e os checkboxes
        # O layout já foi limpo em _load_installed, mas vamos garantir
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
        self._log(f"[INFO] {len(self._checkboxes)} pacotes encontrados em {self.python_exe}.", "#6ee7b7")

        # Reaplica o filtro se houver texto na busca
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
        # separa por vírgula, espaço ou nova linha
        pkgs = [p.strip() for p in _re.split(r"[\s,]+", raw) if p.strip()]
        if not pkgs:
            self._log("[AVISO] Nenhum pacote informado.", "#fbbf24")
            return

        cmd = [self.python_exe, "-m", "pip", "install"] + pkgs
        if self.chk_upgrade.isChecked():
            cmd.append("--upgrade")
        if self.chk_no_deps.isChecked():
            cmd.append("--no-deps")

        self._log(f"[CMD] {' '.join(cmd)}", "#93c5fd")
        self._run_cmd(cmd, post_action=self._on_install_done)

    def _on_install_done(self):
        """Após instalar, se estiver no modo desinstalar, recarrega a lista."""
        if self.rb_uninstall.isChecked():
            self._load_installed()

    # ── Desinstalar ───────────────────────────────────────────────────────────
    def _run_uninstall(self):
        selected = [
            cb.text().split("  (")[0].strip()
            for cb in self._checkboxes if cb.isChecked()
        ]
        if not selected:
            self._log("[AVISO] Nenhum pacote selecionado.", "#fbbf24")
            return

        confirm = QMessageBox.question(
            self, "Confirmar remoção",
            f"Desinstalar {len(selected)} pacote(s)?\n\n" + "\n".join(selected),
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return

        cmd = [self.python_exe, "-m", "pip", "uninstall", "-y"] + selected
        self._log(f"[CMD] {' '.join(cmd)}", "#93c5fd")
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
        color = "#6ee7b7" if ok else "#f87171"
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

    def _log(self, text: str, color: str = "#e2e8f0"):
        self.log.setTextColor(QColor(color))
        self.log.append(text)
        self.log.moveCursor(QTextCursor.End)

    # ── Estilo ────────────────────────────────────────────────────────────────
    def _apply_style(self):
        self.setStyleSheet("""
            /* ── Geral ── */
            QWidget {
                background: #0f172a;
                color: #e2e8f0;
                font-family: 'Consolas', 'JetBrains Mono', monospace;
                font-size: 13px;
            }

            /* ── Cabeçalho ── */
            QFrame#header {
                background: #1e293b;
                border-bottom: 2px solid #334155;
                min-height: 72px;
            }
            QLabel#title {
                font-size: 17px;
                font-weight: bold;
                color: #38bdf8;
                letter-spacing: 1px;
            }
            QLabel#pyinfo {
                font-size: 11px;
                color: #64748b;
                margin-left: 12px;
                padding: 4px 8px;
                border-radius: 4px;
                border: 1px solid transparent;
            }
            QLabel#pyinfo:hover {
                color: #38bdf8;
                background: #1e293b;
                border: 1px solid #334155;
            }

            /* ── Seletor de Python ── */
            QFrame#selectorFrame {
                background: transparent;
            }
            QComboBox#pySelector {
                background: #0f172a;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 6px 12px;
                color: #e2e8f0;
                font-size: 12px;
                min-width: 280px;
                max-width: 480px;
            }
            QComboBox#pySelector:hover {
                border-color: #38bdf8;
            }
            QComboBox#pySelector::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox#pySelector::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid #64748b;
                margin-right: 6px;
            }
            QComboBox#pySelector QAbstractItemView {
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 4px;
                selection-background-color: #0ea5e9;
                selection-color: #fff;
                color: #e2e8f0;
                font-size: 12px;
                padding: 4px;
                outline: none;
            }

            /* ── Barra de modo ── */
            QFrame#modeBar {
                background: #1e293b;
                border-bottom: 1px solid #334155;
            }
            QRadioButton#rb {
                font-size: 14px;
                spacing: 8px;
                color: #cbd5e1;
            }
            QRadioButton#rb::indicator {
                width: 18px; height: 18px;
                border-radius: 9px;
                border: 2px solid #475569;
                background: #0f172a;
            }
            QRadioButton#rb::indicator:checked {
                border-color: #38bdf8;
                background: #38bdf8;
            }
            QRadioButton#rb:checked {
                color: #38bdf8;
                font-weight: bold;
            }

            /* ── Inputs ── */
            QTextEdit#inputBox, QLineEdit#searchBox {
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 10px;
                color: #e2e8f0;
                font-size: 13px;
            }
            QTextEdit#inputBox:focus, QLineEdit#searchBox:focus {
                border-color: #38bdf8;
            }

            /* ── Log ── */
            QFrame#logFrame {
                background: #0b1120;
                border-top: 2px solid #334155;
            }
            QTextEdit#logBox {
                background: #020817;
                border: 1px solid #1e293b;
                border-radius: 4px;
                color: #94a3b8;
                font-size: 12px;
                padding: 6px;
            }

            /* ── Progress bar ── */
            QProgressBar#pbar {
                border: none;
                background: #1e293b;
                border-radius: 2px;
            }
            QProgressBar#pbar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #38bdf8, stop:1 #818cf8);
                border-radius: 2px;
            }

            /* ── Botões ── */
            QPushButton#btnPrimary {
                background: #0ea5e9;
                color: #fff;
                font-size: 14px;
                font-weight: bold;
                border: none;
                border-radius: 8px;
                padding: 12px 24px;
            }
            QPushButton#btnPrimary:hover  { background: #38bdf8; }
            QPushButton#btnPrimary:pressed{ background: #0284c7; }
            QPushButton#btnPrimary:disabled { background: #334155; color: #64748b; }

            QPushButton#btnDanger {
                background: #dc2626;
                color: #fff;
                font-size: 14px;
                font-weight: bold;
                border: none;
                border-radius: 8px;
                padding: 12px 24px;
            }
            QPushButton#btnDanger:hover  { background: #ef4444; }
            QPushButton#btnDanger:pressed{ background: #b91c1c; }
            QPushButton#btnDanger:disabled{ background: #334155; color: #64748b; }

            QPushButton#btnSecondary {
                background: #334155;
                color: #e2e8f0;
                border: none;
                border-radius: 6px;
                padding: 7px 16px;
            }
            QPushButton#btnSecondary:hover { background: #475569; }

            QPushButton#btnTiny {
                background: #1e293b;
                color: #94a3b8;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
            }
            QPushButton#btnTiny:hover { background: #334155; color: #e2e8f0; }

            /* ── Checkboxes de pacotes ── */
            QCheckBox#pkgCheck {
                spacing: 10px;
                color: #cbd5e1;
                padding: 5px 8px;
                border-radius: 4px;
            }
            QCheckBox#pkgCheck:hover { background: #1e293b; }
            QCheckBox#pkgCheck::indicator {
                width: 16px; height: 16px;
                border-radius: 3px;
                border: 1px solid #475569;
                background: #0f172a;
            }
            QCheckBox#pkgCheck::indicator:checked {
                background: #0ea5e9;
                border-color: #0ea5e9;
                image: none;
            }

            QCheckBox#optCheck {
                spacing: 8px;
                color: #94a3b8;
            }
            QCheckBox#optCheck::indicator {
                width: 15px; height: 15px;
                border-radius: 3px;
                border: 1px solid #475569;
                background: #1e293b;
            }
            QCheckBox#optCheck::indicator:checked {
                background: #818cf8;
                border-color: #818cf8;
            }

            /* ── Badge contador ── */
            QLabel#badge {
                background: #1e40af;
                color: #bfdbfe;
                border-radius: 10px;
                padding: 2px 10px;
                font-size: 11px;
                font-weight: bold;
            }

            QLabel#hint {
                color: #64748b;
                font-size: 12px;
            }

            /* ── Scroll ── */
            QScrollArea#pkgScroll {
                border: 1px solid #1e293b;
                border-radius: 6px;
                background: #080f1e;
            }
            QScrollBar:vertical {
                background: #1e293b;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #475569;
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
        """)


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = QGISPkgManager()
    win.show()
    sys.exit(app.exec())