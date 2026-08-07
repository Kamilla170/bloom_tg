"""
Админ-панель /admin — inline-меню вместо запоминания команд.

Разделы: промокоды (список + пошаговый мастер создания),
статистика бота, пользователи, сообщения, справка по командам.
"""

import logging
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_USER_IDS, SUBSCRIPTION_PLANS
from database import get_db
from states.user_states import AdminPromoStates
from services.promo_service import create_promo, calc_price, discount_label

logger = logging.getLogger(__name__)

router = Router()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_USER_IDS


# === ГЛАВНОЕ МЕНЮ ===

def admin_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎟 Промокоды", callback_data="adm_promos")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats")],
        [
            InlineKeyboardButton(text="👥 Пользователи", callback_data="adm_users"),
            InlineKeyboardButton(text="📨 Сообщения", callback_data="adm_messages"),
        ],
        [InlineKeyboardButton(text="ℹ️ Все команды", callback_data="adm_help")],
    ])


@router.message(Command("admin"))
async def admin_command(message: types.Message):
    """/admin — панель администратора"""
    if not is_admin(message.from_user.id):
        await message.reply("❌ Нет прав администратора")
        return

    await message.answer(
        "🛠 <b>Панель администратора</b>\n\nВыберите раздел:",
        parse_mode="HTML",
        reply_markup=admin_menu_keyboard()
    )


@router.callback_query(F.data == "adm_menu")
async def adm_menu_callback(callback: types.CallbackQuery, state: FSMContext):
    """Возврат в главное меню панели"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    await state.clear()
    await callback.message.answer(
        "🛠 <b>Панель администратора</b>\n\nВыберите раздел:",
        parse_mode="HTML",
        reply_markup=admin_menu_keyboard()
    )
    await callback.answer()


# === РАЗДЕЛ: ПРОМОКОДЫ ===

def promo_section_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать промокод", callback_data="adm_promo_create")],
        [InlineKeyboardButton(text="📋 Список промокодов", callback_data="adm_promo_list")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="adm_menu")],
    ])


@router.callback_query(F.data == "adm_promos")
async def adm_promos_callback(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    await callback.message.answer(
        "🎟 <b>Промокоды</b>\n\nЧто сделать?",
        parse_mode="HTML",
        reply_markup=promo_section_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "adm_promo_list")
async def adm_promo_list_callback(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    from handlers.subscription import promos_list_view
    text, keyboard = await promos_list_view()

    if keyboard is None:
        keyboard = promo_section_keyboard()

    await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()


# === МАСТЕР СОЗДАНИЯ ПРОМОКОДА ===

def _cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admpw_cancel")],
    ])


@router.callback_query(F.data == "adm_promo_create")
async def promo_wizard_start(callback: types.CallbackQuery, state: FSMContext):
    """Шаг 1: код"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    await state.clear()
    await state.set_state(AdminPromoStates.waiting_code)

    await callback.message.answer(
        "➕ <b>Новый промокод — шаг 1 из 5</b>\n\n"
        "Введите код (например, LETO25).\n"
        "Регистр не важен — сохранится в верхнем.",
        parse_mode="HTML",
        reply_markup=_cancel_keyboard()
    )
    await callback.answer()


@router.message(AdminPromoStates.waiting_code, F.text)
async def promo_wizard_code(message: types.Message, state: FSMContext):
    """Шаг 2: тип скидки"""
    code = message.text.strip().upper()

    if not code or len(code) > 30 or ' ' in code:
        await message.reply(
            "❌ Код должен быть одним словом до 30 символов. Попробуйте ещё раз:",
            reply_markup=_cancel_keyboard()
        )
        return

    await state.update_data(code=code)
    await state.set_state(None)  # тип выбирается кнопкой

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="% Процент", callback_data="admpw_type_percent"),
            InlineKeyboardButton(text="₽ Рубли", callback_data="admpw_type_fixed"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admpw_cancel")],
    ])

    await message.answer(
        f"➕ <b>Промокод {code} — шаг 2 из 5</b>\n\n"
        f"Тип скидки?",
        parse_mode="HTML",
        reply_markup=keyboard
    )


