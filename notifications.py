import requests
import logging

# Функция отправки сообщения в Telegram через Bot API
def send_telegram_message(message, token, chat_id):
    # Формируем URL для обращения к Telegram Bot API с использованием токена
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    
    # Подготавливаем полезную нагрузку с параметрами сообщения
    payload = {
        "chat_id": chat_id,                   # ID чата для отправки сообщения
        "text": message,                      # Текст сообщения
        "parse_mode": "HTML",                 # Парсинг HTML для форматирования сообщения
        "disable_web_page_preview": True      # Отключение предпросмотра ссылок
    }
    
    try:
        # Отправляем POST запрос с таймаутом 10 секунд
        requests.post(url, data=payload, timeout=10)
        # Логируем отправку сообщения, выводим первую строку сообщения для краткости
        logging.info(f"[Telegram] {message.splitlines()[0]}")
    except Exception as e:
        # В случае ошибки логируем сообщение об ошибке
        logging.error(f"Ошибка при отправке в Telegram: {e}")
