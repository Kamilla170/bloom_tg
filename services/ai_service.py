import logging
import base64
from openai import AsyncOpenAI

from config import OPENAI_API_KEY, PLANT_IDENTIFICATION_PROMPT
from utils.image_utils import optimize_image_for_analysis
from utils.formatters import format_plant_analysis
from utils.season_utils import get_current_season, get_seasonal_care_tips

logger = logging.getLogger(__name__)

# Инициализация OpenAI клиента
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# Модель GPT-5.1 для reasoning задач
GPT_5_1_MODEL = "gpt-5.1-2025-11-13"  # Правильный model ID для GPT-5.1


def extract_plant_state_from_analysis(raw_analysis: str) -> dict:
    """Извлечь информацию о состоянии из анализа AI"""
    state_info = {
        'current_state': 'healthy',
        'state_reason': '',
        'growth_stage': 'young',
        'watering_adjustment': 0,
        'feeding_adjustment': None,
        'recommendations': ''
    }
    
    if not raw_analysis:
        return state_info
    
    lines = raw_analysis.split('\n')
    
    for line in lines:
        line = line.strip()
        
        if line.startswith("ТЕКУЩЕЕ_СОСТОЯНИЕ:"):
            state_text = line.replace("ТЕКУЩЕЕ_СОСТОЯНИЕ:", "").strip().lower()
            # Определяем состояние
            if 'flowering' in state_text or 'цветен' in state_text:
                state_info['current_state'] = 'flowering'
                state_info['watering_adjustment'] = -2  # Поливать чаще
            elif 'active_growth' in state_text or 'активн' in state_text:
                state_info['current_state'] = 'active_growth'
                state_info['feeding_adjustment'] = 7  # Подкормка раз в неделю
            elif 'dormancy' in state_text or 'покой' in state_text:
                state_info['current_state'] = 'dormancy'
                state_info['watering_adjustment'] = 5  # Поливать реже
            elif 'stress' in state_text or 'стресс' in state_text or 'болезн' in state_text:
                state_info['current_state'] = 'stress'
            elif 'adaptation' in state_text or 'адаптац' in state_text:
                state_info['current_state'] = 'adaptation'
            else:
                state_info['current_state'] = 'healthy'
        
        elif line.startswith("ПРИЧИНА_СОСТОЯНИЯ:"):
            state_info['state_reason'] = line.replace("ПРИЧИНА_СОСТОЯНИЯ:", "").strip()
        
        elif line.startswith("ЭТАП_РОСТА:"):
            stage_text = line.replace("ЭТАП_РОСТА:", "").strip().lower()
            if 'young' in stage_text or 'молод' in stage_text:
                state_info['growth_stage'] = 'young'
            elif 'mature' in stage_text or 'взросл' in stage_text:
                state_info['growth_stage'] = 'mature'
            elif 'old' in stage_text or 'стар' in stage_text:
                state_info['growth_stage'] = 'old'
        
        elif line.startswith("ДИНАМИЧЕСКИЕ_РЕКОМЕНДАЦИИ:"):
            state_info['recommendations'] = line.replace("ДИНАМИЧЕСКИЕ_РЕКОМЕНДАЦИИ:", "").strip()
    
    return state_info


def extract_watering_info(analysis_text: str) -> dict:
    """Извлечь информацию о поливе"""
    watering_info = {
        "interval_days": 7,  # Изменено с 5 на 7 как более безопасный default
        "personal_recommendations": "",
        "current_state": "",
        "needs_adjustment": False
    }
    
    if not analysis_text:
        return watering_info
    
    lines = analysis_text.split('\n')
    
    for line in lines:
        line = line.strip()
        
        if line.startswith("ПОЛИВ_ИНТЕРВАЛ:"):
            interval_text = line.replace("ПОЛИВ_ИНТЕРВАЛ:", "").strip()
            import re
            numbers = re.findall(r'\d+', interval_text)
            if numbers:
                try:
                    interval = int(numbers[0])
                    if 2 <= interval <= 28:
                        watering_info["interval_days"] = interval
                except:
                    pass
        
        elif line.startswith("ПОЛИВ_АНАЛИЗ:"):
            current_state = line.replace("ПОЛИВ_АНАЛИЗ:", "").strip()
            watering_info["current_state"] = current_state
            if "не видна" in current_state.lower() or "невозможно оценить" in current_state.lower():
                watering_info["needs_adjustment"] = True
            elif any(word in current_state.lower() for word in ["переувлажн", "перелив", "недополит", "пересушен", "проблем"]):
                watering_info["needs_adjustment"] = True
        
        elif line.startswith("ПОЛИВ_РЕКОМЕНДАЦИИ:"):
            recommendations = line.replace("ПОЛИВ_РЕКОМЕНДАЦИИ:", "").strip()
            watering_info["personal_recommendations"] = recommendations
            
    return watering_info


