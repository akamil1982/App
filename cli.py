#!/usr/bin/env python3
import sys
import os
import json
import threading
import signal
import re
import subprocess
from datetime import datetime
from config import ConfigManager, GLOBAL_STATS_FILE
from parser import ParserThread

# ANSI-коды для цветов
ORANGE = "\033[38;5;208m"  # Оранжевый: опции меню
BLUE   = "\033[94m"       # Голубой: динамические значения
GREEN  = "\033[92m"       # Зеленый: статические заголовки/лейблы
RESET  = "\033[0m"

# Функция для окрашивания текста
def colored(text, color):
    return f"{color}{text}{RESET}"

# Функция для печати заголовков в зеленом (статичные заголовки)
def print_header(text):
    print(colored(text, GREEN))

# Очистка экрана
def clear_screen():
    cmd = "cls" if os.name == "nt" else "clear"
    os.system(cmd)

# Ожидание ввода и очистка
def pause_and_clear():
    input(colored("\nНажмите Enter для возврата в меню...", BLUE))
    clear_screen()

# Глобальные переменные для логов/прогресса/статистики
LAST_LOG = None
LAST_PROGRESS = None
LAST_STATS = None

### Функции для вывода динамичных значений (лог, прогресс, статистика)
def log_callback(msg):
    global LAST_LOG
    if msg == LAST_LOG:
        return
    LAST_LOG = msg
    print(colored("[LOG] " + msg, BLUE))

def progress_callback(val):
    global LAST_PROGRESS
    msg = "[PROGRESS] {}%".format(val)
    if msg == LAST_PROGRESS:
        return
    LAST_PROGRESS = msg
    print(colored(msg, BLUE))

def stats_callback(sess, glob):
    global LAST_STATS
    session_str = "Сессия: " + ", ".join(f"{k}: {v}" for k, v in sess.items())
    global_str = "Глобальная статистика: " + ", ".join(f"{k}: {v}" for k, v in glob.items())
    msg = "[STATS] " + session_str
    if msg != LAST_STATS:
        LAST_STATS = msg
        print(colored(msg, BLUE))
    print(colored("[STATS] " + global_str, BLUE))

### Функции запуска/остановки парсера
def start_parser():
    config = ConfigManager.load_config()
    stop_event = threading.Event()
    parser_thread = ParserThread(config, stop_event, progress_callback, log_callback, stats_callback)
    parser_thread.daemon = True
    parser_thread.start()
    print(colored("[INFO] Парсер запущен.", ORANGE))
    return parser_thread, stop_event

def stop_parser(parser_thread, stop_event):
    if stop_event:
        stop_event.set()
        if parser_thread:
            parser_thread.join(timeout=5)
        print(colored("[INFO] Парсер остановлен.", ORANGE))
        return None, None
    else:
        print(colored("[WARN] Парсер не запущен.", BLUE))
        return parser_thread, stop_event

### Функции для управления ГРУППАМИ
def list_groups():
    config = ConfigManager.load_config()
    groups = config.get("groups", [])
    if not groups:
        print(colored("[INFO] Нет групп.", BLUE))
        return
    print_header("Список групп:")
    for idx, group in enumerate(groups):
        status = "включена" if group.get("enabled", True) else "выключена"
        # Название группы выводим зеленым (статическое), статус — голубым (значение)
        print(f" {idx+1}. {colored(group.get('group_name', 'Без названия'), GREEN)} - {colored(status, BLUE)}")

def toggle_group_interactive():
    config = ConfigManager.load_config()
    groups = config.get("groups", [])
    if not groups:
        print(colored("[WARN] Нет групп для изменения статуса.", BLUE))
        return
    list_groups()
    choice = input("Введите номер группы для переключения состояния: ").strip()
    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(groups):
            print(colored("[ERROR] Некорректный номер.", BLUE))
            return
        group = groups[idx]
        group["enabled"] = not group.get("enabled", True)
        groups[idx] = group
        config["groups"] = groups
        ConfigManager.save_config(config)
        status = "включена" if group["enabled"] else "выключена"
        print(colored(f"[INFO] Группа '{group.get('group_name', 'Без названия')}' теперь {status}.", ORANGE))
    except ValueError:
        print(colored("[ERROR] Некорректный ввод.", BLUE))

