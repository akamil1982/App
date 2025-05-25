import time
import threading
import json
import random
from datetime import datetime
import re

from config import load_known_apps, save_known_apps, ConfigManager
from search import (
    search_google_play,
    search_app_store,
    search_rustore,
    search_xiaomi_global,
    search_xiaomi_getapps,
    search_galaxy_store,
    search_huawei_appgallery
)
from notifications import send_telegram_message

# ------------------------------------------------------------------------------
# Вспомогательная функция для получения дефолтного чата (первый из списка)
def get_default_chat():
    config = ConfigManager.load_config()
    chats = config.get("chats", [])
    if chats:
        return chats[0]
    return None

# ------------------------------------------------------------------------------
# Функция для отправки уведомления об ошибке в выбранный чат (если включена такая опция)
def notify_error(error_message):
    config = ConfigManager.load_config()
    if config.get("notify_errors", False) and config.get("error_chat", ""):
        try:
            error_chat = json.loads(config.get("error_chat", ""))
        except Exception as e:
            error_chat = None
        if error_chat:
            formatted_message = f"🚨 <b>Ошибка!</b>\n{error_message}"
            send_telegram_message(formatted_message, error_chat["telegram_token"], error_chat["telegram_chat_id"])

# ------------------------------------------------------------------------------
# Функция формирует подробное сообщение о приложении для отправки уведомлений
def build_detailed_app_message(app: dict, notification_type: str, group_name: str, timestamp: str, include_header: bool = True) -> str:
    details = []
    if app.get("platform"):
        details.append(f"💻 Платформа: <b>{app['platform']}</b>")
    if app.get("title"):
        details.append(f"📱 Название: <b>{app['title']}</b>")
    if app.get("developer"):
        details.append(f"👨‍💻 Разработчик: <b>{app['developer']}</b>")
    version_field = app.get("version", "").strip()
    if version_field.lower().startswith("версия:"):
        version_field = version_field[len("версия:"):].strip()
    if version_field:
        details.append(f"🔢 Версия: <b>{version_field}</b>")
    if app.get("rating"):
        details.append(f"⭐ Рейтинг: <b>{app['rating']}</b>")
    if app.get("description"):
        details.append(f"📄 Описание: {app['description']}")
    if app.get("url") or app.get("detail_url"):
        url = app.get("url", "") or app.get("detail_url", "")
        details.append(f'🔗 Ссылка: <a href="{url}">📥 скачать</a>')
    details_text = "\n".join(details)
    if include_header:
        if notification_type == "new":
            header = f"📱 <b>Новое приложение обнаружено</b>"
        elif notification_type == "exact":
            header = f"📲 <b>Найдено точное совпадение</b>"
        elif notification_type == "update":
            header = f"🔄 <b>Обновление приложения</b>"
        else:
            header = "<b>Уведомление</b>"
        header += f" в группе <b>{group_name}</b> за {timestamp}\n\n"
        return header + details_text
    else:
        return details_text

