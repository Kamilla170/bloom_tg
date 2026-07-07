import logging
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_USER_IDS, SUBSCRIPTION_PLANS
from database import get_db
from services.subscription_service import (
    get_user_plan, get_usage_stats, activate_pro, revoke_pro, is_pro,
)
from services.payment_service import create_payment, cancel_auto_payment

logger = logging.getLogger(__name__)

router = Router()

PLAN_BENEFITS_TEXT = (
    "• Неограниченное добавление растений\n"
    "• Безлимитное количество анализов растений\n"
    "• Поддержка 24/7 по всем вопросам о растениях\n"
)


def plans_keyboard():
    """Клавиатура с выбором тарифа"""
    buttons = []
    for plan_id, plan in SUBSCRIPTION_PLANS.items():
        if plan.get('lifetime'):
            text = f"♾ {plan['label']} — {plan['price']}₽"
        elif plan['days'] > 30:
            text = f"⭐ {plan['label']} — {plan['price']}₽ ({plan['per_month']}₽/мес)"
        else:
            text = f"⭐ {plan['label']} — {plan['price']}₽/мес"
        buttons.append([InlineKeyboardButton(
            text=text,
            callback_data=f"buy_{plan_id}"
        )])
    buttons.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def subscription_manage_keyboard(plan_info: dict):
    """Клавиатура управления подпиской"""
    buttons = []

    if plan_info['plan'] == 'pro':
        if plan_info.get('auto_pay'):
            buttons.append([InlineKeyboardButton(
                text="🔕 Отключить автопродление",
                callback_data="cancel_auto_pay"
            )])
        buttons.append([InlineKeyboardButton(
            text="💳 Отвязать карту",
            callback_data="unlink_card"
        )])
        buttons.append([InlineKeyboardButton(
            text="📊 Моя статистика", callback_data="stats"
        )])
    else:
        buttons.append([InlineKeyboardButton(
            text="⭐ Оформить подписку",
            callback_data="subscribe_pro"
        )])

    buttons.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _pro_status_text(plan_info: dict) -> str:
    """Текст статуса активной подписки"""
    if plan_info.get('is_lifetime'):
        return (
            "⭐ <b>Ваш план: Подписка</b>\n\n"
            "📅 Активна: <b>навсегда</b> ♾\n\n"
            "🌱 Без ограничений на растения, анализы и вопросы"
        )

    expires_str = plan_info['expires_at'].strftime('%d.%m.%Y') if plan_info['expires_at'] else '—'
    auto_text = "✅ Автопродление включено" if plan_info['auto_pay'] else "❌ Автопродление выключено"
    grace_text = "\n⚠️ <b>Grace period — продлите подписку!</b>" if plan_info['is_grace_period'] else ""

    return (
        f"⭐ <b>Ваш план: Подписка</b>\n\n"
        f"📅 Активна до: <b>{expires_str}</b>\n"
        f"📆 Осталось дней: <b>{plan_info['days_left']}</b>\n"
        f"{auto_text}"
        f"{grace_text}\n\n"
        f"🌱 Без ограничений на растения, анализы и вопросы"
    )


async def send_limit_message(message_or_callback, error_text: str):
    """Отправить сообщение о достижении лимита"""
    keyboard = plans_keyboard()

    if isinstance(message_or_callback, types.CallbackQuery):
        await message_or_callback.message.answer(
            error_text, parse_mode="HTML", reply_markup=keyboard
        )
        await message_or_callback.answer()
    else:
        await message_or_callback.answer(
            error_text, parse_mode="HTML", reply_markup=keyboard
        )


# === КОМАНДЫ ===

@router.message(Command("pro"))
async def pro_command(message: types.Message):
    """Команда /pro — информация о подписке и оформление"""
    user_id = message.from_user.id
    plan_info = await get_user_plan(user_id)

    if plan_info['plan'] == 'pro':
        await message.answer(
            _pro_status_text(plan_info),
            parse_mode="HTML",
            reply_markup=subscription_manage_keyboard(plan_info)
        )
    else:
        stats = await get_usage_stats(user_id)

        await message.answer(
            f"🌱 <b>Ваш план: Бесплатный</b>\n\n"
            f"<b>Использование функций:</b>\n"
            f"🌱 Растений: {stats['plants_count']}/{stats['plants_limit']}\n"
            f"📸 Анализов: {stats['analyses_used']}/{stats['analyses_limit']}\n"
            f"🤖 Вопросов: {stats['questions_used']}/{stats['questions_limit']}\n\n"
            f"<b>⭐ Выберите тариф:</b>\n"
            f"{PLAN_BENEFITS_TEXT}",
            parse_mode="HTML",
            reply_markup=plans_keyboard()
        )


