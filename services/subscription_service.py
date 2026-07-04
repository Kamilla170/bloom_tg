import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

from database import get_db
from config import FREE_LIMITS, PRO_DURATION_DAYS, PRO_GRACE_PERIOD_DAYS, PRO_PRICE, ADMIN_USER_IDS

logger = logging.getLogger(__name__)


async def ensure_plan_columns():
    """Миграция: добавляем plan_amount и plan_days в subscriptions"""
    db = await get_db()
    async with db.pool.acquire() as conn:
        await conn.execute("""
            ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS plan_amount INTEGER DEFAULT 199;
        """)
        await conn.execute("""
            ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS plan_days INTEGER DEFAULT 30;
        """)
    logger.info("✅ Миграция plan_amount/plan_days применена")


async def get_user_plan(user_id: int) -> Dict:
    """
    Получить текущий план пользователя.
    
    Возвращает:
        {
            'plan': 'free' | 'pro',
            'expires_at': datetime | None,
            'is_grace_period': bool,
            'days_left': int | None,
            'auto_pay': bool,
        }
    """
    db = await get_db()
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT plan, expires_at, auto_pay_method_id, granted_by_admin
            FROM subscriptions
            WHERE user_id = $1
        """, user_id)
    
    if not row or row['plan'] == 'free':
        return {
            'plan': 'free',
            'expires_at': None,
            'is_grace_period': False,
            'days_left': None,
            'auto_pay': False,
        }
    
    now = datetime.now()
    expires_at = row['expires_at']
    
    if expires_at and expires_at > now:
        days_left = (expires_at - now).days
        return {
            'plan': 'pro',
            'expires_at': expires_at,
            'is_grace_period': False,
            'days_left': days_left,
            'auto_pay': bool(row['auto_pay_method_id']),
        }
    
    # Проверяем grace period
    if expires_at:
        grace_end = expires_at + timedelta(days=PRO_GRACE_PERIOD_DAYS)
        if now < grace_end:
            return {
                'plan': 'pro',
                'expires_at': expires_at,
                'is_grace_period': True,
                'days_left': 0,
                'auto_pay': bool(row['auto_pay_method_id']),
            }
    
    # Подписка истекла — переводим на free
    await downgrade_to_free(user_id)
    return {
        'plan': 'free',
        'expires_at': None,
        'is_grace_period': False,
        'days_left': None,
        'auto_pay': False,
    }


async def is_pro(user_id: int) -> bool:
    """Быстрая проверка — PRO ли пользователь"""
    # Админы всегда PRO
    if user_id in ADMIN_USER_IDS:
        return True
    plan = await get_user_plan(user_id)
    return plan['plan'] == 'pro'


async def check_limit(user_id: int, action: str) -> Tuple[bool, Optional[str]]:
    """
    Проверить лимит действия.
    
    action: 'plants' | 'analyses' | 'questions'
    
    Возвращает:
        (allowed: bool, error_message: str | None)
    """
    # Админы без лимитов
    if user_id in ADMIN_USER_IDS:
        return True, None
    
    # PRO без лимитов
    if await is_pro(user_id):
        return True, None
    
    db = await get_db()
    usage = await get_or_create_usage(user_id)
    
    limit = FREE_LIMITS.get(action, 0)
    
    if action == 'plants':
        # Для растений проверяем общее количество в коллекции
        async with db.pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM plants WHERE user_id = $1 AND plant_type = 'regular'",
                user_id
            )
        if count >= limit:
            return False, (
                f"🌱 Достигнут лимит бесплатного плана: <b>{limit} растений</b>\n\n"
                f"Оформите <b>подписку</b> для неограниченного доступа!"
            )
        return True, None
    
    elif action == 'analyses':
        if usage['analyses_used'] >= limit:
            return False, (
                f"📸 Достигнут лимит бесплатного плана: <b>{limit} анализа фото</b> в месяц\n\n"
                f"Оформите <b>подписку</b> для неограниченного доступа!"
            )
        return True, None
    
    elif action == 'questions':
        if usage['questions_used'] >= limit:
            return False, (
                f"🤖 Достигнут лимит бесплатного плана: <b>{limit} вопроса</b> в месяц\n\n"
                f"Оформите <b>подписку</b> для неограниченного доступа!"
            )
        return True, None
    
    return True, None


async def increment_usage(user_id: int, action: str):
    """
    Увеличить счётчик использования.
    
    action: 'analyses' | 'questions'
    """
    if await is_pro(user_id):
        return
    
    db = await get_db()
    await get_or_create_usage(user_id)
    
    column_map = {
        'analyses': 'analyses_used',
        'questions': 'questions_used',
    }
    
    column = column_map.get(action)
    if not column:
        return
    
    async with db.pool.acquire() as conn:
        await conn.execute(f"""
            UPDATE usage_limits
            SET {column} = {column} + 1
            WHERE user_id = $1
        """, user_id)


async def get_or_create_usage(user_id: int) -> Dict:
    """Получить или создать запись использования"""
    db = await get_db()
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM usage_limits WHERE user_id = $1", user_id
        )
        
        if row:
            # Проверяем нужен ли сброс (новый месяц)
            now = datetime.now()
            if row['reset_date'] and row['reset_date'] <= now:
                next_reset = (now.replace(day=1) + timedelta(days=32)).replace(day=1)
                await conn.execute("""
                    UPDATE usage_limits
                    SET analyses_used = 0, questions_used = 0, reset_date = $2
                    WHERE user_id = $1
                """, user_id, next_reset)
                return {
                    'analyses_used': 0,
                    'questions_used': 0,
                    'reset_date': next_reset,
                }
            return dict(row)
        
        # Создаём новую запись
        now = datetime.now()
        next_reset = (now.replace(day=1) + timedelta(days=32)).replace(day=1)
        await conn.execute("""
            INSERT INTO usage_limits (user_id, analyses_used, questions_used, reset_date)
            VALUES ($1, 0, 0, $2)
            ON CONFLICT (user_id) DO NOTHING
        """, user_id, next_reset)
        
        return {
            'analyses_used': 0,
            'questions_used': 0,
            'reset_date': next_reset,
        }


async def get_usage_stats(user_id: int) -> Dict:
    """Получить статистику использования для отображения"""
    plan_info = await get_user_plan(user_id)
    usage = await get_or_create_usage(user_id)
    
    db = await get_db()
    async with db.pool.acquire() as conn:
        plants_count = await conn.fetchval(
            "SELECT COUNT(*) FROM plants WHERE user_id = $1 AND plant_type = 'regular'",
            user_id
        )
    
    return {
        'plan': plan_info['plan'],
        'expires_at': plan_info.get('expires_at'),
        'days_left': plan_info.get('days_left'),
        'auto_pay': plan_info.get('auto_pay', False),
        'is_grace_period': plan_info.get('is_grace_period', False),
        'plants_count': plants_count or 0,
        'plants_limit': FREE_LIMITS['plants'] if plan_info['plan'] == 'free' else '∞',
        'analyses_used': usage['analyses_used'],
        'analyses_limit': FREE_LIMITS['analyses'] if plan_info['plan'] == 'free' else '∞',
        'questions_used': usage['questions_used'],
        'questions_limit': FREE_LIMITS['questions'] if plan_info['plan'] == 'free' else '∞',
    }


async def activate_pro(user_id: int, days: int = PRO_DURATION_DAYS, amount: int = None,
                       payment_method_id: str = None, granted_by: int = None):
    """Активировать PRO подписку"""
    db = await get_db()
    now = datetime.now()
    
    if amount is None:
        amount = PRO_PRICE
    
    # Миграция на случай первого запуска
    await ensure_plan_columns()
    
    async with db.pool.acquire() as conn:
        # Проверяем существующую подписку
        existing = await conn.fetchrow(
            "SELECT expires_at, plan FROM subscriptions WHERE user_id = $1", user_id
        )
        
        if existing and existing['plan'] == 'pro' and existing['expires_at'] and existing['expires_at'] > now:
            # Продлеваем от текущей даты окончания
            expires_at = existing['expires_at'] + timedelta(days=days)
        else:
            expires_at = now + timedelta(days=days)
        
        await conn.execute("""
            INSERT INTO subscriptions (user_id, plan, expires_at, auto_pay_method_id, 
                                       granted_by_admin, plan_amount, plan_days, updated_at)
            VALUES ($1, 'pro', $2, $3, $4, $5, $6, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id) 
            DO UPDATE SET 
                plan = 'pro',
                expires_at = $2,
                auto_pay_method_id = COALESCE($3, subscriptions.auto_pay_method_id),
                granted_by_admin = $4,
                plan_amount = $5,
                plan_days = $6,
                updated_at = CURRENT_TIMESTAMP
        """, user_id, expires_at, payment_method_id, granted_by, amount, days)
    
    logger.info(f"✅ PRO активирован для user_id={user_id}, {amount}₽/{days}д, expires={expires_at}")
    return expires_at


async def downgrade_to_free(user_id: int):
    """Понизить до бесплатного плана"""
    db = await get_db()
    async with db.pool.acquire() as conn:
        await conn.execute("""
            UPDATE subscriptions
            SET plan = 'free', auto_pay_method_id = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = $1
        """, user_id)
    
    logger.info(f"⬇️ Пользователь {user_id} переведён на FREE план")


async def revoke_pro(user_id: int):
    """Отозвать PRO (админ-команда)"""
    await downgrade_to_free(user_id)


async def reset_all_usage_limits():
    """Сброс лимитов у всех пользователей (вызывается 1 числа)"""
    db = await get_db()
    now = datetime.now()
    next_reset = (now.replace(day=1) + timedelta(days=32)).replace(day=1)
    
    async with db.pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE usage_limits
            SET analyses_used = 0, questions_used = 0, reset_date = $1
            WHERE reset_date <= $2
        """, next_reset, now)
    
    logger.info(f"🔄 Лимиты использования сброшены, следующий сброс: {next_reset}")


async def get_expiring_subscriptions(days_before: int = 1) -> list:
    """Получить подписки, истекающие через N дней (для автоплатежей)"""
    db = await get_db()
    now = datetime.now()
    target_date = now + timedelta(days=days_before)
    
    await ensure_plan_columns()
    
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT s.user_id, s.expires_at, s.auto_pay_method_id,
                   COALESCE(s.plan_amount, 199) as plan_amount,
                   COALESCE(s.plan_days, 30) as plan_days
            FROM subscriptions s
            WHERE s.plan = 'pro'
              AND s.auto_pay_method_id IS NOT NULL
              AND s.expires_at BETWEEN $1 AND $2
              AND s.granted_by_admin IS NULL
        """, now, target_date)
    
    return [dict(row) for row in rows]
async def has_apology_discount(user_id: int) -> bool:
    """Проверяет активна ли у пользователя скидка-извинение 40%"""
    db = await get_db()
    async with db.pool.acquire() as conn:
        until = await conn.fetchval("""
            SELECT apology_discount_until FROM users WHERE user_id = $1
        """, user_id)
    
    if not until:
        return False
    
    now = datetime.now()
    if until.tzinfo:
        until = until.replace(tzinfo=None)
    
    return until > now