def add_group_interactive():
    print_header("Добавление новой группы:")
    name = input(colored("Название группы: ", GREEN)).strip()
    if not name:
        print(colored("[ERROR] Название не может быть пустым.", BLUE))
        return
    # Получение ключевых слов
    kw_input = input(colored("Введите ключевые слова через запятую или путь к файлу: ", GREEN)).strip()
    keywords = []
    if os.path.exists(kw_input):
        try:
            with open(kw_input, "r", encoding="utf-8") as f:
                content = f.read()
            keywords = [w.strip() for w in re.split(r"[,\s;]+", content) if w.strip()]
        except Exception as e:
            print(colored(f"[ERROR] Ошибка загрузки файла: {e}", BLUE))
    elif kw_input:
        keywords = [w.strip() for w in kw_input.split(",") if w.strip()]
    else:
        print(colored("Введите ключевые слова по одному (пустая строка — завершить):", GREEN))
        while True:
            kw = input(colored("Ключевое слово: ", BLUE)).strip()
            if not kw:
                break
            keywords.append(kw)
    # Статус группы
    enabled = input(colored("Группа включена? (да/нет): ", GREEN)).strip().lower() == "да"
    # Уведомления – выбор чата для каждого типа уведомлений, если включено.
    notify_new = input(colored("Уведомлять о новых приложениях? (да/нет): ", GREEN)).strip().lower() == "да"
    notify_new_chat = select_chat() if notify_new else ""
    notify_exact = input(colored("Уведомлять о точном совпадении? (да/нет): ", GREEN)).strip().lower() == "да"
    notify_exact_chat = select_chat() if notify_exact else ""
    notify_update = input(colored("Уведомлять об обновлениях? (да/нет): ", GREEN)).strip().lower() == "да"
    notify_update_chat = select_chat() if notify_update else ""
    config = ConfigManager.load_config()
    groups = config.get("groups", [])
    new_group = {
        "group_name": name,
        "keywords": keywords,
        "enabled": enabled,
        "notify_new": notify_new,
        "notify_new_chat": notify_new_chat,
        "notify_exact": notify_exact,
        "notify_exact_chat": notify_exact_chat,
        "notify_update": notify_update,
        "notify_update_chat": notify_update_chat
    }
    groups.append(new_group)
    config["groups"] = groups
    ConfigManager.save_config(config)
    print(colored(f"[INFO] Группа '{name}' добавлена.", ORANGE))

def edit_group_interactive():
    config = ConfigManager.load_config()
    groups = config.get("groups", [])
    if not groups:
        print(colored("[WARN] Нет групп для редактирования.", BLUE))
        return
    list_groups()
    choice = input(colored("Введите номер группы для редактирования: ", GREEN)).strip()
    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(groups):
            print(colored("[ERROR] Некорректный номер.", BLUE))
            return
        group = groups[idx]
        print_header(f"Редактирование группы: {group.get('group_name', '')}")
        new_name = input(colored(f"Новое название (текущее {group.get('group_name', '')}): ", GREEN)).strip()
        if new_name:
            group["group_name"] = new_name
        # Редактирование ключевых слов
        print(colored("Текущие ключевые слова: ", GREEN) + colored(", ".join(group.get("keywords", [])), BLUE))
        new_keywords = input(colored("Введите новые ключевые слова через запятую (оставьте пустым для сохранения): ", GREEN)).strip()
        if new_keywords:
            group["keywords"] = [kw.strip() for kw in new_keywords.split(",") if kw.strip()]
        # Статус группы
        cur_status = "да" if group.get("enabled", True) else "нет"
        en_input = input(colored(f"Группа включена? (да/нет, текущий: {cur_status}): ", GREEN)).strip().lower()
        if en_input in ["да", "нет"]:
            group["enabled"] = (en_input == "да")
        # Уведомления
        for key, desc in [("notify_new", "новых"), ("notify_exact", "точкого совпадения"), ("notify_update", "обновлений")]:
            cur_val = "да" if group.get(key, False) else "нет"
            new_flag = input(colored(f"Уведомлять {desc}? (да/нет, текущий: {cur_val}): ", GREEN)).strip().lower()
            if new_flag in ["да", "нет"]:
                group[key] = (new_flag == "да")
                if group[key]:
                    print(colored(f"Выберите чат для уведомлений {desc}: ", GREEN))
                    chat_choice = select_chat()
                    if key == "notify_new":
                        group["notify_new_chat"] = chat_choice
                    elif key == "notify_exact":
                        group["notify_exact_chat"] = chat_choice
                    elif key == "notify_update":
                        group["notify_update_chat"] = chat_choice
        groups[idx] = group
        config["groups"] = groups
        ConfigManager.save_config(config)
        print(colored("[INFO] Группа обновлена.", ORANGE))
    except ValueError:
        print(colored("[ERROR] Некорректный ввод.", BLUE))