@router.message(Command("subscription"))
async def subscription_command(message: types.Message):
    """Команда /subscription — то же что /pro"""
    await pro_command(message)


# === CALLBACK-и ===

@router.callback_query(F.data == "subscribe_pro")
async def subscribe_pro_callback(callback: types.CallbackQuery):
    """Показать выбор тарифа"""
    user_id = callback.from_user.id

    if await is_pro(user_id):
        await callback.answer("У вас уже есть подписка! ⭐", show_alert=True)
        return

    await callback.message.answer(
        "⭐ <b>Выберите тариф подписки:</b>\n\n"
        f"{PLAN_BENEFITS_TEXT}",
        parse_mode="HTML",
        reply_markup=plans_keyboard()
    )

    await callback.answer()


@router.callback_query(F.data.in_({"show_discount_plans", "show_apology_plans"}))
async def legacy_discount_callback(callback: types.CallbackQuery):
    """Кнопки из старых сообщений со скидками — показываем актуальные тарифы"""
    user_id = callback.from_user.id

    if await is_pro(user_id):
        await callback.answer("У вас уже есть подписка! ⭐", show_alert=True)
        return

    await callback.message.answer(
        "⭐ <b>Выберите тариф подписки:</b>\n\n"
        f"{PLAN_BENEFITS_TEXT}",
        parse_mode="HTML",
        reply_markup=plans_keyboard()
    )

    await callback.answer()


@router.callback_query(F.data.startswith("buy_"))
async def buy_plan_callback(callback: types.CallbackQuery):
    """Оформление подписки"""
    user_id = callback.from_user.id
    plan_id = callback.data.replace("buy_", "")

    plan = SUBSCRIPTION_PLANS.get(plan_id)
    if not plan:
        # Кнопки из старых сообщений (buy_discount_*, buy_apology_*, старые тарифы)
        await callback.message.answer(
            "⭐ <b>Тарифы обновились — выберите актуальный:</b>\n\n"
            f"{PLAN_BENEFITS_TEXT}",
            parse_mode="HTML",
            reply_markup=plans_keyboard()
        )
        await callback.answer()
        return

    if await is_pro(user_id):
        await callback.answer("У вас уже есть подписка! ⭐", show_alert=True)
        return

    processing_msg = await callback.message.answer(
        "💳 <b>Создаю ссылку на оплату...</b>",
        parse_mode="HTML"
    )

    save_method = (plan_id == '1month')

    result = await create_payment(
        user_id=user_id,
        amount=plan['price'],
        days=plan['days'],
        plan_label=plan['label'],
        save_method=save_method
    )

    await processing_msg.delete()

    if result:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Перейти к оплате", url=result['confirmation_url'])],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu")],
        ])

        period_text = "навсегда ♾" if plan.get('lifetime') else f"{plan['days']} дней"
        auto_text = "\n🔄 Автопродление: включено" if save_method else ""

        await callback.message.answer(
            f"💳 <b>Оплата подписки</b>\n\n"
            f"⭐ Тариф: <b>{plan['label']}</b>\n"
            f"💰 Сумма: <b>{plan['price']}₽</b>\n"
            f"📅 Период: <b>{period_text}</b>"
            f"{auto_text}\n\n"
            f"Нажмите кнопку ниже для перехода к оплате.\n"
            f"После оплаты подписка активируется автоматически.",
            parse_mode="HTML",
            reply_markup=keyboard
        )
    else:
        await callback.message.answer(
            "❌ <b>Не удалось создать платёж</b>\n\n"
            "Платёжная система временно недоступна. Попробуйте позже.",
            parse_mode="HTML"
        )

    await callback.answer()


@router.callback_query(F.data == "cancel_auto_pay")
async def cancel_auto_pay_callback(callback: types.CallbackQuery):
    """Отключение автопродления"""
    user_id = callback.from_user.id

    await cancel_auto_payment(user_id)

    plan_info = await get_user_plan(user_id)
    expires_str = plan_info['expires_at'].strftime('%d.%m.%Y') if plan_info['expires_at'] else '—'

    await callback.message.answer(
        f"🔕 <b>Автопродление отключено</b>\n\n"
        f"Ваша подписка действует до <b>{expires_str}</b>.\n"
        f"После этой даты аккаунт перейдёт на бесплатный план.\n\n"
        f"Вы можете снова подписаться в любой момент через /pro",
        parse_mode="HTML"
    )

    await callback.answer()


