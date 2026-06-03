<div align="center">

<img src="https://img.shields.io/badge/QGIS-Package%20Manager-021BA3?style=for-the-badge&logo=qgis&logoColor=white" alt="QGIS Package Manager"/>

# ⚙ QGIS Package Manager

**Gerenciador visual de pacotes Python para o QGIS — instale e remova dependências com facilidade, em qualquer ambiente.**

[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/PySide6-UI-41CD52?style=flat-square&logo=qt&logoColor=white)](https://doc.qt.io/qtforpython/)
[![Windows](https://img.shields.io/badge/Windows-✓-0078D4?style=flat-square&logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![Linux](https://img.shields.io/badge/Linux-✓-FCC624?style=flat-square&logo=linux&logoColor=black)](https://kernel.org/)
[![macOS](https://img.shields.io/badge/macOS-✓-000000?style=flat-square&logo=apple&logoColor=white)](https://www.apple.com/macos/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Version](https://img.shields.io/badge/Version-1.0.1-A38F00?style=flat-square)](CHANGELOG.md)

</div>

---

## 🗺 Índice

- [Sobre o projeto](#-sobre-o-projeto)
- [Funcionalidades](#-funcionalidades)
- [Requisitos](#-requisitos)
- [Instalação](#-instalação)
- [Como usar](#-como-usar)
- [Detecção automática de ambientes](#-detecção-automática-de-ambientes)
- [Estrutura do código](#-estrutura-do-código)
- [Exemplos de uso](#-exemplos-de-uso)
- [Perguntas frequentes](#-perguntas-frequentes)
- [Contribuindo](#-contribuindo)
- [Licença](#-licença)

---

## 📌 Sobre o projeto

O **QGIS Package Manager** nasceu de uma necessidade real: instalar pacotes Python no ambiente correto do QGIS é confuso. Chamar `pip install` no terminal errado instala o pacote no Python do sistema — não no Python embutido no QGIS — e os plugins continuam quebrando.

Esta ferramenta resolve isso com uma interface gráfica simples que:

1. **Detecta automaticamente** todos os Pythons e instalações do QGIS no sistema.
2. Permite **escolher exatamente** qual interpretador recebe os pacotes.
3. Executa `pip install` / `pip uninstall` **visualmente**, com log em tempo real.

É um arquivo `.py` único — sem configuração, sem dependências além do PySide6.

---

## ✨ Funcionalidades

### 🔍 Detecção Automática de Ambientes
- Pythons instalados via **instalador oficial** (leitura do registro do Windows)
- Pythons em **paths padrão** do sistema (Windows, Linux e macOS)
- **Python embutido** em cada instalação do QGIS encontrada
- Instalações QGIS via **OSGeo4W**, **standalone**, **Flatpak**, **Snap**, **Homebrew** e **app bundle** (.app)
- Ambientes **conda/mamba** (opcional)
- **Virtualenvs** locais (opcional)
- Python **atual** (o que está rodando o script)

### 📦 Gerenciador de Pacotes
- **Instalar** um ou mais pacotes de uma vez (separados por vírgula, espaço ou nova linha)
- Suporte a **especificadores de versão**: `numpy>=1.24`, `opencv-python==4.8.0`
- Opções de pip: `--upgrade` e `--no-deps`
- **Desinstalar** pacotes com lista navegável e filtro por nome
- Seleção em massa ("Selecionar todos" / "Limpar seleção")
- **Log em tempo real** com saída colorida do pip
- Indicador de progresso animado durante operações

### 🛠 Flexibilidade
- Seletor de Python com **ComboBox**: troca o ambiente-alvo em um clique
- Botão **"Procurar"**: localiza um Python fora da detecção automática
  - Aceita o executável diretamente (`python.exe`, `python3`)
  - Aceita a **pasta raiz do QGIS** — o Python embutido é localizado automaticamente
- Pythons adicionados manualmente são **salvos em disco** e lembrados na próxima execução
- Clique no nome do Python para **abrir a pasta no explorador de arquivos**

---

## 📋 Requisitos

| Requisito | Versão mínima |
|-----------|---------------|
| Python    | 3.9+          |
| PySide6   | 6.4+          |

> **Nota:** O QGIS em si **não** é obrigatório para rodar a ferramenta. Você pode instalá-la em qualquer Python com PySide6 disponível.
> Se o `PySide6` não estiver instalado, o script tentará instalá-lo automaticamente no Python que está executando.

---

## 🚀 Instalação

### 1. Clone o repositório

```bash
git clone https://github.com/seu-usuario/qgis-package-manager.git
cd qgis-package-manager
```

### 2. Instale a dependência (opcional)

```bash
pip install PySide6
```

> Se você não instalar manualmente, o script tentará instalar o `PySide6` automaticamente ao ser executado.

### 3. Execute

```bash
python qgis_pkg_manager.py
```

#### Alternativa: Rodar direto dentro do QGIS

Abra o **Console Python** do QGIS (`Plugins → Console Python`) e execute:

```python
import subprocess, sys
subprocess.Popen([sys.executable, "/caminho/para/qgis_pkg_manager.py"])
```

#### Alternativa: Windows — criar atalho `.bat`

```bat
@echo off
"C:\Program Files\QGIS 3.x\apps\Python312\python.exe" "C:\ferramentas\qgis_pkg_manager.py"
pause
```

---

## 🖥 Como usar

### Aba Instalar

1. Selecione o **interpretador Python** desejado no seletor do cabeçalho.
2. Digite os pacotes no campo de texto — um por linha, ou separados por vírgula/espaço.
3. (Opcional) Marque `--upgrade` para forçar atualização ou `--no-deps` para pular dependências.
4. Clique em **▶ Instalar pacotes** e acompanhe o log.

```
# Exemplos de entrada válida
opencv-python
numpy>=1.24
scipy, geopandas
shapely==2.0.1
```

### Aba Desinstalar

1. Troque para o modo **Desinstalar** no seletor de modo.
2. A lista de pacotes instalados é carregada automaticamente.
3. Use o campo de **filtro** para encontrar o pacote rapidamente.
4. Marque os pacotes desejados e clique em **🗑 Desinstalar selecionados**.
5. Confirme na caixa de diálogo — a remoção é permanente.

### Adicionar um Python manualmente

Clique em **📂 Procurar…** e:
- Selecione diretamente o executável `python.exe` / `python3`, **ou**
- Selecione a **pasta raiz** de uma instalação QGIS — o Python embutido será encontrado automaticamente.

O Python adicionado é salvo em `%TEMP%/qgis_pkg_manager/custom_pythons.json` e reaparece na lista nas próximas execuções.

---

## 🔎 Detecção automática de ambientes

O detector (`QGISPythonDetector`) roda em segundo plano ao iniciar e mapeia:

```
Sistema
├── Windows
│   ├── Registro (HKLM/HKCU SOFTWARE\Python)
│   ├── Paths padrão (C:\Python*, AppData, Miniconda, etc.)
│   └── QGIS
│       ├── Registro (SOFTWARE\QGIS, Uninstall keys)
│       └── Path scan (Program Files, OSGeo4W)
├── Linux
│   ├── PATH do sistema + /usr/bin, /usr/local/bin, etc.
│   ├── pyenv (~/.pyenv/versions)
│   └── QGIS
│       ├── apt (which qgis)
│       ├── Snap (/snap/qgis*)
│       ├── Flatpak (~/.local/share/flatpak/...)
│       └── /opt e /usr/local
└── macOS
    ├── /usr/bin, /usr/local/bin, /opt/homebrew/bin
    └── QGIS
        ├── App bundle (/Applications/QGIS*.app)
        └── Homebrew (brew --prefix qgis)
```

Além disso, opcionalmente detecta:
- **Ambientes conda/mamba** via `conda env list --json`
- **Virtualenvs** em `~`, `.venv`, `venv`, `env`, `.env`

---

## 🗂 Estrutura do código

```
qgis_pkg_manager.py
│
├── Data classes
│   ├── PythonInfo          # Representa um interpretador Python
│   ├── QGISInfo            # Representa uma instalação do QGIS
│   └── DetectionResult     # Resultado completo da detecção
│
├── Helpers
│   ├── _run()              # Executa subprocess com timeout
│   ├── _python_version()   # Extrai versão de um executável
│   ├── _python_arch()      # Detecta arquitetura (32/64-bit)
│   └── _seen()             # Desduplicação por path resolvido
│
├── Detectores por SO
│   ├── Windows
│   │   ├── _win_pythons_from_registry()
│   │   ├── _win_pythons_from_paths()
│   │   ├── _win_qgis_from_registry()
│   │   ├── _win_qgis_from_paths()
│   │   └── _win_qgis_python()
│   ├── Linux
│   │   ├── _unix_pythons_from_paths()
│   │   ├── _linux_qgis()
│   │   └── _linux_qgis_python()
│   └── macOS
│       ├── _macos_qgis()
│       └── _macos_qgis_python()
│
├── QGISPythonDetector      # Orquestra toda a detecção
│
├── Workers (QThread)
│   ├── PipWorker           # Roda pip install/uninstall com streaming de log
│   └── ListPackagesWorker  # Lista pacotes instalados via importlib.metadata
│
└── QGISPkgManager (QWidget)
    ├── Painel Instalar
    └── Painel Desinstalar
```

---

## 💡 Exemplos de uso

### Usando o detector via código

```python
from qgis_pkg_manager import QGISPythonDetector

detector = QGISPythonDetector(
    include_conda_envs=True,
    include_venvs=True,
)
result = detector.detect()

# Listar todos os Pythons encontrados
for py in result.system_pythons:
    print(f"{py.name} → {py.executable}")

# Listar todas as instalações do QGIS
for qgis in result.qgis_installations:
    print(f"{qgis.name} ({qgis.source}) → {qgis.install_path}")
    if qgis.python:
        print(f"  Python embutido: {qgis.python.executable}")

# Exportar como JSON
print(result.to_json())
```

**Saída exemplo:**
```json
{
  "system_pythons": [
    {
      "name": "Python 3.12.3",
      "version": "3.12.3",
      "executable": "C:\\Python312\\python.exe",
      "source": "registry",
      "os_name": "windows",
      "architecture": "64bit",
      "is_qgis_python": false
    }
  ],
  "qgis_installations": [
    {
      "name": "QGIS 3.36.3",
      "version": "3.36.3",
      "install_path": "C:\\Program Files\\QGIS 3.36.3",
      "source": "registry",
      "python": {
        "name": "Python 3.12.3",
        "executable": "C:\\Program Files\\QGIS 3.36.3\\apps\\Python312\\python.exe",
        "is_qgis_python": true,
        "qgis_version": "3.36.3"
      }
    }
  ]
}
```

### Rodando a GUI

```python
from PySide6.QtWidgets import QApplication
from qgis_pkg_manager import QGISPkgManager
import sys

app = QApplication(sys.argv)
app.setStyle("Fusion")
win = QGISPkgManager()
win.show()
sys.exit(app.exec())
```

---

## ❓ Perguntas frequentes

**P: Preciso ter o QGIS instalado para usar?**
Não. A ferramenta detecta instalações do QGIS se houver, mas funciona em qualquer Python com PySide6.

**P: O pip_worker precisa de permissões de administrador?**
Depende do Python alvo. Se ele estiver em `Program Files`, sim. Para Pythons do usuário ou ambientes conda/venv, geralmente não.

**P: Os Pythons adicionados manualmente somem ao fechar o app?**
Não. Eles são salvos em `%TEMP%\qgis_pkg_manager\custom_pythons.json` (Windows) ou equivalente em Linux/macOS.

**P: Posso usar com QGIS via OSGeo4W?**
Sim. O detector lida com a estrutura `OSGeo4W\apps\qgis*` e localiza o Python embutido corretamente.

**P: É possível instalar a partir de um arquivo `.whl` local?**
Sim — basta digitar o caminho completo do arquivo `.whl` no campo de pacotes, da mesma forma que faria no terminal.

```
C:\Downloads\meu_pacote-1.0-py3-none-any.whl
```

---

## 🤝 Contribuindo

Contribuições são bem-vindas! Para contribuir:

1. Faça um **fork** do repositório.
2. Crie uma branch: `git checkout -b feature/minha-melhoria`
3. Faça suas alterações e commit: `git commit -m 'feat: descrição da melhoria'`
4. Envie para o fork: `git push origin feature/minha-melhoria`
5. Abra um **Pull Request**.

### Ideias de contribuição

- [ ] Suporte a `pip install -r requirements.txt`
- [ ] Exportar lista de pacotes instalados como `requirements.txt`
- [ ] Suporte a índices alternativos (`--index-url`, `--extra-index-url`)
- [ ] Tema claro (light mode)
- [ ] Integração com o gerenciador de plugins do próprio QGIS
- [ ] Empacotamento como plugin QGIS `.zip`
- [ ] Testes automatizados para o detector

---

## 📄 Licença

Distribuído sob a licença **MIT**. Veja o arquivo [LICENSE](LICENSE) para mais detalhes.

---

<div align="center">

Feito com ♥ para a comunidade QGIS

</div>