def extract_and_remove_watering_interval(text: str, season_info: dict) -> tuple:
    """
    Извлечь интервал полива из текста и удалить эту строку.
    
    Args:
        text: текст ответа от GPT
        season_info: информация о сезоне для определения default
        
    Returns:
        tuple: (interval: int, clean_text: str)
    """
    import re
    
    # Default интервал зависит от сезона
    default_interval = 10  # Безопасный default для зимы
    if season_info.get('season') == 'summer':
        default_interval = 7
    elif season_info.get('season') == 'winter':
        default_interval = 12
    
    interval = default_interval
    clean_text = text
    
    # Ищем строку ПОЛИВ_ИНТЕРВАЛ: число
    pattern = r'\n?ПОЛИВ_ИНТЕРВАЛ:\s*(\d+)\s*'
    match = re.search(pattern, text)
    
    if match:
        try:
            interval = int(match.group(1))
            # Валидация
            interval = max(3, min(28, interval))
            logger.info(f"💧 Извлечён интервал полива: {interval} дней")
        except:
            logger.warning(f"⚠️ Не удалось извлечь интервал, используем default: {default_interval}")
            interval = default_interval
        
        # Удаляем строку из текста
        clean_text = re.sub(pattern, '', text).strip()
    else:
        logger.warning(f"⚠️ Строка ПОЛИВ_ИНТЕРВАЛ не найдена, используем default: {default_interval}")
    
    return interval, clean_text