@router.callback_query(F.data == "unlink_card")
async def unlink_card_callback(callback: types.CallbackQuery):
    """Отвязка карты"""
    user_id = callback.from_user.id

    await cancel_auto_payment(user_id)

    await callback.message.answer(
        "💳 <b>Карта отвязана</b>\n\n"
        "Сохранённый способ оплаты удалён из системы.\n"
        "Автопродление отключено.\n\n"
        "Для следующей оплаты нужно будет ввести данные карты заново.",
        parse_mode="HTML"
    )

    await callback.answer()


@router.callback_query(F.data == "show_subscription")
async def show_subscription_callback(callback: types.CallbackQuery):
    """Показать информацию о подписке"""
    user_id = callback.from_user.id

    plan_info = await get_user_plan(user_id)

    if plan_info['plan'] == 'pro':
        await callback.message.answer(
            _pro_status_text(plan_info),
            parse_mode="HTML",
            reply_markup=subscription_manage_keyboard(plan_info)
        )
    else:
        stats = await get_usage_stats(user_id)

        await callback.message.answer(
            f"🌱 <b>Ваш план: Бесплатный</b>\n\n"
            f"<b>Использование функций:</b>\n"
            f"🌱 Растений: {stats['plants_count']}/{stats['plants_limit']}\n"
            f"📸 Анализов: {stats['analyses_used']}/{stats['analyses_limit']}\n"
            f"🤖 Вопросов: {stats['questions_used']}/{stats['questions_limit']}\n\n"
            f"<b>⭐ Выберите тариф:</b>\n"
            f"{PLAN_BENEFITS_TEXT}",
            parse_mode="HTML",
            reply_markup=plans_keyboard()
        )

    await callback.answer()


# === АДМИН-КОМАНДЫ ===

@router.message(Command("grant_pro"))
async def grant_pro_command(message: types.Message):
    """/grant_pro {user_id} {days}"""
    if message.from_user.id not in ADMIN_USER_IDS:
        await message.reply("❌ Нет прав администратора")
        return

    try:
        parts = message.text.split()

        if len(parts) < 3:
            await message.reply(
                "📝 <b>Формат:</b> /grant_pro {user_id} {days}\n\n"
                "<b>Пример:</b> /grant_pro 123456789 30",
                parse_mode="HTML"
            )
            return

        target_user_id = int(parts[1])
        days = int(parts[2])

        if days < 1 or days > 36500:
            await message.reply("❌ Количество дней должно быть от 1 до 36500")
            return

        db = await get_db()
        user_info = await db.get_user_info_by_id(target_user_id)

        if not user_info:
            await message.reply(f"❌ Пользователь с ID {target_user_id} не найден")
            return

        expires_at = await activate_pro(
            target_user_id,
            days=days,
            granted_by=message.from_user.id
        )

        username = user_info.get('username') or user_info.get('first_name') or f"user_{target_user_id}"
        expires_str = expires_at.strftime('%d.%m.%Y %H:%M')

        await message.reply(
            f"✅ <b>Подписка выдана!</b>\n\n"
            f"👤 Кому: {username} (ID: {target_user_id})\n"
            f"📅 На: {days} дней\n"
            f"⏰ До: {expires_str}",
            parse_mode="HTML"
        )

        try:
            await message.bot.send_message(
                chat_id=target_user_id,
                text=(
                    f"🎁 <b>Вам подарена подписка!</b>\n\n"
                    f"📅 Активна до: <b>{expires_str}</b>\n\n"
                    f"🌱 Неограниченный доступ к функциям бота"
                ),
                parse_mode="HTML"
            )
        except Exception:
            pass

    except ValueError:
        await message.reply("❌ Неверный формат. Используйте: /grant_pro {user_id} {days}")
    except Exception as e:
        logger.error(f"Ошибка grant_pro: {e}", exc_info=True)
        await message.reply(f"❌ Ошибка: {str(e)}")


@router.message(Command("revoke_pro"))
async def revoke_pro_command(message: types.Message):
    """/revoke_pro {user_id}"""
    if message.from_user.id not in ADMIN_USER_IDS:
        await message.reply("❌ Нет прав администратора")
        return

    try:
        parts = message.text.split()

        if len(parts) < 2:
            await message.reply(
                "📝 <b>Формат:</b> /revoke_pro {user_id}\n\n"
                "<b>Пример:</b> /revoke_pro 123456789",
                parse_mode="HTML"
            )
            return

        target_user_id = int(parts[1])

        await revoke_pro(target_user_id)

        await message.reply(
            f"✅ Подписка отозвана у пользователя {target_user_id}",
            parse_mode="HTML"
        )

    except ValueError:
        await message.reply("❌ Неверный формат user_id")
    except Exception as e:
        logger.error(f"Ошибка revoke_pro: {e}", exc_info=True)
        await message.reply(f"❌ Ошибка: {str(e)}")
