#!/usr/bin/env python3
import sys
import time
import threading
import datetime
import json
import os
import math
import re

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout,
                             QListWidget, QListWidgetItem, QPushButton, QLabel, QTextEdit, QTableWidget, QTableWidgetItem,
                             QGridLayout, QLineEdit, QCheckBox, QMessageBox, QInputDialog, QDialog, QFormLayout,
                             QDialogButtonBox, QFileDialog, QHeaderView, QSizePolicy, QPlainTextEdit, QComboBox)
from PyQt5.QtCore import QTimer, Qt, pyqtSignal

from config import ConfigManager, GLOBAL_STATS_FILE, load_known_apps, save_known_apps
from parser import ParserThread, scan_group_immediately
from notifications import send_telegram_message


# ---------------------
# МОДАЛЬНОЕ ОКНО ДЛЯ ДОБАВЛЕНИЯ/РЕДАКТИРОВАНИЯ ЧАТА
# ---------------------
class ChatSettingsDialog(QDialog):
    def __init__(self, chat_data=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки чата")
        self.resize(350, 180)  # Уменьшен размер по высоте

        self.chat_data = chat_data if chat_data is not None else {
            "name": "",
            "telegram_token": "",
            "telegram_chat_id": ""
        }

        # Используем QVBoxLayout с вложенным QFormLayout
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.name_edit = QLineEdit(self.chat_data.get("name", ""))
        self.token_edit = QLineEdit(self.chat_data.get("telegram_token", ""))
        self.chat_id_edit = QLineEdit(self.chat_data.get("telegram_chat_id", ""))

        form_layout.addRow("Название чата:", self.name_edit)
        form_layout.addRow("Telegram Token:", self.token_edit)
        form_layout.addRow("Telegram Chat ID:", self.chat_id_edit)

        layout.addLayout(form_layout)

        # Растягиваем кнопки по ширине окна и убираем лишнее пространство снизу
        self.button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.button_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(self.button_box)

        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

    def get_data(self):
        return {
            "name": self.name_edit.text().strip(),
            "telegram_token": self.token_edit.text().strip(),
            "telegram_chat_id": self.chat_id_edit.text().strip()
        }

# ---------------------
# МОДАЛЬНОЕ ОКНО НАСТРОЕК ГРУППЫ
# ---------------------
class GroupSettingsDialog(QDialog):
    def __init__(self, group_data=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки группы")
        self.resize(400, 450)
        # Новые ключи для уведомлений: notify_new, notify_new_chat, notify_exact, notify_exact_chat, notify_update, notify_update_chat
        self.group_data = group_data if group_data is not None else {
            "group_name": "",
            "keywords": [],
            "enabled": True,
            "notify_new": False,
            "notify_new_chat": "",
            "notify_exact": False,
            "notify_exact_chat": "",
            "notify_update": False,
            "notify_update_chat": ""
        }
        layout = QFormLayout(self)
        
        # Название группы
        self.name_edit = QLineEdit(self.group_data.get("group_name", ""))
        layout.addRow("Название группы:", self.name_edit)
        
        # Ключевые слова
        self.keywords_edit = QPlainTextEdit()
        self.keywords_edit.setPlaceholderText("Введите ключевые слова, по одному на строке...")
        keywords = self.group_data.get("keywords", [])
        if isinstance(keywords, list):
            self.keywords_edit.setPlainText("\n".join(keywords))
        elif isinstance(keywords, str):
            self.keywords_edit.setPlainText(keywords)
        layout.addRow("Ключевые слова:", self.keywords_edit)
        
        self.load_keywords_btn = QPushButton("Загрузить из файла")
        self.load_keywords_btn.clicked.connect(self.load_keywords_from_file)
        layout.addRow("", self.load_keywords_btn)
        
        # Уведомления для новых приложений
        self.notify_new_chk = QCheckBox("Уведомлять (новые)")
        self.notify_new_chk.setChecked(self.group_data.get("notify_new", False))
        layout.addRow("", self.notify_new_chk)
        self.new_combo = QComboBox()
        self.new_combo.addItem("— Не выбрано —", "")
        chats = self.load_chats()
        for chat in chats:
            self.new_combo.addItem(chat.get("name", ""), json.dumps(chat))
        selected_new = self.group_data.get("notify_new_chat", "")
        if selected_new:
            index = self.new_combo.findData(selected_new)
            if index >= 0:
                self.new_combo.setCurrentIndex(index)
        layout.addRow("Чат (новые):", self.new_combo)
        
        # Уведомления для точного совпадения
        self.notify_exact_chk = QCheckBox("Уведомлять (точкое)")
        self.notify_exact_chk.setChecked(self.group_data.get("notify_exact", False))
        layout.addRow("", self.notify_exact_chk)
        self.exact_combo = QComboBox()
        self.exact_combo.addItem("— Не выбрано —", "")
        for chat in chats:
            self.exact_combo.addItem(chat.get("name", ""), json.dumps(chat))
        selected_exact = self.group_data.get("notify_exact_chat", "")
        if selected_exact:
            index = self.exact_combo.findData(selected_exact)
            if index >= 0:
                self.exact_combo.setCurrentIndex(index)
        layout.addRow("Чат (точкое):", self.exact_combo)
        
        # Уведомления для обновлений
        self.notify_update_chk = QCheckBox("Уведомлять (обновления)")
        self.notify_update_chk.setChecked(self.group_data.get("notify_update", False))
        layout.addRow("", self.notify_update_chk)
        self.update_combo = QComboBox()
        self.update_combo.addItem("— Не выбрано —", "")
        for chat in chats:
            self.update_combo.addItem(chat.get("name", ""), json.dumps(chat))
        selected_update = self.group_data.get("notify_update_chat", "")
        if selected_update:
            index = self.update_combo.findData(selected_update)
            if index >= 0:
                self.update_combo.setCurrentIndex(index)
        layout.addRow("Чат (обновления):", self.update_combo)
        
        # Чекбокс для включения группы
        self.enabled_chk = QCheckBox("Включить группу")
        self.enabled_chk.setChecked(self.group_data.get("enabled", True))
        layout.addRow("", self.enabled_chk)
        
        self.button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addRow(self.button_box)
    
    def load_keywords_from_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите файл с ключевыми словами",
            "",
            "Text Files (*.txt);;All Files (*)"
        )
        if path:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                keywords = []
                for line in content.splitlines():
                    for word in re.split(r'[,\s;]+', line):
                        word = word.strip()
                        if word:
                            keywords.append(word)
                self.keywords_edit.setPlainText("\n".join(keywords))
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить файл: {e}")
    
    def load_chats(self):
        config = ConfigManager.load_config()
        return config.get("chats", [])
    
    def get_data(self):
        keywords_text = self.keywords_edit.toPlainText()
        keywords = [line.strip() for line in keywords_text.splitlines() if line.strip()]
        return {
            "group_name": self.name_edit.text().strip(),
            "keywords": keywords,
            "enabled": self.enabled_chk.isChecked(),
            "notify_new": self.notify_new_chk.isChecked(),
            "notify_new_chat": self.new_combo.currentData() if self.new_combo.currentIndex() != -1 else "",
            "notify_exact": self.notify_exact_chk.isChecked(),
            "notify_exact_chat": self.exact_combo.currentData() if self.exact_combo.currentIndex() != -1 else "",
            "notify_update": self.notify_update_chk.isChecked(),
            "notify_update_chat": self.update_combo.currentData() if self.update_combo.currentIndex() != -1 else ""
        }


# ---------------------
# Виджет для отображения элемента группы
# ---------------------
class GroupItemWidget(QWidget):
    def __init__(self, group_data):
        super().__init__()
        self.group_data = group_data
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 0, 0, 0)
        self.enabled_chk = QCheckBox()
        self.enabled_chk.setChecked(self.group_data.get("enabled", True))
        layout.addWidget(self.enabled_chk)
        self.name_btn = QPushButton(self.group_data.get("group_name", "Без названия"))
        self.name_btn.setFlat(True)
        self.name_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self.name_btn)
        layout.addStretch()


