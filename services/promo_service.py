"""
Сервис промокодов.

Жизненный цикл активации (promo_activations.status):
    entered         — ввёл код, скидка закреплена за пользователем
    payment_created — создал платёж со скидкой, но ещё не оплатил
    paid            — оплата прошла (или 100%-код активирован без оплаты)
    replaced        — ввёл другой код поверх этого
    removed         — убрал код вручную

used_count у промокода растёт только по статусу paid.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

from database import get_db

logger = logging.getLogger(__name__)

PROMO_ERRORS = {
    'not_found': "❌ Такого промокода нет. Проверьте написание и попробуйте ещё раз.",
    'inactive': "❌ Этот промокод больше не действует.",
    'expired': "⏰ Срок действия этого промокода истёк.",
    'exhausted': "😔 Лимит активаций этого промокода исчерпан.",
    'already_used': "❌ Вы уже использовали этот промокод.",
}


def normalize_code(code: str) -> str:
    return code.strip().upper()


def calc_price(promo: Dict, price: int) -> int:
    """Цена тарифа с учётом промокода (0 = бесплатно)"""
    if promo['discount_type'] == 'percent':
        discounted = price * (100 - promo['discount_value']) // 100
    else:
        discounted = price - promo['discount_value']
    return max(discounted, 0)


def discount_label(promo: Dict) -> str:
    """Человекочитаемый размер скидки: «−25%» или «−500₽»"""
    if promo['discount_type'] == 'percent':
        return f"−{promo['discount_value']}%"
    return f"−{promo['discount_value']}₽"


def _is_valid(promo: Dict, now: datetime) -> bool:
    if not promo['is_active']:
        return False
    if promo['valid_until'] and promo['valid_until'] <= now:
        return False
    if promo['max_uses'] is not None and promo['used_count'] >= promo['max_uses']:
        return False
    return True


async def validate_promo(code: str, user_id: int) -> Tuple[Optional[Dict], Optional[str]]:
    """
    Проверить код при вводе.
    Возвращает (promo, None) или (None, ключ ошибки из PROMO_ERRORS).
    """
    code = normalize_code(code)
    db = await get_db()
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM promo_codes WHERE code = $1", code)
        if not row:
            return None, 'not_found'

        promo = dict(row)
        now = datetime.now()

        if not promo['is_active']:
            return None, 'inactive'
        if promo['valid_until'] and promo['valid_until'] <= now:
            return None, 'expired'
        if promo['max_uses'] is not None and promo['used_count'] >= promo['max_uses']:
            return None, 'exhausted'

        already = await conn.fetchval("""
            SELECT COUNT(*) FROM promo_activations
            WHERE promo_id = $1 AND user_id = $2 AND status = 'paid'
        """, promo['id'], user_id)
        if already:
            return None, 'already_used'

    return promo, None


async def apply_promo(user_id: int, promo_id: int):
    """Закрепить код за пользователем (статус entered). Прежний применённый код замещается."""
    db = await get_db()
    async with db.pool.acquire() as conn:
        await conn.execute("""
            UPDATE promo_activations
            SET status = 'replaced', updated_at = CURRENT_TIMESTAMP
            WHERE user_id = $1 AND status IN ('entered', 'payment_created')
        """, user_id)
        await conn.execute("""
            INSERT INTO promo_activations (promo_id, user_id, status)
            VALUES ($1, $2, 'entered')
        """, promo_id, user_id)
    logger.info(f"🎁 Промокод id={promo_id} применён пользователем {user_id}")


async def get_attached_promo(user_id: int) -> Optional[Dict]:
    """
    Промокод, закреплённый за пользователем (ввёл, но ещё не оплатил).
    Возвращает None, если кода нет или он успел протухнуть/исчерпаться.
    """
    db = await get_db()
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT pc.*
            FROM promo_activations pa
            JOIN promo_codes pc ON pc.id = pa.promo_id
            WHERE pa.user_id = $1 AND pa.status IN ('entered', 'payment_created')
            ORDER BY pa.created_at DESC
            LIMIT 1
        """, user_id)

    if not row:
        return None
    promo = dict(row)
    if not _is_valid(promo, datetime.now()):
        return None
    return promo


async def remove_promo(user_id: int):
    """Пользователь убрал код вручную"""
    db = await get_db()
    async with db.pool.acquire() as conn:
        await conn.execute("""
            UPDATE promo_activations
            SET status = 'removed', updated_at = CURRENT_TIMESTAMP
            WHERE user_id = $1 AND status IN ('entered', 'payment_created')
        """, user_id)


async def mark_payment_created(user_id: int, payment_id: str, plan_id: str, amount: int):
    """Пользователь дошёл до создания платежа со скидкой"""
    db = await get_db()
    async with db.pool.acquire() as conn:
        await conn.execute("""
            UPDATE promo_activations
            SET status = 'payment_created', payment_id = $2, plan_id = $3,
                amount = $4, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = $1 AND status IN ('entered', 'payment_created')
        """, user_id, payment_id, plan_id, amount)


