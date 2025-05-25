import os
import json
import logging
from logging.handlers import RotatingFileHandler

# Определяем базовую директорию для хранения данных
BASE_DIR = "data"
if not os.path.exists(BASE_DIR):
    os.makedirs(BASE_DIR)  # Создаем директорию, если она отсутствует

# Определяем пути к файлам конфигурации, статистики и логов
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
GLOBAL_STATS_FILE = os.path.join(BASE_DIR, "global_stats.json")
KNOWN_APPS_FILE = os.path.join(BASE_DIR, "known_apps.json")
RESULTS_FILE = os.path.join(BASE_DIR, "results.json")
LOG_FILE = os.path.join(BASE_DIR, "app.log")

# Функция настройки логирования с использованием вращающихся файлов
def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    # Настройка обработчика, который будет записывать логи в файл с ограничением по размеру
    handler = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    # Добавляем обработчик логов, если он еще не добавлен
    if not logger.handlers:
        logger.addHandler(handler)

# Инициализируем настройку логирования
setup_logging()

# Функция обновления глобальной статистики
def update_global_stats(new_counts):
    file_path = GLOBAL_STATS_FILE
    try:
        # Если файл статистики существует, загружаем его содержимое
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                global_stats = json.load(f)
        else:
            # Инициализируем статистику по умолчанию
            global_stats = {
                "Google Play": 0,
                "App Store": 0,
                "RuStore": 0,
                "Xiaomi Global Store": 0,
                "Xiaomi GetApps": 0,
                "Samsung Galaxy Store": 0,
                "Huawei AppGallery": 0,
                "Всего": 0
            }
    except Exception as e:
        logging.error(f"Ошибка загрузки {file_path}: {e}")
        global_stats = {
            "Google Play": 0,
            "App Store": 0,
            "RuStore": 0,
            "Xiaomi Global Store": 0,
            "Xiaomi GetApps": 0,
            "Samsung Galaxy Store": 0,
            "Huawei AppGallery": 0,
            "Всего": 0
        }
    # Обновляем статистику для каждого магазина, используя данные new_counts
    for key in ["Google Play", "App Store", "RuStore", "Xiaomi Global Store", "Xiaomi GetApps", "Samsung Galaxy Store", "Huawei AppGallery"]:
        global_stats[key] = global_stats.get(key, 0) + new_counts.get(key, 0)
    # Пересчитываем общее количество приложений
    global_stats["Всего"] = (global_stats.get("Google Play", 0) +
                             global_stats.get("App Store", 0) +
                             global_stats.get("RuStore", 0) +
                             global_stats.get("Xiaomi Global Store", 0) +
                             global_stats.get("Xiaomi GetApps", 0) +
                             global_stats.get("Samsung Galaxy Store", 0) +
                             global_stats.get("Huawei AppGallery", 0))
    try:
        # Сохраняем обновлённую статистику в файл
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(global_stats, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Ошибка сохранения {file_path}: {e}")
    return global_stats

# Класс для управления конфигурацией приложения
class ConfigManager:
    config_file = CONFIG_FILE

    # Метод для загрузки конфигурации из файла с объединением с дефолтными значениями
    @classmethod
    def load_config(cls):
        default_config = {
            "groups": [],
            "interval": 12000,
            "cycle_interval": 1500,    # изменено с 600 на 1500
            "delay_range": [2, 6],
            "auto_parse_on_create": False,
            "enable_google_play": True,
            "enable_app_store": True,
            "enable_rustore": True,
            "enable_xiaomi_global": True,
            "enable_xiaomi_getapps": True,  # Новый параметр для Xiaomi GetApps
            "proxy": "",
            "chats": [],  # Чаты для уведомлений
            "notify_errors": False,  # Уведомления об ошибках
            "error_chat": "",        # Чат для уведомлений об ошибках (JSON-строка)
            # Лимиты по количеству результатов для магазинов:
            "max_results_google_play": 8,
            "max_results_app_store": 8,
            "max_results_rustore": 20,
            "max_results_xiaomi_global": 8,
            "max_results_xiaomi_getapps": 8,
            "max_results_samsung_galaxy": 27,
            "max_results_huawei_appgallery": 8
        }

        config_data = {}
        if os.path.exists(cls.config_file):
            try:
                with open(cls.config_file, "r", encoding="utf-8") as f:
                    config_data = json.load(f)
            except Exception as e:
                logging.error(f"Ошибка загрузки конфигурации из файла: {e}")
                # Если ошибка происходит, берем пустой словарь вместо дефолтных,
                # чтобы избежать полного перезаписывания уже заданных настроек.
                config_data = {}
        # Объединяем дефолтные и загруженные настройки: если ключ отсутствует,
        # то берем значение по умолчанию.
        merged_config = default_config.copy()
        merged_config.update(config_data)
        return merged_config

    @classmethod
    def save_config(cls, config):
        try:
            with open(cls.config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Ошибка сохранения конфигурации: {e}")

# Функция для загрузки известных приложений
def load_known_apps():
    if os.path.exists(KNOWN_APPS_FILE):
        try:
            with open(KNOWN_APPS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Ошибка загрузки {KNOWN_APPS_FILE}: {e}")
    return {}

# Функция для сохранения известных приложений
def save_known_apps(known_apps):
    try:
        with open(KNOWN_APPS_FILE, "w", encoding="utf-8") as f:
            json.dump(known_apps, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Ошибка сохранения {KNOWN_APPS_FILE}: {e}")
