from datetime import datetime
import pytz
from config import MOSCOW_TZ

def get_moscow_now():
    """Получить текущее время в Москве"""
    return datetime.now(MOSCOW_TZ)

def get_moscow_date():
    """Получить текущую дату в Москве"""
    return get_moscow_now().date()

def moscow_to_naive(moscow_datetime):
    """Конвертировать московское время в naive datetime"""
    if moscow_datetime.tzinfo is not None:
        return moscow_datetime.replace(tzinfo=None)
    return moscow_datetime

def format_days_ago(last_date):
    """Форматировать 'N дней назад'"""
    if not last_date:
        return "еще не поливали"
    
    moscow_now = get_moscow_now()
    
    # Конвертируем в московское время если нужно
    if last_date.tzinfo is None:
        last_date_utc = pytz.UTC.localize(last_date)
    else:
        last_date_utc = last_date
    
    last_date_moscow = last_date_utc.astimezone(MOSCOW_TZ)
    days_ago = (moscow_now.date() - last_date_moscow.date()).days
    
    if days_ago == 0:
        return "сегодня"
    elif days_ago == 1:
        return "вчера"
    else:
        return f"{days_ago} дней назад"