async def analyze_vision_step(image_data: bytes, user_question: str = None, previous_state: str = None) -> dict:
    """ШАГ 1: Vision анализ через GPT-4o - что видно, проблемы, уверенность
    
    Returns:
        dict: {
            "success": bool,
            "vision_analysis": str,  # Что видно на фото
            "possible_problems": str,  # Возможные проблемы
            "confidence": float,  # Уровень уверенности 0-100
            "plant_name": str,
            "raw_observations": str  # Сырые наблюдения для передачи в reasoning
        }
    """
    if not openai_client:
        return {"success": False, "error": "OpenAI API недоступен"}
    
    try:
        optimized_image = await optimize_image_for_analysis(image_data, high_quality=True)
        base64_image = base64.b64encode(optimized_image).decode('utf-8')
        
        vision_prompt = """Вы - профессиональный ботаник-диагност. Проанализируйте фотографию растения и опишите ТОЛЬКО то, что видно на изображении.

ВАША ЗАДАЧА:
1. Опишите что видно на фото (морфология, состояние листьев, стеблей, цветов)
2. Выявите возможные проблемы (пятна, пожелтение, увядание, вредители и т.д.)
3. Оцените уровень уверенности в своих наблюдениях (0-100%)

ФОРМАТ ОТВЕТА (строго соблюдайте):
РАСТЕНИЕ: [конкретное название растения, например: Фикус Бенджамина, Монстера, Сенполия. Если не можете определить точно - напишите наиболее вероятный вариант]
УВЕРЕННОСТЬ: [число от 0 до 100]%

ЧТО ВИДНО:
- [детальное описание морфологических признаков]
- [состояние листьев, стеблей, корневой системы если видна]
- [наличие цветов, бутонов, плодов]

ВОЗМОЖНЫЕ ПРОБЛЕМЫ:
- [список проблем которые вы видите или "Проблем не обнаружено"]
- [признаки заболеваний если есть]
- [признаки вредителей если есть]
- [признаки неправильного ухода если видны]

ВАЖНО: 
- Описывайте ТОЛЬКО то, что реально видно на фото
- Если что-то не видно - укажите "не видно на фото"
- Будьте объективны и точны"""
        
        if previous_state:
            vision_prompt += f"\n\nПредыдущее состояние растения: {previous_state}. Обратите внимание на изменения."
        
        if user_question:
            vision_prompt += f"\n\nДополнительный вопрос пользователя: {user_question}"
        
        logger.info("📸 Vision анализ: использую модель GPT-4o")
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "Вы - профессиональный ботаник-диагност. Анализируйте только визуальные признаки на фотографии. Будьте точны и объективны."
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": vision_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ],
            max_tokens=1000,
            temperature=0.2
        )
        
        raw_vision = response.choices[0].message.content
        
        if len(raw_vision) < 50:
            raise Exception("Некачественный ответ от vision модели")
        
        # Извлекаем данные из ответа
        plant_name = "Неизвестное растение"
        confidence = 50
        vision_analysis = ""
        possible_problems = ""
        
        lines = raw_vision.split('\n')
        current_section = None
        
        for line in lines:
            line = line.strip()
            
            if line.startswith("РАСТЕНИЕ:"):
                raw_name = line.replace("РАСТЕНИЕ:", "").strip()
                # Очищаем от "Неизвестное растение (возможно, X)" → "X"
                import re
                if "неизвестное растение" in raw_name.lower() and "(" in raw_name:
                    # Извлекаем то что в скобках
                    match = re.search(r'\((?:возможно,?\s*)?([^)]+)\)', raw_name, re.IGNORECASE)
                    if match:
                        plant_name = match.group(1).strip()
                    else:
                        plant_name = raw_name
                else:
                    # Убираем "(возможно)" если есть
                    plant_name = re.sub(r'\s*\(возможно[^)]*\)\s*', '', raw_name, flags=re.IGNORECASE).strip()
                    if not plant_name:
                        plant_name = raw_name
            elif line.startswith("УВЕРЕННОСТЬ:"):
                try:
                    conf_str = line.replace("УВЕРЕННОСТЬ:", "").strip().replace("%", "")
                    confidence = float(conf_str)
                except:
                    confidence = 50
            elif line.startswith("ЧТО ВИДНО:"):
                current_section = "vision"
                vision_analysis = line.replace("ЧТО ВИДНО:", "").strip() + "\n"
            elif line.startswith("ВОЗМОЖНЫЕ ПРОБЛЕМЫ:"):
                current_section = "problems"
                possible_problems = line.replace("ВОЗМОЖНЫЕ ПРОБЛЕМЫ:", "").strip() + "\n"
            elif current_section == "vision":
                vision_analysis += line + "\n"
            elif current_section == "problems":
                possible_problems += line + "\n"
        
        # Если не удалось извлечь структурированно, используем весь текст
        if not vision_analysis:
            vision_analysis = raw_vision
        
        logger.info(f"✅ Vision анализ завершен (модель: GPT-4o, растение={plant_name}, уверенность={confidence}%)")
        
        return {
            "success": True,
            "vision_analysis": vision_analysis.strip(),
            "possible_problems": possible_problems.strip() if possible_problems else "Проблем не обнаружено",
            "confidence": confidence,
            "plant_name": plant_name,
            "raw_observations": raw_vision
        }
        
    except Exception as e:
        logger.error(f"❌ Vision анализ ошибка: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


async def analyze_reasoning_step(vision_result: dict, plant_context: str = None, user_question: str = None) -> dict:
    """ШАГ 2: Reasoning через GPT-5.1 - объясняет почему, план действий, адаптация
    
    Args:
        vision_result: Результат от analyze_vision_step
        plant_context: Контекст истории растения (опционально)
        user_question: Вопрос пользователя (опционально)
    
    Returns:
        dict: {
            "success": bool,
            "reasoning": str,  # Объяснение почему
            "action_plan": str,  # План действий
            "adapted_recommendations": str,  # Адаптированные рекомендации
            "full_analysis": str,  # Полный анализ для пользователя
            "watering_interval": int  # Интервал полива в днях
        }
    """
    if not openai_client:
        return {"success": False, "error": "OpenAI API недоступен"}
    
    try:
        # Получаем информацию о сезоне
        season_info = get_current_season()
        
        seasonal_context = f"""
ТЕКУЩИЙ СЕЗОН: {season_info['season_ru']} ({season_info['month_name_ru']})
ФАЗА РОСТА: {season_info['growth_phase']}
СВЕТОВОЙ ДЕНЬ: {season_info['light_hours']}
КОРРЕКТИРОВКА ПОЛИВА: {season_info['watering_adjustment']}

СЕЗОННЫЕ ОСОБЕННОСТИ:
{season_info['recommendations']}
"""
        
        system_prompt = """Вы - профессиональный ботаник-консультант с многолетним опытом. Ваша задача - проанализировать визуальные наблюдения и дать глубокое объяснение с планом действий.

СТИЛЬ ОБЩЕНИЯ:
- Авторитетный, экспертный, но доступный
- Конкретные рекомендации на основе фактов
- Обращение на "вы" (профессиональное)
- Структурированные ответы: диагноз → причина → решение

ВАЖНО: НЕ ИСПОЛЬЗУЙТЕ markdown форматирование (**, *, _). Пишите обычным текстом.

КРИТИЧЕСКИ ВАЖНО: Всегда учитывайте текущий сезон и время года при рекомендациях по поливу и уходу!
Зимой полив значительно сокращается, летом увеличивается. Игнорирование сезона может погубить растение."""

        user_prompt = f"""ВИЗУАЛЬНЫЕ НАБЛЮДЕНИЯ (от vision модели):
{vision_result.get('raw_observations', '')}

ЧТО ВИДНО: {vision_result.get('vision_analysis', '')}
ВОЗМОЖНЫЕ ПРОБЛЕМЫ: {vision_result.get('possible_problems', '')}
УВЕРЕННОСТЬ: {vision_result.get('confidence', 50)}%

ИСТОРИЯ РАСТЕНИЯ:
{plant_context if plant_context else "Контекст отсутствует"}

{seasonal_context}

{f'ВОПРОС ПОЛЬЗОВАТЕЛЯ: {user_question}' if user_question else ''}

ВАША ЗАДАЧА:
1. ОБЪЯСНИТЕ ПОЧЕМУ - проанализируйте визуальные наблюдения и объясните причины проблем или текущего состояния
2. ДАЙТЕ ПЛАН ДЕЙСТВИЙ - конкретные шаги для решения проблем или улучшения состояния
3. АДАПТИРУЙТЕ ПОД УСЛОВИЯ - учтите сезон, условия содержания (дом), частоту полива

ФОРМАТ ОТВЕТА (2-4 абзаца БЕЗ нумерации и markdown):

Абзац 1: ОБЪЯСНЕНИЕ ПОЧЕМУ - диагноз ситуации на основе визуальных наблюдений
Абзац 2: ПЛАН ДЕЙСТВИЙ - конкретные шаги с параметрами (температура, частота, количество)
Абзац 3: АДАПТАЦИЯ - как адаптировать уход под текущий сезон и условия
Абзац 4 (при необходимости): КОНТРОЛЬ - когда ожидать результат

ОБЯЗАТЕЛЬНО учитывайте текущий сезон в рекомендациях по поливу и уходу!

ТИПИЧНЫЕ ИНТЕРВАЛЫ ПОЛИВА ДЛЯ ЗИМЫ:
- Суккуленты, кактусы: 21-28 дней
- Фикусы, монстеры: 12-16 дней  
- Спатифиллум, папоротники: 7-10 дней
- Драцены, юкки: 14-21 дней
- Пальмы: 12-16 дней

В САМОМ КОНЦЕ ответа ОБЯЗАТЕЛЬНО добавьте отдельной строкой:
ПОЛИВ_ИНТЕРВАЛ: [число от 3 до 28]

Это число - рекомендуемый интервал полива в днях с учётом вида растения и текущего сезона ({season_info['season_ru']})."""
        
        # Используем GPT-5.1 для reasoning (Chat Completions API)
        logger.info(f"🧠 Reasoning анализ: использую модель {GPT_5_1_MODEL}")
        response = await openai_client.chat.completions.create(
            model=GPT_5_1_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_completion_tokens=4000,  # GPT-5.1 тратит токены на reasoning + ответ
            extra_body={"reasoning_effort": "low"}
            # GPT-5.1 не поддерживает temperature
        )
        
        reasoning_text = response.choices[0].message.content
        
        if not reasoning_text or len(reasoning_text) < 50:
            raise Exception("Некачественный ответ от reasoning модели")
        
        # Извлекаем интервал полива и удаляем строку из текста
        watering_interval, clean_reasoning = extract_and_remove_watering_interval(reasoning_text, season_info)
        
        logger.info(f"✅ Reasoning анализ завершен (модель: {GPT_5_1_MODEL}, сезон: {season_info['season_ru']}, интервал: {watering_interval} дней)")
        
        # Формируем полный анализ для пользователя (без строки ПОЛИВ_ИНТЕРВАЛ)
        full_analysis = f"""🌱 <b>Растение:</b> {vision_result.get('plant_name', 'Неизвестное растение')}
📊 <b>Уверенность:</b> {vision_result.get('confidence', 50)}%

<b>Визуальный анализ:</b>
{vision_result.get('vision_analysis', '')}

<b>Рекомендации:</b>
{clean_reasoning}"""
        
        return {
            "success": True,
            "reasoning": clean_reasoning,
            "action_plan": clean_reasoning,  # План действий включен в reasoning
            "adapted_recommendations": clean_reasoning,  # Адаптированные рекомендации включены
            "full_analysis": full_analysis,
            "watering_interval": watering_interval
        }
        
    except Exception as e:
        logger.error(f"❌ Reasoning анализ ошибка: {e}", exc_info=True)
        # Fallback на более простую модель если gpt-5.1 недоступна
        try:
            logger.warning(f"🔄 {GPT_5_1_MODEL} недоступна, использую fallback модель GPT-4o для reasoning")
            response = await openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=800,
                temperature=0.3
            )
            
            reasoning_text = response.choices[0].message.content
            
            # Извлекаем интервал полива и удаляем строку из текста
            watering_interval, clean_reasoning = extract_and_remove_watering_interval(reasoning_text, season_info)
            
            logger.info(f"✅ Reasoning анализ завершен (модель: GPT-4o fallback, сезон: {season_info['season_ru']}, интервал: {watering_interval} дней)")
            
            full_analysis = f"""🌱 <b>Растение:</b> {vision_result.get('plant_name', 'Неизвестное растение')}
📊 <b>Уверенность:</b> {vision_result.get('confidence', 50)}%

<b>Визуальный анализ:</b>
{vision_result.get('vision_analysis', '')}

<b>Рекомендации:</b>
{clean_reasoning}"""
            
            return {
                "success": True,
                "reasoning": clean_reasoning,
                "action_plan": clean_reasoning,
                "adapted_recommendations": clean_reasoning,
                "full_analysis": full_analysis,
                "watering_interval": watering_interval
            }
        except Exception as fallback_error:
            logger.error(f"❌ Fallback reasoning ошибка: {fallback_error}")
            return {"success": False, "error": str(e)}