def remove_group_interactive():
    config = ConfigManager.load_config()
    groups = config.get("groups", [])
    if not groups:
        print(colored("[INFO] Нет групп для удаления.", BLUE))
        return
    list_groups()
    choice = input(colored("Введите номер группы для удаления: ", GREEN)).strip()
    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(groups):
            print(colored("[ERROR] Некорректный номер.", BLUE))
            return
        removed = groups.pop(idx)
        config["groups"] = groups
        ConfigManager.save_config(config)
        print(colored(f"[INFO] Группа '{removed.get('group_name', '')}' удалена.", ORANGE))
    except ValueError:
        print(colored("[ERROR] Некорректный ввод.", BLUE))

### Функции для работы с чатами
def list_chats():
    config = ConfigManager.load_config()
    chats = config.get("chats", [])
    if not chats:
        print(colored("[INFO] Нет настроенных чатов.", BLUE))
        return
    print_header("Список чатов:")
    for idx, chat in enumerate(chats):
        # Название чата выводим зелёным, остальное значение (Chat ID) — голубым:
        print(f"  {idx+1}. {colored(chat.get('name', 'Без названия'), GREEN)} — Chat ID: {colored(chat.get('telegram_chat_id', ''), BLUE)}")

def add_chat_interactive():
    print_header("Добавление нового чата:")
    name = input(colored("Название чата: ", GREEN)).strip()
    token = input(colored("Telegram Token: ", GREEN)).strip()
    chat_id = input(colored("Telegram Chat ID: ", GREEN)).strip()
    if not name or not token or not chat_id:
        print(colored("[ERROR] Все поля обязательны.", BLUE))
        return
    config = ConfigManager.load_config()
    chats = config.get("chats", [])
    new_chat = {"name": name, "telegram_token": token, "telegram_chat_id": chat_id}
    chats.append(new_chat)
    config["chats"] = chats
    ConfigManager.save_config(config)
    print(colored(f"[INFO] Чат '{name}' добавлен.", ORANGE))

def edit_chat_interactive():
    config = ConfigManager.load_config()
    chats = config.get("chats", [])
    if not chats:
        print(colored("[WARN] Нет чатов для редактирования.", BLUE))
        return
    list_chats()
    choice = input(colored("Введите номер чата для редактирования: ", GREEN)).strip()
    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(chats):
            print(colored("[ERROR] Некорректный номер.", BLUE))
            return
        chat = chats[idx]
        print_header(f"Редактирование чата: {chat.get('name', '')}")
        new_name = input(colored(f"Новое название (текущее: {chat.get('name', '')}): ", GREEN)).strip()
        new_token = input(colored("Новый Telegram Token (оставьте пустым для сохранения): ", GREEN)).strip()
        new_chat_id = input(colored("Новый Telegram Chat ID (оставьте пустым для сохранения): ", GREEN)).strip()
        if new_name:
            chat["name"] = new_name
        if new_token:
            chat["telegram_token"] = new_token
        if new_chat_id:
            chat["telegram_chat_id"] = new_chat_id
        chats[idx] = chat
        config["chats"] = chats
        ConfigManager.save_config(config)
        print(colored("[INFO] Чат обновлён.", ORANGE))
    except ValueError:
        print(colored("[ERROR] Некорректный ввод.", BLUE))

def remove_chat_interactive():
    config = ConfigManager.load_config()
    chats = config.get("chats", [])
    if not chats:
        print(colored("[INFO] Нет чатов для удаления.", BLUE))
        return
    list_chats()
    choice = input(colored("Введите номер чата для удаления: ", GREEN)).strip()
    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(chats):
            print(colored("[ERROR] Некорректный номер.", BLUE))
            return
        removed = chats.pop(idx)
        config["chats"] = chats
        ConfigManager.save_config(config)
        print(colored(f"[INFO] Чат '{removed.get('name', 'Без названия')}' удалён.", ORANGE))
    except ValueError:
        print(colored("[ERROR] Некорректный ввод.", BLUE))

