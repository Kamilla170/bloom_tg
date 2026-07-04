import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext

from states.user_states import PlantStates
from database import get_db

logger = logging.getLogger(__name__)

router = Router()


async def start_onboarding(message: types.Message):
    """Онбординг для новых пользователей — одно сообщение, сразу в действие"""
    first_name = message.from_user.first_name or "друг"

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    keyboard = [
        [InlineKeyboardButton(
            text="📸 Да, анализируем моё растение!",
            callback_data="onboarding_analyze"
        )],
    ]

    await message.answer(
        f"👋 Привет, {first_name}!\n"
        f"Я — Блум, твой ИИ-ассистент по растениям.\n\n"
        f"🌱 Что я умею:\n"
        f"• Определяю вид растения по фото и оцениваю его состояние за пару секунд\n"
        f"• Помогу по всем вопросам и дам персональные рекомендации об уходе\n"
        f"• Научу правильно ухаживать за растениями: буду напоминать о поливах и подкормках\n\n"
        f"💡 Попробуем прямо сейчас?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


@router.callback_query(F.data == "onboarding_analyze")
async def onboarding_analyze_callback(callback: types.CallbackQuery):
    """Пользователь нажал кнопку анализа из онбординга"""
    await mark_onboarding_completed(callback.from_user.id)

    await callback.message.answer(
        "📸 <b>Отлично! Пришлите фото вашего растения</b>\n\n"
        "💡 <b>Советы для лучшего результата:</b>\n"
        "• Фотографируйте при дневном свете\n"
        "• Покажите листья и общий вид растения\n"
        "• Включите почву в кадр, если возможно",
        parse_mode="HTML"
    )
    await callback.answer()


async def mark_onboarding_completed(user_id: int):
    """Отметить онбординг завершенным"""
    try:
        db = await get_db()
        async with db.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET onboarding_completed = TRUE WHERE user_id = $1",
                user_id
            )
        logger.info(f"✅ Онбординг завершен для пользователя {user_id}")

        # Запускаем триггерную цепочку для тех, кто не добавит растение
        from services.trigger_service import start_chain
        await start_chain(user_id, 'onboarding_no_plant')

    except Exception as e:
        logger.error(f"Ошибка онбординга: {e}")


# === КОНТЕКСТНЫЕ ПОДСКАЗКИ (onboarding tips) ===

async def send_tip_if_needed(user_id: int, tip_type: str, send_func) -> bool:
    """
    Проверяет, нужно ли показать подсказку, и если да — отправляет.

    Args:
        user_id: ID пользователя
        tip_type: 'analysis' | 'save' | 'watering'
        send_func: async callable, которая отправляет сообщение

    Returns:
        True если подсказка была отправлена
    """
    column_map = {
        'analysis': 'tip_analysis_shown',
        'save': 'tip_save_shown',
        'watering': 'tip_watering_shown',
    }

    column = column_map.get(tip_type)
    if not column:
        return False

    try:
        db = await get_db()
        async with db.pool.acquire() as conn:
            # Проверяем флаг
            shown = await conn.fetchval(
                f"SELECT {column} FROM users WHERE user_id = $1",
                user_id
            )

            if shown:
                return False

            # Ставим флаг ДО отправки (чтобы не дублировать при ошибках)
            await conn.execute(
                f"UPDATE users SET {column} = TRUE WHERE user_id = $1",
                user_id
            )

        # Отправляем подсказку с задержкой, чтобы пользователь успел прочитать
        import asyncio
        await asyncio.sleep(3)
        await send_func()
        logger.info(f"💡 Подсказка '{tip_type}' отправлена пользователю {user_id}")
        return True

    except Exception as e:
        logger.error(f"Ошибка отправки подсказки '{tip_type}': {e}")
        return False


# Тексты подсказок
TIP_AFTER_ANALYSIS = (
    "💾 <b>Сохраните растение!</b>\n\n"
    "Нажмите «Добавить в коллекцию» — и я настрою напоминания о поливе "
    "и буду следить за состоянием вашего растения."
)

TIP_AFTER_SAVE = (
    "📊 В разделе «Мои растения» ты найдёшь всё о каждом растении — "
    "поливы, состояние, историю анализов. А в разделе «Статистика» "
    "можно увидеть полную статистику использования бота."
)

TIP_AFTER_WATERING = (
    "🌿 Отлично, первый полив записан! Я буду напоминать, когда придёт "
    "время следующего. А ещё я слежу за сезоном и автоматически корректирую "
    "частоту полива, чтобы твоим растениям было комфортно."
)
