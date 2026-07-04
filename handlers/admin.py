import logging
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter

from database import get_db
from states.user_states import AdminStates
from config import ADMIN_USER_IDS

logger = logging.getLogger(__name__)

router = Router()


def is_admin(user_id: int) -> bool:
    """Проверка прав администратора"""
    return user_id in ADMIN_USER_IDS


@router.message(Command("delete_user"))
async def delete_user_command(message: types.Message):
    """
    Удаление пользователя из БД
    Формат: /delete_user {user_id}
    """
    if not is_admin(message.from_user.id):
        await message.reply("❌ У вас нет прав администратора")
        return
    
    try:
        parts = message.text.split()
        
        if len(parts) < 2:
            await message.reply(
                "📝 <b>Формат команды:</b>\n"
                "/delete_user {user_id}\n\n"
                "<b>Пример:</b>\n"
                "/delete_user 123456789",
                parse_mode="HTML"
            )
            return
        
        target_user_id = int(parts[1])
        
        db = await get_db()
        async with db.pool.acquire() as conn:
            # Проверяем существование
            user = await conn.fetchrow(
                "SELECT user_id, username, first_name, plants_count FROM users WHERE user_id = $1",
                target_user_id
            )
            
            if not user:
                await message.reply(f"❌ Пользователь {target_user_id} не найден в БД")
                return
            
            username = user['username'] or user['first_name'] or f"user_{target_user_id}"
            
            # Удаляем из всех таблиц в правильном порядке
            deleted = {}
            
            deleted['trigger_queue'] = await conn.execute(
                "DELETE FROM trigger_queue WHERE user_id = $1", target_user_id
            )
            deleted['reminders'] = await conn.execute(
                "DELETE FROM reminders WHERE user_id = $1", target_user_id
            )
            deleted['care_history'] = await conn.execute(
                "DELETE FROM care_history WHERE user_id = $1", target_user_id
            )
            deleted['plant_qa_history'] = await conn.execute(
                "DELETE FROM plant_qa_history WHERE user_id = $1", target_user_id
            )
            deleted['plant_state_history'] = await conn.execute(
                "DELETE FROM plant_state_history WHERE plant_id IN (SELECT id FROM plants WHERE user_id = $1)",
                target_user_id
            )
            deleted['plants'] = await conn.execute(
                "DELETE FROM plants WHERE user_id = $1", target_user_id
            )
            deleted['growing_plants'] = await conn.execute(
                "DELETE FROM growing_plants WHERE user_id = $1", target_user_id
            )
            deleted['user_settings'] = await conn.execute(
                "DELETE FROM user_settings WHERE user_id = $1", target_user_id
            )
            deleted['subscriptions'] = await conn.execute(
                "DELETE FROM subscriptions WHERE user_id = $1", target_user_id
            )
            deleted['payments'] = await conn.execute(
                "DELETE FROM payments WHERE user_id = $1", target_user_id
            )
            deleted['admin_messages'] = await conn.execute(
                "DELETE FROM admin_messages WHERE from_user_id = $1 OR to_user_id = $1", target_user_id
            )
            deleted['users'] = await conn.execute(
                "DELETE FROM users WHERE user_id = $1", target_user_id
            )
        
        logger.info(f"🗑️ Админ {message.from_user.id} удалил пользователя {target_user_id} ({username})")
        
        await message.reply(
            f"✅ <b>Пользователь удалён</b>\n\n"
            f"👤 {username} (ID: <code>{target_user_id}</code>)\n"
            f"🌱 Растений было: {user['plants_count'] or 0}\n\n"
            f"Все данные удалены из БД.",
            parse_mode="HTML"
        )
        
    except ValueError:
        await message.reply("❌ Неверный формат user_id. Должно быть число.")
    except Exception as e:
        logger.error(f"Ошибка удаления пользователя: {e}", exc_info=True)
        await message.reply(f"❌ Ошибка: {str(e)}")