@router.callback_query(F.data.startswith("admpw_type_"))
async def promo_wizard_type(callback: types.CallbackQuery, state: FSMContext):
    """Шаг 3: размер скидки"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    data = await state.get_data()
    if 'code' not in data:
        await callback.answer("Начните заново: /admin → Промокоды", show_alert=True)
        return

    dtype = callback.data.replace("admpw_type_", "")
    await state.update_data(dtype=dtype)
    await state.set_state(AdminPromoStates.waiting_value)

    hint = "от 1 до 100 (100 = подписка бесплатно)" if dtype == 'percent' else "в рублях, например 500"

    await callback.message.answer(
        f"➕ <b>Промокод {data['code']} — шаг 3 из 5</b>\n\n"
        f"Введите размер скидки: {hint}",
        parse_mode="HTML",
        reply_markup=_cancel_keyboard()
    )
    await callback.answer()


@router.message(AdminPromoStates.waiting_value, F.text)
async def promo_wizard_value(message: types.Message, state: FSMContext):
    """Шаг 4: лимит активаций"""
    data = await state.get_data()

    try:
        value = int(message.text.strip().replace('%', '').replace('₽', ''))
    except ValueError:
        await message.reply("❌ Нужно число. Попробуйте ещё раз:", reply_markup=_cancel_keyboard())
        return

    if data['dtype'] == 'percent' and not (1 <= value <= 100):
        await message.reply("❌ Процент должен быть от 1 до 100:", reply_markup=_cancel_keyboard())
        return
    if data['dtype'] == 'fixed' and value < 1:
        await message.reply("❌ Сумма должна быть больше 0:", reply_markup=_cancel_keyboard())
        return

    await state.update_data(value=value)
    await state.set_state(AdminPromoStates.waiting_limit)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="♾ Без лимита", callback_data="admpw_nolimit")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admpw_cancel")],
    ])

    await message.answer(
        f"➕ <b>Промокод {data['code']} — шаг 4 из 5</b>\n\n"
        f"Сколько человек смогут <b>оплатить</b> с этим кодом?\n"
        f"Введите число (например, 1000) или нажмите кнопку:",
        parse_mode="HTML",
        reply_markup=keyboard
    )


async def _wizard_ask_days(target_message: types.Message, state: FSMContext):
    """Шаг 5: срок действия"""
    data = await state.get_data()
    await state.set_state(AdminPromoStates.waiting_days)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="♾ Бессрочно", callback_data="admpw_forever")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admpw_cancel")],
    ])

    await target_message.answer(
        f"➕ <b>Промокод {data['code']} — шаг 5 из 5</b>\n\n"
        f"Сколько дней действует код?\n"
        f"Введите число (например, 14) или нажмите кнопку:",
        parse_mode="HTML",
        reply_markup=keyboard
    )


@router.message(AdminPromoStates.waiting_limit, F.text)
async def promo_wizard_limit(message: types.Message, state: FSMContext):
    try:
        limit = int(message.text.strip())
        if limit < 1:
            raise ValueError
    except ValueError:
        await message.reply("❌ Нужно число больше 0 (или кнопка «Без лимита»):")
        return

    await state.update_data(max_uses=limit)
    await _wizard_ask_days(message, state)


@router.callback_query(F.data == "admpw_nolimit")
async def promo_wizard_nolimit(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    await state.update_data(max_uses=None)
    await _wizard_ask_days(callback.message, state)
    await callback.answer()


async def _wizard_confirm(target_message: types.Message, state: FSMContext):
    """Карточка подтверждения с предпросмотром цен"""
    data = await state.get_data()
    await state.set_state(None)

    promo_preview = {'discount_type': data['dtype'], 'discount_value': data['value']}

    prices = ""
    for plan in SUBSCRIPTION_PLANS.values():
        new_price = calc_price(promo_preview, plan['price'])
        price_str = "бесплатно" if new_price == 0 else f"{new_price}₽"
        prices += f"• {plan['label']}: <s>{plan['price']}₽</s> <b>{price_str}</b>\n"

    limit_str = data['max_uses'] if data['max_uses'] else "без лимита"
    days_str = f"{data['valid_days']} дней" if data['valid_days'] else "бессрочно"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Создать", callback_data="admpw_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admpw_cancel")],
    ])

    await target_message.answer(
        f"🎟 <b>Проверьте промокод:</b>\n\n"
        f"Код: <b>{data['code']}</b>\n"
        f"Скидка: <b>{discount_label(promo_preview)}</b>\n"
        f"Лимит оплат: <b>{limit_str}</b>\n"
        f"Срок: <b>{days_str}</b>\n\n"
        f"<b>Цены с этим кодом:</b>\n{prices}",
        parse_mode="HTML",
        reply_markup=keyboard
    )


@router.message(AdminPromoStates.waiting_days, F.text)
async def promo_wizard_days(message: types.Message, state: FSMContext):
    try:
        days = int(message.text.strip())
        if days < 1:
            raise ValueError
    except ValueError:
        await message.reply("❌ Нужно число больше 0 (или кнопка «Бессрочно»):")
        return

    await state.update_data(valid_days=days)
    await _wizard_confirm(message, state)


@router.callback_query(F.data == "admpw_forever")
async def promo_wizard_forever(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    await state.update_data(valid_days=None)
    await _wizard_confirm(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "admpw_confirm")
async def promo_wizard_confirm(callback: types.CallbackQuery, state: FSMContext):
    """Создание промокода"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    data = await state.get_data()
    if 'code' not in data or 'dtype' not in data or 'value' not in data:
        await callback.answer("Данные потеряны, начните заново", show_alert=True)
        return

    promo, error = await create_promo(
        code=data['code'],
        discount_type=data['dtype'],
        value=data['value'],
        max_uses=data.get('max_uses'),
        valid_days=data.get('valid_days'),
        created_by=callback.from_user.id,
    )

    await state.clear()

    if error:
        await callback.message.answer(f"❌ {error}", reply_markup=promo_section_keyboard())
    else:
        await callback.message.answer(
            f"✅ <b>Промокод {promo['code']} создан!</b>\n\n"
            f"Пользователи вводят его через кнопку "
            f"«🎁 У меня есть промокод» на экране тарифов.",
            parse_mode="HTML",
            reply_markup=promo_section_keyboard()
        )

    await callback.answer()