async def analyze_with_openai_advanced(image_data: bytes, user_question: str = None, previous_state: str = None) -> dict:
    """Продвинутый анализ с определением состояния через OpenAI"""
    if not openai_client:
        return {"success": False, "error": "OpenAI API недоступен"}
    
    try:
        # Получаем информацию о текущем сезоне
        season_data = get_current_season()
        
        # ИСПРАВЛЕНО: Формируем рекомендации по подкормке на основе сезона
        feeding_recommendations = {
            'winter': 'Прекратить подкормки или минимизировать до 1 раза в месяц половинной дозой',
            'spring': 'Начать подкормки с половинной дозы, постепенно увеличивая до полной каждые 2 недели',
            'summer': 'Регулярные подкормки каждые 1-2 недели полной дозой',
            'autumn': 'Постепенно сокращать подкормки, с октября прекратить для большинства видов'
        }
        
        # ИСПРАВЛЕНО: Вычисляем числовую корректировку полива
        water_adjustment_days = 0
        if season_data['season'] == 'winter':
            water_adjustment_days = +5  # Зимой поливать реже
        elif season_data['season'] == 'spring':
            water_adjustment_days = 0  # Весной базовый интервал
        elif season_data['season'] == 'summer':
            water_adjustment_days = -2  # Летом поливать чаще
        elif season_data['season'] == 'autumn':
            water_adjustment_days = +2  # Осенью начинать сокращать
        
        optimized_image = await optimize_image_for_analysis(image_data, high_quality=True)
        base64_image = base64.b64encode(optimized_image).decode('utf-8')
        
        # ИСПРАВЛЕНО: Форматируем промпт с правильными ключами
        prompt = PLANT_IDENTIFICATION_PROMPT.format(
            season_name=season_data['season_ru'],  # ✅ 'Зима'
            season_description=season_data['growth_phase'],  # ✅ 'Период покоя'
            season_water_note=season_data['watering_adjustment'],  # ✅ строка с описанием
            season_light_note=season_data['light_hours'],  # ✅ описание светового дня
            season_temperature_note=season_data['temperature_note'],  # ✅ рекомендации по температуре
            season_feeding_note=feeding_recommendations.get(season_data['season'], 'Стандартный режим'),  # ✅ рекомендации по подкормке
            season_water_adjustment=f"{water_adjustment_days:+d} дня к базовому интервалу"  # ✅ числовая корректировка
        )
        
        if previous_state:
            prompt += f"\n\nПредыдущее состояние растения: {previous_state}. Определите что изменилось с учетом сезонных факторов."
        
        if user_question:
            prompt += f"\n\nДополнительный вопрос пользователя: {user_question}"
        
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "Вы - профессиональный ботаник-диагност с 30-летним опытом. Проводите точную идентификацию и профессиональную оценку состояния растений. Все выводы обосновывайте наблюдаемыми признаками. ОБЯЗАТЕЛЬНО учитывайте сезонность при рекомендациях по поливу."
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ],
            max_tokens=1500,
            temperature=0.2
        )
        
        raw_analysis = response.choices[0].message.content
        
        if len(raw_analysis) < 100:
            raise Exception("Некачественный ответ")
        
        # Извлекаем уверенность
        confidence = 0
        for line in raw_analysis.split('\n'):
            if line.startswith("УВЕРЕННОСТЬ:"):
                try:
                    conf_str = line.replace("УВЕРЕННОСТЬ:", "").strip().replace("%", "")
                    confidence = float(conf_str)
                except:
                    confidence = 70
                break
        
        # Извлекаем название растения
        plant_name = "Неизвестное растение"
        import re
        for line in raw_analysis.split('\n'):
            if line.startswith("РАСТЕНИЕ:"):
                raw_name = line.replace("РАСТЕНИЕ:", "").strip()
                # Очищаем от "Неизвестное растение (возможно, X)" → "X"
                if "неизвестное растение" in raw_name.lower() and "(" in raw_name:
                    match = re.search(r'\((?:возможно,?\s*)?([^)]+)\)', raw_name, re.IGNORECASE)
                    if match:
                        plant_name = match.group(1).strip()
                    else:
                        plant_name = raw_name
                else:
                    plant_name = re.sub(r'\s*\(возможно[^)]*\)\s*', '', raw_name, flags=re.IGNORECASE).strip()
                    if not plant_name:
                        plant_name = raw_name
                break
        
        # Извлекаем состояние
        state_info = extract_plant_state_from_analysis(raw_analysis)
        
        # ИСПРАВЛЕНО: Применяем сезонную корректировку
        state_info['season_adjustment'] = water_adjustment_days
        
        formatted_analysis = format_plant_analysis(raw_analysis, confidence, state_info)
        
        logger.info(f"✅ Анализ завершен. Сезон: {season_data['season_ru']}, Состояние: {state_info['current_state']}, Уверенность: {confidence}%")
        
        return {
            "success": True,
            "analysis": formatted_analysis,
            "raw_analysis": raw_analysis,
            "plant_name": plant_name,
            "confidence": confidence,
            "source": "openai_advanced",
            "state_info": state_info,
            "season_data": season_data
        }
        
    except Exception as e:
        logger.error(f"❌ OpenAI error: {e}", exc_info=True)  # ИСПРАВЛЕНО: добавлен exc_info для полного стека
        return {"success": False, "error": str(e)}


