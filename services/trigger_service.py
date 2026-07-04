import logging
from datetime import timedelta
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.exceptions import TelegramForbiddenError

from database import get_db
from utils.time_utils import get_moscow_now

logger = logging.getLogger(__name__)


# === КОНФИГУРАЦИЯ ЦЕПОЧЕК ===

TRIGGER_CHAINS = {
    'onboarding_no_click': {
        'description': 'Нажал /start, но не нажал кнопку анализа',
        'steps': [
            {
                'delay_hours': 3,
                'message': (
                    "🌱 Пришли мне фото любого растения — расскажу, "
                    "что это за вид и как за ним ухаживать. "
                    "Это бесплатно и занимает пару секунд."
                ),
                'button_text': '📸 Отправить фото',
                'button_callback': 'onboarding_analyze',
            },
            {
                'delay_hours': 24,
                'message': (
                    "🌿 Вот что ты получишь, когда пришлёшь фото растения:\n\n"
                    "🔍 Вид и состояние\n"
                    "💧 График полива\n"
                    "🔔 Напоминания\n\n"
                    "Одно фото — и всё настроено!"
                ),
                'button_text': '📸 Отправить фото',
                'button_callback': 'onboarding_analyze',
            },
            {
                'delay_hours': 72,
                'message': (
                    "🌿 Я умею распознавать тысячи видов — "
                    "от обычных фиалок до редких тропических. "
                    "Подбираю уход под конкретное состояние: "
                    "если растение болеет — одни советы, "
                    "если цветёт — совсем другие.\n\n"
                    "Пришли фото, когда будет настроение!"
                ),
                'button_text': '📸 Отправить фото',
                'button_callback': 'onboarding_analyze',
            },
        ],
        'cancel_on': 'onboarding_clicked',
    },

    'onboarding_no_plant': {
        'description': 'Прошёл онбординг, но не добавил растение',
        'steps': [
            {
                'delay_hours': 3,
                'message': (
                    "🌱 Кстати, я всё ещё жду фото твоего растения!\n\n"
                    "Просто сфотографируй твое растение — и пришли мне. "
                    "Через пару секунд расскажу, что это за вид, "
                    "как за ним ухаживать и настрою полив."
                ),
                'button_text': '📸 Отправить фото',
                'button_callback': 'onboarding_analyze',
            },
            {
                'delay_hours': 24,
                'message': (
                    "🤔 Не знаешь, с чего начать? Вот что получишь, "
                    "когда добавишь растение:\n\n"
                    "🔍 Узнаешь точный вид и состояние\n"
                    "💧 Получишь персональный график полива\n"
                    "🔔 Я буду напоминать, когда пора поливать\n\n"
                    "Достаточно одного фото — попробуй!"
                ),
                'button_text': '📸 Добавить растение',
                'button_callback': 'onboarding_analyze',
            },
            {
                'delay_hours': 72,
                'message': (
                    "🌿 Я умею распознавать тысячи видов растений — "
                    "от обычных фиалок до редких тропических. "
                    "А ещё подбираю уход под конкретное состояние: "
                    "если растение болеет, получишь одни советы, "
                    "если цветёт — совсем другие.\n\n"
                    "Пришли фото, когда будет настроение — "
                    "посмотрим, что у тебя растёт!"
                ),
                'button_text': None,
                'button_callback': None,
            },
        ],
        'cancel_on': 'plant_added',
    },

    'first_plant_discount': {
        'description': 'Скидка через 15 мин после первого растения (если не задал вопрос)',
        'steps': [
            {
                'delay_hours': 0.25,  # 15 минут
                'message': (
                    "🌿 <b>Это только начало!</b>\n\n"
                    "Вы добавили растение — отличный старт! "
                    "А ещё мне можно задавать вопросы об уходе.\n\n"
                    "Сейчас вам доступен бесплатный план — "
                    "1 анализ и 1 вопрос в месяц.\n\n"
                    "Для новых пользователей — <b>скидка 33%</b> в первые 3 дня:\n\n"
                    "• 1 мес — <s>249₽</s> <b>169₽</b>\n"
                    "• 3 мес — <s>599₽</s> <b>399₽</b>\n"
                    "• 6 мес — <s>1099₽</s> <b>739₽</b>\n"
                    "• 12 мес — <s>2099₽</s> <b>1369₽</b>"
                ),
                'button_text': '⭐ Выбрать тариф со скидкой',
                'button_callback': 'show_discount_plans',
            },
        ],
        'cancel_on': 'payment_made',
        'next_chain': 'new_user_discount',
    },

    'new_user_discount': {
        'description': 'Follow-up скидки: напоминания через 24ч и 60ч',
        'steps': [
            {
                # Шаг 1 (через 24ч после первого сообщения о скидке)
                'delay_hours': 24,
                'message': (
                    "⏰ Ваша персональная скидка 33% ещё действует!\n\n"
                    "С подпиской вы сможете:\n"
                    "🔍 Анализировать растения без ограничений\n"
                    "🤖 Задавать любые вопросы об уходе\n"
                    "🌿 Добавлять неограниченное количество растений"
                ),
                'button_text': '⭐ Оформить со скидкой',
                'button_callback': 'show_discount_plans',
            },
            {
                # Шаг 2 (через 60ч — за 12 часов до сгорания скидки)
                'delay_hours': 60,
                'message': (
                    "🔥 Скидка 33% сгорает через 12 часов!\n\n"
                    "Это последний шанс оформить подписку по сниженной цене:\n"
                    "• 1 мес — 169₽ вместо 249₽\n"
                    "• 12 мес — 1369₽ вместо 2099₽"
                ),
                'button_text': '⭐ Оформить со скидкой',
                'button_callback': 'show_discount_plans',
            },
        ],
        'cancel_on': 'payment_made',
    },
}


