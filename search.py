import requests
import logging
from bs4 import BeautifulSoup
import re
from google_play_scraper import search as gp_search, app as gp_app
import time
from playwright.sync_api import sync_playwright, TimeoutError
import json  # Для работы с JSON (используется в save_results_to_json)

# Глобальная настройка для включения/отключения парсера Xiaomi GetApps
ENABLE_XIAOMI_GETAPPS = True

# Функция для извлечения версии приложения с Google Play по ID приложения
def get_google_play_version(app_id):
    url = f"https://play.google.com/store/apps/details?id={app_id}&hl=ru"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        version_label = soup.find(string=re.compile("Текущая версия", re.IGNORECASE))
        if version_label:
            parent = version_label.find_parent("div")
            if parent:
                sibling = parent.find_next_sibling("span")
                if sibling:
                    version_text = sibling.get_text(strip=True)
                    if version_text:
                        return version_text
        match = re.search(r"Текущая версия.*?>([^<]+)<", response.text, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    except Exception as e:
        logging.error(f"Ошибка парсинга версии для Google Play ({app_id}): {e}")
    return ""

# Функция для поиска приложений в Google Play по ключевому слову
def search_google_play(keyword, num_results=8):
    try:
        results = gp_search(keyword, lang="ru", country="ru")
        apps = []
        for app_data in results[:num_results]:
            app_id = app_data.get("appId", "")
            version_value = app_data.get("version", "")
            if not version_value and app_id:
                try:
                    details = gp_app(app_id, lang="ru", country="ru")
                    version_value = details.get("version", "")
                except Exception as e:
                    logging.error(f"Ошибка получения версии через gp_app для {app_id}: {e}")
            if not version_value and app_id:
                version_value = get_google_play_version(app_id)
            apps.append({
                "platform": "Google Play",
                "keyword": keyword,
                "title": app_data.get("title", ""),
                "developer": app_data.get("developer", ""),
                "url": f"https://play.google.com/store/apps/details?id={app_id}",
                "version": version_value
            })
        return apps
    except Exception as e:
        logging.error(f"❌ Google Play ошибка для '{keyword}': {e}")
        return []

# Функция для поиска приложений в App Store (iTunes)
def search_app_store(keyword, country="US", num_results=8, proxies=None):
    url = "https://itunes.apple.com/search"
    params = {"term": keyword, "country": country, "media": "software", "limit": num_results}
    try:
        response = requests.get(url, params=params, timeout=10, proxies=proxies)
        response.raise_for_status()
        data = response.json()
        apps = []
        for app in data.get("results", []):
            apps.append({
                "platform": "App Store",
                "keyword": keyword,
                "title": app.get("trackName", ""),
                "developer": app.get("artistName", ""),
                "url": app.get("trackViewUrl", ""),
                "version": app.get("version", "")
            })
        return apps
    except Exception as e:
        logging.error(f"❌ App Store ошибка для '{keyword}': {e}")
        return []

# Функция для извлечения версии приложения с RuStore по URL результата
def get_rustore_version(url_result, proxies=None):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url_result, headers=headers, timeout=10, proxies=proxies)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        version_elem = soup.find(attrs={"itemprop": "softwareVersion"})
        if version_elem:
            version_text = version_elem.get_text(strip=True)
            if version_text:
                return version_text
        label = soup.find(text=re.compile("Версия", re.IGNORECASE))
        if label:
            parent = label.parent
            sibling = parent.find_next_sibling()
            if sibling:
                version_text = sibling.get_text(strip=True)
                if version_text:
                    return version_text
            match = re.search(r"Версия[:\s\-]*([\d]+(?:\.[\d]+)+)", parent.get_text(" ", strip=True))
            if match:
                return match.group(1)
        match = re.search(r"Версия[:\s\-]*([\d]+(?:\.[\d]+)+)", response.text)
        if match:
            return match.group(1)
    except Exception as e:
        logging.error(f"Ошибка получения версии для RuStore ({url_result}): {e}")
    return ""