async def analyze_plant_image(image_data: bytes, user_question: str = None, 
                             previous_state: str = None, retry_count: int = 0, plant_context: str = None) -> dict:
    """Анализ изображения растения - ДВУХЭТАПНЫЙ ПРОЦЕСС:
    Шаг 1: Vision (gpt-4o) - что видно, проблемы, уверенность
    Шаг 2: Reasoning (gpt-5.1) - объясняет почему, план действий, адаптация + интервал полива"""
    
    logger.info("🔍 Начало двухэтапного анализа: Vision → Reasoning")
    
    # ШАГ 1: Vision анализ через GPT-4o
    logger.info("📸 Шаг 1: Vision анализ (GPT-4o)...")
    vision_result = await analyze_vision_step(image_data, user_question, previous_state)
    
    if not vision_result["success"]:
        logger.error(f"❌ Vision анализ не удался: {vision_result.get('error')}")
        # Fallback на старый метод
        if retry_count == 0:
            logger.info("🔄 Fallback на старый метод анализа...")
            openai_result = await analyze_with_openai_advanced(image_data, user_question, previous_state)
            if openai_result["success"]:
                return openai_result
        return {"success": False, "error": vision_result.get("error", "Vision анализ не удался")}
    
    # ШАГ 2: Reasoning анализ через GPT-5.1 (включает извлечение интервала полива)
    logger.info(f"🧠 Шаг 2: Reasoning анализ ({GPT_5_1_MODEL})...")
    reasoning_result = await analyze_reasoning_step(vision_result, plant_context, user_question)
    
    if not reasoning_result["success"]:
        logger.error(f"❌ Reasoning анализ не удался: {reasoning_result.get('error')}")
        # Если reasoning не удался, возвращаем хотя бы vision результат
        return {
            "success": True,
            "analysis": f"🌱 <b>Растение:</b> {vision_result.get('plant_name', 'Неизвестное растение')}\n\n<b>Визуальный анализ:</b>\n{vision_result.get('vision_analysis', '')}\n\n<b>Возможные проблемы:</b>\n{vision_result.get('possible_problems', '')}",
            "raw_analysis": vision_result.get('raw_observations', ''),
            "plant_name": vision_result.get('plant_name', 'Неизвестное растение'),
            "confidence": vision_result.get('confidence', 50),
            "source": "vision_only",
            "state_info": extract_plant_state_from_analysis(vision_result.get('raw_observations', '')),
            "watering_interval": 10,  # Default для fallback
            "needs_retry": True
        }
    
    # Получаем интервал из reasoning результата
    watering_interval = reasoning_result.get('watering_interval', 10)
    plant_name = vision_result.get('plant_name', 'Неизвестное растение')
    
    logger.info(f"✅ Двухэтапный анализ завершен (уверенность: {vision_result.get('confidence', 50)}%, интервал: {watering_interval} дней)")
    
    # Извлекаем состояние из vision анализа
    state_info = extract_plant_state_from_analysis(vision_result.get('raw_observations', ''))
    
    # Добавляем интервал в raw_analysis для совместимости с extract_watering_info
    raw_analysis_with_interval = f"ПОЛИВ_ИНТЕРВАЛ: {watering_interval}\n" + vision_result.get('raw_observations', '')
    
    return {
        "success": True,
        "analysis": reasoning_result.get("full_analysis", reasoning_result.get("reasoning", "")),
        "raw_analysis": raw_analysis_with_interval,
        "plant_name": plant_name,
        "confidence": vision_result.get('confidence', 50),
        "source": "two_stage_analysis",
        "state_info": state_info,
        "vision_result": vision_result,
        "reasoning_result": reasoning_result,
        "watering_interval": watering_interval,
        "needs_retry": vision_result.get('confidence', 50) < 50
    }


