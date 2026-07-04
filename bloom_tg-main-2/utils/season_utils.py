"""
Утилиты для работы с сезонами
GPT сам определяет интервалы полива, здесь только информация о сезоне
"""

from datetime import datetime
from typing import Dict
import pytz


def get_current_season(timezone_str: str = 'Europe/Moscow') -> Dict[str, str]:
    """
    Определить текущий сезон и базовую информацию
    
    Returns:
        Dict с информацией о сезоне для передачи в GPT
    """
    tz = pytz.timezone(timezone_str)
    now = datetime.now(tz)
    month = now.month
    
    # Определяем сезон для северного полушария (Россия)
    if month in [12, 1, 2]:
        season = 'winter'
        season_ru = 'Зима'
        growth_phase = 'Период покоя'
        light_hours = 'Короткий световой день (7-9 часов)'
        temperature_note = 'Оптимально 16-20°C, избегать сквозняков от батарей'
        watering_adjustment = 'Полив сокращается в 1.5-2.5 раза'
        recommendations = (
            'Большинство растений в состоянии покоя. '
            'Сократить полив, прекратить подкормки. '
            'Избегать переувлажнения - риск корневых гнилей.'
        )
    elif month in [3, 4, 5]:
        season = 'spring'
        season_ru = 'Весна'
        growth_phase = 'Начало вегетации'
        light_hours = 'Увеличивающийся световой день (11-15 часов)'
        temperature_note = 'Оптимально 18-22°C'
        watering_adjustment = 'Постепенно увеличивать полив'
        recommendations = (
            'Растения выходят из покоя и начинают рост. '
            'Постепенно увеличивать полив, начинать подкормки. '
            'Оптимальное время для пересадки.'
        )
    elif month in [6, 7, 8]:
        season = 'summer'
        season_ru = 'Лето'
        growth_phase = 'Активная вегетация'
        light_hours = 'Длинный световой день (15-18 часов)'
        temperature_note = 'Оптимально 20-26°C, проветривание при жаре'
        watering_adjustment = 'Максимальная частота полива'
        recommendations = (
            'Период максимальной активности растений. '
            'Регулярный полив, не допускать пересыхания. '
            'Подкормки каждые 1-2 недели.'
        )
    else:  # 9, 10, 11
        season = 'autumn'
        season_ru = 'Осень'
        growth_phase = 'Подготовка к покою'
        light_hours = 'Сокращающийся световой день (10-12 часов)'
        temperature_note = 'Оптимально 18-22°C, постепенно снижать'
        watering_adjustment = 'Постепенно сокращать полив'
        recommendations = (
            'Растения готовятся к периоду покоя. '
            'Постепенно сокращать полив и подкормки. '
            'С октября прекратить подкормки.'
        )
    
    return {
        'season': season,
        'season_ru': season_ru,
        'month': month,
        'month_name': now.strftime('%B'),
        'month_name_ru': get_month_name_ru(month),
        'growth_phase': growth_phase,
        'light_hours': light_hours,
        'temperature_note': temperature_note,
        'watering_adjustment': watering_adjustment,
        'recommendations': recommendations,
        'date': now.strftime('%Y-%m-%d')
    }


def get_month_name_ru(month: int) -> str:
    """Получить название месяца на русском"""
    months = {
        1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
        5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
        9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь'
    }
    return months.get(month, '')


def get_seasonal_care_tips(season: str, plant_state: str = 'healthy') -> str:
    """
    Получить сезонные советы по уходу с учетом состояния растения
    
    Args:
        season: текущий сезон
        plant_state: состояние растения (healthy, flowering, stress и т.д.)
    """
    tips = {
        'winter': {
            'healthy': 'Зимой главное - не переливать! Большинство растений в покое.',
            'flowering': 'Зимнее цветение требует дополнительного освещения и аккуратного полива.',
            'stress': 'Зимой стресс часто связан с переливом или холодом от окна.',
            'dormancy': 'Нормальное состояние для зимы. Минимальный полив, никаких подкормок.'
        },
        'spring': {
            'healthy': 'Весна - лучшее время для пересадки и начала подкормок.',
            'flowering': 'Весеннее цветение естественно. Поддержите удобрениями для цветения.',
            'stress': 'Весной растения быстро восстанавливаются.',
            'active_growth': 'Идеальное время для роста. Обеспечьте питание и полив.'
        },
        'summer': {
            'healthy': 'Летом следите за влажностью. Поливайте чаще, но не заливайте.',
            'flowering': 'Летнее цветение требует регулярного полива и подкормок.',
            'stress': 'Летом стресс может быть от жары. Притените от прямого солнца.',
            'active_growth': 'Пик вегетации. Регулярные подкормки и полив.'
        },
        'autumn': {
            'healthy': 'Осенью готовьте растения к зиме, сокращая полив.',
            'flowering': 'Осеннее цветение - продолжайте поддерживать растение.',
            'stress': 'Осенний стресс может быть от сокращения света.',
            'dormancy': 'Растение готовится к покою - это нормально.'
        }
    }
    
    return tips.get(season, {}).get(plant_state, 'Следите за состоянием растения.')