# Функция для поиска приложений в RuStore по ключевому слову
def search_rustore(keyword, num_results=20, proxies=None):
    search_url = f"https://apps.rustore.ru/search?query={keyword}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(search_url, headers=headers, timeout=10, proxies=proxies)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        cards = soup.find_all("div", class_="rEyNkpHT")
        if not cards or len(cards) < 10:
            candidate_blocks = soup.find_all("div")
            groups = {}
            for block in candidate_blocks:
                classes = block.get("class")
                if classes:
                    key = tuple(sorted(classes))
                    groups.setdefault(key, []).append(block)
            candidate_groups = {k: v for k, v in groups.items() if len(v) > 10}
            if candidate_groups:
                selected_key = max(candidate_groups.keys(), key=lambda k: len(candidate_groups[k]))
                cards = candidate_groups[selected_key]
        apps = []
        seen_fingerprints = set()
        for card in cards:
            name_tag = card.find("p", itemprop="name")
            title = name_tag.get_text(strip=True) if name_tag else ""
            desc_tag = card.find("p", itemprop="description")
            description = desc_tag.get_text(strip=True) if desc_tag else ""
            rating_tag = card.find("span", {"data-testid": "rating"})
            rating = rating_tag.get_text(strip=True) if rating_tag else ""
            parent_anchor = card.find_parent("a", href=lambda h: h and "/catalog/app" in h)
            if parent_anchor:
                url_result = "https://apps.rustore.ru" + parent_anchor.get("href").strip()
            else:
                anchor = card.find("a", href=lambda h: h and "/catalog/app" in h)
                if anchor:
                    url_result = "https://apps.rustore.ru" + anchor.get("href").strip()
                else:
                    url_result = ""
            fingerprint = (title, description, url_result)
            if fingerprint in seen_fingerprints:
                continue
            seen_fingerprints.add(fingerprint)
            version_value = ""
            if url_result:
                version_value = get_rustore_version(url_result, proxies=proxies)
            apps.append({
                "platform": "RuStore",
                "keyword": keyword,
                "title": title,
                "developer": "",
                "description": description,
                "rating": rating,
                "url": url_result,
                "version": version_value
            })
            if len(apps) >= num_results:
                break
        return apps
    except Exception as e:
        logging.error(f"❌ RuStore ошибка для '{keyword}': {e}")
        return []

# Функция для поиска приложений в Xiaomi Global Store с использованием Playwright
def search_xiaomi_global(keyword, num_results=8):
    VALID_VERSION_PATTERN = re.compile(r'^\d+(?:\.\d+)+$')
    def extract_version(page):
        locator = page.locator("div.app-more__item_DrPSb[aria-label^='Version:']")
        if locator.count() > 0:
            aria_str = locator.first.get_attribute("aria-label")
            if aria_str:
                version = aria_str.split("Version:")[-1].strip()
                if version and VALID_VERSION_PATTERN.match(version):
                    return version
        return ""
    results = []
    search_url = f"https://global.app.mi.com/search?lo=RU&la=ru&q={keyword}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)", locale="ru-RU")
            page = context.new_page()
            page.goto(search_url, timeout=30000)
            page.wait_for_selector("div.container_oG9MN", timeout=15000)
            cards = page.locator("div.container_oG9MN")
            total = cards.count()
            for i in range(total):
                card = cards.nth(i)
                aria_label = card.get_attribute("aria-label") or ""
                name, developer = "", ""
                if aria_label:
                    parts = aria_label.split(",")
                    for part in parts:
                        if "APP Name:" in part:
                            name = part.split("APP Name:")[-1].strip()
                        elif "Developer:" in part:
                            developer = part.split("Developer:")[-1].strip()
                if not name:
                    title_el = card.locator("p.app__title_rSTA+")
                    if title_el.count() > 0:
                        name = title_el.first.inner_text().strip()
                if not developer:
                    dev_el = card.locator("p.app__developer_eTDFg")
                    if dev_el.count() > 0:
                        developer = dev_el.first.inner_text().strip()
                if not name or not developer:
                    continue
                img_locator = card.locator("img.icon_2wPOA")
                if img_locator.count() == 0:
                    continue
                img_locator.wait_for(state="visible", timeout=5000)
                with page.expect_navigation(timeout=15000):
                    img_locator.click()
                detail_url = page.url
                version = extract_version(page)
                results.append({
                    "platform": "Xiaomi Global Store",
                    "keyword": keyword,
                    "title": name,
                    "developer": developer,
                    "url": detail_url,
                    "version": version
                })
                if len(results) >= num_results:
                    break
                page.go_back(timeout=15000)
                page.wait_for_selector("div.container_oG9MN", timeout=15000)
            browser.close()
            return results
    except Exception as e:
        logging.error(f"Ошибка парсинга Xiaomi Global Store по '{keyword}': {e}")
        return []