def select_chat():
    """Функция выбора чата. Показывает список чатов и возвращает выбранный чат в виде JSON-строки или пустую строку."""
    config = ConfigManager.load_config()
    chats = config.get("chats", [])
    if not chats:
        print(colored("[WARN] Чаты не настроены.", BLUE))
        return ""
    print_header("Список чатов:")
    for idx, chat in enumerate(chats):
        print(f"  {idx+1}. {colored(chat.get('name', 'Без названия'), GREEN)} — Chat ID: {colored(chat.get('telegram_chat_id', ''), BLUE)}")
    choice = input(colored("Введите номер выбранного чата (0 для пропуска): ", GREEN)).strip()
    try:
        num = int(choice)
        if num == 0 or num > len(chats):
            return ""
        return json.dumps(chats[num - 1])
    except ValueError:
        return ""

### Функции для управления магазинами и глобальными настройками
def toggle_stores_interactive():
    config = ConfigManager.load_config()
    stores = [
        ("Google Play", "enable_google_play"),
        ("App Store", "enable_app_store"),
        ("Rustore", "enable_rustore"),
        ("Xiaomi Global", "enable_xiaomi_global"),
        ("Xiaomi GetApps", "enable_xiaomi_getapps"),
        ("Galaxy Store", "enable_galaxy_store"),
        ("Huawei AppGallery", "enable_huawei_appgallery")
    ]
    print_header("Магазины приложений:")
    for idx, (name, key) in enumerate(stores):
        status = "включен" if config.get(key, True) else "отключен"
        print(f"  {idx+1}. {colored(name, GREEN)}: {colored(status, BLUE)}")
    choice = input(colored("Введите номер магазина для переключения состояния (0 для отмены): ", GREEN)).strip()
    try:
        num = int(choice)
        if num == 0:
            print(colored("[INFO] Операция отменена.", BLUE))
            return
        if 1 <= num <= len(stores):
            store_name, key = stores[num - 1]
            config[key] = not config.get(key, True)
            ConfigManager.save_config(config)
            new_status = "включен" if config[key] else "отключен"
            print(colored(f"[INFO] Магазин '{store_name}' теперь {new_status}.", ORANGE))
        else:
            print(colored("[ERROR] Некорректный номер магазина.", BLUE))
    except ValueError:
        print(colored("[ERROR] Некорректный ввод. Введите число.", BLUE))

def global_settings_interactive():
    config = ConfigManager.load_config()
    print_header("Глобальные настройки:")
    print(f" Интервал парсинга (сек): {colored(config.get('interval', 12000), BLUE)}")
    print(f" Интервал цикла (сек): {colored(config.get('cycle_interval', 1500), BLUE)}")
    print(f" Диапазон задержки (сек): {colored(str(config.get('delay_range', [2,6])), BLUE)}")
    print(f" Прокси: {colored(config.get('proxy', ''), BLUE)}")
    if input(colored("Изменить настройки? (да/нет): ", GREEN)).strip().lower() == "да":
        try:
            interval = int(input(colored("Новый интервал парсинга (сек): ", GREEN)).strip())
            cycle = int(input(colored("Новый интервал цикла (сек): ", GREEN)).strip())
            delay_min = float(input(colored("Новая задержка мин (сек): ", GREEN)).strip())
            delay_max = float(input(colored("Новая задержка макс (сек): ", GREEN)).strip())
            proxy = input(colored("Новый прокси (http://хост:порт): ", GREEN)).strip()
            config["interval"] = interval
            config["cycle_interval"] = cycle
            config["delay_range"] = [delay_min, delay_max]
            config["proxy"] = proxy
            ConfigManager.save_config(config)
            print(colored("[INFO] Глобальные настройки обновлены.", ORANGE))
        except Exception as e:
            print(colored(f"[ERROR] Ошибка ввода: {e}", BLUE))
    else:
        print(colored("[INFO] Настройки не изменены.", BLUE))

def show_stats():
    if os.path.exists(GLOBAL_STATS_FILE):
        with open(GLOBAL_STATS_FILE, "r", encoding="utf-8") as f:
            stats = json.load(f)
        print_header("Глобальная статистика:")
        for k, v in stats.items():
            print(f" {colored(k, GREEN)}: {colored(str(v), BLUE)}")
    else:
        print(colored("[INFO] Статистика отсутствует.", BLUE))

