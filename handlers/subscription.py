import logging
import asyncio
from datetime import datetime, timedelta
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

from config import (
    ADMIN_USER_IDS, SUBSCRIPTION_PLANS, FREE_LIMITS,
    DISCOUNT_PLANS, DISCOUNT_DURATION_DAYS,
    APOLOGY_DISCOUNT_PLANS, APOLOGY_DISCOUNT_DURATION_DAYS,
)
from database import get_db
from services.subscription_service import (
    get_user_plan, get_usage_stats, activate_pro, revoke_pro, is_pro,
    has_apology_discount,
)
from services.payment_service import create_payment, cancel_auto_payment

logger = logging.getLogger(__name__)

router = Router()


def plans_keyboard():
    """Клавиатура с выбором тарифа (обычные цены)"""
    buttons = []
    for plan_id, plan in SUBSCRIPTION_PLANS.items():
        if plan['days'] > 30:
            text = f"⭐ {plan['label']} — {plan['price']}₽ ({plan['per_month']}₽/мес)"
        else:
            text = f"⭐ {plan['label']} — {plan['price']}₽/мес"
        buttons.append([InlineKeyboardButton(
            text=text,
            callback_data=f"buy_{plan_id}"
        )])
    buttons.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def discount_plans_keyboard():
    """Клавиатура с выбором тарифа (скидка 33% для новых)"""
    buttons = []
    for plan_id, plan in DISCOUNT_PLANS.items():
        original = plan['original_price']
        discounted = plan['price']
        label = plan['label']
        if plan['days'] > 30:
            text = f"🔥 {label} — {discounted}₽ (вместо {original}₽)"
        else:
            text = f"🔥 {label} — {discounted}₽/мес (вместо {original}₽)"
        buttons.append([InlineKeyboardButton(
            text=text,
            callback_data=f"buy_discount_{plan_id}"
        )])
    buttons.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def apology_plans_keyboard():
    """Клавиатура с выбором тарифа (скидка 40% — извинения)"""
    buttons = []
    for plan_id, plan in APOLOGY_DISCOUNT_PLANS.items():
        original = plan['original_price']
        discounted = plan['price']
        label = plan['label']
        if plan['days'] > 30:
            text = f"🔥 {label} — {discounted}₽ (вместо {original}₽)"
        else:
            text = f"🔥 {label} — {discounted}₽/мес (вместо {original}₽)"
        buttons.append([InlineKeyboardButton(
            text=text,
            callback_data=f"buy_apology_{plan_id}"
        )])
    buttons.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def is_discount_eligible(user_id: int) -> bool:
    """Проверяет, имеет ли пользователь право на скидку 33% (≤ 3 дней с регистрации)"""
    try:
        db = await get_db()
        async with db.pool.acquire() as conn:
            created_at = await conn.fetchval("""
                SELECT created_at FROM users WHERE user_id = $1
            """, user_id)
            
            if not created_at:
                return False
            
            now = datetime.utcnow()
            if created_at.tzinfo:
                created_at = created_at.replace(tzinfo=None)
            
            days_since = (now - created_at).total_seconds() / 86400
            return days_since <= DISCOUNT_DURATION_DAYS
    except Exception as e:
        logger.error(f"Ошибка проверки скидки для {user_id}: {e}")
        return False


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
        expires_str = plan_info['expires_at'].strftime('%d.%m.%Y') if plan_info['expires_at'] else '—'
        auto_text = "✅ Автопродление включено" if plan_info['auto_pay'] else "❌ Автопродление выключено"
        grace_text = "\n⚠️ <b>Grace period — продлите подписку!</b>" if plan_info['is_grace_period'] else ""
        
        await message.answer(
            f"⭐ <b>Ваш план: Подписка</b>\n\n"
            f"📅 Активна до: <b>{expires_str}</b>\n"
            f"📆 Осталось дней: <b>{plan_info['days_left']}</b>\n"
            f"{auto_text}"
            f"{grace_text}\n\n"
            f"🌱 Без ограничений на растения, анализы и вопросы",
            parse_mode="HTML",
            reply_markup=subscription_manage_keyboard(plan_info)
        )
    else:
        stats = await get_usage_stats(user_id)
        
        # Приоритет: скидка-извинение 40% > обычная 33%
        has_apology = await has_apology_discount(user_id)
        has_discount = await is_discount_eligible(user_id) if not has_apology else False
        
        if has_apology:
            await message.answer(
                f"🌱 <b>Ваш план: Бесплатный</b>\n\n"
                f"<b>Использование функций:</b>\n"
                f"🌱 Растений: {stats['plants_count']}/{stats['plants_limit']}\n"
                f"📸 Анализов: {stats['analyses_used']}/{stats['analyses_limit']}\n"
                f"🤖 Вопросов: {stats['questions_used']}/{stats['questions_limit']}\n\n"
                f"🎁 <b>Скидка 40% в качестве извинений</b>\n\n"
                f"⭐ Подписка снимает все ограничения:\n"
                f"• Неограниченное добавление растений\n"
                f"• Безлимитное количество анализов растений\n"
                f"• Поддержка 24/7 по всем вопросам о растениях\n",
                parse_mode="HTML",
                reply_markup=apology_plans_keyboard()
            )
        elif has_discount:
            await message.answer(
                f"🌱 <b>Ваш план: Бесплатный</b>\n\n"
                f"<b>Использование функций:</b>\n"
                f"🌱 Растений: {stats['plants_count']}/{stats['plants_limit']}\n"
                f"📸 Анализов: {stats['analyses_used']}/{stats['analyses_limit']}\n"
                f"🤖 Вопросов: {stats['questions_used']}/{stats['questions_limit']}\n\n"
                f"🔥 <b>У вас есть скидка 33% для новых пользователей!</b>\n\n"
                f"⭐ Подписка снимает все ограничения:\n"
                f"• Неограниченное добавление растений\n"
                f"• Безлимитное количество анализов растений\n"
                f"• Поддержка 24/7 по всем вопросам о растениях\n",
                parse_mode="HTML",
                reply_markup=discount_plans_keyboard()
            )
        else:
            await message.answer(
                f"🌱 <b>Ваш план: Бесплатный</b>\n\n"
                f"<b>Использование функций:</b>\n"
                f"🌱 Растений: {stats['plants_count']}/{stats['plants_limit']}\n"
                f"📸 Анализов: {stats['analyses_used']}/{stats['analyses_limit']}\n"
                f"🤖 Вопросов: {stats['questions_used']}/{stats['questions_limit']}\n\n"
                f"<b>⭐ Выберите тариф:</b>\n"
                f"• Неограниченное добавление растений\n"
                f"• Безлимитное количество анализов растений\n"
                f"• Поддержка 24/7 по всем вопросам о растениях\n",
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
    
    has_apology = await has_apology_discount(user_id)
    has_discount = await is_discount_eligible(user_id) if not has_apology else False
    
    if has_apology:
        await callback.message.answer(
            "🎁 <b>Скидка 40% в качестве извинений</b>\n\n"
            "⭐ Подписка снимает все ограничения:\n"
            "• Неограниченное добавление растений\n"
            "• Безлимитное количество анализов растений\n"
            "• Поддержка 24/7 по всем вопросам о растениях\n",
            parse_mode="HTML",
            reply_markup=apology_plans_keyboard()
        )
    elif has_discount:
        await callback.message.answer(
            "🔥 <b>Скидка 33% для новых пользователей!</b>\n\n"
            "⭐ Подписка снимает все ограничения:\n"
            "• Неограниченное добавление растений\n"
            "• Безлимитное количество анализов растений\n"
            "• Поддержка 24/7 по всем вопросам о растениях\n",
            parse_mode="HTML",
            reply_markup=discount_plans_keyboard()
        )
    else:
        await callback.message.answer(
            "⭐ <b>Выберите тариф подписки:</b>\n\n"
            "• Неограниченное добавление растений\n"
            "• Безлимитное количество анализов растений\n"
            "• Поддержка 24/7 по всем вопросам о растениях\n",
            parse_mode="HTML",
            reply_markup=plans_keyboard()
        )
    
    await callback.answer()


@router.callback_query(F.data == "show_apology_plans")
async def show_apology_plans_callback(callback: types.CallbackQuery):
    """Показать тарифы со скидкой 40% (из рассылки-извинения)"""
    user_id = callback.from_user.id
    
    if await is_pro(user_id):
        await callback.answer("У вас уже есть подписка! ⭐", show_alert=True)
        return
    
    has_apology = await has_apology_discount(user_id)
    
    if has_apology:
        await callback.message.answer(
            "🎁 <b>Ваша скидка 40%</b>\n\n"
            "Выберите тариф:\n\n"
            "• 1 мес — <s>249₽</s> <b>149₽</b>\n"
            "• 3 мес — <s>599₽</s> <b>349₽</b>\n"
            "• 6 мес — <s>1099₽</s> <b>649₽</b>\n"
            "• 12 мес — <s>2099₽</s> <b>1249₽</b>\n\n"
            "Подписка снимает все ограничения.",
            parse_mode="HTML",
            reply_markup=apology_plans_keyboard()
        )
    else:
        await callback.message.answer(
            "⏰ К сожалению, скидка уже истекла.\n\n"
            "Но вы можете оформить подписку по обычной цене:",
            parse_mode="HTML",
            reply_markup=plans_keyboard()
        )
    
    await callback.answer()


@router.callback_query(F.data.startswith("buy_apology_"))
async def buy_apology_plan_callback(callback: types.CallbackQuery):
    """Оформление подписки со скидкой 40% (без автопродления)"""
    user_id = callback.from_user.id
    plan_id = callback.data.replace("buy_apology_", "")
    
    apology_plan = APOLOGY_DISCOUNT_PLANS.get(plan_id)
    if not apology_plan:
        await callback.answer("❌ Тариф не найден", show_alert=True)
        return
    
    if await is_pro(user_id):
        await callback.answer("У вас уже есть подписка! ⭐", show_alert=True)
        return
    
    has_apology = await has_apology_discount(user_id)
    
    if not has_apology:
        await callback.message.answer(
            "⏰ К сожалению, скидка уже истекла.\n\n"
            "Вы можете оформить подписку по обычной цене:",
            parse_mode="HTML",
            reply_markup=plans_keyboard()
        )
        await callback.answer()
        return
    
    processing_msg = await callback.message.answer(
        "💳 <b>Создаю ссылку на оплату...</b>",
        parse_mode="HTML"
    )
    
    result = await create_payment(
        user_id=user_id,
        amount=apology_plan['price'],
        days=apology_plan['days'],
        plan_label=f"{apology_plan['label']} (скидка 40%)",
        save_method=False
    )
    
    await processing_msg.delete()
    
    if result:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Перейти к оплате", url=result['confirmation_url'])],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu")],
        ])
        
        await callback.message.answer(
            f"💳 <b>Оплата подписки со скидкой</b>\n\n"
            f"⭐ Тариф: <b>{apology_plan['label']}</b>\n"
            f"💰 Сумма: <s>{apology_plan['original_price']}₽</s> <b>{apology_plan['price']}₽</b>\n"
            f"📅 Период: <b>{apology_plan['days']} дней</b>\n\n"
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


@router.callback_query(F.data == "show_discount_plans")
async def show_discount_plans_callback(callback: types.CallbackQuery):
    """Показать скидочные тарифы 33% (из триггерных сообщений)"""
    user_id = callback.from_user.id
    
    if await is_pro(user_id):
        await callback.answer("У вас уже есть подписка! ⭐", show_alert=True)
        return
    
    has_discount = await is_discount_eligible(user_id)
    
    if has_discount:
        await callback.message.answer(
            "🔥 <b>Ваша персональная скидка 33%</b>\n\n"
            "Выберите тариф:\n\n"
            "• 1 мес — <s>249₽</s> <b>169₽</b>\n"
            "• 3 мес — <s>599₽</s> <b>399₽</b>\n"
            "• 6 мес — <s>1099₽</s> <b>739₽</b>\n"
            "• 12 мес — <s>2099₽</s> <b>1369₽</b>\n\n"
            "Подписка снимает все ограничения.",
            parse_mode="HTML",
            reply_markup=discount_plans_keyboard()
        )
    else:
        await callback.message.answer(
            "⏰ К сожалению, скидка уже истекла.\n\n"
            "Но вы можете оформить подписку по обычной цене:",
            parse_mode="HTML",
            reply_markup=plans_keyboard()
        )
    
    await callback.answer()


@router.callback_query(F.data.startswith("buy_discount_"))
async def buy_discount_plan_callback(callback: types.CallbackQuery):
    """Оформление подписки со скидкой 33%"""
    user_id = callback.from_user.id
    plan_id = callback.data.replace("buy_discount_", "")
    
    discount_plan = DISCOUNT_PLANS.get(plan_id)
    regular_plan = SUBSCRIPTION_PLANS.get(plan_id)
    if not discount_plan or not regular_plan:
        await callback.answer("❌ Тариф не найден", show_alert=True)
        return
    
    if await is_pro(user_id):
        await callback.answer("У вас уже есть подписка! ⭐", show_alert=True)
        return
    
    has_discount = await is_discount_eligible(user_id)
    
    if not has_discount:
        await callback.message.answer(
            "⏰ К сожалению, скидка уже истекла.\n\n"
            "Вы можете оформить подписку по обычной цене:",
            parse_mode="HTML",
            reply_markup=plans_keyboard()
        )
        await callback.answer()
        return
    
    processing_msg = await callback.message.answer(
        "💳 <b>Создаю ссылку на оплату...</b>",
        parse_mode="HTML"
    )
    
    save_method = (plan_id == '1month')
    
    result = await create_payment(
        user_id=user_id,
        amount=discount_plan['price'],
        days=discount_plan['days'],
        plan_label=f"{discount_plan['label']} (скидка 33%)",
        save_method=save_method
    )
    
    await processing_msg.delete()
    
    if result:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Перейти к оплате", url=result['confirmation_url'])],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu")],
        ])
        
        auto_text = "\n🔄 Автопродление: включено (по обычной цене)" if save_method else ""
        
        await callback.message.answer(
            f"💳 <b>Оплата подписки со скидкой</b>\n\n"
            f"⭐ Тариф: <b>{discount_plan['label']}</b>\n"
            f"💰 Сумма: <s>{discount_plan['original_price']}₽</s> <b>{discount_plan['price']}₽</b>\n"
            f"📅 Период: <b>{discount_plan['days']} дней</b>"
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


@router.callback_query(F.data.startswith("buy_"))
async def buy_plan_callback(callback: types.CallbackQuery):
    """Оформление подписки (обычная цена)"""
    user_id = callback.from_user.id
    plan_id = callback.data.replace("buy_", "")
    
    if plan_id.startswith("discount_") or plan_id.startswith("apology_"):
        return
    
    plan = SUBSCRIPTION_PLANS.get(plan_id)
    if not plan:
        await callback.answer("❌ Тариф не найден", show_alert=True)
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
        
        auto_text = "\n🔄 Автопродление: включено" if save_method else ""
        
        await callback.message.answer(
            f"💳 <b>Оплата подписки</b>\n\n"
            f"⭐ Тариф: <b>{plan['label']}</b>\n"
            f"💰 Сумма: <b>{plan['price']}₽</b>\n"
            f"📅 Период: <b>{plan['days']} дней</b>"
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
        expires_str = plan_info['expires_at'].strftime('%d.%m.%Y') if plan_info['expires_at'] else '—'
        auto_text = "✅ Автопродление включено" if plan_info['auto_pay'] else "❌ Автопродление выключено"
        grace_text = "\n⚠️ <b>Grace period — продлите подписку!</b>" if plan_info['is_grace_period'] else ""
        
        await callback.message.answer(
            f"⭐ <b>Ваш план: Подписка</b>\n\n"
            f"📅 Активна до: <b>{expires_str}</b>\n"
            f"📆 Осталось дней: <b>{plan_info['days_left']}</b>\n"
            f"{auto_text}"
            f"{grace_text}\n\n"
            f"🌱 Без ограничений на растения, анализы и вопросы",
            parse_mode="HTML",
            reply_markup=subscription_manage_keyboard(plan_info)
        )
    else:
        stats = await get_usage_stats(user_id)
        
        has_apology = await has_apology_discount(user_id)
        has_discount = await is_discount_eligible(user_id) if not has_apology else False
        
        if has_apology:
            await callback.message.answer(
                f"🌱 <b>Ваш план: Бесплатный</b>\n\n"
                f"<b>Использование функций:</b>\n"
                f"🌱 Растений: {stats['plants_count']}/{stats['plants_limit']}\n"
                f"📸 Анализов: {stats['analyses_used']}/{stats['analyses_limit']}\n"
                f"🤖 Вопросов: {stats['questions_used']}/{stats['questions_limit']}\n\n"
                f"🎁 <b>Скидка 40% в качестве извинений</b>\n\n"
                f"⭐ Подписка снимает все ограничения:\n"
                f"• Неограниченное добавление растений\n"
                f"• Безлимитное количество анализов растений\n"
                f"• Поддержка 24/7 по всем вопросам о растениях\n",
                parse_mode="HTML",
                reply_markup=apology_plans_keyboard()
            )
        elif has_discount:
            await callback.message.answer(
                f"🌱 <b>Ваш план: Бесплатный</b>\n\n"
                f"<b>Использование функций:</b>\n"
                f"🌱 Растений: {stats['plants_count']}/{stats['plants_limit']}\n"
                f"📸 Анализов: {stats['analyses_used']}/{stats['analyses_limit']}\n"
                f"🤖 Вопросов: {stats['questions_used']}/{stats['questions_limit']}\n\n"
                f"🔥 <b>У вас есть скидка 33% для новых пользователей!</b>\n\n"
                f"⭐ Подписка снимает все ограничения:\n"
                f"• Неограниченное добавление растений\n"
                f"• Безлимитное количество анализов растений\n"
                f"• Поддержка 24/7 по всем вопросам о растениях\n",
                parse_mode="HTML",
                reply_markup=discount_plans_keyboard()
            )
        else:
            await callback.message.answer(
                f"🌱 <b>Ваш план: Бесплатный</b>\n\n"
                f"<b>Использование функций:</b>\n"
                f"🌱 Растений: {stats['plants_count']}/{stats['plants_limit']}\n"
                f"📸 Анализов: {stats['analyses_used']}/{stats['analyses_limit']}\n"
                f"🤖 Вопросов: {stats['questions_used']}/{stats['questions_limit']}\n\n"
                f"<b>⭐ Выберите тариф:</b>\n"
                f"• Неограниченное добавление растений\n"
                f"• Безлимитное количество анализов растений\n"
                f"• Поддержка 24/7 по всем вопросам о растениях\n",
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
        
        if days < 1 or days > 365:
            await message.reply("❌ Количество дней должно быть от 1 до 365")
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


@router.message(Command("send_apology"))
async def send_apology_command(message: types.Message):
    """
    /send_apology {user_id}
    Выставляет пользователю скидку 40% (или продлевает подписку) и отправляет извинение.
    """
    if message.from_user.id not in ADMIN_USER_IDS:
        await message.reply("❌ Нет прав администратора")
        return
    
    try:
        parts = message.text.split()
        
        if len(parts) < 2:
            await message.reply(
                "📝 <b>Формат:</b> /send_apology {user_id}\n\n"
                "<b>Пример:</b> /send_apology 8390994875",
                parse_mode="HTML"
            )
            return
        
        target_user_id = int(parts[1])
        
        db = await get_db()
        user_info = await db.get_user_info_by_id(target_user_id)
        
        if not user_info:
            await message.reply(f"❌ Пользователь с ID {target_user_id} не найден")
            return
        
        async with db.pool.acquire() as conn:
            existing = await conn.fetchrow("""
                SELECT sent_at, status FROM apology_broadcast_log WHERE user_id = $1
            """, target_user_id)
        
        if existing and existing['status'] in ('sent', 'blocked'):
            await message.reply(
                f"⚠️ Пользователю {target_user_id} уже отправлялось извинение "
                f"({existing['sent_at'].strftime('%d.%m.%Y %H:%M')}, статус: {existing['status']})\n\n"
                f"Для повторной отправки удалите запись из apology_broadcast_log"
            )
            return
        
        # Определяем вариант: платник (не-админ с PRO) или бесплатник
        is_admin = target_user_id in ADMIN_USER_IDS
        is_paid = (not is_admin) and await is_pro(target_user_id)
        
        now = datetime.now()
        discount_until = now + timedelta(days=APOLOGY_DISCOUNT_DURATION_DAYS)
        
        if is_paid:
            # Продлеваем подписку на 3 месяца
            await activate_pro(target_user_id, days=90)
            variant = 'paid'
        else:
            # Выставляем скидку 40%
            async with db.pool.acquire() as conn:
                await conn.execute("""
                    UPDATE users SET apology_discount_until = $1 WHERE user_id = $2
                """, discount_until, target_user_id)
            variant = 'free'
        
        text, keyboard = _build_apology_message(variant)
        
        try:
            await message.bot.send_message(
                chat_id=target_user_id, text=text, reply_markup=keyboard
            )
            status = 'sent'
            blocked = False
        except TelegramForbiddenError:
            status = 'blocked'
            blocked = True
        except Exception as e:
            logger.warning(f"Не удалось отправить {target_user_id}: {e}")
            status = 'failed'
            blocked = False
        
        async with db.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO apology_broadcast_log (user_id, variant, blocked, status)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id) 
                DO UPDATE SET variant = $2, blocked = $3, status = $4, sent_at = CURRENT_TIMESTAMP
            """, target_user_id, variant, blocked, status)
        
        username = user_info.get('username') or user_info.get('first_name') or f"user_{target_user_id}"
        status_emoji = {'sent': '✅', 'blocked': '❌', 'failed': '⚠️'}[status]
        
        reply_text = (
            f"{status_emoji} {status}\n\n"
            f"👤 {username} (ID: {target_user_id})\n"
            f"📋 Вариант: {'платник (+3 мес подписки)' if is_paid else 'бесплатник (скидка 40%)'}\n"
        )
        if not is_paid and status == 'sent':
            reply_text += f"🕒 Скидка до: {discount_until.strftime('%d.%m.%Y %H:%M')}"
        
        await message.reply(reply_text, parse_mode="HTML")
        
    except ValueError:
        await message.reply("❌ Неверный формат user_id")
    except Exception as e:
        logger.error(f"Ошибка send_apology: {e}", exc_info=True)
        await message.reply(f"❌ Ошибка: {str(e)}")


@router.message(Command("send_apology_all"))
async def send_apology_all_command(message: types.Message):
    """
    /send_apology_all
    Запускает массовую рассылку извинений всем пользователям.
    Идемпотентно: можно перезапускать, уже обработанные пропускаются.
    """
    if message.from_user.id not in ADMIN_USER_IDS:
        await message.reply("❌ Нет прав администратора")
        return
    
    # Проверяем, не запущена ли уже рассылка
    if getattr(send_apology_all_command, '_running', False):
        await message.reply("⚠️ Рассылка уже запущена. Дождитесь завершения или перезапустите бота.")
        return
    
    db = await get_db()
    async with db.pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        already_done = await conn.fetchval("""
            SELECT COUNT(*) FROM apology_broadcast_log WHERE status IN ('sent', 'blocked')
        """)
        admin_count = len(ADMIN_USER_IDS)
    
    remaining = total_users - already_done - admin_count
    
    status_msg = await message.reply(
        f"🚀 <b>Запускаю рассылку извинений</b>\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"👑 Админов (пропуск): {admin_count}\n"
        f"✅ Уже обработано: {already_done}\n"
        f"📨 Осталось: ~{remaining}\n\n"
        f"⏳ Ожидаемое время: ~{max(1, remaining // 10)} сек",
        parse_mode="HTML"
    )
    
    send_apology_all_command._running = True
    asyncio.create_task(
        _run_apology_broadcast(message.bot, status_msg, message.from_user.id)
    )


@router.message(Command("apology_status"))
async def apology_status_command(message: types.Message):
    """/apology_status — статистика рассылки извинений"""
    if message.from_user.id not in ADMIN_USER_IDS:
        await message.reply("❌ Нет прав администратора")
        return
    
    db = await get_db()
    async with db.pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        
        stats = await conn.fetch("""
            SELECT status, variant, COUNT(*) as cnt
            FROM apology_broadcast_log
            GROUP BY status, variant
            ORDER BY status, variant
        """)
        
        pending = await conn.fetchval("""
            SELECT COUNT(*) FROM apology_broadcast_log WHERE status = 'pending'
        """)
    
    text = f"📊 <b>Статус рассылки извинений</b>\n\n"
    text += f"👥 Всего пользователей: {total_users}\n"
    text += f"👑 Админов (пропуск): {len(ADMIN_USER_IDS)}\n\n"
    
    if stats:
        text += "<b>По статусам:</b>\n"
        for row in stats:
            emoji = {'sent': '✅', 'blocked': '🚫', 'failed': '⚠️', 'pending': '⏳'}
            text += f"{emoji.get(row['status'], '❓')} {row['status']} / {row['variant']}: {row['cnt']}\n"
    else:
        text += "Рассылка ещё не начиналась\n"
    
    if pending and pending > 0:
        text += f"\n⚠️ {pending} записей в статусе pending (БД обновлена, сообщение не ушло)"
    
    running = getattr(send_apology_all_command, '_running', False)
    text += f"\n\n🔄 Рассылка {'запущена' if running else 'не запущена'}"
    
    await message.reply(text, parse_mode="HTML")


# === ФУНКЦИИ РАССЫЛКИ ===

def _build_apology_message(variant: str):
    """Собрать текст и клавиатуру извинения по варианту"""
    if variant == 'paid':
        text = (
            "Привет! 🌱\n\n"
            "У нас случился технический сбой, из-за которого все растения "
            "пользователей были удалены из базы. Восстановить данные, "
            "к сожалению, не получилось.\n\n"
            "Чтобы вернуться к уходу за зелёными друзьями, добавьте их заново.\n\n"
            "В качестве извинений продлим вашу подписку ещё на 3 месяца бесплатно.\n\n"
            "Спасибо, что остаётесь со мной 💚"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌿 Добавить растение", callback_data="add_plant")],
        ])
    else:
        text = (
            "Привет! 🌱\n\n"
            "У нас случился технический сбой, из-за которого все растения "
            "пользователей были удалены из базы. Восстановить данные, "
            "к сожалению, не получилось.\n\n"
            "Чтобы вернуться к уходу за зелёными друзьями, добавьте их заново.\n\n"
            "В качестве извинений получите скидку 40% на подписку — действует 3 дня.\n\n"
            "Спасибо, что остаётесь со мной 💚"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌿 Добавить растение", callback_data="add_plant")],
            [InlineKeyboardButton(text="✨ Оформить со скидкой 40%", callback_data="show_apology_plans")],
        ])
    
    return text, keyboard


async def _run_apology_broadcast(bot, status_msg, admin_user_id: int):
    """
    Фоновая задача массовой рассылки.
    Идемпотентна: можно перезапускать, уже обработанные (sent/blocked) пропускаются.
    При падении бота pending-записи будут обработаны повторно (без дублирования продления).
    """
    sent = 0
    skipped = 0
    blocked = 0
    failed = 0
    extended = 0
    processed = 0
    
    try:
        db = await get_db()
        
        async with db.pool.acquire() as conn:
            all_users = await conn.fetch("SELECT user_id FROM users ORDER BY user_id")
        
        total = len(all_users)
        discount_until = datetime.now() + timedelta(days=APOLOGY_DISCOUNT_DURATION_DAYS)
        
        for i, user_row in enumerate(all_users):
            user_id = user_row['user_id']
            
            # Пропускаем админов
            if user_id in ADMIN_USER_IDS:
                skipped += 1
                continue
            
            # Проверяем, обработан ли уже
            async with db.pool.acquire() as conn:
                existing = await conn.fetchrow("""
                    SELECT status, variant FROM apology_broadcast_log WHERE user_id = $1
                """, user_id)
            
            if existing and existing['status'] in ('sent', 'blocked'):
                skipped += 1
                continue
            
            # Определяем вариант
            is_paid = await is_pro(user_id)
            variant = 'paid' if is_paid else 'free'
            
            # Если нет записи — первый раз: делаем БД-изменения + создаём pending
            if not existing:
                async with db.pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO apology_broadcast_log (user_id, variant, status)
                        VALUES ($1, $2, 'pending')
                    """, user_id, variant)
                
                if is_paid:
                    await activate_pro(user_id, days=90)
                    extended += 1
                else:
                    async with db.pool.acquire() as conn:
                        await conn.execute("""
                            UPDATE users SET apology_discount_until = $1 WHERE user_id = $2
                        """, discount_until, user_id)
            
            # existing с pending/failed — БД-изменения уже сделаны, просто шлём сообщение
            
            text, keyboard = _build_apology_message(variant)
            
            # Отправляем
            try:
                await bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)
                
                async with db.pool.acquire() as conn:
                    await conn.execute("""
                        UPDATE apology_broadcast_log 
                        SET status = 'sent', sent_at = CURRENT_TIMESTAMP, blocked = FALSE
                        WHERE user_id = $1
                    """, user_id)
                sent += 1
                
            except TelegramForbiddenError:
                async with db.pool.acquire() as conn:
                    await conn.execute("""
                        UPDATE apology_broadcast_log 
                        SET status = 'blocked', blocked = TRUE
                        WHERE user_id = $1
                    """, user_id)
                blocked += 1
                
            except TelegramRetryAfter as e:
                # Telegram просит подождать — ждём и пробуем ещё раз
                logger.warning(f"⏳ Flood control: ждём {e.retry_after}s")
                await asyncio.sleep(e.retry_after + 1)
                try:
                    await bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)
                    async with db.pool.acquire() as conn:
                        await conn.execute("""
                            UPDATE apology_broadcast_log 
                            SET status = 'sent', sent_at = CURRENT_TIMESTAMP, blocked = FALSE
                            WHERE user_id = $1
                        """, user_id)
                    sent += 1
                except Exception as retry_e:
                    logger.error(f"❌ Повторная ошибка для {user_id}: {retry_e}")
                    async with db.pool.acquire() as conn:
                        await conn.execute("""
                            UPDATE apology_broadcast_log SET status = 'failed' WHERE user_id = $1
                        """, user_id)
                    failed += 1
                    
            except Exception as e:
                logger.error(f"❌ Ошибка отправки {user_id}: {e}")
                async with db.pool.acquire() as conn:
                    await conn.execute("""
                        UPDATE apology_broadcast_log SET status = 'failed' WHERE user_id = $1
                    """, user_id)
                failed += 1
            
            processed += 1
            
            # Rate limit: пауза между сообщениями + доп. пауза каждые 20 сообщений
            await asyncio.sleep(0.05)
            if processed % 20 == 0:
                await asyncio.sleep(1.0)
            
            # Обновляем прогресс каждые 50 обработанных
            if processed % 50 == 0:
                try:
                    await status_msg.edit_text(
                        f"📨 <b>Рассылка в процессе...</b>\n\n"
                        f"✅ Отправлено: {sent}\n"
                        f"🚫 Заблокировано: {blocked}\n"
                        f"⚠️ Ошибок: {failed}\n"
                        f"⏭️ Пропущено: {skipped}\n"
                        f"📊 Обработано: {processed}/{total}\n"
                        f"🔄 Продлено подписок: {extended}",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
        
        # Финальный отчёт
        try:
            await status_msg.edit_text(
                f"✅ <b>Рассылка завершена!</b>\n\n"
                f"📨 Отправлено: {sent}\n"
                f"🚫 Заблокировано: {blocked}\n"
                f"⚠️ Ошибок: {failed}\n"
                f"⏭️ Пропущено: {skipped}\n"
                f"🔄 Продлено подписок: {extended}\n"
                f"👥 Всего обработано: {total}\n\n"
                + (f"⚠️ {failed} ошибок — запустите /send_apology_all повторно для дозвона" if failed > 0 else ""),
                parse_mode="HTML"
            )
        except Exception:
            pass
        
        logger.info(
            f"📊 Рассылка завершена: sent={sent}, blocked={blocked}, "
            f"failed={failed}, skipped={skipped}, extended={extended}"
        )
    
    except Exception as e:
        logger.error(f"❌ Критическая ошибка рассылки: {e}", exc_info=True)
        try:
            await bot.send_message(
                chat_id=admin_user_id,
                text=(
                    f"❌ <b>Рассылка прервана ошибкой</b>\n\n"
                    f"<code>{str(e)[:200]}</code>\n\n"
                    f"✅ Отправлено до сбоя: {sent}\n"
                    f"🚫 Заблокировано: {blocked}\n"
                    f"⚠️ Ошибок: {failed}\n\n"
                    f"Запустите /send_apology_all повторно — продолжит с места обрыва"
                ),
                parse_mode="HTML"
            )
        except Exception:
            pass
    finally:
        send_apology_all_command._running = False