async def answer_plant_question(question: str, plant_context: str = None) -> dict:
    """Ответить на вопрос о растении с контекстом
    
    Returns:
        dict: {"answer": str, "model": str} или {"error": str} в случае ошибки
    """
    if not openai_client:
        return {"error": "❌ OpenAI API недоступен"}
    
    try:
        # Получаем информацию о сезоне
        season_info = get_current_season()
        
        seasonal_context = f"""
ТЕКУЩИЙ СЕЗОН: {season_info['season_ru']} ({season_info['month_name_ru']})
ФАЗА РОСТА: {season_info['growth_phase']}
СВЕТОВОЙ ДЕНЬ: {season_info['light_hours']}
КОРРЕКТИРОВКА ПОЛИВА: {season_info['watering_adjustment']}

СЕЗОННЫЕ ОСОБЕННОСТИ:
{season_info['recommendations']}
"""
        
        system_prompt = """Вы - опытный ботаник-консультант. Отвечайте на вопросы пользователя естественно и по существу.

ПРАВИЛА:
- Отвечайте именно на тот вопрос, который задан. Не навязывайте лишнюю информацию.
- Пишите свободно, как в живом разговоре с экспертом — без жёсткой структуры и шаблонов.
- Если вопрос простой — дайте короткий ответ (3-5 предложений).
- Если вопрос сложный или требует пошаговых действий — можете структурировать, но только когда это действительно нужно.
- Давайте конкретные цифры где уместно: температура, мл воды, дни между поливами.
- Учитывайте текущий сезон при рекомендациях по уходу.
- Если есть история растения — опирайтесь на неё.
- Обращение на «вы».
- Используйте HTML-теги <b></b> для выделения, если нужно. НЕ используйте markdown (**, *, _).
- НЕ начинайте ответ с шаблонных заголовков типа «Диагноз», «Причины», «Что делать». Просто отвечайте на вопрос."""

        user_prompt = question
        
        if plant_context:
            user_prompt = f"ИСТОРИЯ РАСТЕНИЯ:\n{plant_context}\n\n{seasonal_context}\n\nВОПРОС:\n{question}"
        else:
            user_prompt = f"{seasonal_context}\n\nВОПРОС:\n{question}"
        
        # Пробуем сначала gpt-5.1, если не получается - fallback на gpt-4o
        models_to_try = [GPT_5_1_MODEL, "gpt-4o"]
        last_error = None
        
        for model_name in models_to_try:
            try:
                logger.info(f"🔄 Пробую модель: {model_name}")
                
                # GPT-5.1 использует max_completion_tokens, остальные модели - max_tokens
                api_params = {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ]
                }
                
                if model_name == GPT_5_1_MODEL:
                    api_params["max_completion_tokens"] = 4000
                    api_params["extra_body"] = {"reasoning_effort": "low"}
                else:
                    api_params["max_tokens"] = 1000
                    api_params["temperature"] = 0.4
                
                response = await openai_client.chat.completions.create(**api_params)
                
                answer = response.choices[0].message.content
                
                if answer and len(answer) > 10:
                    logger.info(f"✅ OpenAI ответил с контекстом (модель: {model_name}, сезон: {season_info['season_ru']})")
                    return {"answer": answer, "model": model_name}
                else:
                    logger.warning(f"⚠️ Модель {model_name} вернула пустой ответ")
                    
            except Exception as model_error:
                last_error = model_error
                logger.warning(f"⚠️ Ошибка с моделью {model_name}: {model_error}")
                if model_name == models_to_try[-1]:
                    # Это была последняя модель, пробрасываем ошибку
                    raise
                # Пробуем следующую модель
                continue
        
        # Если дошли сюда, значит все модели вернули пустой ответ
        raise Exception("Все модели вернули пустой ответ")
        
    except Exception as e:
        logger.error(f"❌ Ошибка ответа на вопрос: {e}", exc_info=True)
        logger.error(f"❌ Тип ошибки: {type(e).__name__}")
        if hasattr(e, 'response'):
            logger.error(f"❌ Response: {e.response}")
        if hasattr(e, 'status_code'):
            logger.error(f"❌ Status code: {e.status_code}")
        return {"error": "❌ Не могу дать ответ. Попробуйте переформулировать вопрос."}


