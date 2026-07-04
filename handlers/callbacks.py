import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext

from keyboards.main_menu import main_menu, simple_back_menu
from states.user_states import PlantStates, FeedbackStates
from database import get_db

logger = logging.getLogger(__name__)

router = Router()


@router.callback_query(F.data == "menu")
async def menu_callback(callback: types.CallbackQuery, state: FSMContext):
    """Главное меню"""
    await state.clear()
    await callback.message.answer("🌱 <b>Главное меню</b>", parse_mode="HTML", reply_markup=main_menu())
    await callback.answer()


@router.callback_query(F.data == "add_plant")
async def add_plant_callback(callback: types.CallbackQuery):
    """Добавить растение"""
    await callback.message.answer("📸 <b>Пришлите фото растения</b>", parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "analyze")
async def analyze_callback(callback: types.CallbackQuery):
    """Анализ растения"""
    await callback.message.answer("📸 <b>Пришлите фото для анализа</b>", parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "reanalyze")
async def reanalyze_callback(callback: types.CallbackQuery):
    """Повторный анализ"""
    await callback.message.answer("📸 <b>Пришлите новое фото</b>", parse_mode="HTML")
    await callback.answer()


# Обработчик "question" перенесён в handlers/questions.py


@router.callback_query(F.data == "ask_about")
async def ask_about_callback(callback: types.CallbackQuery, state: FSMContext):
    """Вопрос о текущем растении (legacy - для обратной совместимости)"""
    # Перенаправляем в новый режим вопросов
    from handlers.questions import start_question_mode_callback
    await start_question_mode_callback(callback, state)


@router.callback_query(F.data == "help")
async def help_callback(callback: types.CallbackQuery):
    """Справка"""
    from handlers.commands import help_command
    await help_command(callback.message)
    await callback.answer()


@router.callback_query(F.data == "stats")
async def stats_callback(callback: types.CallbackQuery):
    """Статистика"""
    # ВАЖНО: берём user_id из callback, а не из message (message.from_user - это бот!)
    user_id = callback.from_user.id
    
    try:
        from database import get_db
        from keyboards.main_menu import main_menu
        from datetime import datetime
        import logging
        
        logger = logging.getLogger(__name__)
        logger.info(f"📊 Запрос статистики (callback) от user_id={user_id}")
        
        db = await get_db()
        stats = await db.get_user_stats(user_id)
        
        logger.info(f"📊 Статистика для user_id={user_id}: plants={stats['total_plants']}, waterings={stats['total_waterings']}")
        
        stats_text = f"📊 <b>Ваша статистика</b>\n\n"
        stats_text += f"🌱 <b>Растений:</b> {stats['total_plants']}\n"
        stats_text += f"💧 <b>Поливов:</b> {stats['total_waterings']}\n"
        
        if stats['total_growing'] > 0:
            stats_text += f"\n🌿 <b>Выращивание:</b>\n"
            stats_text += f"• Активных: {stats['active_growing']}\n"
            stats_text += f"• Завершенных: {stats['completed_growing']}\n"
        
        if stats['first_plant_date']:
            days_using = (datetime.now().date() - stats['first_plant_date'].date()).days
            stats_text += f"\n📅 <b>Используете бота:</b> {days_using} дней\n"
        
        stats_text += f"\n🎯 <b>Продолжайте ухаживать за растениями!</b>"
        
        await callback.message.answer(
            stats_text,
            parse_mode="HTML",
            reply_markup=main_menu()
        )
        
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"❌ Ошибка статистики: {e}", exc_info=True)
        await callback.message.answer("❌ Ошибка загрузки статистики")
    
    await callback.answer()


@router.callback_query(F.data == "my_plants")
async def my_plants_callback(callback: types.CallbackQuery):
    """Моя коллекция"""
    from handlers.plants import show_plants_collection
    await show_plants_collection(callback)


@router.callback_query(F.data == "save_plant")
async def save_plant_callback(callback: types.CallbackQuery, state: FSMContext):
    """Сохранить проанализированное растение - теперь с выбором даты полива"""
    from handlers.plants import save_plant_handler
    await save_plant_handler(callback, state)


@router.callback_query(F.data == "toggle_reminders")
async def toggle_reminders_callback(callback: types.CallbackQuery):
    """Переключить напоминания"""
    try:
        user_id = callback.from_user.id
        db = await get_db()
        
        async with db.pool.acquire() as conn:
            current = await conn.fetchrow("""
                SELECT reminder_enabled FROM user_settings WHERE user_id = $1
            """, user_id)
            
            if current:
                new_status = not current['reminder_enabled']
            else:
                new_status = False
            
            await conn.execute("""
                UPDATE user_settings
                SET reminder_enabled = $1
                WHERE user_id = $2
            """, new_status, user_id)
        
        status_text = "✅ включены" if new_status else "❌ выключены"
        
        await callback.message.answer(
            f"🔔 <b>Напоминания {status_text}</b>\n\n"
            f"Используйте /notifications для управления настройками",
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка переключения: {e}")
        await callback.answer("❌ Ошибка")
    
    await callback.answer()


@router.callback_query(F.data == "disable_monthly_reminders")
async def disable_monthly_reminders_callback(callback: types.CallbackQuery):
    """Отключить месячные напоминания"""
    try:
        user_id = callback.from_user.id
        db = await get_db()
        
        async with db.pool.acquire() as conn:
            await conn.execute("""
                UPDATE user_settings
                SET monthly_photo_reminder = FALSE
                WHERE user_id = $1
            """, user_id)
        
        await callback.message.answer(
            "🔕 <b>Месячные напоминания об обновлении фото отключены</b>\n\n"
            "Вы можете включить их обратно в настройках.",
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка отключения напоминаний: {e}")
    
    await callback.answer()


@router.callback_query(F.data == "snooze_monthly_reminder")
async def snooze_monthly_reminder_callback(callback: types.CallbackQuery):
    """Отложить месячное напоминание"""
    try:
        from datetime import datetime, timedelta
        
        user_id = callback.from_user.id
        db = await get_db()
        
        week_ago = datetime.now() - timedelta(days=23)
        
        async with db.pool.acquire() as conn:
            await conn.execute("""
                UPDATE user_settings
                SET last_monthly_reminder = $1
                WHERE user_id = $2
            """, week_ago, user_id)
        
        await callback.message.answer(
            "⏰ <b>Напомню через неделю!</b>\n\n"
            "Тогда еще раз предложу обновить фото растений.",
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка отложения напоминания: {e}")
    
    await callback.answer()


@router.callback_query(F.data == "feedback")
async def feedback_callback(callback: types.CallbackQuery, state: FSMContext):
    """Обратная связь - упрощённая версия"""
    from handlers.feedback import show_feedback_prompt
    await state.set_state(FeedbackStates.writing_message)
    await show_feedback_prompt(callback)
    await callback.answer()