async def confirm_paid_by_payment(user_id: int, code: str, payment_id: str):
    """Вебхук: оплата с промокодом прошла — фиксируем использование"""
    code = normalize_code(code)
    db = await get_db()
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE promo_activations pa
            SET status = 'paid', payment_id = $3, updated_at = CURRENT_TIMESTAMP
            FROM promo_codes pc
            WHERE pa.promo_id = pc.id
              AND pa.user_id = $1 AND pc.code = $2
              AND pa.status IN ('entered', 'payment_created')
            RETURNING pa.promo_id
        """, user_id, code, payment_id)

        if row:
            await conn.execute("""
                UPDATE promo_codes SET used_count = used_count + 1 WHERE id = $1
            """, row['promo_id'])
            logger.info(f"✅ Промокод {code} использован (оплата {payment_id}, user_id={user_id})")


async def confirm_free_activation(user_id: int, promo_id: int, plan_id: str):
    """100%-код: подписка выдана без оплаты"""
    db = await get_db()
    async with db.pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE promo_activations
            SET status = 'paid', plan_id = $3, amount = 0, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = $1 AND promo_id = $2
              AND status IN ('entered', 'payment_created')
        """, user_id, promo_id, plan_id)

        if result != 'UPDATE 0':
            await conn.execute("""
                UPDATE promo_codes SET used_count = used_count + 1 WHERE id = $1
            """, promo_id)
            logger.info(f"🎉 Бесплатная активация по промокоду id={promo_id}, user_id={user_id}")


# === АДМИН ===

async def create_promo(code: str, discount_type: str, value: int,
                       max_uses: int = None, valid_days: int = None,
                       created_by: int = None) -> Tuple[Optional[Dict], Optional[str]]:
    """Создать промокод. Возвращает (promo, None) или (None, текст ошибки)."""
    code = normalize_code(code)

    if discount_type not in ('percent', 'fixed'):
        return None, "Тип скидки должен быть percent или fixed"
    if discount_type == 'percent' and not (1 <= value <= 100):
        return None, "Процент должен быть от 1 до 100"
    if discount_type == 'fixed' and value < 1:
        return None, "Сумма скидки должна быть больше 0"

    valid_until = datetime.now() + timedelta(days=valid_days) if valid_days else None

    db = await get_db()
    async with db.pool.acquire() as conn:
        exists = await conn.fetchval("SELECT id FROM promo_codes WHERE code = $1", code)
        if exists:
            return None, f"Код {code} уже существует (id={exists})"

        row = await conn.fetchrow("""
            INSERT INTO promo_codes (code, discount_type, discount_value, max_uses, valid_until, created_by)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING *
        """, code, discount_type, value, max_uses, valid_until, created_by)

    logger.info(f"🎟️ Создан промокод {code}: {discount_type} {value}, uses={max_uses}, until={valid_until}")
    return dict(row), None


async def list_promos(limit: int = 30) -> list:
    db = await get_db()
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM promo_codes ORDER BY created_at DESC LIMIT $1
        """, limit)
    return [dict(r) for r in rows]


async def get_promo_by_id(promo_id: int) -> Optional[Dict]:
    db = await get_db()
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM promo_codes WHERE id = $1", promo_id)
    return dict(row) if row else None


async def toggle_promo(promo_id: int) -> Optional[bool]:
    """Включить/выключить код. Возвращает новое состояние is_active или None."""
    db = await get_db()
    async with db.pool.acquire() as conn:
        new_state = await conn.fetchval("""
            UPDATE promo_codes SET is_active = NOT is_active
            WHERE id = $1
            RETURNING is_active
        """, promo_id)
    return new_state


async def delete_promo(promo_id: int) -> Optional[str]:
    """
    Удалить код. Если по нему уже были оплаты — только деактивация
    (историю активаций не теряем). Возвращает 'deleted' | 'deactivated' | None.
    """
    db = await get_db()
    async with db.pool.acquire() as conn:
        paid = await conn.fetchval("""
            SELECT COUNT(*) FROM promo_activations WHERE promo_id = $1 AND status = 'paid'
        """, promo_id)

        if paid:
            updated = await conn.fetchval("""
                UPDATE promo_codes SET is_active = FALSE WHERE id = $1 RETURNING id
            """, promo_id)
            return 'deactivated' if updated else None

        deleted = await conn.fetchval("""
            DELETE FROM promo_codes WHERE id = $1 RETURNING id
        """, promo_id)
        return 'deleted' if deleted else None


async def promo_funnel(promo_id: int) -> Dict:
    """Воронка по коду: ввели → дошли до оплаты → оплатили + выручка"""
    db = await get_db()
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT status, COUNT(*) as cnt, COALESCE(SUM(amount), 0) as amount_sum
            FROM promo_activations
            WHERE promo_id = $1
            GROUP BY status
        """, promo_id)

    by_status = {r['status']: dict(r) for r in rows}
    entered_total = sum(r['cnt'] for r in rows)  # все, кто вводил (включая заменивших/убравших)
    paid = by_status.get('paid', {}).get('cnt', 0)
    return {
        'entered_total': entered_total,
        'waiting': by_status.get('entered', {}).get('cnt', 0),
        'payment_created': by_status.get('payment_created', {}).get('cnt', 0),
        'paid': paid,
        'revenue': by_status.get('paid', {}).get('amount_sum', 0),
    }
