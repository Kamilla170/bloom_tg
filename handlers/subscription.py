import logging
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_USER_IDS, SUBSCRIPTION_PLANS
from database import get_db
from states.user_states import PromoStates
from services.subscription_service import (
    get_user_plan, get_usage_stats, activate_pro, revoke_pro, is_pro,
)
from services.payment_service import create_payment, cancel_auto_payment
from services.promo_service import (
    PROMO_ERRORS, validate_promo, apply_promo, get_attached_promo, remove_promo,
    calc_price, discount_label, mark_payment_created, confirm_free_activation,
    create_promo, list_promos, get_promo_by_id, toggle_promo, delete_promo, promo_funnel,
)
from services.trigger_service import start_chain

logger = logging.getLogger(__name__)

router = Router()

PLAN_BENEFITS_TEXT = (
    "• Неограниченное добавление растений\n"
    "• Безлимитное количество анализов растений\n"
    "• Поддержка 24/7 по всем вопросам о растениях\n"
)


def plans_keyboard(promo: dict = None):
    """Клавиатура с выбором тарифа (с учётом применённого промокода)"""
    buttons = []
    for plan_id, plan in SUBSCRIPTION_PLANS.items():
        emoji = "🌟" if plan.get('lifetime') else "⭐"
        price = plan['price']

        if promo:
            new_price = calc_price(promo, price)
            if new_price == 0:
                text = f"{emoji} {plan['label']} — бесплатно (вместо {price}₽)"
            else:
                text = f"{emoji} {plan['label']} — {new_price}₽ (вместо {price}₽)"
        elif plan.get('lifetime'):
            text = f"{emoji} {plan['label']} — {price}₽"
        elif plan['days'] > 30:
            text = f"{emoji} {plan['label']} — {price}₽ ({plan['per_month']}₽/мес)"
        else:
            text = f"{emoji} {plan['label']} — {price}₽/мес"

        buttons.append([InlineKeyboardButton(
            text=text,
            callback_data=f"buy_{plan_id}"
        )])

    if promo:
        buttons.append([InlineKeyboardButton(
            text=f"❌ Убрать промокод {promo['code']}",
            callback_data="promo_remove"
        )])
    else:
        buttons.append([InlineKeyboardButton(
            text="🎁 У меня есть промокод",
            callback_data="promo_enter"
        )])

    buttons.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def plans_offer(user_id: int, header: str = "⭐ <b>Выберите тариф подписки:</b>"):
    """Текст + клавиатура тарифов с учётом закреплённого промокода"""
    promo = await get_attached_promo(user_id)
    promo_note = (
        f"🎁 Применён промокод <b>{promo['code']}</b> ({discount_label(promo)})\n\n"
        if promo else ""
    )
    text = f"{header}\n\n{promo_note}{PLAN_BENEFITS_TEXT}"
    return text, plans_keyboard(promo)


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
            "📅 Активна: <b>навсегда</b> 🌟\n\n"
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
    if isinstance(message_or_callback, types.CallbackQuery):
        user_id = message_or_callback.from_user.id
        promo = await get_attached_promo(user_id)
        await message_or_callback.message.answer(
            error_text, parse_mode="HTML", reply_markup=plans_keyboard(promo)
        )
        await message_or_callback.answer()
    else:
        user_id = message_or_callback.from_user.id
        promo = await get_attached_promo(user_id)
        await message_or_callback.answer(
            error_text, parse_mode="HTML", reply_markup=plans_keyboard(promo)
        )


# === КОМАНДЫ ===

@router.message(Command("subscription"))
async def subscription_command(message: types.Message):
    """Команда /subscription — информация о подписке и оформление"""
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
        header = (
            f"🌱 <b>Ваш план: Бесплатный</b>\n\n"
            f"<b>Использование функций:</b>\n"
            f"🌱 Растений: {stats['plants_count']}/{stats['plants_limit']}\n"
            f"📸 Анализов: {stats['analyses_used']}/{stats['analyses_limit']}\n"
            f"🤖 Вопросов: {stats['questions_used']}/{stats['questions_limit']}\n\n"
            f"<b>⭐ Выберите тариф:</b>"
        )
        text, keyboard = await plans_offer(user_id, header)

        await message.answer(text, parse_mode="HTML", reply_markup=keyboard)


@router.message(Command("pro"))
async def pro_command(message: types.Message):
    """Команда /pro — скрытый алиас /subscription (для старых пользователей)"""
    await subscription_command(message)


# === CALLBACK-и ===