@router.message(Command("check_plant"))
async def check_plant_command(message: types.Message):
    """
    Диагностика растения и напоминаний
    Формат: /check_plant {plant_id}
    """
    if not is_admin(message.from_user.id):
        await message.reply("❌ У вас нет прав администратора")
        return
    
    try:
        parts = message.text.split()
        
        if len(parts) < 2:
            await message.reply(
                "📝 <b>Формат команды:</b>\n"
                "/check_plant {plant_id}\n\n"
                "<b>Пример:</b>\n"
                "/check_plant 9",
                parse_mode="HTML"
            )
            return
        
        plant_id = int(parts[1])
        
        db = await get_db()
        async with db.pool.acquire() as conn:
            # Данные растения
            plant = await conn.fetchrow("""
                SELECT p.id, p.user_id, p.plant_name, p.custom_name,
                       p.plant_type, p.current_state, p.reminder_enabled,
                       p.watering_interval, p.last_watered, p.saved_date,
                       COALESCE(p.custom_name, p.plant_name, 'Растение #' || p.id) as display_name
                FROM plants p
                WHERE p.id = $1
            """, plant_id)
            
            if not plant:
                await message.reply(f"❌ Растение с ID {plant_id} не найдено")
                return
            
            # Настройки пользователя
            user_settings = await conn.fetchrow("""
                SELECT reminder_enabled FROM user_settings
                WHERE user_id = $1
            """, plant['user_id'])
            
            # Напоминания
            reminders = await conn.fetch("""
                SELECT id, reminder_type, next_date, last_sent, 
                       is_active, send_count
                FROM reminders
                WHERE plant_id = $1
                ORDER BY is_active DESC, next_date DESC
            """, plant_id)
            
            # Триггеры пользователя
            triggers = await conn.fetch("""
                SELECT chain_type, step, send_at, sent, cancelled
                FROM trigger_queue
                WHERE user_id = $1
                ORDER BY send_at DESC
                LIMIT 10
            """, plant['user_id'])
        
        # Формируем отчёт
        from utils.time_utils import get_moscow_now
        now = get_moscow_now()
        
        text = f"🔍 <b>Диагностика растения #{plant_id}</b>\n\n"
        
        # Растение
        text += f"<b>🌱 Растение:</b>\n"
        text += f"   Название: {plant['display_name']}\n"
        text += f"   User ID: <code>{plant['user_id']}</code>\n"
        text += f"   Тип: {plant['plant_type']}\n"
        text += f"   Состояние: {plant['current_state']}\n"
        text += f"   Интервал полива: {plant['watering_interval']} дней\n"
        text += f"   reminder_enabled: {'✅' if plant['reminder_enabled'] else '❌'}\n"
        
        if plant['last_watered']:
            days_ago = (now.date() - plant['last_watered'].date()).days
            text += f"   Последний полив: {plant['last_watered'].strftime('%d.%m.%Y')} ({days_ago} дн. назад)\n"
        else:
            text += f"   Последний полив: никогда ❗\n"
        
        text += f"   Создано: {plant['saved_date'].strftime('%d.%m.%Y %H:%M')}\n"
        
        # Настройки пользователя
        text += f"\n<b>👤 User settings:</b>\n"
        if user_settings:
            text += f"   reminder_enabled: {'✅' if user_settings['reminder_enabled'] else '❌'}\n"
        else:
            text += f"   ❌ Запись user_settings НЕ НАЙДЕНА!\n"
        
        # Напоминания
        text += f"\n<b>🔔 Напоминания ({len(reminders)}):</b>\n"
        if reminders:
            for r in reminders:
                status = "✅ active" if r['is_active'] else "❌ inactive"
                next_d = r['next_date'].strftime('%d.%m.%Y') if r['next_date'] else '-'
                last_s = r['last_sent'].strftime('%d.%m.%Y') if r['last_sent'] else 'никогда'
                text += (
                    f"   ID={r['id']} [{status}] {r['reminder_type']}\n"
                    f"      next_date: {next_d}, last_sent: {last_s}, "
                    f"отправлено: {r['send_count'] or 0} раз\n"
                )
        else:
            text += f"   ❗ НЕТ ЗАПИСЕЙ В REMINDERS!\n"
        
        # Триггеры
        if triggers:
            text += f"\n<b>⏰ Триггеры пользователя:</b>\n"
            for t in triggers:
                status = "✅ sent" if t['sent'] else ("🛑 cancelled" if t['cancelled'] else "⏳ pending")
                text += f"   {t['chain_type']} step={t['step']} [{status}] {t['send_at'].strftime('%d.%m %H:%M')}\n"
        
        await message.reply(text, parse_mode="HTML")
        
    except ValueError:
        await message.reply("❌ Неверный формат plant_id. Должно быть число.")
    except Exception as e:
        logger.error(f"Ошибка диагностики растения: {e}", exc_info=True)
        await message.reply(f"❌ Ошибка: {str(e)}")


