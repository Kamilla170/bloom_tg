import logging
from io import BytesIO
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter

from states.user_states import PlantStates
from services.ai_service import analyze_plant_image
from services.plant_service import temp_analyses, update_plant_state_from_photo
from services.subscription_service import check_limit, increment_usage
from keyboards.plant_menu import plant_analysis_actions
from utils.formatters import get_state_recommendations
from utils.time_utils import get_moscow_now
from config import STATE_EMOJI, STATE_NAMES

logger = logging.getLogger(__name__)

router = Router()


@router.message(StateFilter(PlantStates.waiting_state_update_photo), F.photo)
async def handle_state_update_photo(message: types.Message, state: FSMContext, bot):
    """Обработка фото для обновления состояния"""
    try:
        data = await state.get_data()
        plant_id = data.get('state_plant_id')
        user_id = message.from_user.id
        
        if not plant_id:
            await message.reply("❌ Ошибка: данные потеряны")
            await state.clear()
            return
        
        # Проверка лимита анализов
        allowed, error_msg = await check_limit(user_id, 'analyses')
        if not allowed:
            from handlers.subscription import send_limit_message
            await send_limit_message(message, error_msg)
            await state.clear()
            return
        
        processing_msg = await message.reply(
            "🔍 <b>Анализирую изменения...</b>\n\n"
            "• Сравниваю с предыдущим фото\n"
            "• Определяю текущее состояние\n"
            "• Готовлю рекомендации...",
            parse_mode="HTML"
        )
        
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        
        # ИСПРАВЛЕНО: правильная обработка bot.download()
        image_data = await bot.download(file)
        
        # Конвертируем в bytes если получили BytesIO
        if isinstance(image_data, BytesIO):
            image_bytes = image_data.getvalue()
        else:
            image_bytes = image_data
        
        from database import get_db
        db = await get_db()
        plant = await db.get_plant_by_id(plant_id, user_id)
        
        if not plant:
            await processing_msg.delete()
            await message.reply("❌ Растение не найдено")
            await state.clear()
            return
        
        previous_state = plant.get('current_state', 'healthy')
        plant_name = plant['display_name']
        
        result = await analyze_plant_image(
            image_bytes,
            previous_state=previous_state
        )
        
        await processing_msg.delete()
        
        if result["success"]:
            # Увеличиваем счётчик использования
            await increment_usage(user_id, 'analyses')
            
            state_info = result.get("state_info", {})
            
            update_result = await update_plant_state_from_photo(
                plant_id, user_id, photo.file_id, state_info, result.get("raw_analysis", "")
            )
            
            if not update_result["success"]:
                await message.reply(f"❌ {update_result['error']}")
                await state.clear()
                return
            
            response_text = f"📊 <b>Состояние обновлено!</b>\n\n{result['analysis']}"
            
            if update_result["state_changed"]:
                prev_emoji = STATE_EMOJI.get(previous_state, '🌱')
                new_emoji = STATE_EMOJI.get(update_result["new_state"], '🌱')
                prev_name = STATE_NAMES.get(previous_state, 'Здоровое')
                new_name = STATE_NAMES.get(update_result["new_state"], 'Здоровое')
                
                response_text += f"\n\n🔄 <b>ИЗМЕНЕНИЕ СОСТОЯНИЯ!</b>\n"
                response_text += f"{prev_emoji} {prev_name} → {new_emoji} {new_name}\n\n"
                
                recommendations = get_state_recommendations(update_result["new_state"], plant_name)
                response_text += f"\n{recommendations}"
            
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
            keyboard = [
                [InlineKeyboardButton(text="📊 История изменений", callback_data=f"view_state_history_{plant_id}")],
                [InlineKeyboardButton(text="🌿 К растению", callback_data=f"edit_plant_{plant_id}")],
            ]
            
            await message.reply(
                response_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
            
            await state.clear()
        else:
            await message.reply("❌ Ошибка анализа. Попробуйте другое фото.")
            await state.clear()
            
    except Exception as e:
        logger.error(f"Ошибка обновления состояния: {e}", exc_info=True)
        await message.reply("❌ Техническая ошибка")
        await state.clear()


@router.message(F.photo)
async def handle_photo(message: types.Message, bot):
    """Обработка фотографий - ГЛАВНЫЙ АНАЛИЗ"""
    try:
        user_id = message.from_user.id
        
        # Проверка лимита анализов
        allowed, error_msg = await check_limit(user_id, 'analyses')
        if not allowed:
            from handlers.subscription import send_limit_message
            await send_limit_message(message, error_msg)
            return
        
        processing_msg = await message.reply(
            "🔍 <b>Анализирую растение...</b>\n\n"
            "• Определяю вид\n"
            "• Анализирую состояние\n"
            "• Готовлю рекомендации...",
            parse_mode="HTML"
        )
        
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        
        # ИСПРАВЛЕНО: правильная обработка bot.download()
        # В aiogram 3.x может вернуть BytesIO или bytes в зависимости от версии
        image_data = await bot.download(file)
        
        # Конвертируем в bytes если получили BytesIO
        if isinstance(image_data, BytesIO):
            image_bytes = image_data.getvalue()
        else:
            image_bytes = image_data
        
        user_question = message.caption if message.caption else None
        
        result = await analyze_plant_image(image_bytes, user_question)
        
        await processing_msg.delete()
        
        if result["success"]:
            # Увеличиваем счётчик использования
            await increment_usage(user_id, 'analyses')
            
            temp_analyses[user_id] = {
                "analysis": result.get("raw_analysis", result["analysis"]),
                "formatted_analysis": result["analysis"],
                "photo_file_id": photo.file_id,
                "date": get_moscow_now(),
                "source": result.get("source", "unknown"),
                "plant_name": result.get("plant_name", "Неизвестное растение"),
                "confidence": result.get("confidence", 0),
                "needs_retry": result.get("needs_retry", False),
                "state_info": result.get("state_info", {})
            }
            
            state_info = result.get("state_info", {})
            current_state = state_info.get('current_state', 'healthy')
            
            response_text = f"🌱 <b>Результат анализа:</b>\n\n{result['analysis']}"
            
            if current_state != 'healthy':
                state_recommendations = get_state_recommendations(
                    current_state, 
                    result.get("plant_name", "растение")
                )
                response_text += f"\n\n{state_recommendations}"
            
            keyboard = plant_analysis_actions(result.get("needs_retry", False))
            
            await message.reply(
                response_text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            
            # === КОНТЕКСТНАЯ ПОДСКАЗКА: после первого анализа ===
            from handlers.onboarding import send_tip_if_needed, TIP_AFTER_ANALYSIS
            
            async def _send_analysis_tip():
                await message.answer(TIP_AFTER_ANALYSIS, parse_mode="HTML")
            
            await send_tip_if_needed(user_id, 'analysis', _send_analysis_tip)
            
        else:
            from keyboards.main_menu import simple_back_menu
            await message.reply("❌ Ошибка анализа", reply_markup=simple_back_menu())
            
    except Exception as e:
        logger.error(f"Ошибка обработки фото: {e}", exc_info=True)
        from keyboards.main_menu import simple_back_menu
        await message.reply("❌ Техническая ошибка", reply_markup=simple_back_menu())
