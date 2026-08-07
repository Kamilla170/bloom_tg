"""
Сервис сезонной корректировки интервалов полива
Запускается 1 числа каждого месяца, спрашивает GPT о новых интервалах
"""

import logging
from openai import AsyncOpenAI

from database import get_db
from config import OPENAI_API_KEY
from utils.season_utils import get_current_season

logger = logging.getLogger(__name__)

# Инициализация OpenAI клиента
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


async def get_seasonal_watering_interval(plant_name: str, current_interval: int, season_info: dict) -> int:
    """
    Спросить GPT какой интервал полива нужен для растения в текущем сезоне
    
    Args:
        plant_name: название растения
        current_interval: текущий интервал полива
        season_info: информация о текущем сезоне
        
    Returns:
        int: новый интервал полива в днях
    """
    if not openai_client:
        logger.warning("⚠️ OpenAI недоступен, оставляем текущий интервал")
        return current_interval
    
    try:
        prompt = f"""Ты - эксперт по комнатным растениям. 

Растение: {plant_name}
Текущий интервал полива: {current_interval} дней
Сейчас: {season_info['month_name_ru']} ({season_info['season_ru']})

Учитывая особенности этого вида растения и текущий сезон, какой должен быть интервал полива?

ВАЖНЫЕ ПРАВИЛА:
- Зимой (декабрь-февраль): большинство растений поливают в 1.5-2.5 раза РЕЖЕ
- Весной (март-май): постепенно увеличиваем полив, интервал как летом или чуть реже
- Летом (июнь-август): максимальная частота полива (самый короткий интервал)
- Осенью (сентябрь-ноябрь): постепенно сокращаем полив

ОСОБЕННОСТИ ВИДОВ:
- Суккуленты и кактусы зимой почти не поливают (21-28 дней)
- Тропические растения (фикусы, монстеры) зимой 10-14 дней
- Цветущие растения требуют больше воды даже зимой
- Папоротники и влаголюбивые - чаще других, но зимой тоже реже

Ответь ТОЛЬКО ОДНИМ ЧИСЛОМ - количество дней между поливами.
Число должно быть от 3 до 28."""

        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",  # Используем дешёвую модель для простых запросов
            messages=[
                {"role": "system", "content": "Ты эксперт по уходу за комнатными растениями. Отвечай только числом - количеством дней между поливами."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=10,
            temperature=0.3
        )
        
        answer = response.choices[0].message.content.strip()
        
        # Извлекаем число из ответа
        import re
        numbers = re.findall(r'\d+', answer)
        if numbers:
            interval = int(numbers[0])
            # Валидация
            interval = max(3, min(28, interval))
            logger.info(f"✅ GPT: {plant_name} → {interval} дней ({season_info['season_ru']})")
            return interval
        else:
            logger.warning(f"⚠️ GPT не вернул число для {plant_name}: '{answer}', оставляем {current_interval}")
            return current_interval
            
    except Exception as e:
        logger.error(f"❌ Ошибка GPT для {plant_name}: {e}")
        return current_interval


async def adjust_all_plants_for_season():
    """
    Главная функция: пересчитать интервалы полива для всех растений через GPT
    Запускается 1 числа каждого месяца
    """
    try:
        logger.info("=" * 60)
        logger.info("🌍 СЕЗОННАЯ КОРРЕКТИРОВКА ИНТЕРВАЛОВ ПОЛИВА (GPT)")
        logger.info("=" * 60)
        
        season_info = get_current_season()
        logger.info(f"📅 Месяц: {season_info['month_name_ru']}")
        logger.info(f"🌍 Сезон: {season_info['season_ru']}")
        logger.info(f"🌱 Фаза: {season_info['growth_phase']}")
        
        db = await get_db()
        
        # Получаем все растения для корректировки
        plants = await db.get_all_plants_for_seasonal_update()
        
        logger.info(f"📊 Найдено растений для обработки: {len(plants)}")
        
        if not plants:
            logger.info("✅ Нет растений для корректировки")
            return
        
        updated_count = 0
        error_count = 0
        skipped_count = 0
        
        # Группируем по пользователям для логирования
        current_user_id = None
        
        for plant in plants:
            try:
                plant_id = plant['id']
                user_id = plant['user_id']
                plant_name = plant['plant_name'] or plant['display_name']
                current_interval = plant['current_interval'] or 7
                
                # Логируем смену пользователя
                if user_id != current_user_id:
                    current_user_id = user_id
                    logger.info(f"👤 Пользователь {user_id}:")
                
                # Пропускаем только если plant_name пустое или NULL
                # Название сохраняется при анализе фото, если уверенность была достаточной
                if not plant_name or not plant_name.strip():
                    logger.info(f"   ⏭️ {plant['display_name']}: пропущено (нет названия вида)")
                    skipped_count += 1
                    continue
                
                # Получаем новый интервал от GPT
                new_interval = await get_seasonal_watering_interval(
                    plant_name, 
                    current_interval, 
                    season_info
                )
                
                # Обновляем только если изменился
                if new_interval != current_interval:
                    async with db.pool.acquire() as conn:
                        await conn.execute("""
                            UPDATE plants 
                            SET watering_interval = $1
                            WHERE id = $2
                        """, new_interval, plant_id)
                    
                    # Пересоздаём напоминание с новым интервалом
                    from services.reminder_service import create_plant_reminder
                    await create_plant_reminder(plant_id, user_id, new_interval)
                    
                    logger.info(f"   🌱 {plant['display_name']}: {current_interval} → {new_interval} дней")
                    updated_count += 1
                else:
                    logger.info(f"   🌱 {plant['display_name']}: без изменений ({current_interval} дней)")
                    
            except Exception as e:
                error_count += 1
                logger.error(f"   ❌ Ошибка для растения {plant.get('id')}: {e}")
        
        logger.info("=" * 60)
        logger.info("✅ КОРРЕКТИРОВКА ЗАВЕРШЕНА")
        logger.info(f"📊 Обновлено: {updated_count}")
        logger.info(f"⏭️ Пропущено: {skipped_count}")
        if error_count:
            logger.info(f"❌ Ошибок: {error_count}")
        logger.info("=" * 60)
            
    except Exception as e:
        logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА сезонной корректировки: {e}", exc_info=True)


async def migrate_base_intervals():
    """
    Миграция: убеждаемся что колонка base_watering_interval существует
    Теперь base_watering_interval = текущий интервал (GPT сам корректирует)
    """
    try:
        logger.info("🔄 Проверка структуры таблицы plants...")
        
        db = await get_db()
        
        async with db.pool.acquire() as conn:
            # Добавляем колонку если её нет
            await conn.execute("""
                ALTER TABLE plants 
                ADD COLUMN IF NOT EXISTS base_watering_interval INTEGER
            """)
            
            # Заполняем base_watering_interval из watering_interval где NULL
            await conn.execute("""
                UPDATE plants
                SET base_watering_interval = watering_interval
                WHERE base_watering_interval IS NULL
                  AND watering_interval IS NOT NULL
            """)
            
            logger.info("✅ Миграция base_watering_interval завершена")
            
    except Exception as e:
        logger.error(f"❌ Ошибка миграции: {e}", exc_info=True)


async def force_seasonal_update_for_plant(plant_id: int, user_id: int) -> dict:
    """
    Принудительно обновить интервал полива для одного растения
    Можно вызвать вручную через админку или команду
    """
    try:
        db = await get_db()
        plant = await db.get_plant_by_id(plant_id, user_id)
        
        if not plant:
            return {"success": False, "error": "Растение не найдено"}
        
        plant_name = plant.get('plant_name') or plant.get('display_name')
        current_interval = plant.get('watering_interval', 7)
        
        if not plant_name or not plant_name.strip():
            return {"success": False, "error": "Не указано название вида растения. Обновите фото для идентификации."}
        
        season_info = get_current_season()
        
        new_interval = await get_seasonal_watering_interval(
            plant_name,
            current_interval,
            season_info
        )
        
        if new_interval != current_interval:
            async with db.pool.acquire() as conn:
                await conn.execute("""
                    UPDATE plants 
                    SET watering_interval = $1
                    WHERE id = $2
                """, new_interval, plant_id)
            
            from services.reminder_service import create_plant_reminder
            await create_plant_reminder(plant_id, user_id, new_interval)
        
        return {
            "success": True,
            "plant_name": plant_name,
            "old_interval": current_interval,
            "new_interval": new_interval,
            "season": season_info['season_ru'],
            "changed": new_interval != current_interval
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка обновления растения {plant_id}: {e}")
        return {"success": False, "error": str(e)}