@router.callback_query(F.data == "subscribe_pro")
async def subscribe_pro_callback(callback: types.CallbackQuery):
    """Показать выбор тарифа"""
    user_id = callback.from_user.id

    if await is_pro(user_id):
        await callback.answer("У вас уже есть подписка! ⭐", show_alert=True)
        return

    text, keyboard = await plans_offer(user_id)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)

    await callback.answer()


@router.callback_query(F.data.in_({"show_discount_plans", "show_apology_plans"}))
async def legacy_discount_callback(callback: types.CallbackQuery):
    """Кнопки из старых сообщений со скидками — показываем актуальные тарифы"""
    user_id = callback.from_user.id

    if await is_pro(user_id):
        await callback.answer("У вас уже есть подписка! ⭐", show_alert=True)
        return

    text, keyboard = await plans_offer(user_id)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)

    await callback.answer()


# === ПРОМОКОДЫ: пользовательский флоу ===

@router.callback_query(F.data == "promo_enter")
async def promo_enter_callback(callback: types.CallbackQuery, state: FSMContext):
    """Кнопка «У меня есть промокод»"""
    if await is_pro(callback.from_user.id):
        await callback.answer("У вас уже есть подписка! ⭐", show_alert=True)
        return

    await state.set_state(PromoStates.waiting_promo_code)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="promo_cancel")],
    ])
    await callback.message.answer(
        "🎁 <b>Введите промокод</b>\n\n"
        "Отправьте код сообщением в чат:",
        parse_mode="HTML",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data == "promo_cancel")
async def promo_cancel_callback(callback: types.CallbackQuery, state: FSMContext):
    """Отмена ввода промокода"""
    await state.clear()

    user_id = callback.from_user.id
    if not await is_pro(user_id):
        text, keyboard = await plans_offer(user_id)
        await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)

    await callback.answer()


@router.callback_query(F.data == "promo_remove")
async def promo_remove_callback(callback: types.CallbackQuery):
    """Убрать применённый промокод"""
    user_id = callback.from_user.id
    await remove_promo(user_id)

    text, keyboard = await plans_offer(user_id, "⭐ <b>Промокод убран. Тарифы без скидки:</b>")
    await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer("Промокод убран")


@router.callback_query(F.data.startswith("buy_"))
async def buy_plan_callback(callback: types.CallbackQuery):
    """Оформление подписки"""
    user_id = callback.from_user.id
    plan_id = callback.data.replace("buy_", "")

    plan = SUBSCRIPTION_PLANS.get(plan_id)
    if not plan:
        # Кнопки из старых сообщений (buy_discount_*, buy_apology_*, старые тарифы)
        text, keyboard = await plans_offer(user_id, "⭐ <b>Тарифы обновились — выберите актуальный:</b>")
        await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()
        return

    if await is_pro(user_id):
        await callback.answer("У вас уже есть подписка! ⭐", show_alert=True)
        return

    promo = await get_attached_promo(user_id)
    price = plan['price']
    final_price = calc_price(promo, price) if promo else price
    period_text = "навсегда 🌟" if plan.get('lifetime') else f"{plan['days']} дней"

    # 100% скидка — активируем подписку без платёжной системы
    if promo and final_price == 0:
        expires_at = await activate_pro(user_id, days=plan['days'], amount=0)
        await confirm_free_activation(user_id, promo['id'], plan_id)

        if plan.get('lifetime'):
            active_text = "📅 Активна: <b>навсегда</b> 🌟"
        else:
            active_text = f"📅 Активна до: <b>{expires_at.strftime('%d.%m.%Y')}</b>"

        await callback.message.answer(
            f"🎉 <b>Подписка активирована!</b>\n\n"
            f"⭐ Тариф: <b>{plan['label']}</b>\n"
            f"🎁 Промокод: <b>{promo['code']}</b> (бесплатно)\n"
            f"{active_text}\n\n"
            f"🌱 Теперь у вас безлимитный доступ:\n"
            f"{PLAN_BENEFITS_TEXT}",
            parse_mode="HTML"
        )
        await callback.answer()
        return

    processing_msg = await callback.message.answer(
        "💳 <b>Создаю ссылку на оплату...</b>",
        parse_mode="HTML"
    )

    save_method = (plan_id == '1month')

    plan_label = plan['label']
    if promo:
        plan_label = f"{plan['label']} (промокод {promo['code']})"

    result = await create_payment(
        user_id=user_id,
        amount=final_price,
        days=plan['days'],
        plan_label=plan_label,
        save_method=save_method,
        promo_code=promo['code'] if promo else None,
        base_amount=price if promo else None
    )

    await processing_msg.delete()

    if result:
        if promo:
            await mark_payment_created(user_id, result['payment_id'], plan_id, final_price)

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Перейти к оплате", url=result['confirmation_url'])],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu")],
        ])

        if promo:
            price_text = f"💰 Сумма: <s>{price}₽</s> <b>{final_price}₽</b> (промокод {promo['code']})"
        else:
            price_text = f"💰 Сумма: <b>{price}₽</b>"

        auto_text = "\n🔄 Автопродление: включено" if save_method else ""

        promo_note = ""
        if promo and not plan.get('lifetime'):
            promo_note = (
                f"\n\n🎁 Промокод действует только на этот платёж — "
                f"дальше подписка по обычной цене {price}₽."
            )

        await callback.message.answer(
            f"💳 <b>Оплата подписки</b>\n\n"
            f"⭐ Тариф: <b>{plan['label']}</b>\n"
            f"{price_text}\n"
            f"📅 Период: <b>{period_text}</b>"
            f"{auto_text}"
            f"{promo_note}\n\n"
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
        f"Вы можете снова подписаться в любой момент через /subscription",
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
        header = (
            f"🌱 <b>Ваш план: Бесплатный</b>\n\n"
            f"<b>Использование функций:</b>\n"
            f"🌱 Растений: {stats['plants_count']}/{stats['plants_limit']}\n"
            f"📸 Анализов: {stats['analyses_used']}/{stats['analyses_limit']}\n"
            f"🤖 Вопросов: {stats['questions_used']}/{stats['questions_limit']}\n\n"
            f"<b>⭐ Выберите тариф:</b>"
        )
        text, keyboard = await plans_offer(user_id, header)
        await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)

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