# === СОЗДАНИЕ ЦЕПОЧКИ ===

async def start_chain(user_id: int, chain_type: str):
    """Запускает триггерную цепочку для пользователя"""
    chain_config = TRIGGER_CHAINS.get(chain_type)
    if not chain_config:
        logger.error(f"❌ Неизвестный тип цепочки: {chain_type}")
        return

    try:
        db = await get_db()
        moscow_now = get_moscow_now()

        async with db.pool.acquire() as conn:
            # Проверяем, нет ли уже активной цепочки этого типа
            existing = await conn.fetchval("""
                SELECT COUNT(*) FROM trigger_queue
                WHERE user_id = $1 AND chain_type = $2
                AND sent = FALSE AND cancelled = FALSE
            """, user_id, chain_type)

            if existing > 0:
                logger.info(f"⏭️ Цепочка '{chain_type}' уже активна для user_id={user_id}")
                return

            # Создаём все шаги цепочки
            for step_num, step_config in enumerate(chain_config['steps'], 1):
                send_at = moscow_now + timedelta(hours=step_config['delay_hours'])
                send_at_naive = send_at.replace(tzinfo=None)

                await conn.execute("""
                    INSERT INTO trigger_queue
                    (user_id, chain_type, step, send_at)
                    VALUES ($1, $2, $3, $4)
                """, user_id, chain_type, step_num, send_at_naive)

            logger.info(
                f"✅ Цепочка '{chain_type}' создана для user_id={user_id}: "
                f"{len(chain_config['steps'])} шагов"
            )

    except Exception as e:
        logger.error(f"❌ Ошибка создания цепочки '{chain_type}' для {user_id}: {e}", exc_info=True)


# === ОТМЕНА ЦЕПОЧКИ ===

async def cancel_chain(user_id: int, chain_type: str):
    """Отменяет все неотправленные сообщения цепочки"""
    try:
        db = await get_db()

        async with db.pool.acquire() as conn:
            result = await conn.fetch("""
                UPDATE trigger_queue
                SET cancelled = TRUE, cancelled_at = CURRENT_TIMESTAMP
                WHERE user_id = $1 AND chain_type = $2
                AND sent = FALSE AND cancelled = FALSE
                RETURNING id
            """, user_id, chain_type)

            cancelled_count = len(result)

            if cancelled_count > 0:
                logger.info(
                    f"🛑 Цепочка '{chain_type}' отменена для user_id={user_id}: "
                    f"{cancelled_count} сообщений"
                )

    except Exception as e:
        logger.error(f"❌ Ошибка отмены цепочки '{chain_type}' для {user_id}: {e}", exc_info=True)


async def cancel_chains_by_event(user_id: int, event: str):
    """Отменяет все цепочки, которые отменяются по данному событию"""
    for chain_type, config in TRIGGER_CHAINS.items():
        if config.get('cancel_on') == event:
            await cancel_chain(user_id, chain_type)


# === ПРОВЕРКА И ОТПРАВКА ===