# Новая функция для поиска приложений в Xiaomi GetApps (наша доработка)
def search_xiaomi_getapps(keyword, num_results=8):
    results = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)", locale="ru-RU")
            page = context.new_page()
            search_url = f"https://global.app.mi.com/search?lo=ID&la=ru&q={keyword}"
            page.goto(search_url, timeout=30000)
            page.wait_for_selector("div.search-result__item__container_KFv1n", timeout=15000)
            cards = page.locator("div.search-result__item__container_KFv1n")
            total = cards.count()
            for i in range(min(num_results, total)):
                card = cards.nth(i)
                clickable = card.locator("div[role='button']")
                clickable.wait_for(state="visible", timeout=5000)
                aria_label = clickable.get_attribute("aria-label") or ""
                title = ""
                developer = ""
                if aria_label:
                    parts = aria_label.split(",")
                    if len(parts) >= 2:
                        title = parts[0].replace("APP Name:", "").strip()
                        developer = parts[1].replace("Developer:", "").strip()
                with page.expect_navigation(timeout=15000):
                    clickable.click()
                time.sleep(1)
                description = ""
                try:
                    desc_locator = page.locator("p.app-info__brief_Ewrks")
                    desc_locator.wait_for(timeout=10000)
                    if desc_locator.count() > 0:
                        description = desc_locator.first.inner_text().strip()
                except Exception as e:
                    logging.warning(f"Не найден селектор описания для '{title}': {e}")
                version = ""
                try:
                    all_texts = page.locator("div.app-more__item__content_YMXlz").all_inner_texts()
                    for text in all_texts:
                        cleaned = text.strip()
                        if re.match(r'^\d+(\.\d+)+', cleaned) and not any(unit in cleaned.upper() for unit in ["MB", "GB", "KB"]):
                            version = cleaned
                            break
                except Exception as e:
                    logging.warning(f"Ошибка извлечения версии для '{title}': {e}")
                app_url = page.url
                results.append({
                    "platform": "Xiaomi GetApps",
                    "keyword": keyword,
                    "title": title,
                    "developer": developer,
                    "version": version,
                    "description": description,
                    "url": app_url
                })
                if len(results) >= num_results:
                    break
                page.go_back(timeout=15000)
                page.wait_for_selector("div.search-result__item__container_KFv1n", timeout=15000)
            browser.close()
        return results
    except Exception as e:
        logging.error(f"❌ Xiaomi GetApps ошибка для '{keyword}': {e}")
        return []