@router.message(Command("send"))
async def send_message_to_user_command(message: types.Message, state: FSMContext):
    """
    Команда /send для отправки сообщения пользователю
    Формат: /send {user_id} {текст сообщения}
    """
    if not is_admin(message.from_user.id):
        await message.reply("❌ У вас нет прав администратора")
        return
    
    try:
        # Парсим команду
        parts = message.text.split(maxsplit=2)
        
        if len(parts) < 3:
            await message.reply(
                "📝 <b>Формат команды:</b>\n"
                "/send {user_id} {текст сообщения}\n\n"
                "<b>Пример:</b>\n"
                "/send 123456789 Привет! Как дела с растениями?",
                parse_mode="HTML"
            )
            return
        
        target_user_id = int(parts[1])
        message_text = parts[2]
        
        # Проверяем существование пользователя
        db = await get_db()
        user_info = await db.get_user_info_by_id(target_user_id)
        
        if not user_info:
            await message.reply(f"❌ Пользователь с ID {target_user_id} не найден")
            return
        
        # Отправляем сообщение пользователю
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        
        keyboard = [
            [InlineKeyboardButton(text="✉️ Ответить", callback_data=f"reply_to_admin_{message.from_user.id}")]
        ]
        
        await message.bot.send_message(
            chat_id=target_user_id,
            text=f"💌 <b>Сообщение от администратора:</b>\n\n{message_text}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        
        # Сохраняем в базу
        message_id = await db.send_admin_message(
            from_user_id=message.from_user.id,
            to_user_id=target_user_id,
            message_text=message_text,
            context={"type": "admin_to_user"}
        )
        
        # Подтверждение админу
        username = user_info.get('username') or user_info.get('first_name') or f"user_{target_user_id}"
        
        await message.reply(
            f"✅ <b>Сообщение отправлено!</b>\n\n"
            f"👤 Кому: {username} (ID: {target_user_id})\n"
            f"📝 Текст: {message_text[:100]}{'...' if len(message_text) > 100 else ''}\n"
            f"🆔 Message ID: {message_id}",
            parse_mode="HTML"
        )
        
    except ValueError:
        await message.reply("❌ Неверный формат user_id. Должно быть число.")
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения: {e}", exc_info=True)
        await message.reply(f"❌ Ошибка: {str(e)}")


@router.callback_query(F.data.startswith("reply_to_admin_"))
async def reply_to_admin_button(callback: types.CallbackQuery, state: FSMContext):
    """Пользователь нажал кнопку 'Ответить' на сообщение от админа"""
    try:
        admin_id = int(callback.data.split("_")[-1])
        
        await state.update_data(replying_to_admin=admin_id)
        await state.set_state(AdminStates.waiting_user_reply)
        
        await callback.message.answer(
            "✍️ <b>Напишите ваш ответ:</b>\n\n"
            "Ваше сообщение будет отправлено администратору.",
            parse_mode="HTML"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка reply_to_admin: {e}")
        await callback.answer("❌ Ошибка")


@router.message(StateFilter(AdminStates.waiting_user_reply))
async def handle_user_reply_to_admin(message: types.Message, state: FSMContext):
    """Обработка ответа пользователя админу"""
    try:
        data = await state.get_data()
        admin_id = data.get('replying_to_admin')
        
        if not admin_id:
            await message.reply("❌ Ошибка: потеряна информация о получателе")
            await state.clear()
            return
        
        user_id = message.from_user.id
        reply_text = message.text.strip()
        
        # Сохраняем в базу
        db = await get_db()
        message_id = await db.send_admin_message(
            from_user_id=user_id,
            to_user_id=admin_id,
            message_text=reply_text,
            context={"type": "user_to_admin"}
        )
        
        # Получаем информацию о пользователе
        user_info = await db.get_user_info_by_id(user_id)
        username = user_info.get('username') or "не указан"
        first_name = user_info.get('first_name') or f"user_{user_id}"
        
        # Отправляем админу
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        
        keyboard = [
            [InlineKeyboardButton(text="✉️ Ответить пользователю", callback_data=f"quick_reply_{user_id}")]
        ]
        
        admin_message = (
            f"📨 <b>Ответ от пользователя:</b>\n\n"
            f"👤 <b>Имя:</b> {first_name}\n"
            f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
            f"👤 <b>Username:</b> @{username if username != 'не указан' else username}\n\n"
            f"💬 <b>Сообщение:</b>\n{reply_text}"
        )
        
        await message.bot.send_message(
            chat_id=admin_id,
            text=admin_message,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        
        # Подтверждение пользователю
        await message.reply(
            "✅ <b>Ваш ответ отправлен администратору!</b>",
            parse_mode="HTML"
        )
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка обработки ответа: {e}", exc_info=True)
        await message.reply("❌ Ошибка отправки")
        await state.clear()


@router.callback_query(F.data.startswith("quick_reply_"))
async def quick_reply_button(callback: types.CallbackQuery, state: FSMContext):
    """Админ нажал кнопку 'Ответить пользователю'"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав")
        return
    
    try:
        target_user_id = int(callback.data.split("_")[-1])
        
        # Получаем информацию о пользователе
        db = await get_db()
        user_info = await db.get_user_info_by_id(target_user_id)
        
        if not user_info:
            await callback.answer("❌ Пользователь не найден", show_alert=True)
            return
        
        username = user_info.get('username') or user_info.get('first_name') or f"user_{target_user_id}"
        
        await state.update_data(quick_reply_to=target_user_id)
        await state.set_state(AdminStates.waiting_admin_reply)
        
        await callback.message.answer(
            f"✍️ <b>Ответ пользователю {username}</b>\n\n"
            f"Напишите текст сообщения:",
            parse_mode="HTML"
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка quick_reply: {e}")
        await callback.answer("❌ Ошибка")


@router.message(StateFilter(AdminStates.waiting_admin_reply))
async def handle_admin_quick_reply(message: types.Message, state: FSMContext):
    """Обработка быстрого ответа админа"""
    if not is_admin(message.from_user.id):
        await message.reply("❌ Нет прав")
        await state.clear()
        return
    
    try:
        data = await state.get_data()
        target_user_id = data.get('quick_reply_to')
        
        if not target_user_id:
            await message.reply("❌ Ошибка: потеряна информация о получателе")
            await state.clear()
            return
        
        reply_text = message.text.strip()
        
        # Отправляем сообщение пользователю
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        
        keyboard = [
            [InlineKeyboardButton(text="✉️ Ответить", callback_data=f"reply_to_admin_{message.from_user.id}")]
        ]
        
        await message.bot.send_message(
            chat_id=target_user_id,
            text=f"💌 <b>Сообщение от администратора:</b>\n\n{reply_text}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        
        # Сохраняем в базу
        db = await get_db()
        message_id = await db.send_admin_message(
            from_user_id=message.from_user.id,
            to_user_id=target_user_id,
            message_text=reply_text,
            context={"type": "admin_reply"}
        )
        
        # Подтверждение админу
        await message.reply(
            f"✅ <b>Сообщение отправлено!</b>\n\n"
            f"👤 Кому: ID {target_user_id}\n"
            f"🆔 Message ID: {message_id}",
            parse_mode="HTML"
        )
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка отправки ответа: {e}", exc_info=True)
        await message.reply("❌ Ошибка отправки")
        await state.clear()


@router.message(Command("reply"))
async def reply_to_user_command(message: types.Message, state: FSMContext):
    """
    Альтернативная команда /reply для ответа пользователю
    Формат: /reply {user_id} {текст}
    """
    if not is_admin(message.from_user.id):
        await message.reply("❌ У вас нет прав администратора")
        return
    
    # Используем ту же логику что и /send
    await send_message_to_user_command(message, state)


@router.message(Command("messages"))
async def view_messages_command(message: types.Message):
    """Просмотр истории сообщений (для админов)"""
    if not is_admin(message.from_user.id):
        await message.reply("❌ У вас нет прав администратора")
        return
    
    try:
        db = await get_db()
        messages = await db.get_user_messages(message.from_user.id, limit=20)
        
        if not messages:
            await message.reply("📭 <b>История сообщений пуста</b>", parse_mode="HTML")
            return
        
        text = "📬 <b>История сообщений (последние 20):</b>\n\n"
        
        for msg in messages:
            date = msg['sent_at'].strftime('%d.%m %H:%M')
            
            if msg['from_user_id'] == message.from_user.id:
                # Исходящее
                to_name = msg.get('to_username') or msg.get('to_first_name') or f"user_{msg['to_user_id']}"
                direction = "→"
                text += f"<b>{date}</b> {direction} {to_name}\n"
            else:
                # Входящее
                from_name = msg.get('from_username') or msg.get('from_first_name') or f"user_{msg['from_user_id']}"
                direction = "←"
                text += f"<b>{date}</b> {direction} {from_name}\n"
            
            preview = msg['message_text'][:50] + "..." if len(msg['message_text']) > 50 else msg['message_text']
            text += f"   {preview}\n\n"
        
        await message.reply(text, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Ошибка просмотра сообщений: {e}", exc_info=True)
        await message.reply("❌ Ошибка загрузки")


@router.message(Command("users"))
async def list_users_command(message: types.Message):
    """Список активных пользователей (для админов)"""
    if not is_admin(message.from_user.id):
        await message.reply("❌ У вас нет прав администратора")
        return
    
    try:
        db = await get_db()
        
        async with db.pool.acquire() as conn:
            # Последние 20 активных пользователей
            users = await conn.fetch("""
                SELECT user_id, username, first_name, last_activity, 
                       plants_count, total_waterings, questions_asked
                FROM users
                WHERE last_activity IS NOT NULL
                ORDER BY last_activity DESC
                LIMIT 20
            """)
        
        if not users:
            await message.reply("📭 <b>Пользователи не найдены</b>", parse_mode="HTML")
            return
        
        text = "👥 <b>Последние 20 активных пользователей:</b>\n\n"
        
        for user in users:
            username = user['username'] or user['first_name'] or f"user_{user['user_id']}"
            last_activity = user['last_activity'].strftime('%d.%m %H:%M') if user['last_activity'] else 'никогда'
            
            text += f"👤 <b>{username}</b>\n"
            text += f"   🆔 ID: <code>{user['user_id']}</code>\n"
            text += f"   📅 Активность: {last_activity}\n"
            text += f"   🌱 Растений: {user['plants_count']}, 💧 Поливов: {user['total_waterings']}\n\n"
        
        await message.reply(text, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Ошибка списка пользователей: {e}", exc_info=True)
        await message.reply("❌ Ошибка загрузки")


@router.message(Command("debug_reminders"))
async def debug_reminders_command(message: types.Message):
    """Диагностика напоминаний"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        db = await get_db()
        async with db.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT p.id, 
                       COALESCE(p.custom_name, p.plant_name, 'Растение #' || p.id) as name,
                       p.watering_interval,
                       p.last_watered::date,
                       r.next_date::date,
                       r.last_sent::date,
                       (r.next_date::date <= CURRENT_DATE) as should_fire
                FROM plants p
                JOIN reminders r ON r.plant_id = p.id 
                    AND r.reminder_type = 'watering' 
                    AND r.is_active = TRUE
                WHERE p.plant_type = 'regular'
                ORDER BY r.next_date ASC
                LIMIT 20
            """)
        
        text = "🔍 <b>Диагностика напоминаний:</b>\n\n"
        for r in rows:
            fire = "🔥" if r['should_fire'] else "⏳"
            text += (
                f"{fire} <b>{r['name']}</b> (ID={r['id']})\n"
                f"   Интервал: {r['watering_interval']}д, "
                f"Полив: {r['last_watered'] or 'никогда'}\n"
                f"   Next: {r['next_date']}, "
                f"LastSent: {r['last_sent'] or 'никогда'}\n\n"
            )
        
        if not rows:
            text += "❌ Нет активных напоминаний"
        
        await message.reply(text, parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")


@router.message(Command("fix_reminders"))
async def fix_reminders_command(message: types.Message):
    """Исправить просроченные напоминания"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        db = await get_db()
        async with db.pool.acquire() as conn:
            # Сбрасываем next_date на сегодня для растений,
            # которые не поливались дольше своего интервала
            result = await conn.execute("""
                UPDATE reminders r
                SET next_date = CURRENT_DATE,
                    last_sent = NULL
                FROM plants p
                WHERE r.plant_id = p.id
                  AND r.reminder_type = 'watering'
                  AND r.is_active = TRUE
                  AND p.plant_type = 'regular'
                  AND (
                    p.last_watered IS NULL 
                    OR p.last_watered::date + p.watering_interval <= CURRENT_DATE
                  )
            """)
            
            count = int(result.split()[-1])
        
        await message.reply(
            f"✅ <b>Исправлено {count} напоминаний</b>\n\n"
            f"Завтра в 09:00 МСК они будут отправлены.",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")