async def check_and_send_triggers(bot):
    """Проверяет и отправляет готовые триггерные сообщения"""
    try:
        db = await get_db()
        moscow_now = get_moscow_now()
        moscow_now_naive = moscow_now.replace(tzinfo=None)

        async with db.pool.acquire() as conn:
            # Берём сообщения, которые пора отправить
            pending = await conn.fetch("""
                SELECT tq.id, tq.user_id, tq.chain_type, tq.step, tq.send_at
                FROM trigger_queue tq
                WHERE tq.sent = FALSE
                AND tq.cancelled = FALSE
                AND tq.send_at <= $1
                ORDER BY tq.send_at ASC
                LIMIT 50
            """, moscow_now_naive)

            if not pending:
                return

            logger.info(f"📨 Найдено {len(pending)} триггерных сообщений для отправки")

            sent_count = 0
            skip_count = 0
            error_count = 0
            blocked_count = 0
            blocked_users = set()

            for msg in pending:
                # Пропускаем заблокировавших пользователей
                if msg['user_id'] in blocked_users:
                    continue

                try:
                    # Проверяем стоп-условие перед отправкой
                    should_send = await check_stop_condition(
                        msg['user_id'], msg['chain_type']
                    )

                    if not should_send:
                        # Отменяем всю оставшуюся цепочку
                        await cancel_chain(msg['user_id'], msg['chain_type'])
                        skip_count += 1
                        continue

                    # Отправляем сообщение
                    await send_trigger_message(bot, msg)

                    # Помечаем как отправленное
                    await conn.execute("""
                        UPDATE trigger_queue
                        SET sent = TRUE, sent_at = $1
                        WHERE id = $2
                    """, moscow_now_naive, msg['id'])

                    sent_count += 1

                    # Проверяем, нужно ли запустить следующую цепочку
                    chain_config = TRIGGER_CHAINS.get(msg['chain_type'], {})
                    total_steps = len(chain_config.get('steps', []))
                    next_chain = chain_config.get('next_chain')

                    if msg['step'] == total_steps and next_chain:
                        await start_chain(msg['user_id'], next_chain)
                        logger.info(
                            f"🔗 Запущена следующая цепочка '{next_chain}' "
                            f"для user_id={msg['user_id']}"
                        )

                except TelegramForbiddenError:
                    blocked_users.add(msg['user_id'])
                    blocked_count += 1
                    # Деактивируем все напоминания и триггеры
                    from services.reminder_service import deactivate_user_reminders
                    await deactivate_user_reminders(msg['user_id'])

                except Exception as e:
                    error_count += 1
                    logger.error(
                        f"❌ Ошибка отправки триггера id={msg['id']}, "
                        f"user={msg['user_id']}: {e}"
                    )

            if sent_count > 0 or skip_count > 0 or error_count > 0 or blocked_count > 0:
                logger.info(
                    f"📊 Триггеры: отправлено={sent_count}, "
                    f"пропущено={skip_count}, заблокировано={blocked_count}, "
                    f"ошибок={error_count}"
                )

    except Exception as e:
        logger.error(f"❌ Ошибка проверки триггеров: {e}", exc_info=True)


async def check_stop_condition(user_id: int, chain_type: str) -> bool:
    """
    Проверяет, нужно ли ещё отправлять сообщения цепочки.
    Возвращает True если нужно отправлять, False если условие выполнено.
    """
    config = TRIGGER_CHAINS.get(chain_type)
    if not config:
        return False

    cancel_on = config.get('cancel_on')
    if not cancel_on:
        return True

    db = await get_db()

    async with db.pool.acquire() as conn:
        if cancel_on == 'plant_added':
            plants_count = await conn.fetchval("""
                SELECT COUNT(*) FROM plants
                WHERE user_id = $1 AND plant_type = 'regular'
            """, user_id)
            return plants_count == 0

        elif cancel_on == 'payment_made':
            # Проверяем, есть ли активная подписка
            has_sub = await conn.fetchval("""
                SELECT COUNT(*) FROM subscriptions
                WHERE user_id = $1 AND plan = 'pro'
                AND expires_at > CURRENT_TIMESTAMP
            """, user_id)
            return has_sub == 0

        elif cancel_on == 'onboarding_clicked':
            # Проверяем: нажал кнопку ИЛИ уже добавил растение
            completed = await conn.fetchval("""
                SELECT onboarding_completed FROM users
                WHERE user_id = $1
            """, user_id)
            if completed:
                return False

            plants_count = await conn.fetchval("""
                SELECT COUNT(*) FROM plants
                WHERE user_id = $1 AND plant_type = 'regular'
            """, user_id)
            return plants_count == 0

    return True


async def send_trigger_message(bot, msg_row):
    """Отправляет одно триггерное сообщение"""
    chain_type = msg_row['chain_type']
    step = msg_row['step']
    user_id = msg_row['user_id']

    config = TRIGGER_CHAINS.get(chain_type)
    if not config:
        logger.error(f"❌ Конфигурация не найдена: {chain_type}")
        return

    step_index = step - 1
    if step_index >= len(config['steps']):
        logger.error(f"❌ Шаг {step} не найден в цепочке '{chain_type}'")
        return

    step_config = config['steps'][step_index]
    message_text = step_config['message']

    # Собираем клавиатуру если есть кнопка
    reply_markup = None
    if step_config.get('button_text') and step_config.get('button_callback'):
        keyboard = [[
            InlineKeyboardButton(
                text=step_config['button_text'],
                callback_data=step_config['button_callback']
            )
        ]]
        reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

    # TelegramForbiddenError пробрасывается наверх
    await bot.send_message(
        chat_id=user_id,
        text=message_text,
        parse_mode="HTML",
        reply_markup=reply_markup
    )

    logger.info(
        f"📤 Триггер отправлен: chain='{chain_type}', "
        f"step={step}, user_id={user_id}"
    )