# === АДМИН: ПРОМОКОДЫ ===

PROMO_ADD_HELP = (
    "📝 <b>Формат:</b> /promo_add КОД тип значение [лимит] [дней]\n\n"
    "<b>тип:</b> percent (скидка в %) или fixed (скидка в ₽)\n"
    "<b>лимит:</b> макс. число активаций (0 или пропустить = безлимит)\n"
    "<b>дней:</b> срок действия кода (0 или пропустить = бессрочно)\n\n"
    "<b>Примеры:</b>\n"
    "<code>/promo_add LETO25 percent 25</code> — −25%, безлимит, бессрочно\n"
    "<code>/promo_add BLOGER percent 100 10 30</code> — бесплатно, 10 активаций, 30 дней\n"
    "<code>/promo_add MINUS500 fixed 500 50</code> — −500₽, 50 активаций"
)


def _promo_line(promo: dict) -> str:
    """Строка описания промокода для списка"""
    status = "🟢" if promo['is_active'] else "🔴"
    uses = f"{promo['used_count']}/{promo['max_uses'] if promo['max_uses'] else '∞'}"
    until = promo['valid_until'].strftime('%d.%m.%Y') if promo['valid_until'] else "бессрочно"
    return f"{status} <b>{promo['code']}</b> — {discount_label(promo)} • оплат: {uses} • до: {until}"