# Функция для поиска приложений в Samsung Galaxy Store с использованием Playwright
def search_galaxy_store(keyword, num_results=27):
    def extract_version(page):
        try:
            page_text = page.inner_text("body")
            match = re.search(r"(\d+)\.(\d+)\.(\d+)", page_text)
            if match:
                version = ".".join(match.groups())
                logging.info(f"[extract_version] Найдена версия: {version}")
                return version
            else:
                logging.info("[extract_version] Версия не найдена по шаблону.")
                return ""
        except Exception as e:
            logging.error(f"[extract_version] Ошибка при поиске версии: {e}")
            return ""
    
    def click_image_get_detail_info(page, card_index: int):
        card_locator = page.locator("li.MuiGridListTile-root").nth(card_index)
        image_locator = card_locator.locator("div.MuiGridListTile-tile img").first
        timeout_val = 5000
        # Для первой карточки можно увеличить таймаут, если необходимо
        if card_index == 0:
            timeout_val = 8000  
        try:
            logging.info(f"[click_image_get_detail_info] Нажимаем на изображение карточки {card_index+1}")
            element = image_locator.element_handle(timeout=timeout_val)
            if not element:
                logging.error("[click_image_get_detail_info] Не удалось найти элемент изображения")
                return "", ""
            with page.expect_navigation(timeout=15000):
                element.evaluate("el => el.click()")
            page.wait_for_load_state("load", timeout=15000)
            detail_url = page.url
            logging.info(f"[click_image_get_detail_info] Детальный URL: {detail_url}")
            version_info = extract_version(page)
            page.go_back()
            page.wait_for_load_state("load", timeout=15000)
            time.sleep(2)
            return detail_url, version_info
        except Exception as e:
            logging.error(f"[click_image_get_detail_info] Ошибка при переходе: {e}")
            return "", ""
    
    apps = []
    search_url = f"https://galaxystore.samsung.com/search?q={keyword}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--disable-gpu", "--no-sandbox"])
            context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
            page = context.new_page()
            page.goto(search_url)
            page.wait_for_selector("li.MuiGridListTile-root", timeout=15000)
            time.sleep(2)
            card_locator = page.locator("li.MuiGridListTile-root")
            total_cards = card_locator.count()
            logging.info(f"[search_galaxy_store] Найдено карточек: {total_cards}")
            limit = min(num_results, total_cards)
            for i in range(limit):
                try:
                    card = card_locator.nth(i)
                    
                    # Извлечение названия с обработкой исключений
                    title_elem = card.locator("#contentName")
                    try:
                        if title_elem.count() > 0:
                            title = title_elem.first.get_attribute("title") or title_elem.first.inner_text().strip()
                        else:
                            title = ""
                    except Exception as e:
                        logging.error(f"[search_galaxy_store] Ошибка получения названия карточки {i+1}: {e}")
                        title = ""
                    
                    # Извлечение разработчика
                    seller_elem = card.locator("#contentSeller")
                    try:
                        if seller_elem.count() > 0:
                            developer = seller_elem.first.get_attribute("title") or seller_elem.first.inner_text().strip()
                        else:
                            developer = ""
                    except Exception as e:
                        logging.error(f"[search_galaxy_store] Ошибка получения разработчика карточки {i+1}: {e}")
                        developer = ""
                    
                    # Извлечение цены
                    price_elem = card.locator("#contentPrice")
                    try:
                        if price_elem.count() > 0:
                            price = price_elem.first.inner_text().strip()
                        else:
                            price = ""
                    except Exception as e:
                        logging.error(f"[search_galaxy_store] Ошибка получения цены карточки {i+1}: {e}")
                        price = ""
                    
                    logging.info(f"[search_galaxy_store] Обрабатываем карточку {i+1}/{limit}: '{title}' от '{developer}'")
                    detail_url, version_info = click_image_get_detail_info(page, i)
                    
                    if not title or not developer or not detail_url:
                        logging.info(f"[search_galaxy_store] Пропуск карточки {i+1}: недостаточно данных")
                        continue
                    
                    app_data = {
                        "platform": "Samsung Galaxy Store",
                        "keyword": keyword,
                        "title": title,
                        "developer": developer,
                        "price": price,
                        "detail_url": detail_url,
                        "version": version_info,
                    }
                    apps.append(app_data)
                except Exception as e:
                    logging.error(f"[search_galaxy_store] Ошибка обработки карточки {i+1}: {e}")
                    continue
            browser.close()
            return apps
    except Exception as e:
        logging.error(f"Ошибка парсинга Galaxy Store по '{keyword}': {e}")
        return []

# Функция для извлечения деталей (версии и разработчика) со страницы приложения
def extract_app_details(page):
    version = ""
    developer = ""
    try:
        page.wait_for_selector("div.appSingleInfo", timeout=10000)
        version_locator = page.locator("//div[@class='appSingleInfo' and .//div[contains(text(), 'Версия')]]//div[@class='info_val']")
        developer_locator = page.locator("//div[@class='appSingleInfo' and .//div[contains(text(), 'Разработчик')]]//div[@class='info_val']")
        if version_locator.count() > 0:
            version = version_locator.first.inner_text().strip()
        if developer_locator.count() > 0:
            developer = developer_locator.first.inner_text().strip()
        logging.info(f"[extract_app_details] Версия: {version}, Разработчик: {developer}")
        return version, developer
    except Exception as e:
        logging.error(f"[extract_app_details] Ошибка при извлечении деталей: {e}")
        return "", ""