# ---------------------
# Виджет для отображения чата в настройках
# ---------------------
class ChatItemWidget(QWidget):
    def __init__(self, chat_data):
        super().__init__()
        self.chat_data = chat_data
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 0, 0, 0)
        self.name_label = QLabel(chat_data.get("name", "Без названия"))
        layout.addWidget(self.name_label)
        layout.addStretch()


# ---------------------
# Основной класс панели приложения
# ---------------------
class MainPanel(QWidget):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    stats_signal = pyqtSignal(dict, dict)
    
    def __init__(self):
        super().__init__()
        self.config = ConfigManager.load_config()
        if "chats" not in self.config:
            self.config["chats"] = []
            ConfigManager.save_config(self.config)
        self.parser_thread = None
        self.stop_event = threading.Event()
        self.parser_start_time = None
        self.log_text = ""
        self.msg_stats = {"новые": 0, "точкое": 0, "обновления": 0}
        self.avg_keyword_time = 0.0
        self.parser_running = False
        self.log_signal.connect(self.append_log)
        self.progress_signal.connect(self.update_progress_label)
        self.stats_signal.connect(self.update_stats_table)
        self.initUI()
        self.runtime_timer = QTimer()
        self.runtime_timer.timeout.connect(self.update_runtime)
        # Загружаем статистику при запуске
        self.load_stats_from_file()

    def load_stats_from_file(self):
        try:
            with open(GLOBAL_STATS_FILE, "r", encoding="utf-8") as f:
                global_stats = json.load(f)
        except Exception:
            global_stats = {
                "Google Play": 0,
                "App Store": 0,
                "RuStore": 0,
                "Xiaomi Global Store": 0,
                "Xiaomi GetApps": 0,
                "Samsung Galaxy Store": 0,
                "Huawei AppGallery": 0,
                "Всего": 0,
                "Новые": 0,
                "Точное совпадение": 0,
                "Обновления": 0,
                "Среднее время обработки": 0.0
            }
        session_stats = {
            "Google Play": 0,
            "App Store": 0,
            "RuStore": 0,
            "Xiaomi Global Store": 0,
            "Xiaomi GetApps": 0,
            "Samsung Galaxy Store": 0,
            "Huawei AppGallery": 0,
            "Всего": 0
        }
        self.update_stats_table(session_stats, global_stats)

    def initUI(self):
        main_layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)
        
        # Вкладка "Парсер"
        self.parser_tab = QWidget()
        self.tabs.addTab(self.parser_tab, "Парсер")
        parser_layout = QHBoxLayout(self.parser_tab)
        
        # Левый блок: группы
        left_panel = QVBoxLayout()
        self.group_list = QListWidget()
        self.group_list.setFixedWidth(200)
        self.update_group_list()
        left_panel.addWidget(QLabel("Группы:"))
        left_panel.addWidget(self.group_list)
        btn_layout = QHBoxLayout()
        self.add_group_btn = QPushButton("Добавить группу")
        self.add_group_btn.clicked.connect(self.add_group)
        self.delete_group_btn = QPushButton("Удалить группу")
        self.delete_group_btn.clicked.connect(self.delete_group)
        btn_layout.addWidget(self.add_group_btn)
        btn_layout.addWidget(self.delete_group_btn)
        left_panel.addLayout(btn_layout)
        parser_layout.addLayout(left_panel, 1)
        
        # Правый блок: управление парсером и лог
        right_panel = QVBoxLayout()
        control_layout = QHBoxLayout()
        self.toggle_parser_btn = QPushButton("Запустить парсер")
        self.toggle_parser_btn.setFixedWidth(150)
        self.toggle_parser_btn.clicked.connect(self.toggle_parser)
        control_layout.addWidget(self.toggle_parser_btn)
        self.runtime_label = QLabel("Время работы: 0 с")
        control_layout.addWidget(self.runtime_label)
        self.progress_label = QLabel("Прогресс: 0%")
        control_layout.addWidget(self.progress_label)
        self.interval_label = QLabel("До нового цикла: - сек")
        control_layout.addWidget(self.interval_label)
        control_layout.addStretch()
        right_panel.addLayout(control_layout)
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        right_panel.addWidget(self.log_edit, 1)
        parser_layout.addLayout(right_panel, 2)
        
                # Вкладка "Статистика"
        self.stats_tab = QWidget()
        self.tabs.addTab(self.stats_tab, "Статистика")
        stats_layout = QVBoxLayout(self.stats_tab)
        self.stats_table = QTableWidget(2, 8)
        headers = ["Google Play", "App Store", "RuStore", "Xiaomi Global Store", "Xiaomi GetApps", "Samsung Galaxy Store", "Huawei AppGallery", "Всего"]
        self.stats_table.setHorizontalHeaderLabels(headers)
        self.stats_table.setVerticalHeaderLabels(["Сессия", "Глобальная"])
        self.stats_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        stats_layout.addWidget(self.stats_table)
        self.notify_stats_label = QLabel("Уведомления:\nНовые: 0\nТочное совпадение: 0\nОбновления: 0\nСреднее время обработки: 0.00 с")
        stats_layout.addWidget(self.notify_stats_label)
        
        # Вкладка "Настройки"
        self.settings_tab = QWidget()
        self.tabs.addTab(self.settings_tab, "Настройки")
        settings_layout = QVBoxLayout(self.settings_tab)
        
        # Раздел управления чатами
        chat_header = QLabel("Управление чатами:")
        chat_header.setStyleSheet("font-weight: bold;")
        settings_layout.addWidget(chat_header)
        self.chat_list = QListWidget()
        self.chat_list.setFixedHeight(150)
        self.update_chat_list()
        settings_layout.addWidget(self.chat_list)
        chat_btn_layout = QHBoxLayout()
        self.add_chat_btn = QPushButton("Добавить чат")
        self.add_chat_btn.clicked.connect(self.add_chat)
        self.edit_chat_btn = QPushButton("Редактировать чат")
        self.edit_chat_btn.clicked.connect(self.edit_chat)
        self.delete_chat_btn = QPushButton("Удалить чат")
        self.delete_chat_btn.clicked.connect(self.delete_chat)
        chat_btn_layout.addWidget(self.add_chat_btn)
        chat_btn_layout.addWidget(self.edit_chat_btn)
        chat_btn_layout.addWidget(self.delete_chat_btn)
        settings_layout.addLayout(chat_btn_layout)
        settings_layout.addSpacing(10)
        
        # Новый раздел: Уведомления об ошибках
        error_header = QLabel("Уведомления об ошибках:")
        error_header.setStyleSheet("font-weight: bold;")
        settings_layout.addWidget(error_header)
        
        self.error_notify_chk = QCheckBox("Отправлять уведомления об ошибках")
        self.error_notify_chk.setChecked(self.config.get("notify_errors", False))
        settings_layout.addWidget(self.error_notify_chk)
        
        self.error_chat_combo = QComboBox()
        self.error_chat_combo.addItem("— Не выбрано —", "")
        chats = self.config.get("chats", [])
        for chat in chats:
            self.error_chat_combo.addItem(chat.get("name", ""), json.dumps(chat))
        selected_error = self.config.get("error_chat", "")
        if selected_error:
            index = self.error_chat_combo.findData(selected_error)
            if index >= 0:
                self.error_chat_combo.setCurrentIndex(index)
        settings_layout.addWidget(QLabel("Чат для ошибок:"))
        settings_layout.addWidget(self.error_chat_combo)
        
        # Настройки интервалов, задержек и прокси
        row_layout = QHBoxLayout()
        interval_layout = QHBoxLayout()
        interval_layout.setSpacing(5)
        interval_label = QLabel("Интервал между циклами (сек):")
        self.cycle_edit = QLineEdit(str(self.config.get("cycle_interval", 1500)))
        interval_layout.addWidget(interval_label)
        interval_layout.addWidget(self.cycle_edit)
        row_layout.addLayout(interval_layout)
        
        min_delay_layout = QHBoxLayout()
        min_delay_layout.setSpacing(5)
        min_delay_label = QLabel("Задержка мин (сек):")
        delay = self.config.get("delay_range", [2, 6])
        self.delay_min_edit = QLineEdit(str(delay[0]))
        min_delay_layout.addWidget(min_delay_label)
        min_delay_layout.addWidget(self.delay_min_edit)
        row_layout.addLayout(min_delay_layout)
        
        max_delay_layout = QHBoxLayout()
        max_delay_layout.setSpacing(5)
        max_delay_label = QLabel("Задержка макс (сек):")
        self.delay_max_edit = QLineEdit(str(delay[1]))
        max_delay_layout.addWidget(max_delay_label)
        max_delay_layout.addWidget(self.delay_max_edit)
        row_layout.addLayout(max_delay_layout)
        settings_layout.addLayout(row_layout)
        
        # Прокси
        proxy_layout = QHBoxLayout()
        proxy_label = QLabel("Прокси (http://хост:порт):")
        self.proxy_edit = QLineEdit(self.config.get("proxy", ""))
        proxy_layout.addWidget(proxy_label)
        proxy_layout.addWidget(self.proxy_edit)
        settings_layout.addLayout(proxy_layout)
        
        # Сетка магазинов с лимитами
        grid2 = QGridLayout()
        grid2.addWidget(QLabel("Google Play:"), 0, 0)
        self.google_chk = QCheckBox()
        self.google_chk.setChecked(self.config.get("enable_google_play", True))
        grid2.addWidget(self.google_chk, 0, 1)
        self.max_gp_edit = QLineEdit(str(self.config.get("max_results_google_play", 8)))
        grid2.addWidget(QLabel("Лимит:"), 0, 2)
        grid2.addWidget(self.max_gp_edit, 0, 3)
        
        grid2.addWidget(QLabel("App Store:"), 0, 4)
        self.app_chk = QCheckBox()
        self.app_chk.setChecked(self.config.get("enable_app_store", True))
        grid2.addWidget(self.app_chk, 0, 5)
        self.max_as_edit = QLineEdit(str(self.config.get("max_results_app_store", 8)))
        grid2.addWidget(QLabel("Лимит:"), 0, 6)
        grid2.addWidget(self.max_as_edit, 0, 7)
        
        grid2.addWidget(QLabel("RuStore:"), 1, 0)
        self.rustore_chk = QCheckBox()
        self.rustore_chk.setChecked(self.config.get("enable_rustore", True))
        grid2.addWidget(self.rustore_chk, 1, 1)
        self.max_rs_edit = QLineEdit(str(self.config.get("max_results_rustore", 20)))
        grid2.addWidget(QLabel("Лимит:"), 1, 2)
        grid2.addWidget(self.max_rs_edit, 1, 3)
        
        grid2.addWidget(QLabel("Xiaomi Global:"), 1, 4)
        self.xiaomi_global_chk = QCheckBox()
        self.xiaomi_global_chk.setChecked(self.config.get("enable_xiaomi_global", True))
        grid2.addWidget(self.xiaomi_global_chk, 1, 5)
        self.max_xiaomi_global_edit = QLineEdit(str(self.config.get("max_results_xiaomi_global", 8)))
        grid2.addWidget(QLabel("Лимит:"), 1, 6)
        grid2.addWidget(self.max_xiaomi_global_edit, 1, 7)
        
        grid2.addWidget(QLabel("Xiaomi GetApps:"), 2, 0)
        self.xiaomi_getapps_chk = QCheckBox()
        self.xiaomi_getapps_chk.setChecked(self.config.get("enable_xiaomi_getapps", True))
        grid2.addWidget(self.xiaomi_getapps_chk, 2, 1)
        self.max_xiaomi_getapps_edit = QLineEdit(str(self.config.get("max_results_xiaomi_getapps", 8)))
        grid2.addWidget(QLabel("Лимит:"), 2, 2)
        grid2.addWidget(self.max_xiaomi_getapps_edit, 2, 3)
        
        grid2.addWidget(QLabel("Samsung Galaxy:"), 2, 4)
        self.galaxy_chk = QCheckBox()
        self.galaxy_chk.setChecked(self.config.get("enable_galaxy_store", True))
        grid2.addWidget(self.galaxy_chk, 2, 5)
        self.max_galaxy_edit = QLineEdit(str(self.config.get("max_results_samsung_galaxy", 27)))
        grid2.addWidget(QLabel("Лимит:"), 2, 6)
        grid2.addWidget(self.max_galaxy_edit, 2, 7)
        
        grid2.addWidget(QLabel("Huawei AppGallery:"), 3, 0)
        self.huawei_chk = QCheckBox()
        self.huawei_chk.setChecked(self.config.get("enable_huawei_appgallery", True))
        grid2.addWidget(self.huawei_chk, 3, 1)
        self.max_huawei_edit = QLineEdit(str(self.config.get("max_results_huawei_appgallery", 8)))
        grid2.addWidget(QLabel("Лимит:"), 3, 2)
        grid2.addWidget(self.max_huawei_edit, 3, 3)
        
        settings_layout.addLayout(grid2)
        
        settings_layout.addStretch()
        self.save_settings_btn = QPushButton("Сохранить настройки")
        self.save_settings_btn.clicked.connect(self.save_config)
        settings_layout.addWidget(self.save_settings_btn)

    def update_group_list(self):
        self.group_list.clear()
        groups = self.config.get("groups", [])
        for i, group in enumerate(groups):
            item = QListWidgetItem()
            widget = GroupItemWidget(group)
            widget.name_btn.clicked.connect(lambda checked, idx=i: self.edit_group(idx))
            widget.enabled_chk.stateChanged.connect(lambda state, idx=i: self.toggle_group_enabled(idx, state))
            item.setSizeHint(widget.sizeHint())
            self.group_list.addItem(item)
            self.group_list.setItemWidget(item, widget)

    def toggle_group_enabled(self, idx, state):
        if "groups" in self.config and idx < len(self.config["groups"]):
            self.config["groups"][idx]["enabled"] = (state == Qt.Checked)
            ConfigManager.save_config(self.config)
            self.append_log(f"Группа '{self.config['groups'][idx]['group_name']}' изменена.")

    def edit_group(self, idx):
        if "groups" in self.config and idx < len(self.config["groups"]):
            group = self.config["groups"][idx]
            dialog = GroupSettingsDialog(group, self)
            if dialog.exec_() == QDialog.Accepted:
                new_data = dialog.get_data()
                self.config["groups"][idx] = new_data
                ConfigManager.save_config(self.config)
                self.update_group_list()
                self.append_log(f"Настройки группы '{new_data['group_name']}' сохранены.")

    def add_group(self):
        text, ok = QInputDialog.getText(self, "Добавить группу", "Название группы:")
        if ok and text:
            if "groups" not in self.config:
                self.config["groups"] = []
            new_group = {
                "group_name": text,
                "keywords": [],
                "enabled": True,
                "notify_new": False,
                "notify_new_chat": "",
                "notify_exact": False,
                "notify_exact_chat": "",
                "notify_update": False,
                "notify_update_chat": ""
            }
            self.config["groups"].append(new_group)
            ConfigManager.save_config(self.config)
            self.update_group_list()
            self.append_log(f"Группа добавлена: {text}")

    def delete_group(self):
        current_row = self.group_list.currentRow()
        if current_row >= 0 and "groups" in self.config and self.config["groups"]:
            group = self.config["groups"].pop(current_row)
            ConfigManager.save_config(self.config)
            self.update_group_list()
            self.append_log(f"Группа удалена: {group.get('group_name', '')}")

    def update_chat_list(self):
        self.chat_list.clear()
        chats = self.config.get("chats", [])
        for chat in chats:
            item = QListWidgetItem(chat.get("name", "Без названия"))
            self.chat_list.addItem(item)

    def add_chat(self):
        dialog = ChatSettingsDialog()
        if dialog.exec_() == QDialog.Accepted:
            new_chat = dialog.get_data()
            if "chats" not in self.config:
                self.config["chats"] = []
            self.config["chats"].append(new_chat)
            ConfigManager.save_config(self.config)
            self.update_chat_list()
            self.append_log(f"Чат '{new_chat.get('name', '')}' добавлен.")

    def edit_chat(self):
        current_row = self.chat_list.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "Ошибка", "Выберите чат для редактирования.")
            return
        chats = self.config.get("chats", [])
        chat = chats[current_row]
        dialog = ChatSettingsDialog(chat)
        if dialog.exec_() == QDialog.Accepted:
            updated_chat = dialog.get_data()
            chats[current_row] = updated_chat
            self.config["chats"] = chats
            ConfigManager.save_config(self.config)
            self.update_chat_list()
            self.append_log(f"Чат '{updated_chat.get('name', '')}' обновлён.")

    def delete_chat(self):
        current_row = self.chat_list.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "Ошибка", "Выберите чат для удаления.")
            return
        chats = self.config.get("chats", [])
        removed = chats.pop(current_row)
        self.config["chats"] = chats
        ConfigManager.save_config(self.config)
        self.update_chat_list()
        self.append_log(f"Чат '{removed.get('name', 'Без названия')}' удалён.")

    def save_config(self):
        try:
            self.config["cycle_interval"] = int(self.cycle_edit.text())
            min_delay = float(self.delay_min_edit.text())
            max_delay = float(self.delay_max_edit.text())
            self.config["delay_range"] = [min_delay, max_delay]
            self.config["proxy"] = self.proxy_edit.text()
            self.config["enable_google_play"] = self.google_chk.isChecked()
            self.config["enable_app_store"] = self.app_chk.isChecked()
            self.config["enable_rustore"] = self.rustore_chk.isChecked()
            self.config["enable_xiaomi_global"] = self.xiaomi_global_chk.isChecked()
            self.config["enable_xiaomi_getapps"] = self.xiaomi_getapps_chk.isChecked()
            self.config["enable_galaxy_store"] = self.galaxy_chk.isChecked()
            self.config["enable_huawei_appgallery"] = self.huawei_chk.isChecked()
            self.config["notify_errors"] = self.error_notify_chk.isChecked()
            self.config["error_chat"] = self.error_chat_combo.currentData() if self.error_chat_combo.currentIndex() != -1 else ""
            self.config["max_results_google_play"] = int(self.max_gp_edit.text())
            self.config["max_results_app_store"] = int(self.max_as_edit.text())
            self.config["max_results_rustore"] = int(self.max_rs_edit.text())
            self.config["max_results_xiaomi_global"] = int(self.max_xiaomi_global_edit.text())
            self.config["max_results_xiaomi_getapps"] = int(self.max_xiaomi_getapps_edit.text())
            self.config["max_results_samsung_galaxy"] = int(self.max_galaxy_edit.text())
            self.config["max_results_huawei_appgallery"] = int(self.max_huawei_edit.text())
            ConfigManager.save_config(self.config)
            self.append_log("Настройки сохранены.")
            QMessageBox.information(self, "Сохранено", "Настройки успешно сохранены!")
        except Exception as e:
            self.append_log(f"Ошибка сохранения настроек: {e}")

    def start_parser(self):
        self.save_config()
        self.append_log("Запуск парсера...")
        self.parser_start_time = time.time()
        self.runtime_timer.start(1000)
        self.stop_event.clear()
        self.parser_thread = ParserThread(
            self.config, self.stop_event, 
            self.progress_signal.emit, 
            self.log_signal.emit, 
            self.stats_signal.emit,
            self.update_interval_label
        )
        self.parser_thread.start()
        self.parser_running = True

    def stop_parser(self):
        self.append_log("Остановка парсера...")
        self.stop_event.set()
        if self.parser_thread:
            self.parser_thread.join(5)
        self.runtime_timer.stop()
        self.append_log("Фоновый парсер остановлен.")
        self.parser_running = False

    def toggle_parser(self):
        if not self.parser_running:
            self.start_parser()
            self.toggle_parser_btn.setText("Остановить парсер")
        else:
            self.stop_parser()
            self.toggle_parser_btn.setText("Запустить парсер")

    def update_runtime(self):
        if self.parser_start_time:
            elapsed = time.time() - self.parser_start_time
            self.runtime_label.setText("Время работы: " + self.format_time(elapsed))

    def format_time(self, seconds):
        if seconds < 60:
            return f"{int(seconds)} с"
        elif seconds < 3600:
            m = int(seconds // 60)
            s = int(seconds % 60)
            return f"{m} мин {s} с"
        elif seconds < 86400:
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            return f"{h} ч {m} мин"
        else:
            d = int(seconds // 86400)
            h = int((seconds % 86400) // 3600)
            return f"{d} д {h} ч"

    def update_interval_label(self, remaining):
        try:
            rem = float(remaining)
        except:
            rem = 0
        if rem >= 60:
            m = int(rem // 60)
            s = int(rem % 60)
            text = f"{m} мин {s} сек"
        else:
            text = f"{int(rem)} сек"
        self.interval_label.setText(f"До нового цикла: {text}")

    def update_progress_label(self, value):
        self.progress_label.setText("Прогресс: {}%".format(value))

    def append_log(self, message):
        if "Уведомление" in message:
            msg = f'<font color="blue">{message}</font>'
        else:
            msg = message
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_text += f"[{timestamp}] {msg}<br/>"
        self.log_edit.setHtml(self.log_text)

    def update_stats_table(self, session_stats, global_stats):
        stores = ["Google Play", "App Store", "RuStore", "Xiaomi Global Store", "Xiaomi GetApps", "Samsung Galaxy Store", "Huawei AppGallery", "Всего"]
        for col, store in enumerate(stores):
            self.stats_table.setItem(0, col, QTableWidgetItem(str(session_stats.get(store, 0))))
            self.stats_table.setItem(1, col, QTableWidgetItem(str(global_stats.get(store, 0))))
        
        new_notif = global_stats.get("Новые", 0)
        exact_notif = global_stats.get("Точное совпадение", 0)
        update_notif = global_stats.get("Обновления", 0)
        avg_time = global_stats.get("Среднее время обработки", 0.0)
        
        notify_text = ("Уведомления:\nНовые: {}\nТочное совпадение: {}\nОбновления: {}\nСреднее время обработки: {:.2f} с"
                       .format(new_notif, exact_notif, update_notif, avg_time))
        self.notify_stats_label.setText(notify_text)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Парсер приложений")
        self.resize(1000, 700)
        self.main_panel = MainPanel()
        self.setCentralWidget(self.main_panel)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
