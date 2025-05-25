#!/usr/bin/env python3
import os
import sys
import platform
import re
import shutil
import json
import subprocess  # добавлен для запуска установки в Linux-среде

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QCheckBox,
    QTextEdit, QRadioButton, QGroupBox, QMessageBox
)
from PyQt5.QtCore import QProcess, QTimer

# Dummy импорт для того, чтобы PyInstaller включил модуль google_play_scraper,
# даже если его импорт не встречается непосредственно в коде
if False:
    import google_play_scraper

# Функция для удаления ANSI escape-последовательностей
ANSI_ESCAPE = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')

def clean_output(text):
    return ANSI_ESCAPE.sub('', text)

def get_pyinstaller_cmd():
    """
    Если в пользовательском каталоге установлен исполняемый файл pyinstaller,
    возвращает его полный путь. Иначе возвращает команду для вызова модуля с
    использованием 'python3 -m PyInstaller'.
    """
    user_pyinstaller = os.path.join(os.path.expanduser("~"), ".local", "bin", "pyinstaller")
    if os.path.exists(user_pyinstaller):
        return [user_pyinstaller]
    else:
        return ["python3", "-m", "PyInstaller"]

class CompilerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyInstaller Compiler GUI")
        self.resize(650, 600)
        self.initUI()
        self.loadSettings()
        
    def initUI(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # Выбор директории проекта
        proj_layout = QHBoxLayout()
        self.projLineEdit = QLineEdit()
        self.projBrowseButton = QPushButton("Выбрать директорию")
        self.projBrowseButton.clicked.connect(self.browseProjectDir)
        proj_layout.addWidget(QLabel("Директория проекта:"))
        proj_layout.addWidget(self.projLineEdit)
        proj_layout.addWidget(self.projBrowseButton)
        layout.addLayout(proj_layout)
        
        # Выбор основного исполняемого файла
        main_file_layout = QHBoxLayout()
        self.mainFileLineEdit = QLineEdit()
        self.mainFileBrowseButton = QPushButton("Выбрать файл")
        self.mainFileBrowseButton.clicked.connect(self.browseMainFile)
        main_file_layout.addWidget(QLabel("Основной файл (например, gui.py):"))
        main_file_layout.addWidget(self.mainFileLineEdit)
        main_file_layout.addWidget(self.mainFileBrowseButton)
        layout.addLayout(main_file_layout)
        
        # Новый блок: выбор файла иконки
        icon_layout = QHBoxLayout()
        self.iconLineEdit = QLineEdit()
        self.iconBrowseButton = QPushButton("Выбрать иконку")
        self.iconBrowseButton.clicked.connect(self.browseIconFile)
        icon_layout.addWidget(QLabel("Файл иконки:"))
        icon_layout.addWidget(self.iconLineEdit)
        icon_layout.addWidget(self.iconBrowseButton)
        layout.addLayout(icon_layout)
        
        # Выбор целевых ОС
        os_layout = QHBoxLayout()
        self.winCheckBox = QCheckBox("Windows")
        self.linuxCheckBox = QCheckBox("Linux")
        os_layout.addWidget(QLabel("Целевые ОС:"))
        os_layout.addWidget(self.winCheckBox)
        os_layout.addWidget(self.linuxCheckBox)
        layout.addLayout(os_layout)
        
        # Выбор режима упаковки (onefile или папка)
        pack_group = QGroupBox("Режим упаковки")
        pack_layout = QHBoxLayout()
        self.onefileRadio = QRadioButton("Onefile")
        self.folderRadio = QRadioButton("Без onefile")
        self.onefileRadio.setChecked(True)
        pack_layout.addWidget(self.onefileRadio)
        pack_layout.addWidget(self.folderRadio)
        pack_group.setLayout(pack_layout)
        layout.addWidget(pack_group)
        
        # Выбор режима консоли
        console_group = QGroupBox("Режим консоли")
        console_layout = QHBoxLayout()
        self.consoleRadio = QRadioButton("С консолью")
        self.windowedRadio = QRadioButton("Без консоли")
        self.consoleRadio.setChecked(True)
        console_layout.addWidget(self.consoleRadio)
        console_layout.addWidget(self.windowedRadio)
        console_group.setLayout(console_layout)
        layout.addWidget(console_group)
        
        # Опция для включения ms-playwright в сборку
        self.playwrightCheckBox = QCheckBox("Включить ms-playwright в сборку")
        self.playwrightCheckBox.setChecked(True)  # По умолчанию включено
        layout.addWidget(self.playwrightCheckBox)
        
        # Чекбокс для добавления google_play_scraper и её зависимостей в билд
        self.googlePlayScraperCheckBox = QCheckBox("Добавить google_play_scraper и зависимости")
        self.googlePlayScraperCheckBox.setChecked(False)
        layout.addWidget(self.googlePlayScraperCheckBox)
        
        # Кнопка компиляции
        self.compileButton = QPushButton("Начать компиляцию")
        self.compileButton.clicked.connect(self.startCompilation)
        layout.addWidget(self.compileButton)
        
        # Кнопка запуска скомпилированной программы
        self.runButton = QPushButton("Запустить программу")
        self.runButton.clicked.connect(self.runCompiledPrograms)
        layout.addWidget(self.runButton)
        
        # Окно логов
        self.logTextEdit = QTextEdit()
        self.logTextEdit.setReadOnly(True)
        layout.addWidget(self.logTextEdit)
        
        # QProcess для фоновых задач (для Windows-задач)
        self.process = None

    def browseIconFile(self):
        options = QFileDialog.Options()
        fileName, _ = QFileDialog.getOpenFileName(
            self, "Выбрать файл иконки", "", 
            "Icon Files (*.ico *.png);;All Files (*)", options=options)
        if fileName:
            self.iconLineEdit.setText(fileName)
    
    def loadSettings(self):
        """
        Загружает настройки из JSON-файла settings.json, расположенного в той же директории, что и скрипт.
        """
        settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except Exception:
            settings = {}
        
        self.projLineEdit.setText(settings.get("projectDir", ""))
        self.mainFileLineEdit.setText(settings.get("mainFile", ""))
        self.iconLineEdit.setText(settings.get("iconFile", ""))  # Загружаем путь до иконки
        self.winCheckBox.setChecked(settings.get("targetWindows", False))
        self.linuxCheckBox.setChecked(settings.get("targetLinux", False))
        mode_pack = settings.get("packagingMode", "onefile")
        if mode_pack == "onefile":
            self.onefileRadio.setChecked(True)
            self.folderRadio.setChecked(False)
        else:
            self.onefileRadio.setChecked(False)
            self.folderRadio.setChecked(True)
        mode_console = settings.get("consoleMode", "console")
        if mode_console == "console":
            self.consoleRadio.setChecked(True)
            self.windowedRadio.setChecked(False)
        else:
            self.consoleRadio.setChecked(False)
            self.windowedRadio.setChecked(True)
        self.playwrightCheckBox.setChecked(settings.get("includePlaywright", True))
        self.googlePlayScraperCheckBox.setChecked(settings.get("includeGooglePlayScraper", False))
    
    def saveSettings(self):
        """
        Сохраняет настройки в JSON-файл settings.json, расположенного в той же директории, что и скрипт.
        """
        settings = {
            "projectDir": self.projLineEdit.text().strip(),
            "mainFile": self.mainFileLineEdit.text().strip(),
            "iconFile": self.iconLineEdit.text().strip(),  # Сохраняем путь до иконки
            "targetWindows": self.winCheckBox.isChecked(),
            "targetLinux": self.linuxCheckBox.isChecked(),
            "packagingMode": "onefile" if self.onefileRadio.isChecked() else "folder",
            "consoleMode": "console" if self.consoleRadio.isChecked() else "windowed",
            "includePlaywright": self.playwrightCheckBox.isChecked(),
            "includeGooglePlayScraper": self.googlePlayScraperCheckBox.isChecked(),
        }
        settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
        try:
            with open(settings_path, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
            self.appendLog("Ошибка сохранения настроек: " + str(e))
    
    def closeEvent(self, event):
        self.saveSettings()
        event.accept()
    
    def browseProjectDir(self):
        directory = QFileDialog.getExistingDirectory(self, "Выберите директорию проекта")
        if directory:
            self.projLineEdit.setText(directory)
    
    def browseMainFile(self):
        options = QFileDialog.Options()
        fileName, _ = QFileDialog.getOpenFileName(
            self, "Выберите основной исполняемый файл", "", 
            "Python Files (*.py);;All Files (*)", options=options)
        if fileName:
            self.mainFileLineEdit.setText(fileName)
    
    def appendLog(self, text):
        self.logTextEdit.append(text)
    
    def convert_to_wsl_path(self, win_path):
        """
        Преобразует путь Windows (например, "C:\Folder\Project") в формат WSL (/mnt/c/Folder/Project).
        """
        win_path = os.path.abspath(win_path)
        drive, path = os.path.splitdrive(win_path)
        if drive:
            drive_letter = drive[0].lower()
            path = path.replace("\\", "/")
            return f"/mnt/{drive_letter}{path}"
        else:
            return win_path.replace("\\", "/")
    
    def startCompilation(self):
        project_dir = self.projLineEdit.text().strip()
        main_file = self.mainFileLineEdit.text().strip()
        target_win = self.winCheckBox.isChecked()
        target_linux = self.linuxCheckBox.isChecked()
        onefile = self.onefileRadio.isChecked()
        icon = self.iconLineEdit.text().strip()  # Получаем путь до иконки
        
        if not project_dir or not os.path.isdir(project_dir):
            QMessageBox.warning(self, "Ошибка", "Выберите корректную директорию проекта.")
            return
        if not main_file or not os.path.isfile(main_file):
            QMessageBox.warning(self, "Ошибка", "Выберите корректный основной исполняемый файл.")
            return
        if not (target_win or target_linux):
            QMessageBox.warning(self, "Ошибка", "Выберите хотя бы одну целевую ОС.")
            return
        
        self.compileButton.setEnabled(False)
        self.appendLog("Начало компиляции...")
        
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.tasks = []  # Задачи: (Целевая ОС, список команды, detached_flag)
        
        # Сборка для Windows
        if target_win:
            win_output_dir = os.path.join(base_dir, "Compiled", "Windows")
            os.makedirs(win_output_dir, exist_ok=True)
            cmd_win = ["pyinstaller"]
            if onefile:
                cmd_win.append("--onefile")
            if self.windowedRadio.isChecked():
                cmd_win.append("--windowed")
            # Добавляем иконку, если выбрана
            if icon and os.path.isfile(icon):
                cmd_win += ["--icon", icon]
            # Добавляем ms-playwright если выбрано
            if self.playwrightCheckBox.isChecked():
                playwright_dir = "C:/Users/SkyWi/AppData/Local/ms-playwright"
                add_data_arg = f"{playwright_dir};ms-playwright"
                cmd_win += ["--add-data", add_data_arg]
            # Добавляем google_play_scraper и её зависимости, если выбрано
            if self.googlePlayScraperCheckBox.isChecked():
                cmd_win += ["--hidden-import", "google_play_scraper", "--collect-all", "google_play_scraper"]
            cmd_win += ["--distpath", win_output_dir, main_file]
            self.tasks.append(("Windows", cmd_win, False))
        
        # Если целевая ОС Linux выбрана и выбран флажок google_play_scraper, устанавливаем библиотеку в Linux-среде
        if target_linux and self.googlePlayScraperCheckBox.isChecked():
            self.appendLog("Устанавливаем google_play_scraper в Linux-среде...")
            if platform.system() == "Windows":
                install_cmd = ["wsl", "-d", "Ubuntu-22.04", "python3", "-m", "pip", "install", "google_play_scraper"]
            else:
                install_cmd = ["python3", "-m", "pip", "install", "google_play_scraper"]
            result = subprocess.run(install_cmd, capture_output=True, text=True)
            if result.returncode == 0:
                self.appendLog("google_play_scraper успешно установлен в Linux-среде.")
            else:
                self.appendLog("Ошибка установки google_play_scraper в Linux-среде: " + result.stderr)
        
        # Сборка для Linux
        if target_linux:
            linux_output_dir = os.path.join(base_dir, "Compiled", "Linux")
            os.makedirs(linux_output_dir, exist_ok=True)
            if platform.system() == "Windows":
                linux_output_dir_wsl = self.convert_to_wsl_path(linux_output_dir)
                main_file_wsl = self.convert_to_wsl_path(main_file)
                cmd_linux = get_pyinstaller_cmd()
                if onefile:
                    cmd_linux.append("--onefile")
                if self.windowedRadio.isChecked():
                    cmd_linux.append("--windowed")
                # Добавляем иконку, если выбрана
                if icon and os.path.isfile(icon):
                    icon_wsl = self.convert_to_wsl_path(icon)
                    cmd_linux += ["--icon", icon_wsl]
                # Добавляем ms-playwright если выбрано
                if self.playwrightCheckBox.isChecked():
                    playwright_dir = "C:/Users/SkyWi/AppData/Local/ms-playwright"
                    playwright_dir_wsl = self.convert_to_wsl_path(playwright_dir)
                    add_data_arg = f"{playwright_dir_wsl}:ms-playwright"
                    cmd_linux += ["--add-data", add_data_arg]
                # Добавляем google_play_scraper и её зависимости, если выбрано
                if self.googlePlayScraperCheckBox.isChecked():
                    cmd_linux += ["--hidden-import", "google_play_scraper", "--collect-all", "google_play_scraper"]
                cmd_linux += ["--distpath", linux_output_dir_wsl, main_file_wsl]
                # Формируем команду для WSL, чтобы окно оставалось открытым
                command_str = "wsl -d Ubuntu-22.04 " + " ".join(cmd_linux) + " & pause"
                detached_cmd = ["cmd.exe", "/c", "start", "", "cmd.exe", "/k", command_str]
                self.tasks.append(("Linux", detached_cmd, True))
            else:
                cmd_linux = ["pyinstaller"]
                if onefile:
                    cmd_linux.append("--onefile")
                if self.windowedRadio.isChecked():
                    cmd_linux.append("--windowed")
                # Добавляем иконку, если выбрана
                if icon and os.path.isfile(icon):
                    cmd_linux += ["--icon", icon]
                # Добавляем ms-playwright если выбрано
                if self.playwrightCheckBox.isChecked():
                    playwright_dir = "C:/Users/SkyWi/AppData/Local/ms-playwright"
                    add_data_arg = f"{playwright_dir}:ms-playwright"  # Для Linux используется ':'
                    cmd_linux += ["--add-data", add_data_arg]
                # Добавляем google_play_scraper и её зависимости, если выбрано
                if self.googlePlayScraperCheckBox.isChecked():
                    cmd_linux += ["--hidden-import", "google_play_scraper", "--collect-all", "google_play_scraper"]
                cmd_linux += ["--distpath", linux_output_dir, main_file]
                self.tasks.append(("Linux", cmd_linux, False))
        
        self.currentTaskIndex = 0
        self.runNextTask()
    
    def runNextTask(self):
        if self.currentTaskIndex >= len(self.tasks):
            self.appendLog("Компиляция завершена.")
            self.compileButton.setEnabled(True)
            if self.check_successful_compilation():
                # После успешной компиляции копируем иконку в папку билда
                self.copy_icon_to_compiled_folder()
                self.cleanup_build_files()
            return
        
        target, command, detached = self.tasks[self.currentTaskIndex]
        self.appendLog(f"\nКомпиляция для {target}:")
        self.appendLog("Команда: " + " ".join(command))
        
        if detached:
            success = QProcess.startDetached(command[0], command[1:], os.path.dirname(os.path.abspath(__file__)))
            if success:
                self.appendLog(f"Задача для {target} запущена в отдельном терминале.\n")
            else:
                self.appendLog(f"Не удалось запустить задачу для {target}.\n")
            self.currentTaskIndex += 1
            QTimer.singleShot(100, self.runNextTask)
        else:
            self.process = QProcess(self)
            self.process.setProcessChannelMode(QProcess.MergedChannels)
            self.process.readyReadStandardOutput.connect(self.handleProcessOutput)
            self.process.readyReadStandardError.connect(self.handleProcessOutput)
            self.process.finished.connect(self.taskFinished)
            self.process.setWorkingDirectory(os.path.dirname(os.path.abspath(__file__)))
            self.process.start(command[0], command[1:])
    
    def handleProcessOutput(self):
        if self.process:
            # Использование errors="replace" позволяет избежать ошибок декодирования
            data = self.process.readAllStandardOutput().data().decode("utf-8", errors="replace")
            cleaned_data = clean_output(data)
            self.appendLog(cleaned_data)
    
    def taskFinished(self):
        if self.process:
            exitCode = self.process.exitCode()
            target, command, detached = self.tasks[self.currentTaskIndex]
            self.appendLog(f"Компиляция для {target} закончена (exit code = {exitCode}).\n")
            self.process = None
            self.currentTaskIndex += 1
            QTimer.singleShot(100, self.runNextTask)
    
    def check_successful_compilation(self):
        """
        Проверяет, существуют ли скомпилированные файлы для выбранных целевых ОС.
        Если для всех ОС файлы найдены – возвращает True, иначе False.
        """
        base_dir = os.path.dirname(os.path.abspath(__file__))
        main_file = self.mainFileLineEdit.text().strip()
        if not main_file:
            return False
        base_name = os.path.splitext(os.path.basename(main_file))[0]
        onefile = self.onefileRadio.isChecked()
        success = True
        if self.winCheckBox.isChecked():
            if onefile:
                win_exe = os.path.join(base_dir, "Compiled", "Windows", base_name + ".exe")
            else:
                win_exe = os.path.join(base_dir, "Compiled", "Windows", base_name, base_name + ".exe")
            if not os.path.exists(win_exe):
                self.appendLog("Отсутствует Windows-исполняемый файл: " + win_exe)
                success = False
        if self.linuxCheckBox.isChecked():
            if onefile:
                linux_exe = os.path.join(base_dir, "Compiled", "Linux", base_name)
            else:
                linux_exe = os.path.join(base_dir, "Compiled", "Linux", base_name, base_name)
            if not os.path.exists(linux_exe):
                self.appendLog("Отсутствует Linux-исполняемый файл: " + linux_exe)
                success = False
        return success

    def copy_icon_to_compiled_folder(self):
        """
        Если указан файл иконки, копирует его (с сохранением имени) в папки с скомпилированными программами.
        """
        icon = self.iconLineEdit.text().strip()
        if not icon or not os.path.isfile(icon):
            return  # Нет валидного файла иконки
        base_dir = os.path.dirname(os.path.abspath(__file__))
        main_file = self.mainFileLineEdit.text().strip()
        base_name = os.path.splitext(os.path.basename(main_file))[0]
        onefile = self.onefileRadio.isChecked()
        
        # Для Windows
        if self.winCheckBox.isChecked():
            if onefile:
                win_folder = os.path.join(base_dir, "Compiled", "Windows")
            else:
                win_folder = os.path.join(base_dir, "Compiled", "Windows", base_name)
            try:
                shutil.copy(icon, win_folder)
                self.appendLog(f"Иконка скопирована в {win_folder}")
            except Exception as e:
                self.appendLog("Не удалось скопировать иконку в Windows: " + str(e))
        
        # Для Linux
        if self.linuxCheckBox.isChecked():
            if onefile:
                linux_folder = os.path.join(base_dir, "Compiled", "Linux")
            else:
                linux_folder = os.path.join(base_dir, "Compiled", "Linux", base_name)
            try:
                shutil.copy(icon, linux_folder)
                self.appendLog(f"Иконка скопирована в {linux_folder}")
            except Exception as e:
                self.appendLog("Не удалось скопировать иконку в Linux: " + str(e))
    
    def cleanup_build_files(self):
        """
        Удаляет все .spec файлы и папку build из базовой директории,
        если сборка прошла успешно.
        """
        base_dir = os.path.dirname(os.path.abspath(__file__))
        for item in os.listdir(base_dir):
            if item.endswith(".spec"):
                try:
                    os.remove(os.path.join(base_dir, item))
                    self.appendLog(f"Удалён файл {item}")
                except Exception as e:
                    self.appendLog(f"Не удалось удалить {item}: {e}")
        build_dir = os.path.join(base_dir, "build")
        if os.path.isdir(build_dir):
            try:
                shutil.rmtree(build_dir)
                self.appendLog("Удалена папка build")
            except Exception as e:
                self.appendLog(f"Не удалось удалить папку build: {e}")
    
    def runCompiledPrograms(self):
        """
        Запускает скомпилированные программы для выбранных ОС.
        Для Windows – запускается исполняемый файл напрямую.
        Для Linux – запускается через WSL (Ubuntu-22.04).
        """
        base_dir = os.path.dirname(os.path.abspath(__file__))
        main_file = self.mainFileLineEdit.text().strip()
        if not main_file:
            QMessageBox.warning(self, "Ошибка", "Основной файл не задан!")
            return
        base_name = os.path.splitext(os.path.basename(main_file))[0]
        onefile = self.onefileRadio.isChecked()
        
        # Запуск Windows-приложения
        if self.winCheckBox.isChecked():
            if onefile:
                win_exe = os.path.join(base_dir, "Compiled", "Windows", base_name + ".exe")
            else:
                win_exe = os.path.join(base_dir, "Compiled", "Windows", base_name, base_name + ".exe")
            if os.path.exists(win_exe):
                QProcess.startDetached(win_exe)
                self.appendLog("Запущено Windows-приложение: " + win_exe)
            else:
                self.appendLog("Не найден Windows-исполняемый файл: " + win_exe)
        
        # Запуск Linux-приложения через WSL
        if self.linuxCheckBox.isChecked():
            if onefile:
                linux_exe = os.path.join(base_dir, "Compiled", "Linux", base_name)
            else:
                linux_exe = os.path.join(base_dir, "Compiled", "Linux", base_name, base_name)
            if os.path.exists(linux_exe):
                linux_exe_wsl = self.convert_to_wsl_path(linux_exe)
                QProcess.startDetached("wsl", ["-d", "Ubuntu-22.04", linux_exe_wsl], os.path.dirname(linux_exe))
                self.appendLog("Запущено Linux-приложение через WSL: " + linux_exe)
            else:
                self.appendLog("Не найден Linux-исполняемый файл: " + linux_exe)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = CompilerWindow()
    window.show()
    sys.exit(app.exec_())