# Функция для клика по заголовку карточки и получения детальной информации
def click_title_get_detail_info(page, card_index: int):
    try:
        title_index = card_index * 2
        title_locator = page.locator("p[data-v-302a9de2]").nth(title_index)
        element = title_locator.element_handle(timeout=5000)
        if not element:
            logging.error("[click_title_get_detail_info] Не найден заголовок карточки")
            return "", "", ""
        logging.info(f"[click_title_get_detail_info] Нажимаем на заголовок карточки {card_index + 1}")
        with page.expect_navigation(timeout=15000):
            element.evaluate("el => el.click()")
        page.wait_for_selector("div.appSingleInfo", timeout=15000)
        detail_url = page.url
        version, developer = extract_app_details(page)
        page.go_back()
        page.wait_for_selector("p[data-v-302a9de2]", timeout=15000)
        time.sleep(2)
        return detail_url, version, developer
    except Exception as e:
        logging.error(f"[click_title_get_detail_info] Ошибка при переходе: {e}")
        return "", "", ""

# Функция для поиска приложений в Huawei AppGallery с использованием Playwright
def search_huawei_appgallery(keyword, num_results=8):
    search_url = f"https://appgallery.huawei.com/#/search/{keyword}"
    apps = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-gpu", "--no-sandbox"])
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        page = context.new_page()
        page.goto(search_url)
        try:
            page.wait_for_selector("p[data-v-302a9de2]", timeout=15000)
        except TimeoutError:
            logging.error("[search_huawei_appgallery] Не удалось загрузить результаты поиска.")
            browser.close()
            return apps
        time.sleep(2)
        elements = page.locator("p[data-v-302a9de2]")
        total_elements = elements.count()
        total_cards = total_elements // 2  # Каждый результат состоит из заголовка и описания
        logging.info(f"[search_huawei_appgallery] Найдено карточек: {total_cards}")

        for i in range(total_cards):
            # Если число уникальных карточек достигло лимита, выходим из цикла
            if len(apps) >= num_results:
                break
            try:
                title = elements.nth(i * 2).inner_text().strip()
                description = elements.nth(i * 2 + 1).inner_text().strip()
                logging.info(f"[search_huawei_appgallery] Обрабатываем карточку {len(apps)+1}/{num_results}: '{title}'")
                detail_url, version, developer = click_title_get_detail_info(page, i)
                if not title or not detail_url:
                    logging.info(f"[search_huawei_appgallery] Пропуск карточки {i+1}: недостаточно данных")
                    continue
                # Проверка уникальности по названию
                if any(app.get("title") == title for app in apps):
                    logging.info(f"[search_huawei_appgallery] Карточка '{title}' уже добавлена, пропускаем.")
                    continue
                app_data = {
                    "platform": "Huawei AppGallery",
                    "keyword": keyword,
                    "title": title,
                    "description": description,
                    "detail_url": detail_url,
                    "version": version,
                    "developer": developer,
                }
                apps.append(app_data)
            except Exception as e:
                logging.error(f"[search_huawei_appgallery] Ошибка обработки карточки {i+1}: {e}")
                continue

        browser.close()
        return apps

# Функция для сохранения результатов поиска в JSON-файл
def save_results_to_json(results, filename="huawei_results.json"):
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        logging.info(f"[save_results_to_json] Сохранено {len(results)} записей в файл {filename}")
    except Exception as e:
        logging.error(f"[save_results_to_json] Ошибка при записи в {filename}: {e}")

# ТЕСТОВЫЙ БЛОК – пример объединения результатов и вывода статистики.
if __name__ == "__main__":
    keyword = "Telegram"
    all_apps = []
    # Поиск по основным магазинам
    apps_gp = search_google_play(keyword)
    apps_as = search_app_store(keyword)
    apps_rs = search_rustore(keyword)
    apps_xm_global = search_xiaomi_global(keyword)
    if ENABLE_XIAOMI_GETAPPS:
        apps_xm_getapps = search_xiaomi_getapps(keyword)
    else:
        apps_xm_getapps = []
    apps_gs = search_galaxy_store(keyword)
    apps_ha = search_huawei_appgallery(keyword)
    
    all_apps.extend(apps_gp)
    all_apps.extend(apps_as)
    all_apps.extend(apps_rs)
    all_apps.extend(apps_xm_global)
    all_apps.extend(apps_xm_getapps)
    all_apps.extend(apps_gs)
    all_apps.extend(apps_ha)
    
    stats = {}
    for app in all_apps:
        platform = app.get("platform", "Unknown")
        stats[platform] = stats.get(platform, 0) + 1
    
    print("Статистика:")
    for plat, count in stats.items():
        print(f"{plat}: {count} приложений найдено")
    
    save_results_to_json(all_apps, filename="results_all.json")