def launch_gui():
    print(colored("[INFO] Запуск графического интерфейса...", BLUE))
    try:
        subprocess.Popen([sys.executable, "gui.py"])
        print(colored("[INFO] Графический интерфейс запущен. Завершаем CLI.", BLUE))
        sys.exit(0)
    except Exception as e:
        print(colored(f"[ERROR] Не удалось запустить графический интерфейс: {e}", BLUE))

def groups_chats_menu():
    while True:
        clear_screen()
        print_header("----- ГРУППЫ -----")
        print(colored(" 1. Список групп", ORANGE))
        print(colored(" 2. Добавить группу", ORANGE))
        print(colored(" 3. Редактировать группу", ORANGE))
        print(colored(" 4. Удалить группу", ORANGE))
        print(colored(" 5. Переключить статус группы", ORANGE))
        print("\n" + colored("----- ЧАТЫ -----", GREEN))
        print(colored(" 6. Список чатов", ORANGE))
        print(colored(" 7. Добавить чат", ORANGE))
        print(colored(" 8. Редактировать чат", ORANGE))
        print(colored(" 9. Удалить чат", ORANGE))
        print(colored(" 0. Назад", ORANGE))
        choice = input(colored("Ваш выбор: ", GREEN)).strip()
        if choice == "1":
            list_groups()
        elif choice == "2":
            add_group_interactive()
        elif choice == "3":
            edit_group_interactive()
        elif choice == "4":
            remove_group_interactive()
        elif choice == "5":
            toggle_group_interactive()
        elif choice == "6":
            list_chats()
        elif choice == "7":
            add_chat_interactive()
        elif choice == "8":
            edit_chat_interactive()
        elif choice == "9":
            remove_chat_interactive()
        elif choice == "0":
            break
        else:
            print(colored("[ERROR] Неверный выбор.", BLUE))
        pause_and_clear()

### Подменю для управления магазинами и глобальными настройками
def stores_settings_menu():
    while True:
        clear_screen()
        print_header("Магазины и настройки")
        print(colored("1. Управление магазинами приложений", ORANGE))
        print(colored("2. Глобальные настройки", ORANGE))
        print(colored("3. Показать глобальную статистику", ORANGE))
        print(colored("0. Назад", ORANGE))
        choice = input(colored("Ваш выбор: ", GREEN)).strip()
        if choice == "1":
            toggle_stores_interactive()
        elif choice == "2":
            global_settings_interactive()
        elif choice == "3":
            show_stats()
        elif choice == "0":
            break
        else:
            print(colored("[ERROR] Неверный выбор.", BLUE))
        pause_and_clear()

### Главное меню CLI (компактное)
def main_menu():
    print(colored("=========================================", ORANGE))
    print(colored("         CLI-парсер приложений", ORANGE))
    print(colored("=========================================", ORANGE))
    print(colored("1. Парсер (Запуск/Остановка)", ORANGE))
    print(colored("2. Группы и Чаты", ORANGE))
    print(colored("3. Магазины и настройки", ORANGE))
    print(colored("4. Запустить графический интерфейс", ORANGE))
    print(colored("0. Выход", ORANGE))
    print(colored("=========================================", ORANGE))

### Основной цикл программы
def main():
    parser_thread = None
    stop_event = None
    while True:
        clear_screen()
        # Если парсер запущен
        if parser_thread is not None and parser_thread.is_alive():
            inp = input(colored("Парсер запущен. Введите '2' или 'stop' для его остановки: ", ORANGE)).strip().lower()
            if inp in ["2", "stop"]:
                parser_thread, stop_event = stop_parser(parser_thread, stop_event)
            else:
                print(colored("[WARN] Неверная команда для остановки.", BLUE))
            pause_and_clear()
            continue

        main_menu()
        choice = input(colored("Выберите опцию: ", GREEN)).strip().lower()
        if choice == "1":
            if parser_thread is not None and parser_thread.is_alive():
                print(colored("[WARN] Парсер уже запущен.", BLUE))
            else:
                parser_thread, stop_event = start_parser()
        elif choice == "2":
            groups_chats_menu()
        elif choice == "3":
            stores_settings_menu()
        elif choice == "4":
            launch_gui()
            continue
        elif choice == "0":
            if stop_event:
                stop_event.set()
                if parser_thread:
                    parser_thread.join(timeout=5)
            print(colored("[INFO] Выход из программы.", ORANGE))
            sys.exit(0)
        else:
            print(colored("[ERROR] Неверный выбор.", BLUE))
        pause_and_clear()

if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    main()
