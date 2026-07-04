"""
Activity Tracking Middleware
Отслеживает активность пользователей для статистики
"""

import logging
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

logger = logging.getLogger(__name__)


class ActivityTrackingMiddleware(BaseMiddleware):
    """Middleware для отслеживания активности пользователей"""
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        """
        Обновляет last_activity при каждом взаимодействии пользователя с ботом
        """
        user: User = data.get("event_from_user")
        
        if user:
            try:
                # Импортируем здесь чтобы избежать циклических импортов
                from database import get_db
                from utils.time_utils import get_moscow_now
                
                db = await get_db()
                moscow_now = get_moscow_now().replace(tzinfo=None)
                
                # Обновляем last_activity
                async with db.pool.acquire() as conn:
                    await conn.execute("""
                        UPDATE users 
                        SET last_activity = $1
                        WHERE user_id = $2
                    """, moscow_now, user.id)
                
            except Exception as e:
                # Не прерываем обработку события при ошибке
                logger.error(f"Ошибка обновления активности: {e}")
        
        # Продолжаем обработку события
        return await handler(event, data)