async def generate_growing_plan(plant_name: str) -> tuple:
    """Генерация плана выращивания через OpenAI"""
    if not openai_client:
        return None, None
    
    try:
        # Получаем информацию о сезоне
        season_info = get_current_season()
        
        prompt = f"""
Составьте профессиональный агротехнический план выращивания для: {plant_name}

ТЕКУЩИЙ СЕЗОН: {season_info['season_ru']} ({season_info['month_name_ru']})
УЧИТЫВАЙТЕ: {season_info['recommendations']}

Требования к плану:
- Научно обоснованные рекомендации с учетом текущего сезона
- Конкретные сроки и параметры
- Учет критических факторов успеха
- Превентивные меры против типичных проблем
- Адаптация под {season_info['season_ru'].lower()}

Формат ответа:

🌱 ЭТАП 1: Название (продолжительность X дней)
• Конкретная агротехническая задача с параметрами
• Следующая задача с обоснованием
• Критические факторы этапа

🌿 ЭТАП 2: Название (продолжительность X дней)
• Задача с точными параметрами
• Контрольные признаки успеха

🌸 ЭТАП 3: Название (продолжительность X дней)
• Задачи с учетом развития растения
• Корректировки ухода

🌳 ЭТАП 4: Название (продолжительность X дней)
• Финальные агротехнические мероприятия
• Критерии готовности растения

В конце добавьте:
КАЛЕНДАРЬ_ЗАДАЧ: [структурированный JSON с задачами по дням]
"""
        
        logger.info(f"📋 Генерация плана выращивания: использую модель {GPT_5_1_MODEL}")
        response = await openai_client.chat.completions.create(
            model=GPT_5_1_MODEL,
            messages=[
                {
                    "role": "system", 
                    "content": f"Вы - агроном-консультант с опытом выращивания широкого спектра растений. Составляйте практичные, научно обоснованные планы. Учитывайте, что сейчас {season_info['season_ru']} - {season_info['growth_phase'].lower()}."
                },
                {"role": "user", "content": prompt}
            ],
            max_completion_tokens=5000,  # GPT-5.1 тратит токены на reasoning + ответ
            extra_body={"reasoning_effort": "low"}
            # GPT-5.1 не поддерживает temperature
        )
        
        plan_text = response.choices[0].message.content
        logger.info(f"✅ План выращивания сгенерирован (модель: {GPT_5_1_MODEL})")
        
        # Создаем календарь задач (упрощенная версия)
        task_calendar = {
            "stage_1": {
                "name": "Подготовка и посадка",
                "duration_days": 7,
                "tasks": [
                    {"day": 1, "title": "Посадка", "description": "Посадите семена/черенок", "icon": "🌱"},
                    {"day": 3, "title": "Первый полив", "description": "Умеренно полейте", "icon": "💧"},
                    {"day": 7, "title": "Проверка", "description": "Проверьте влажность", "icon": "🔍"},
                ]
            },
            "stage_2": {
                "name": "Прорастание",
                "duration_days": 14,
                "tasks": [
                    {"day": 10, "title": "Первые всходы", "description": "Проверьте появление ростков", "icon": "🌱"},
                    {"day": 14, "title": "Регулярный полив", "description": "Поддерживайте влажность", "icon": "💧"},
                ]
            },
            "stage_3": {
                "name": "Активный рост",
                "duration_days": 30,
                "tasks": [
                    {"day": 21, "title": "Первая подкормка", "description": "Внесите удобрение", "icon": "🍽️"},
                    {"day": 35, "title": "Проверка роста", "description": "Оцените развитие растения", "icon": "📊"},
                ]
            },
            "stage_4": {
                "name": "Взрослое растение",
                "duration_days": 30,
                "tasks": [
                    {"day": 50, "title": "Пересадка", "description": "Пересадите в больший горшок", "icon": "🪴"},
                    {"day": 60, "title": "Формирование", "description": "При необходимости обрежьте", "icon": "✂️"},
                ]
            }
        }
        
        return plan_text, task_calendar
        
    except Exception as e:
        logger.error(f"Ошибка генерации плана: {e}")
        # Fallback на GPT-4o
        try:
            logger.warning(f"🔄 {GPT_5_1_MODEL} недоступна для генерации плана, использую GPT-4o")
            response = await openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system", 
                        "content": f"Вы - агроном-консультант с опытом выращивания широкого спектра растений. Составляйте практичные, научно обоснованные планы. Учитывайте, что сейчас {season_info['season_ru']} - {season_info['growth_phase'].lower()}."
                    },
                    {"role": "user", "content": prompt}
                ],
                max_tokens=1200,
                temperature=0.2
            )
            
            plan_text = response.choices[0].message.content
            logger.info("✅ План выращивания сгенерирован (модель: GPT-4o fallback)")
            
            # Тот же календарь задач
            task_calendar = {
                "stage_1": {
                    "name": "Подготовка и посадка",
                    "duration_days": 7,
                    "tasks": [
                        {"day": 1, "title": "Посадка", "description": "Посадите семена/черенок", "icon": "🌱"},
                        {"day": 3, "title": "Первый полив", "description": "Умеренно полейте", "icon": "💧"},
                        {"day": 7, "title": "Проверка", "description": "Проверьте влажность", "icon": "🔍"},
                    ]
                },
                "stage_2": {
                    "name": "Прорастание",
                    "duration_days": 14,
                    "tasks": [
                        {"day": 10, "title": "Первые всходы", "description": "Проверьте появление ростков", "icon": "🌱"},
                        {"day": 14, "title": "Регулярный полив", "description": "Поддерживайте влажность", "icon": "💧"},
                    ]
                },
                "stage_3": {
                    "name": "Активный рост",
                    "duration_days": 30,
                    "tasks": [
                        {"day": 21, "title": "Первая подкормка", "description": "Внесите удобрение", "icon": "🍽️"},
                        {"day": 35, "title": "Проверка роста", "description": "Оцените развитие растения", "icon": "📊"},
                    ]
                },
                "stage_4": {
                    "name": "Взрослое растение",
                    "duration_days": 30,
                    "tasks": [
                        {"day": 50, "title": "Пересадка", "description": "Пересадите в больший горшок", "icon": "🪴"},
                        {"day": 60, "title": "Формирование", "description": "При необходимости обрежьте", "icon": "✂️"},
                    ]
                }
            }
            
            return plan_text, task_calendar
            
        except Exception as fallback_error:
            logger.error(f"❌ Fallback генерации плана ошибка: {fallback_error}")
            return None, None
