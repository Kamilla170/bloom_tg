import logging
import uuid
import aiohttp
from datetime import datetime
from typing import Dict, Optional
from base64 import b64encode

from config import YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY, PRO_PRICE, WEBHOOK_URL

logger = logging.getLogger(__name__)

YOOKASSA_API_URL = "https://api.yookassa.ru/v3"


def _get_auth_header() -> str:
    """Basic Auth header для YooKassa"""
    credentials = f"{YOOKASSA_SHOP_ID}:{YOOKASSA_SECRET_KEY}"
    encoded = b64encode(credentials.encode()).decode()
    return f"Basic {encoded}"


def _get_headers(idempotency_key: str = None) -> dict:
    """Заголовки для запросов к YooKassa"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": _get_auth_header(),
    }
    if idempotency_key:
        headers["Idempotence-Key"] = idempotency_key
    return headers


async def create_payment(user_id: int, amount: int = None, days: int = 30,
                         plan_label: str = "1 месяц", save_method: bool = True) -> Optional[Dict]:
    """
    Создать платёж в YooKassa.
    
    Args:
        user_id: ID пользователя Telegram
        amount: сумма платежа в рублях
        days: количество дней подписки
        plan_label: название тарифа для описания
        save_method: сохранить метод оплаты для автоплатежей
    
    Returns:
        dict с payment_id, confirmation_url, status или None
    """
    if not YOOKASSA_SHOP_ID or not YOOKASSA_SECRET_KEY:
        logger.error("❌ YooKassa не настроена: YOOKASSA_SHOP_ID или YOOKASSA_SECRET_KEY отсутствуют")
        return None
    
    if amount is None:
        amount = PRO_PRICE
    
    idempotency_key = str(uuid.uuid4())
    
    return_url = WEBHOOK_URL or "https://t.me/bloom_ai_bot"
    
    description = f"Bloom AI подписка — {plan_label} (пользователь {user_id})"
    
    payload = {
        "amount": {
            "value": f"{amount}.00",
            "currency": "RUB"
        },
        "capture": True,
        "confirmation": {
            "type": "redirect",
            "return_url": return_url
        },
        "description": description,
        "metadata": {
            "user_id": str(user_id),
            "type": "subscription",
            "days": str(days),
            "amount": str(amount),
            "plan_label": plan_label,
        },
        "save_payment_method": save_method,
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{YOOKASSA_API_URL}/payments",
                headers=_get_headers(idempotency_key),
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                data = await resp.json()
                
                if resp.status == 200:
                    logger.info(f"✅ Платёж создан: {data['id']} для user_id={user_id}, {plan_label}, {amount}₽")
                    
                    # Сохраняем платёж в БД
                    from database import get_db
                    db = await get_db()
                    async with db.pool.acquire() as conn:
                        await conn.execute("""
                            INSERT INTO payments (payment_id, user_id, amount, currency, status, description, created_at)
                            VALUES ($1, $2, $3, 'RUB', $4, $5, CURRENT_TIMESTAMP)
                        """, data['id'], user_id, amount, data['status'], description)
                    
                    return {
                        'payment_id': data['id'],
                        'confirmation_url': data['confirmation']['confirmation_url'],
                        'status': data['status'],
                    }
                else:
                    logger.error(f"❌ Ошибка создания платежа: {resp.status} {data}")
                    return None
                    
    except Exception as e:
        logger.error(f"❌ Ошибка запроса к YooKassa: {e}", exc_info=True)
        return None


async def create_recurring_payment(user_id: int, payment_method_id: str,
                                   amount: int = None, days: int = 30) -> Optional[Dict]:
    """
    Создать рекуррентный (автоматический) платёж.
    
    Args:
        user_id: ID пользователя
        payment_method_id: сохранённый метод оплаты
        amount: сумма списания
        days: количество дней продления
    """
    if not YOOKASSA_SHOP_ID or not YOOKASSA_SECRET_KEY:
        return None
    
    if amount is None:
        amount = PRO_PRICE
    
    idempotency_key = str(uuid.uuid4())
    
    payload = {
        "amount": {
            "value": f"{amount}.00",
            "currency": "RUB"
        },
        "capture": True,
        "payment_method_id": payment_method_id,
        "description": f"Bloom AI — автопродление {days}д (пользователь {user_id})",
        "metadata": {
            "user_id": str(user_id),
            "type": "recurring",
            "days": str(days),
            "amount": str(amount),
        }
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{YOOKASSA_API_URL}/payments",
                headers=_get_headers(idempotency_key),
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                data = await resp.json()
                
                if resp.status == 200:
                    logger.info(f"✅ Рекуррентный платёж создан: {data['id']} для user_id={user_id}, {amount}₽/{days}д")
                    
                    from database import get_db
                    db = await get_db()
                    async with db.pool.acquire() as conn:
                        await conn.execute("""
                            INSERT INTO payments (payment_id, user_id, amount, currency, status, description, is_recurring, created_at)
                            VALUES ($1, $2, $3, 'RUB', $4, $5, TRUE, CURRENT_TIMESTAMP)
                        """, data['id'], user_id, amount, data['status'], payload['description'])
                    
                    return {
                        'payment_id': data['id'],
                        'status': data['status'],
                    }
                else:
                    logger.error(f"❌ Ошибка рекуррентного платежа: {resp.status} {data}")
                    return None
                    
    except Exception as e:
        logger.error(f"❌ Ошибка рекуррентного платежа: {e}", exc_info=True)
        return None


async def handle_payment_webhook(payload: dict) -> bool:
    """
    Обработка webhook от YooKassa.
    """
    try:
        event_type = payload.get('event')
        payment_data = payload.get('object', {})
        payment_id = payment_data.get('id')
        status = payment_data.get('status')
        metadata = payment_data.get('metadata', {})
        user_id = metadata.get('user_id')
        
        if not payment_id or not user_id:
            logger.warning(f"⚠️ Webhook без payment_id или user_id: {payload}")
            return False
        
        user_id = int(user_id)
        days = int(metadata.get('days', 30))
        amount = int(metadata.get('amount', PRO_PRICE))
        
        logger.info(f"💳 Webhook: event={event_type}, payment_id={payment_id}, status={status}, user_id={user_id}, {amount}₽/{days}д")
        
        from database import get_db
        db = await get_db()
        
        # Обновляем статус платежа в БД
        async with db.pool.acquire() as conn:
            await conn.execute("""
                UPDATE payments SET status = $1, updated_at = CURRENT_TIMESTAMP
                WHERE payment_id = $2
            """, status, payment_id)
        
        if event_type == 'payment.succeeded' and status == 'succeeded':
            # Получаем payment_method_id для автоплатежей
            payment_method = payment_data.get('payment_method', {})
            payment_method_id = None
            if payment_method.get('saved'):
                payment_method_id = payment_method.get('id')
                logger.info(f"💾 Сохранён метод оплаты: {payment_method_id}")
            
            # Сохраняем payment_method_id в БД
            async with db.pool.acquire() as conn:
                await conn.execute("""
                    UPDATE payments 
                    SET payment_method_id = $1, updated_at = CURRENT_TIMESTAMP
                    WHERE payment_id = $2
                """, payment_method_id, payment_id)
            
            # Активируем подписку на нужное количество дней
            from services.subscription_service import activate_pro
            expires_at = await activate_pro(
                user_id, 
                days=days,
                amount=amount,
                payment_method_id=payment_method_id
            )
            
            plan_label = metadata.get('plan_label', f'{days} дней')
            logger.info(f"✅ Подписка активирована для user_id={user_id}, план={plan_label}, expires={expires_at}")
            
            # Отправляем уведомление пользователю
            await _notify_user_payment_success(user_id, expires_at, plan_label)
            
            return True
        
        elif event_type == 'payment.canceled' and status == 'canceled':
            cancellation = payment_data.get('cancellation_details', {})
            reason = cancellation.get('reason', 'unknown')
            
            logger.warning(f"❌ Платёж отменён: user_id={user_id}, reason={reason}")
            
            # Уведомляем если это был рекуррентный платёж
            if metadata.get('type') == 'recurring':
                await _notify_user_payment_failed(user_id, reason)
            
            return True
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка обработки webhook: {e}", exc_info=True)
        return False


async def process_auto_payments():
    """
    Обработка автоплатежей — вызывается scheduler'ом ежедневно.
    Ищет подписки, истекающие завтра, и создаёт рекуррентные платежи.
    """
    from services.subscription_service import get_expiring_subscriptions
    
    expiring = await get_expiring_subscriptions(days_before=1)
    
    if not expiring:
        logger.info("💳 Нет подписок для автопродления")
        return
    
    logger.info(f"💳 Найдено {len(expiring)} подписок для автопродления")
    
    for sub in expiring:
        user_id = sub['user_id']
        method_id = sub['auto_pay_method_id']
        amount = sub.get('plan_amount', PRO_PRICE)
        days = sub.get('plan_days', 30)
        
        if not method_id:
            continue
        
        result = await create_recurring_payment(user_id, method_id, amount=amount, days=days)
        
        if result:
            logger.info(f"✅ Автоплатёж создан для user_id={user_id}: {result['payment_id']}, {amount}₽/{days}д")
        else:
            logger.error(f"❌ Не удалось создать автоплатёж для user_id={user_id}")
            await _notify_user_payment_failed(user_id, "auto_payment_creation_failed")


async def _notify_user_payment_success(user_id: int, expires_at: datetime, plan_label: str = ""):
    """Уведомить пользователя об успешной оплате"""
    try:
        from bot import bot
        
        # «Доступ навсегда» хранится как подписка на 100 лет — дату не показываем
        if expires_at.year >= 2100:
            expires_text = "📅 Активна: <b>навсегда</b> ♾"
        else:
            expires_text = f"📅 Активна до: <b>{expires_at.strftime('%d.%m.%Y')}</b>"
        plan_text = f"\n📦 Тариф: <b>{plan_label}</b>" if plan_label else ""

        await bot.send_message(
            chat_id=user_id,
            text=(
                "🎉 <b>Подписка активирована!</b>\n\n"
                f"✅ Ваш план: <b>Подписка</b>"
                f"{plan_text}\n"
                f"{expires_text}\n\n"
                "🌱 Теперь у вас безлимитный доступ:\n"
                "• Неограниченные растения\n"
                "• Безлимитные анализы фото\n"
                "• Безлимитные вопросы ИИ\n\n"
                "Спасибо за поддержку! 🙏"
            ),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"❌ Не удалось уведомить user_id={user_id}: {e}")


async def _notify_user_payment_failed(user_id: int, reason: str):
    """Уведомить пользователя о неудачной оплате"""
    try:
        from bot import bot
        from config import PRO_GRACE_PERIOD_DAYS
        
        reason_texts = {
            'insufficient_funds': 'Недостаточно средств на карте',
            'card_expired': 'Срок действия карты истёк',
            'auto_payment_creation_failed': 'Не удалось списать средства',
        }
        reason_text = reason_texts.get(reason, f'Техническая ошибка ({reason})')
        
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить вручную", callback_data="subscribe_pro")],
        ])
        
        await bot.send_message(
            chat_id=user_id,
            text=(
                "⚠️ <b>Не удалось продлить подписку</b>\n\n"
                f"Причина: {reason_text}\n\n"
                f"У вас есть ещё <b>{PRO_GRACE_PERIOD_DAYS} дня</b>, "
                "чтобы продлить подписку вручную.\n"
                "После этого аккаунт перейдёт на бесплатный план."
            ),
            parse_mode="HTML",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"❌ Не удалось уведомить user_id={user_id} о неудаче: {e}")


async def cancel_auto_payment(user_id: int):
    """Отключить автоплатёж и удалить сохранённый метод оплаты"""
    from database import get_db
    db = await get_db()
    async with db.pool.acquire() as conn:
        await conn.execute("""
            UPDATE subscriptions
            SET auto_pay_method_id = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = $1
        """, user_id)
    
    logger.info(f"🔕 Автоплатёж отключён, карта отвязана для user_id={user_id}")