@router.message(Command("promo_add"))
async def promo_add_command(message: types.Message):
    """/promo_add КОД тип значение [лимит] [дней]"""
    if message.from_user.id not in ADMIN_USER_IDS:
        await message.reply("❌ Нет прав администратора")
        return

    try:
        parts = message.text.split()

        if len(parts) < 4:
            await message.reply(PROMO_ADD_HELP, parse_mode="HTML")
            return

        code = parts[1]
        discount_type = parts[2].lower()
        value = int(parts[3])
        max_uses = int(parts[4]) if len(parts) > 4 else 0
        valid_days = int(parts[5]) if len(parts) > 5 else 0

        promo, error = await create_promo(
            code=code,
            discount_type=discount_type,
            value=value,
            max_uses=max_uses or None,
            valid_days=valid_days or None,
            created_by=message.from_user.id,
        )

        if error:
            await message.reply(f"❌ {error}\n\n{PROMO_ADD_HELP}", parse_mode="HTML")
            return

        await message.reply(
            f"✅ <b>Промокод создан!</b>\n\n"
            f"{_promo_line(promo)}\n\n"
            f"Пользователи вводят его через кнопку «🎁 У меня есть промокод» "
            f"на экране тарифов.",
            parse_mode="HTML"
        )

    except ValueError:
        await message.reply(PROMO_ADD_HELP, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка promo_add: {e}", exc_info=True)
        await message.reply(f"❌ Ошибка: {str(e)}")


async def promos_list_view():
    """Текст и клавиатура списка промокодов (используется в /promos и /admin)"""
    promos = await list_promos()

    if not promos:
        return "🎟️ Промокодов пока нет.\n\n" + PROMO_ADD_HELP, None

    text = "🎟️ <b>Промокоды</b>\n\n"
    buttons = []
    for promo in promos:
        text += _promo_line(promo) + "\n"
        toggle_label = "🔴 Выключить" if promo['is_active'] else "🟢 Включить"
        buttons.append([
            InlineKeyboardButton(text=promo['code'], callback_data=f"padmin_stats_{promo['id']}"),
            InlineKeyboardButton(text=toggle_label, callback_data=f"padmin_toggle_{promo['id']}"),
            InlineKeyboardButton(text="🗑", callback_data=f"padmin_del_{promo['id']}"),
        ])

    text += "\nНажмите на код — статистика."
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(Command("promos"))
async def promos_command(message: types.Message):
    """/promos — список промокодов с управлением"""
    if message.from_user.id not in ADMIN_USER_IDS:
        await message.reply("❌ Нет прав администратора")
        return

    text, keyboard = await promos_list_view()
    await message.reply(text, parse_mode="HTML", reply_markup=keyboard)


@router.callback_query(F.data.startswith("padmin_toggle_"))
async def promo_toggle_callback(callback: types.CallbackQuery):
    """Вкл/выкл промокод"""
    if callback.from_user.id not in ADMIN_USER_IDS:
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    promo_id = int(callback.data.replace("padmin_toggle_", ""))
    new_state = await toggle_promo(promo_id)

    if new_state is None:
        await callback.answer("❌ Код не найден", show_alert=True)
        return

    promo = await get_promo_by_id(promo_id)
    await callback.answer(f"{promo['code']}: {'🟢 включён' if new_state else '🔴 выключен'}", show_alert=True)


@router.callback_query(F.data.startswith("padmin_stats_"))
async def promo_stats_callback(callback: types.CallbackQuery):
    """Воронка по промокоду"""
    if callback.from_user.id not in ADMIN_USER_IDS:
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    promo_id = int(callback.data.replace("padmin_stats_", ""))
    promo = await get_promo_by_id(promo_id)

    if not promo:
        await callback.answer("❌ Код не найден", show_alert=True)
        return

    funnel = await promo_funnel(promo_id)

    await callback.message.answer(
        f"📊 <b>Промокод {promo['code']}</b>\n\n"
        f"{_promo_line(promo)}\n\n"
        f"<b>Воронка:</b>\n"
        f"🎁 Вводили код: {funnel['entered_total']}\n"
        f"⏳ Ждут с применённым кодом: {funnel['waiting']}\n"
        f"💳 Дошли до оплаты: {funnel['payment_created']}\n"
        f"✅ Оплатили: {funnel['paid']}\n"
        f"💰 Выручка: {funnel['revenue']}₽",
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("padmin_del_"))
async def promo_delete_callback(callback: types.CallbackQuery):
    """Удалить промокод (или деактивировать, если были оплаты)"""
    if callback.from_user.id not in ADMIN_USER_IDS:
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    promo_id = int(callback.data.replace("padmin_del_", ""))
    promo = await get_promo_by_id(promo_id)

    if not promo:
        await callback.answer("❌ Код не найден", show_alert=True)
        return

    result = await delete_promo(promo_id)

    if result == 'deleted':
        await callback.answer(f"🗑 {promo['code']} удалён", show_alert=True)
    elif result == 'deactivated':
        await callback.answer(
            f"🔴 {promo['code']} выключен (по нему были оплаты, история сохранена)",
            show_alert=True
        )
    else:
        await callback.answer("❌ Не удалось удалить", show_alert=True)


# === ВВОД ПРОМОКОДА (в конце файла — чтобы команды имели приоритет) ===

@router.message(PromoStates.waiting_promo_code, F.text)
async def promo_code_entered(message: types.Message, state: FSMContext):
    """Пользователь прислал промокод текстом"""
    user_id = message.from_user.id

    if await is_pro(user_id):
        await state.clear()
        await message.reply("У вас уже есть подписка! ⭐")
        return

    promo, error = await validate_promo(message.text, user_id)

    if error:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="promo_cancel")],
        ])
        await message.reply(
            f"{PROMO_ERRORS[error]}\n\nМожно ввести другой код:",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        return

    await apply_promo(user_id, promo['id'])
    await state.clear()

    # Напоминание через 24ч, если не оплатит (отменится само после оплаты)
    await start_chain(user_id, 'promo_not_paid')

    text, keyboard = await plans_offer(
        user_id,
        f"🎉 <b>Промокод {promo['code']} применён!</b>\n\n"
        f"Скидка {discount_label(promo)} уже в ценах — выберите тариф:"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)