@router.callback_query(F.data == "admpw_cancel")
async def promo_wizard_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(
        "🎟 Создание промокода отменено.",
        reply_markup=promo_section_keyboard()
    )
    await callback.answer()


# === РАЗДЕЛ: СТАТИСТИКА ===

@router.callback_query(F.data == "adm_stats")
async def adm_stats_callback(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    db = await get_db()
    async with db.pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        active_week = await conn.fetchval("""
            SELECT COUNT(*) FROM users
            WHERE last_activity > CURRENT_TIMESTAMP - INTERVAL '7 days'
        """)
        total_plants = await conn.fetchval(
            "SELECT COUNT(*) FROM plants WHERE plant_type = 'regular' OR plant_type IS NULL"
        )
        active_subs = await conn.fetchval("""
            SELECT COUNT(*) FROM subscriptions
            WHERE plan = 'pro' AND expires_at > CURRENT_TIMESTAMP
        """)
        revenue_30d = await conn.fetchval("""
            SELECT COALESCE(SUM(amount), 0) FROM payments
            WHERE status = 'succeeded'
              AND created_at > CURRENT_TIMESTAMP - INTERVAL '30 days'
        """)
        payments_30d = await conn.fetchval("""
            SELECT COUNT(*) FROM payments
            WHERE status = 'succeeded'
              AND created_at > CURRENT_TIMESTAMP - INTERVAL '30 days'
        """)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 В меню", callback_data="adm_menu")],
    ])

    await callback.message.answer(
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Пользователей всего: <b>{total_users}</b>\n"
        f"🔥 Активных за 7 дней: <b>{active_week}</b>\n"
        f"🌱 Растений в коллекциях: <b>{total_plants}</b>\n\n"
        f"⭐ Активных подписок: <b>{active_subs}</b>\n"
        f"💳 Оплат за 30 дней: <b>{payments_30d}</b>\n"
        f"💰 Выручка за 30 дней: <b>{revenue_30d}₽</b>",
        parse_mode="HTML",
        reply_markup=keyboard
    )
    await callback.answer()


# === РАЗДЕЛ: ПОЛЬЗОВАТЕЛИ И СООБЩЕНИЯ ===

@router.callback_query(F.data == "adm_users")
async def adm_users_callback(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    from handlers.admin import get_users_list_text
    text = await get_users_list_text()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 В меню", callback_data="adm_menu")],
    ])
    await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "adm_messages")
async def adm_messages_callback(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    from handlers.admin import get_messages_list_text
    text = await get_messages_list_text(callback.from_user.id)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 В меню", callback_data="adm_menu")],
    ])
    await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()


# === РАЗДЕЛ: СПРАВКА ===

ADMIN_HELP_TEXT = (
    "ℹ️ <b>Все админ-команды</b>\n\n"
    "<b>Панель:</b>\n"
    "/admin — эта панель\n\n"
    "<b>Подписки:</b>\n"
    "/grant_pro {user_id} {days} — выдать подписку\n"
    "/revoke_pro {user_id} — отозвать подписку\n\n"
    "<b>Промокоды:</b>\n"
    "/promos — список с управлением\n"
    "/promo_add КОД тип значение [лимит] [дней] — создать командой\n\n"
    "<b>Пользователи:</b>\n"
    "/users — активные пользователи\n"
    "/send {user_id} {текст} — написать пользователю\n"
    "/reply — ответить на последнее сообщение\n"
    "/messages — история переписки\n"
    "/delete_user {user_id} — удалить пользователя\n\n"
    "<b>Диагностика:</b>\n"
    "/check_plant {plant_id} — проверить растение\n"
    "/debug_reminders — диагностика напоминаний\n"
    "/fix_reminders — починка напоминаний"
)


@router.callback_query(F.data == "adm_help")
async def adm_help_callback(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 В меню", callback_data="adm_menu")],
    ])
    await callback.message.answer(ADMIN_HELP_TEXT, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()
