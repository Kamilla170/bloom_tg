"""
Утилиты для парсинга дат из пользовательского ввода
"""

import re
from datetime import datetime, timedelta
from typing import Optional

# Месяцы на русском
MONTHS_RU = {
    'январ': 1, 'янв': 1,
    'феврал': 2, 'фев': 2,
    'март': 3, 'мар': 3,
    'апрел': 4, 'апр': 4,
    'ма': 5, 'май': 5,
    'июн': 6,
    'июл': 7,
    'август': 8, 'авг': 8,
    'сентябр': 9, 'сен': 9,
    'октябр': 10, 'окт': 10,
    'ноябр': 11, 'ноя': 11,
    'декабр': 12, 'дек': 12
}


def parse_user_date(text: str) -> Optional[datetime]:
    """
    Парсит дату из пользовательского ввода.
    
    Поддерживает форматы:
    - "сегодня", "вчера", "позавчера"
    - "3 дня назад", "неделю назад"
    - "28.01", "28.01.2025"
    - "28 января", "28 янв"
    
    Returns:
        datetime или None если не удалось распарсить
    """
    if not text:
        return None
    
    text = text.lower().strip()
    now = datetime.now()
    
    # Относительные даты
    if text in ('сегодня', 'сейчас'):
        return now
    
    if text == 'вчера':
        return now - timedelta(days=1)
    
    if text == 'позавчера':
        return now - timedelta(days=2)
    
    # "X дней назад"
    days_ago_match = re.search(r'(\d+)\s*(дн|день|дня|дней)', text)
    if days_ago_match and 'назад' in text:
        days = int(days_ago_match.group(1))
        if 1 <= days <= 365:
            return now - timedelta(days=days)
    
    # "неделю назад"
    if 'недел' in text and 'назад' in text:
        weeks_match = re.search(r'(\d+)\s*недел', text)
        if weeks_match:
            weeks = int(weeks_match.group(1))
        else:
            weeks = 1
        if 1 <= weeks <= 52:
            return now - timedelta(weeks=weeks)
    
    # "2-3 дня назад" - берём среднее
    range_match = re.search(r'(\d+)\s*-\s*(\d+)\s*(дн|день|дня|дней)', text)
    if range_match and 'назад' in text:
        days_min = int(range_match.group(1))
        days_max = int(range_match.group(2))
        days_avg = (days_min + days_max) // 2
        if 1 <= days_avg <= 365:
            return now - timedelta(days=days_avg)
    
    # Формат "28.01" или "28.01.2025"
    date_dot_match = re.search(r'(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?', text)
    if date_dot_match:
        day = int(date_dot_match.group(1))
        month = int(date_dot_match.group(2))
        year = date_dot_match.group(3)
        
        if year:
            year = int(year)
            if year < 100:
                year += 2000
        else:
            year = now.year
            # Если дата в будущем, значит это прошлый год
            try:
                test_date = datetime(year, month, day)
                if test_date > now:
                    year -= 1
            except:
                pass
        
        try:
            result = datetime(year, month, day)
            # Проверяем что дата не слишком старая и не в будущем
            if result <= now and result > now - timedelta(days=365):
                return result
        except ValueError:
            pass
    
    # Формат "28 января" или "28 янв"
    for month_name, month_num in MONTHS_RU.items():
        if month_name in text:
            day_match = re.search(r'(\d{1,2})', text)
            if day_match:
                day = int(day_match.group(1))
                year = now.year
                
                try:
                    result = datetime(year, month_num, day)
                    # Если дата в будущем, значит это прошлый год
                    if result > now:
                        result = datetime(year - 1, month_num, day)
                    
                    # Проверяем что дата не слишком старая
                    if result > now - timedelta(days=365):
                        return result
                except ValueError:
                    pass
            break
    
    return None


def format_date_ago(date: datetime) -> str:
    """
    Форматирует дату в человекочитаемый формат.
    
    Returns:
        str: "сегодня", "вчера", "3 дня назад", "28.01"
    """
    if not date:
        return "неизвестно"
    
    now = datetime.now()
    diff = now - date
    days = diff.days
    
    if days == 0:
        return "сегодня"
    elif days == 1:
        return "вчера"
    elif days == 2:
        return "позавчера"
    elif days <= 7:
        return f"{days} дней назад"
    elif days <= 14:
        return "неделю назад"
    elif days <= 21:
        return "2 недели назад"
    elif days <= 30:
        return "3 недели назад"
    else:
        return date.strftime("%d.%m")


def get_days_offset(choice: str) -> int:
    """
    Получить смещение в днях для кнопок выбора.
    
    Args:
        choice: "today", "yesterday", "2_3_days", "week", "skip"
    
    Returns:
        int: количество дней назад (0 = сегодня, -1 = не устанавливать)
    """
    offsets = {
        'today': 0,
        'yesterday': 1,
        '2_3_days': 2,  # Берём 2 дня как среднее
        'week': 7,
        'skip': -1  # Не устанавливать дату
    }
    return offsets.get(choice, -1)