# ------------------------------------------------------------------------------
# Функция обновляет глобальную статистику, сохраняемую в файле global_stats.json
def update_global_stats_final(new_counts: dict, msg_stats: dict, avg_keyword_time: float) -> dict:
    try:
        with open("data/global_stats.json", "r", encoding="utf-8") as f:
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
    stores = ["Google Play", "App Store", "RuStore", "Xiaomi Global Store", "Xiaomi GetApps", "Samsung Galaxy Store", "Huawei AppGallery"]
    for store in stores:
        global_stats[store] = global_stats.get(store, 0) + new_counts.get(store, 0)
    global_stats["Всего"] = sum(global_stats.get(store, 0) for store in stores)
    global_stats["Новые"] = global_stats.get("Новые", 0) + msg_stats.get("новые", 0)
    global_stats["Точное совпадение"] = global_stats.get("Точное совпадение", 0) + msg_stats.get("точкое", 0)
    global_stats["Обновления"] = global_stats.get("Обновления", 0) + msg_stats.get("обновления", 0)
    old_avg = global_stats.get("Среднее время обработки", 0.0)
    if old_avg > 0:
        global_stats["Среднее время обработки"] = (old_avg + avg_keyword_time) / 2
    else:
        global_stats["Среднее время обработки"] = avg_keyword_time
    try:
        with open("data/global_stats.json", "w", encoding="utf-8") as f:
            json.dump(global_stats, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ошибка записи глобальной статистики: {e}")
    return global_stats

# ------------------------------------------------------------------------------
# Функция для немедленного сканирования группы с целью поиска приложений
def scan_group_immediately(group, delay_range, log_callback, global_config):
    group_name = group.get("group_name", "Без названия")
    if not group.get("enabled", True):
        log_callback(f"Группа '{group_name}' отключена для автопарсинга.")
        return
    # Из настроек группы извлекаем уведомления:
    notify_new = group.get("notify_new", False)
    exact_chat_json = group.get("notify_exact_chat", "")
    update_chat_json = group.get("notify_update_chat", "")
    keywords = group.get("keywords", [])
    if not keywords:
        log_callback(f"Пропуск группы '{group_name}': недостаточно данных.")
        return
    log_callback(f"Автопарсирование группы '{group_name}' запущено...")
    known_apps = load_known_apps()
    if group_name not in known_apps or not isinstance(known_apps[group_name], dict):
        known_apps[group_name] = {}
    group_known = known_apps[group_name]
    group_results = []
    proxy_str = global_config.get("proxy", "").strip()
    proxies = {"http": proxy_str, "https": proxy_str} if proxy_str else None
    notified_new_ids = set()
    new_counts = {
        "Google Play": 0,
        "App Store": 0,
        "RuStore": 0,
        "Xiaomi Global Store": 0,
        "Xiaomi GetApps": 0,
        "Samsung Galaxy Store": 0,
        "Huawei AppGallery": 0
    }
    for i, keyword in enumerate(keywords):
        start_kw = time.time()
        log_callback(f"[{group_name}] Обработка ключевого слова '{keyword}' ({i+1}/{len(keywords)})")
        gp = search_google_play(keyword) if global_config.get("enable_google_play", True) else []
        time.sleep(random.uniform(*delay_range))
        ios = search_app_store(keyword, proxies=proxies) if global_config.get("enable_app_store", True) else []
        time.sleep(random.uniform(*delay_range))
        ru = search_rustore(keyword, proxies=proxies) if global_config.get("enable_rustore", True) else []
        time.sleep(random.uniform(*delay_range))
        xiaomi = search_xiaomi_global(keyword) if global_config.get("enable_xiaomi_global", True) else []
        time.sleep(random.uniform(*delay_range))
        xiaomi_getapps = search_xiaomi_getapps(keyword) if global_config.get("enable_xiaomi_getapps", True) else []
        time.sleep(random.uniform(*delay_range))
        galaxy = search_galaxy_store(keyword) if global_config.get("enable_galaxy_store", True) else []
        time.sleep(random.uniform(*delay_range))
        huawei = search_huawei_appgallery(keyword) if global_config.get("enable_huawei_appgallery", True) else []
        time.sleep(random.uniform(*delay_range))
        combined = gp + ios + ru + xiaomi + xiaomi_getapps + galaxy + huawei
        for app in combined:
            url = app.get("url", "") or app.get("detail_url", "")
            if not url:
                continue
            unique_id = f"{app['platform']}::{url}"
            if unique_id not in group_known:
                group_known[unique_id] = app.get("version", "")
                group_results.append(app)
                if notify_new and unique_id not in notified_new_ids:
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    message = build_detailed_app_message(app, "new", group_name, ts)
                    if group.get("notify_new_chat", ""):
                        new_chat = json.loads(group.get("notify_new_chat", ""))
                        chat_name = new_chat.get("name", "Не выбран")
                        send_telegram_message(message, new_chat["telegram_token"], new_chat["telegram_chat_id"])
                    else:
                        default_chat = get_default_chat()
                        chat_name = default_chat.get("name", "Дефолтный") if default_chat else "Не выбран"
                        if default_chat:
                            send_telegram_message(message, default_chat["telegram_token"], default_chat["telegram_chat_id"])
                    self.msg_stats["новые"] += 1
                    notified_new_ids.add(unique_id)
                if app["platform"] in new_counts:
                    new_counts[app["platform"]] += 1
            else:
                stored_version = group_known.get(unique_id, "")
                current_version = app.get("version", "")
                if current_version and current_version != stored_version:
                    group_known[unique_id] = current_version
                    group_results.append(app)
        end_kw = time.time()
        log_callback(f"[{group_name}] Прогресс: {int(((i+1)/len(keywords))*100)}%")
    if notified_new_ids:
        if group.get("notify_new_chat", ""):
            new_chat = json.loads(group.get("notify_new_chat", ""))
            chat_name = new_chat.get("name", "Не выбран")
        else:
            default_chat = get_default_chat()
            chat_name = default_chat.get("name", "Дефолтный") if default_chat else "Не выбран"
        log_callback(f"Уведомление (новые) отправлено для группы '{group_name}' через чат '{chat_name}' - {len(notified_new_ids)} раз.")
    if not group_results:
        log_callback(f"Группа '{group_name}': новых приложений не найдено.")
    updates = {}
    exact_matches = {}
    for app in group_results:
        url = app.get("url", "") or app.get("detail_url", "")
        if not url:
            continue
        unique_id = f"{app['platform']}::{url}"
        stored_version = group_known.get(unique_id, "")
        if app.get("version") and app.get("version") != stored_version:
            if group.get("notify_update", False):
                updates[unique_id] = app
        if group.get("notify_exact", False):
            for kw in keywords:
                if kw.casefold() in app.get("title", "").casefold():
                    exact_matches[unique_id] = app
                    break
    if group_results:
        try:
            with open("data/results.json", "a", encoding="utf-8") as f:
                data_to_save = {
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "group": group_name,
                    "results": group_results
                }
                f.write(json.dumps(data_to_save, ensure_ascii=False, indent=2))
                f.write("\n\n")
        except Exception as e:
            log_callback(f"Ошибка сохранения JSON для группы '{group_name}': {e}")
    if updates:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message_upd = f"🔄 <b>Обновления версий в группе '{group_name}' за {ts}</b>\n"
        for app in updates.values():
            message_upd += "\n" + build_detailed_app_message(app, "update", group_name, ts, include_header=False) + "\n"
        if update_chat_json:
            update_chat = json.loads(update_chat_json)
            chat_name = update_chat.get("name", "Не выбран")
            send_telegram_message(message_upd, update_chat["telegram_token"], update_chat["telegram_chat_id"])
        else:
            default_chat = get_default_chat()
            chat_name = default_chat.get("name", "Дефолтный") if default_chat else "Не выбран"
            if default_chat:
                send_telegram_message(message_upd, default_chat["telegram_token"], default_chat["telegram_chat_id"])
        log_callback(f"Уведомление (обновления) отправлено для группы '{group_name}' через чат '{chat_name}' с {len(updates)} обновлениями.")
        self.msg_stats["обновления"] += len(updates)
    else:
        log_callback(f"Уведомление (обновления) не отправлено для группы '{group_name}': обновлений не найдено.")
    if exact_matches:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message_exact = f"📲 <b>Новые приложения (точкое совпадение) в группе '{group_name}' за {ts}</b>\n"
        for app in exact_matches.values():
            message_exact += "\n" + build_detailed_app_message(app, "exact", group_name, ts, include_header=False) + "\n"
        if exact_chat_json:
            exact_chat = json.loads(exact_chat_json)
            chat_name = exact_chat.get("name", "Не выбран")
            send_telegram_message(message_exact, exact_chat["telegram_token"], exact_chat["telegram_chat_id"])
        else:
            default_chat = get_default_chat()
            chat_name = default_chat.get("name", "Дефолтный") if default_chat else "Не выбран"
            if default_chat:
                send_telegram_message(message_exact, default_chat["telegram_token"], default_chat["telegram_chat_id"])
        log_callback(f"Уведомление (точкое совпадение) отправлено для группы '{group_name}' через чат '{chat_name}' с {len(exact_matches)} совпадениями.")
        self.msg_stats["точкое"] += len(exact_matches)
    else:
        log_callback(f"Уведомление (точкое совпадение) не отправлено для группы '{group_name}': точных совпадений не найдено.")
    for key in ["Google Play", "App Store", "RuStore", "Xiaomi Global Store", "Xiaomi GetApps", "Samsung Galaxy Store", "Huawei AppGallery"]:
        if key not in new_counts:
            new_counts[key] = 0
    session_stats = {
        "Google Play": new_counts["Google Play"],
        "App Store": new_counts["App Store"],
        "RuStore": new_counts["RuStore"],
        "Xiaomi Global Store": new_counts["Xiaomi Global Store"],
        "Xiaomi GetApps": new_counts["Xiaomi GetApps"],
        "Samsung Galaxy Store": new_counts["Samsung Galaxy Store"],
        "Huawei AppGallery": new_counts["Huawei AppGallery"],
        "Всего": (new_counts["Google Play"] + new_counts["App Store"] +
                  new_counts["RuStore"] + new_counts["Xiaomi Global Store"] +
                  new_counts["Xiaomi GetApps"] + new_counts["Samsung Galaxy Store"] +
                  new_counts["Huawei AppGallery"])
    }
    global_stats = update_global_stats_final(new_counts, self.msg_stats, self.avg_keyword_time)
    self.stats_callback(session_stats, global_stats)
    self.progress_callback(0)
    log_callback(f"Цикл завершен. Ожидание {self.config.get('cycle_interval', 1500)} сек перед новым циклом.")
    waiting_time = self.config.get("cycle_interval", 1500)
    start_wait = time.time()
    while time.time() - start_wait < waiting_time and not self.stop_event.is_set():
        remaining = int(waiting_time - (time.time() - start_wait))
        if self.interval_callback:
            self.interval_callback(remaining)
        time.sleep(1)
    if self.interval_callback:
        self.interval_callback(0)
    if self.keyword_count > 0:
        self.avg_keyword_time = self.total_keyword_time / self.keyword_count
    else:
        self.avg_keyword_time = 0.0
    log_callback("Фоновый парсер остановлен.")
    save_known_apps(known_apps)

# ------------------------------------------------------------------------------
# Класс потока для фонового парсинга групп
class ParserThread(threading.Thread):
    def __init__(self, config, stop_event, progress_callback, log_callback, stats_callback, interval_callback=None):
        super().__init__()
        self.config = config
        self.stop_event = stop_event
        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self.stats_callback = stats_callback
        self.interval_callback = interval_callback
        self.session_stats = {
            "Google Play": 0,
            "App Store": 0,
            "RuStore": 0,
            "Xiaomi Global Store": 0,
            "Xiaomi GetApps": 0,
            "Samsung Galaxy Store": 0,
            "Huawei AppGallery": 0,
            "Всего": 0
        }
        self.msg_stats = {"новые": 0, "точкое": 0, "обновления": 0}
        self.total_keyword_time = 0.0
        self.keyword_count = 0
        self.avg_keyword_time = 0.0

    def run(self):
        try:
            self.config.setdefault("cycle_interval", 1500)
            cycle_interval = self.config.get("cycle_interval", 1500)
            delay_range = self.config.get("delay_range", [2, 6])
            self.log_callback("Фоновый парсер запущен.")
            proxy_str = self.config.get("proxy", "").strip()
            proxies = {"http": proxy_str, "https": proxy_str} if proxy_str else None
            known_apps = load_known_apps()
            for group_name in known_apps:
                if not isinstance(known_apps[group_name], dict):
                    known_apps[group_name] = {}
            while not self.stop_event.is_set():
                for group in self.config.get("groups", []):
                    if self.stop_event.is_set():
                        break
                    group_name = group.get("group_name", "Без названия")
                    if not group.get("enabled", True):
                        self.log_callback(f"Группа '{group_name}' отключена для парсинга.")
                        continue
                    # Настройки уведомлений из группы: notify_new, notify_new_chat, notify_exact, notify_exact_chat, notify_update, notify_update_chat
                    notify_new = group.get("notify_new", False)
                    exact_chat_json = group.get("notify_exact_chat", "")
                    update_chat_json = group.get("notify_update_chat", "")
                    keywords = group.get("keywords", [])
                    if not keywords:
                        self.log_callback(f"Пропуск группы '{group_name}': недостаточно данных.")
                        continue
                    self.log_callback(f"Начинаем обработку группы '{group_name}' ({len(keywords)} ключевых слов).")
                    if group_name not in known_apps or not isinstance(known_apps[group_name], dict):
                        known_apps[group_name] = {}
                    group_known = known_apps[group_name]
                    group_results = []
                    notified_new_ids = set()
                    new_counts = {
                        "Google Play": 0,
                        "App Store": 0,
                        "RuStore": 0,
                        "Xiaomi Global Store": 0,
                        "Xiaomi GetApps": 0,
                        "Samsung Galaxy Store": 0,
                        "Huawei AppGallery": 0
                    }
                    for i, keyword in enumerate(keywords):
                        if self.stop_event.is_set():
                            break
                        start_kw = time.time()
                        self.log_callback(f"[{group_name}] Обработка ключевого слова '{keyword}' ({i+1}/{len(keywords)})")
                        gp = search_google_play(keyword) if self.config.get("enable_google_play", True) else []
                        time.sleep(random.uniform(*delay_range))
                        ios = search_app_store(keyword, proxies=proxies) if self.config.get("enable_app_store", True) else []
                        time.sleep(random.uniform(*delay_range))
                        ru = search_rustore(keyword, proxies=proxies) if self.config.get("enable_rustore", True) else []
                        time.sleep(random.uniform(*delay_range))
                        xiaomi = search_xiaomi_global(keyword) if self.config.get("enable_xiaomi_global", True) else []
                        time.sleep(random.uniform(*delay_range))
                        xiaomi_getapps = search_xiaomi_getapps(keyword) if self.config.get("enable_xiaomi_getapps", True) else []
                        time.sleep(random.uniform(*delay_range))
                        galaxy = search_galaxy_store(keyword) if self.config.get("enable_galaxy_store", True) else []
                        time.sleep(random.uniform(*delay_range))
                        huawei = search_huawei_appgallery(keyword) if self.config.get("enable_huawei_appgallery", True) else []
                        time.sleep(random.uniform(*delay_range))
                        combined = gp + ios + ru + xiaomi + xiaomi_getapps + galaxy + huawei
                        for app in combined:
                            url = app.get("url", "") or app.get("detail_url", "")
                            if not url:
                                continue
                            unique_id = f"{app['platform']}::{url}"
                            if unique_id not in group_known:
                                group_known[unique_id] = app.get("version", "")
                                group_results.append(app)
                                if notify_new and unique_id not in notified_new_ids:
                                    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                    message = build_detailed_app_message(app, "new", group_name, ts)
                                    if group.get("notify_new_chat", ""):
                                        new_chat = json.loads(group.get("notify_new_chat", ""))
                                        chat_name = new_chat.get("name", "Не выбран")
                                        send_telegram_message(message, new_chat["telegram_token"], new_chat["telegram_chat_id"])
                                    else:
                                        default_chat = get_default_chat()
                                        chat_name = default_chat.get("name", "Дефолтный") if default_chat else "Не выбран"
                                        if default_chat:
                                            send_telegram_message(message, default_chat["telegram_token"], default_chat["telegram_chat_id"])
                                    self.msg_stats["новые"] += 1
                                    notified_new_ids.add(unique_id)
                                if app["platform"] in new_counts:
                                    new_counts[app["platform"]] += 1
                            else:
                                stored_version = group_known.get(unique_id, "")
                                current_version = app.get("version", "")
                                if current_version and current_version != stored_version:
                                    group_known[unique_id] = current_version
                                    group_results.append(app)
                        end_kw = time.time()
                        self.total_keyword_time += (end_kw - start_kw)
                        self.keyword_count += 1
                        progress = int(((i+1)/len(keywords))*100)
                        self.progress_callback(progress)
                        self.log_callback(f"[{group_name}] Прогресс: {progress}%")
                    if notified_new_ids:
                        if group.get("notify_new_chat", ""):
                            new_chat = json.loads(group.get("notify_new_chat", ""))
                            chat_name = new_chat.get("name", "Не выбран")
                        else:
                            default_chat = get_default_chat()
                            chat_name = default_chat.get("name", "Дефолтный") if default_chat else "Не выбран"
                        self.log_callback(f"Уведомление (новые) отправлено для группы '{group_name}' через чат '{chat_name}' - {len(notified_new_ids)} раз.")
                    if not group_results:
                        self.log_callback(f"Группа '{group_name}': новых приложений не найдено.")
                    updates = {}
                    exact_matches = {}
                    for app in group_results:
                        url = app.get("url", "") or app.get("detail_url", "")
                        if not url:
                            continue
                        unique_id = f"{app['platform']}::{url}"
                        stored_version = group_known.get(unique_id, "")
                        if app.get("version") and app.get("version") != stored_version:
                            if group.get("notify_update", False):
                                updates[unique_id] = app
                        if group.get("notify_exact", False):
                            for kw in keywords:
                                if kw.casefold() in app.get("title", "").casefold():
                                    exact_matches[unique_id] = app
                                    break
                    if group_results:
                        try:
                            with open("data/results.json", "a", encoding="utf-8") as f:
                                data_to_save = {
                                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "group": group_name,
                                    "results": group_results
                                }
                                f.write(json.dumps(data_to_save, ensure_ascii=False, indent=2))
                                f.write("\n\n")
                        except Exception as e:
                            self.log_callback(f"Ошибка сохранения JSON для группы '{group_name}': {e}")
                    if updates:
                        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        message_upd = f"🔄 <b>Обновления версий в группе '{group_name}' за {ts}</b>\n"
                        for app in updates.values():
                            message_upd += "\n" + build_detailed_app_message(app, "update", group_name, ts, include_header=False) + "\n"
                        if update_chat_json:
                            update_chat = json.loads(update_chat_json)
                            chat_name = update_chat.get("name", "Не выбран")
                            send_telegram_message(message_upd, update_chat["telegram_token"], update_chat["telegram_chat_id"])
                        else:
                            default_chat = get_default_chat()
                            chat_name = default_chat.get("name", "Дефолтный") if default_chat else "Не выбран"
                            if default_chat:
                                send_telegram_message(message_upd, default_chat["telegram_token"], default_chat["telegram_chat_id"])
                        self.log_callback(f"Уведомление (обновления) отправлено для группы '{group_name}' через чат '{chat_name}' с {len(updates)} обновлениями.")
                        self.msg_stats["обновления"] += len(updates)
                    else:
                        self.log_callback(f"Уведомление (обновления) не отправлено для группы '{group_name}': обновлений не найдено.")
                    if exact_matches:
                        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        message_exact = f"📲 <b>Новые приложения (точкое совпадение) в группе '{group_name}' за {ts}</b>\n"
                        for app in exact_matches.values():
                            message_exact += "\n" + build_detailed_app_message(app, "exact", group_name, ts, include_header=False) + "\n"
                        if exact_chat_json:
                            exact_chat = json.loads(exact_chat_json)
                            chat_name = exact_chat.get("name", "Не выбран")
                            send_telegram_message(message_exact, exact_chat["telegram_token"], exact_chat["telegram_chat_id"])
                        else:
                            default_chat = get_default_chat()
                            chat_name = default_chat.get("name", "Дефолтный") if default_chat else "Не выбран"
                            if default_chat:
                                send_telegram_message(message_exact, default_chat["telegram_token"], default_chat["telegram_chat_id"])
                        self.log_callback(f"Уведомление (точкое совпадение) отправлено для группы '{group_name}' через чат '{chat_name}' с {len(exact_matches)} совпадениями.")
                        self.msg_stats["точкое"] += len(exact_matches)
                    else:
                        self.log_callback(f"Уведомление (точкое совпадение) не отправлено для группы '{group_name}': точных совпадений не найдено.")
                    for key in ["Google Play", "App Store", "RuStore", "Xiaomi Global Store", "Xiaomi GetApps", "Samsung Galaxy Store", "Huawei AppGallery"]:
                        if key not in new_counts:
                            new_counts[key] = 0
                    self.session_stats = {
                        "Google Play": new_counts["Google Play"],
                        "App Store": new_counts["App Store"],
                        "RuStore": new_counts["RuStore"],
                        "Xiaomi Global Store": new_counts["Xiaomi Global Store"],
                        "Xiaomi GetApps": new_counts["Xiaomi GetApps"],
                        "Samsung Galaxy Store": new_counts["Samsung Galaxy Store"],
                        "Huawei AppGallery": new_counts["Huawei AppGallery"],
                        "Всего": (new_counts["Google Play"] + new_counts["App Store"] +
                                  new_counts["RuStore"] + new_counts["Xiaomi Global Store"] +
                                  new_counts["Xiaomi GetApps"] + new_counts["Samsung Galaxy Store"] +
                                  new_counts["Huawei AppGallery"])
                    }
                    global_stats = update_global_stats_final(new_counts, self.msg_stats, self.avg_keyword_time)
                    self.stats_callback(self.session_stats, global_stats)
                    self.progress_callback(0)
                    self.log_callback(f"Цикл завершен. Ожидание {self.config.get('cycle_interval', 1500)} сек перед новым циклом.")
                waiting_time = self.config.get("cycle_interval", 1500)
                start_wait = time.time()
                while time.time() - start_wait < waiting_time and not self.stop_event.is_set():
                    remaining = int(waiting_time - (time.time() - start_wait))
                    if self.interval_callback:
                        self.interval_callback(remaining)
                    time.sleep(1)
                if self.interval_callback:
                    self.interval_callback(0)
                if self.keyword_count > 0:
                    self.avg_keyword_time = self.total_keyword_time / self.keyword_count
                else:
                    self.avg_keyword_time = 0.0
            self.log_callback("Фоновый парсер остановлен.")
            save_known_apps(known_apps)
        except Exception as err:
            error_message = f"Ошибка в ParserThread: {str(err)}"
            self.log_callback(error_message)
            try:
                notify_error(error_message)
            except Exception:
                pass

# ------------------------------------------------------------------------------
# Класс потока для фонового парсинга групп
class ParserThread(threading.Thread):
    def __init__(self, config, stop_event, progress_callback, log_callback, stats_callback, interval_callback=None):
        super().__init__()
        self.config = config
        self.stop_event = stop_event
        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self.stats_callback = stats_callback
        self.interval_callback = interval_callback
        self.session_stats = {
            "Google Play": 0,
            "App Store": 0,
            "RuStore": 0,
            "Xiaomi Global Store": 0,
            "Xiaomi GetApps": 0,
            "Samsung Galaxy Store": 0,
            "Huawei AppGallery": 0,
            "Всего": 0
        }
        self.msg_stats = {"новые": 0, "точкое": 0, "обновления": 0}
        self.total_keyword_time = 0.0
        self.keyword_count = 0
        self.avg_keyword_time = 0.0

    def run(self):
        try:
            self.config.setdefault("cycle_interval", 1500)
            cycle_interval = self.config.get("cycle_interval", 1500)
            delay_range = self.config.get("delay_range", [2, 6])
            self.log_callback("Фоновый парсер запущен.")
            proxy_str = self.config.get("proxy", "").strip()
            proxies = {"http": proxy_str, "https": proxy_str} if proxy_str else None

            # Чтение лимитов из конфигурации
            max_gp = self.config.get("max_results_google_play", 8)
            max_as = self.config.get("max_results_app_store", 8)
            max_rs = self.config.get("max_results_rustore", 20)
            max_xm_global = self.config.get("max_results_xiaomi_global", 8)
            max_xm_getapps = self.config.get("max_results_xiaomi_getapps", 8)
            max_galaxy = self.config.get("max_results_samsung_galaxy", 27)
            max_ha = self.config.get("max_results_huawei_appgallery", 8)

            known_apps = load_known_apps()
            for group_name in known_apps:
                if not isinstance(known_apps[group_name], dict):
                    known_apps[group_name] = {}
            while not self.stop_event.is_set():
                for group in self.config.get("groups", []):
                    if self.stop_event.is_set():
                        break
                    group_name = group.get("group_name", "Без названия")
                    if not group.get("enabled", True):
                        self.log_callback(f"Группа '{group_name}' отключена для парсинга.")
                        continue
                    # Настройки уведомлений из группы:
                    notify_new = group.get("notify_new", False)
                    exact_chat_json = group.get("notify_exact_chat", "")
                    update_chat_json = group.get("notify_update_chat", "")
                    keywords = group.get("keywords", [])
                    if not keywords:
                        self.log_callback(f"Пропуск группы '{group_name}': недостаточно данных.")
                        continue
                    self.log_callback(f"Начинаем обработку группы '{group_name}' ({len(keywords)} ключевых слов).")
                    if group_name not in known_apps or not isinstance(known_apps[group_name], dict):
                        known_apps[group_name] = {}
                    group_known = known_apps[group_name]
                    group_results = []
                    notified_new_ids = set()
                    new_counts = {
                        "Google Play": 0,
                        "App Store": 0,
                        "RuStore": 0,
                        "Xiaomi Global Store": 0,
                        "Xiaomi GetApps": 0,
                        "Samsung Galaxy Store": 0,
                        "Huawei AppGallery": 0
                    }
                    for i, keyword in enumerate(keywords):
                        if self.stop_event.is_set():
                            break
                        start_kw = time.time()
                        self.log_callback(f"[{group_name}] Обработка ключевого слова '{keyword}' ({i+1}/{len(keywords)})")
                        # Передаем параметры num_results, взятые из конфигурации:
                        gp = search_google_play(keyword, num_results=max_gp) if self.config.get("enable_google_play", True) else []
                        time.sleep(random.uniform(*delay_range))
                        ios = search_app_store(keyword, num_results=max_as, proxies=proxies) if self.config.get("enable_app_store", True) else []
                        time.sleep(random.uniform(*delay_range))
                        ru = search_rustore(keyword, num_results=max_rs, proxies=proxies) if self.config.get("enable_rustore", True) else []
                        time.sleep(random.uniform(*delay_range))
                        xiaomi = search_xiaomi_global(keyword, num_results=max_xm_global) if self.config.get("enable_xiaomi_global", True) else []
                        time.sleep(random.uniform(*delay_range))
                        xiaomi_getapps = search_xiaomi_getapps(keyword, num_results=max_xm_getapps) if self.config.get("enable_xiaomi_getapps", True) else []
                        time.sleep(random.uniform(*delay_range))
                        galaxy = search_galaxy_store(keyword, num_results=max_galaxy) if self.config.get("enable_galaxy_store", True) else []
                        time.sleep(random.uniform(*delay_range))
                        huawei = search_huawei_appgallery(keyword, num_results=max_ha) if self.config.get("enable_huawei_appgallery", True) else []
                        time.sleep(random.uniform(*delay_range))
                        combined = gp + ios + ru + xiaomi + xiaomi_getapps + galaxy + huawei
                        for app in combined:
                            url = app.get("url", "") or app.get("detail_url", "")
                            if not url:
                                continue
                            unique_id = f"{app['platform']}::{url}"
                            if unique_id not in group_known:
                                group_known[unique_id] = app.get("version", "")
                                group_results.append(app)
                                if notify_new and unique_id not in notified_new_ids:
                                    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                    message = build_detailed_app_message(app, "new", group_name, ts)
                                    if group.get("notify_new_chat", ""):
                                        new_chat = json.loads(group.get("notify_new_chat", ""))
                                        chat_name = new_chat.get("name", "Не выбран")
                                        send_telegram_message(message, new_chat["telegram_token"], new_chat["telegram_chat_id"])
                                    else:
                                        default_chat = get_default_chat()
                                        chat_name = default_chat.get("name", "Дефолтный") if default_chat else "Не выбран"
                                        if default_chat:
                                            send_telegram_message(message, default_chat["telegram_token"], default_chat["telegram_chat_id"])
                                    self.msg_stats["новые"] += 1
                                    notified_new_ids.add(unique_id)
                                if app["platform"] in new_counts:
                                    new_counts[app["platform"]] += 1
                            else:
                                stored_version = group_known.get(unique_id, "")
                                current_version = app.get("version", "")
                                if current_version and current_version != stored_version:
                                    group_known[unique_id] = current_version
                                    group_results.append(app)
                        end_kw = time.time()
                        self.total_keyword_time += (end_kw - start_kw)
                        self.keyword_count += 1
                        progress = int(((i+1)/len(keywords))*100)
                        self.progress_callback(progress)
                        self.log_callback(f"[{group_name}] Прогресс: {progress}%")
                    if notified_new_ids:
                        if group.get("notify_new_chat", ""):
                            new_chat = json.loads(group.get("notify_new_chat", ""))
                            chat_name = new_chat.get("name", "Не выбран")
                        else:
                            default_chat = get_default_chat()
                            chat_name = default_chat.get("name", "Дефолтный") if default_chat else "Не выбран"
                        self.log_callback(f"Уведомление (новые) отправлено для группы '{group_name}' через чат '{chat_name}' - {len(notified_new_ids)} раз.")
                    if not group_results:
                        self.log_callback(f"Группа '{group_name}': новых приложений не найдено.")
                    updates = {}
                    exact_matches = {}
                    for app in group_results:
                        url = app.get("url", "") or app.get("detail_url", "")
                        if not url:
                            continue
                        unique_id = f"{app['platform']}::{url}"
                        stored_version = group_known.get(unique_id, "")
                        if app.get("version") and app.get("version") != stored_version:
                            if group.get("notify_update", False):
                                updates[unique_id] = app
                        if group.get("notify_exact", False):
                            for kw in keywords:
                                if kw.casefold() in app.get("title", "").casefold():
                                    exact_matches[unique_id] = app
                                    break
                    if group_results:
                        try:
                            with open("data/results.json", "a", encoding="utf-8") as f:
                                data_to_save = {
                                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "group": group_name,
                                    "results": group_results
                                }
                                f.write(json.dumps(data_to_save, ensure_ascii=False, indent=2))
                                f.write("\n\n")
                        except Exception as e:
                            self.log_callback(f"Ошибка сохранения JSON для группы '{group_name}': {e}")
                    if updates:
                        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        message_upd = f"🔄 <b>Обновления версий в группе '{group_name}' за {ts}</b>\n"
                        for app in updates.values():
                            message_upd += "\n" + build_detailed_app_message(app, "update", group_name, ts, include_header=False) + "\n"
                        if update_chat_json:
                            update_chat = json.loads(update_chat_json)
                            chat_name = update_chat.get("name", "Не выбран")
                            send_telegram_message(message_upd, update_chat["telegram_token"], update_chat["telegram_chat_id"])
                        else:
                            default_chat = get_default_chat()
                            chat_name = default_chat.get("name", "Дефолтный") if default_chat else "Не выбран"
                            if default_chat:
                                send_telegram_message(message_upd, default_chat["telegram_token"], default_chat["telegram_chat_id"])
                        self.log_callback(f"Уведомление (обновления) отправлено для группы '{group_name}' через чат '{chat_name}' с {len(updates)} обновлениями.")
                        self.msg_stats["обновления"] += len(updates)
                    else:
                        self.log_callback(f"Уведомление (обновления) не отправлено для группы '{group_name}': обновлений не найдено.")
                    if exact_matches:
                        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        message_exact = f"📲 <b>Новые приложения (точкое совпадение) в группе '{group_name}' за {ts}</b>\n"
                        for app in exact_matches.values():
                            message_exact += "\n" + build_detailed_app_message(app, "exact", group_name, ts, include_header=False) + "\n"
                        if exact_chat_json:
                            exact_chat = json.loads(exact_chat_json)
                            chat_name = exact_chat.get("name", "Не выбран")
                            send_telegram_message(message_exact, exact_chat["telegram_token"], exact_chat["telegram_chat_id"])
                        else:
                            default_chat = get_default_chat()
                            chat_name = default_chat.get("name", "Дефолтный") if default_chat else "Не выбран"
                            if default_chat:
                                send_telegram_message(message_exact, default_chat["telegram_token"], default_chat["telegram_chat_id"])
                        self.log_callback(f"Уведомление (точкое совпадение) отправлено для группы '{group_name}' через чат '{chat_name}' с {len(exact_matches)} совпадениями.")
                        self.msg_stats["точкое"] += len(exact_matches)
                    else:
                        self.log_callback(f"Уведомление (точкое совпадение) не отправлено для группы '{group_name}': точных совпадений не найдено.")
                    for key in ["Google Play", "App Store", "RuStore", "Xiaomi Global Store", "Xiaomi GetApps", "Samsung Galaxy Store", "Huawei AppGallery"]:
                        if key not in new_counts:
                            new_counts[key] = 0
                    self.session_stats = {
                        "Google Play": new_counts["Google Play"],
                        "App Store": new_counts["App Store"],
                        "RuStore": new_counts["RuStore"],
                        "Xiaomi Global Store": new_counts["Xiaomi Global Store"],
                        "Xiaomi GetApps": new_counts["Xiaomi GetApps"],
                        "Samsung Galaxy Store": new_counts["Samsung Galaxy Store"],
                        "Huawei AppGallery": new_counts["Huawei AppGallery"],
                        "Всего": (new_counts["Google Play"] + new_counts["App Store"] +
                                  new_counts["RuStore"] + new_counts["Xiaomi Global Store"] +
                                  new_counts["Xiaomi GetApps"] + new_counts["Samsung Galaxy Store"] +
                                  new_counts["Huawei AppGallery"])
                    }
                    global_stats = update_global_stats_final(new_counts, self.msg_stats, self.avg_keyword_time)
                    self.stats_callback(self.session_stats, global_stats)
                    self.progress_callback(0)
                    self.log_callback(f"Цикл завершен. Ожидание {self.config.get('cycle_interval', 1500)} сек перед новым циклом.")
                waiting_time = self.config.get("cycle_interval", 1500)
                start_wait = time.time()
                while time.time() - start_wait < waiting_time and not self.stop_event.is_set():
                    remaining = int(waiting_time - (time.time() - start_wait))
                    if self.interval_callback:
                        self.interval_callback(remaining)
                    time.sleep(1)
                if self.interval_callback:
                    self.interval_callback(0)
                if self.keyword_count > 0:
                    self.avg_keyword_time = self.total_keyword_time / self.keyword_count
                else:
                    self.avg_keyword_time = 0.0
            self.log_callback("Фоновый парсер остановлен.")
            save_known_apps(known_apps)
        except Exception as err:
            error_message = f"Ошибка в ParserThread: {str(err)}"
            self.log_callback(error_message)
            try:
                notify_error(error_message)
            except Exception:
                pass

if __name__ == "__main__":
    pass
