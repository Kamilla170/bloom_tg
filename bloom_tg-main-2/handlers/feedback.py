import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter

from states.user_states import FeedbackStates
from keyboards.main_menu import main_menu
from database import get_db

logger = logging.getLogger(__name__)

router = Router()


async def show_feedback_prompt(message_or_callback):
    """Показать запрос обратной связи"""
    text = (
        "📝 <b>Обратная связь</b>\n\n"
        "Мы будем очень благодарны за оставленную вами обратную связь. "
        "Напишите сообщение, мы постараемся ответить в течение 24 часов."
    )

    if isinstance(message_or_callback, types.CallbackQuery):
        await message_or_callback.message.answer(text, parse_mode="HTML")
    else:
        await message_or_callback.answer(text, parse_mode="HTML")


@router.callback_query(F.data == "feedback")
async def feedback_callback(callback: types.CallbackQuery, state: FSMContext):
    """Callback на кнопку обратной связи"""
    await state.set_state(FeedbackStates.writing_message)
    await show_feedback_prompt(callback)
    await callback.answer()


@router.message(StateFilter(FeedbackStates.writing_message))
async def handle_feedback_message(message: types.Message, state: FSMContext):
    """Обработка сообщения обратной связи"""
    try:
        feedback_text = message.text.strip() if message.text else ""
        feedback_photo = None
        if message.photo:
            feedback_photo = message.photo[-1].file_id

        if not feedback_text and not feedback_photo:
            await message.reply("📝 Напишите сообщение или приложите фото")
            return

        if feedback_text and len(feedback_text) < 5:
            await message.reply("📝 Слишком короткое сообщение (минимум 5 символов)")
            return

        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name or f"user_{user_id}"

        db = await get_db()
        await db.save_feedback(
            user_id=user_id,
            username=username,
            feedback_type='general',
            message=feedback_text or "Фото без комментария",
            photo_file_id=feedback_photo
        )

        await message.answer(
            "✅ <b>Спасибо за отзыв!</b>\n\n"
            "Ваше сообщение принято и поможет улучшить бота.",
            parse_mode="HTML",
            reply_markup=main_menu()
        )

        await state.clear()

    except Exception as e:
        logger.error(f"Ошибка обратной связи: {e}")
        await message.reply("❌ Ошибка обработки")
        await state.clear()
