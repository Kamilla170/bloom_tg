import os
import asyncpg
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

class PlantDatabase:
    def __init__(self):
        self.database_url = os.getenv("DATABASE_URL")
        self.pool = None
        
    async def init_pool(self):
        """Инициализация пула соединений"""
        try:
            self.pool = await asyncpg.create_pool(
                self.database_url,
                min_size=2,
                max_size=10
            )
            await self.create_tables()
            logger.info("✅ База данных подключена")
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к БД: {e}")
            raise
            
    async def create_tables(self):
        """Создание таблиц"""
        async with self.pool.acquire() as conn:
            # Таблица пользователей
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    onboarding_completed BOOLEAN DEFAULT FALSE,
                    care_style_profile JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_activity TIMESTAMP,
                    last_action TEXT,
                    plants_count INTEGER DEFAULT 0,
                    total_waterings INTEGER DEFAULT 0,
                    questions_asked INTEGER DEFAULT 0,
                    tip_analysis_shown BOOLEAN DEFAULT FALSE,
                    tip_save_shown BOOLEAN DEFAULT FALSE,
                    tip_watering_shown BOOLEAN DEFAULT FALSE,
                    utm_source TEXT
                )
            """)
            
            # Таблица настроек пользователей
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id BIGINT PRIMARY KEY,
                    reminder_time TEXT DEFAULT '09:00',
                    timezone TEXT DEFAULT 'Europe/Moscow',
                    reminder_enabled BOOLEAN DEFAULT TRUE,
                    monthly_photo_reminder BOOLEAN DEFAULT TRUE,
                    last_monthly_reminder TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                )
            """)
            
            # Таблица растений
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS plants (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    analysis TEXT NOT NULL,
                    photo_file_id TEXT NOT NULL,
                    plant_name TEXT,
                    custom_name TEXT,
                    saved_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_watered TIMESTAMP,
                    watering_count INTEGER DEFAULT 0,
                    watering_interval INTEGER DEFAULT 5,
                    base_watering_interval INTEGER,
                    notes TEXT,
                    reminder_enabled BOOLEAN DEFAULT TRUE,
                    plant_type TEXT DEFAULT 'regular',
                    growing_id INTEGER,
                    current_state TEXT DEFAULT 'healthy',
                    state_changed_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    state_changes_count INTEGER DEFAULT 0,
                    growth_stage TEXT DEFAULT 'young',
                    last_photo_analysis TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    environment_data JSONB,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                )
            """)
            
            # === НОВЫЕ ТАБЛИЦЫ ДЛЯ ПОЛНОГО КОНТЕКСТА ===
            
            # Полная история всех анализов
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS plant_analyses_full (
                    id SERIAL PRIMARY KEY,
                    plant_id INTEGER NOT NULL,
                    user_id BIGINT NOT NULL,
                    analysis_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    photo_file_id TEXT NOT NULL,
                    full_analysis TEXT NOT NULL,
                    ai_model TEXT DEFAULT 'gpt-4o',
                    confidence FLOAT,
                    identified_species TEXT,
                    detected_state TEXT,
                    detected_problems JSONB,
                    recommendations JSONB,
                    watering_advice TEXT,
                    lighting_advice TEXT,
                    FOREIGN KEY (plant_id) REFERENCES plants (id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                )
            """)
            
            # История вопросов и ответов
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS plant_qa_history (
                    id SERIAL PRIMARY KEY,
                    plant_id INTEGER NOT NULL,
                    user_id BIGINT NOT NULL,
                    question_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    question_text TEXT NOT NULL,
                    answer_text TEXT NOT NULL,
                    ai_model TEXT DEFAULT 'gpt-4o',
                    context_used JSONB,
                    user_feedback TEXT,
                    follow_up_action TEXT,
                    problem_resolved BOOLEAN,
                    FOREIGN KEY (plant_id) REFERENCES plants (id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                )
            """)
            
            # История проблем и решений
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS plant_problems_log (
                    id SERIAL PRIMARY KEY,
                    plant_id INTEGER NOT NULL,
                    user_id BIGINT NOT NULL,
                    problem_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    problem_type TEXT NOT NULL,
                    problem_description TEXT,
                    suspected_cause TEXT,
                    solution_tried TEXT,
                    solution_date TIMESTAMP,
                    result TEXT,
                    resolved BOOLEAN DEFAULT FALSE,
                    resolution_date TIMESTAMP,
                    FOREIGN KEY (plant_id) REFERENCES plants (id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                )
            """)
            
            # Паттерны ухода пользователя (обучение)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS plant_user_patterns (
                    id SERIAL PRIMARY KEY,
                    plant_id INTEGER NOT NULL,
                    user_id BIGINT NOT NULL,
                    pattern_type TEXT NOT NULL,
                    pattern_data JSONB NOT NULL,
                    confidence FLOAT DEFAULT 0.5,
                    occurrences INTEGER DEFAULT 1,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (plant_id) REFERENCES plants (id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                )
            """)
            
            # Условия содержания растения
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS plant_environment (
                    id SERIAL PRIMARY KEY,
                    plant_id INTEGER NOT NULL,
                    user_id BIGINT NOT NULL,
                    location TEXT,
                    lighting TEXT,
                    humidity_level TEXT,
                    temperature_range TEXT,
                    air_circulation TEXT,
                    distance_from_window TEXT,
                    updated_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    notes TEXT,
                    FOREIGN KEY (plant_id) REFERENCES plants (id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                )
            """)
            
            # Таблица истории состояний растений
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS plant_state_history (
                    id SERIAL PRIMARY KEY,
                    plant_id INTEGER NOT NULL,
                    user_id BIGINT NOT NULL,
                    previous_state TEXT,
                    new_state TEXT NOT NULL,
                    change_reason TEXT,
                    change_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    photo_file_id TEXT,
                    ai_analysis TEXT,
                    watering_adjustment INTEGER DEFAULT 0,
                    feeding_adjustment INTEGER,
                    recommendations TEXT,
                    manual_event BOOLEAN DEFAULT FALSE,
                    event_type TEXT,
                    FOREIGN KEY (plant_id) REFERENCES plants (id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                )
            """)
            
            # Остальные таблицы
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS growing_plants (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    plant_name TEXT NOT NULL,
                    growth_method TEXT NOT NULL,
                    growing_plan TEXT NOT NULL,
                    task_calendar JSONB,
                    current_stage INTEGER DEFAULT 0,
                    total_stages INTEGER DEFAULT 4,
                    started_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    estimated_completion DATE,
                    status TEXT DEFAULT 'active',
                    notes TEXT,
                    photo_file_id TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS growth_stages (
                    id SERIAL PRIMARY KEY,
                    growing_plant_id INTEGER NOT NULL,
                    stage_number INTEGER NOT NULL,
                    stage_name TEXT NOT NULL,
                    stage_description TEXT NOT NULL,
                    estimated_duration_days INTEGER NOT NULL,
                    completed_date TIMESTAMP,
                    photo_file_id TEXT,
                    notes TEXT,
                    reminder_interval INTEGER DEFAULT 2,
                    FOREIGN KEY (growing_plant_id) REFERENCES growing_plants (id) ON DELETE CASCADE
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS growth_diary (
                    id SERIAL PRIMARY KEY,
                    growing_plant_id INTEGER NOT NULL,
                    entry_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    entry_type TEXT NOT NULL,
                    description TEXT,
                    photo_file_id TEXT,
                    stage_number INTEGER,
                    user_id BIGINT NOT NULL,
                    FOREIGN KEY (growing_plant_id) REFERENCES growing_plants (id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                )
            """)
            
            await conn.execute("""
              CREATE TABLE IF NOT EXISTS care_history (
                    id SERIAL PRIMARY KEY,
                    plant_id INTEGER NOT NULL,
                    user_id BIGINT NOT NULL,
                    action_type TEXT NOT NULL,
                    action_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    notes TEXT,
                    FOREIGN KEY (plant_id) REFERENCES plants (id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                )
            """)
            
            # ИСПРАВЛЕНО: Таблица reminders с правильным UNIQUE constraint
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    plant_id INTEGER,
                    growing_plant_id INTEGER,
                    reminder_type TEXT NOT NULL,
                    next_date TIMESTAMP NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_sent TIMESTAMP,
                    send_count INTEGER DEFAULT 0,
                    stage_number INTEGER,
                    task_day INTEGER,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
                    FOREIGN KEY (plant_id) REFERENCES plants (id) ON DELETE CASCADE,
                    FOREIGN KEY (growing_plant_id) REFERENCES growing_plants (id) ON DELETE CASCADE
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    username TEXT,
                    feedback_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    photo_file_id TEXT,
                    context_data TEXT,
                    status TEXT DEFAULT 'new',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                )
            """)
            
            # === ТАБЛИЦЫ ПОДПИСКИ ===
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    user_id BIGINT PRIMARY KEY,
                    plan TEXT NOT NULL DEFAULT 'free',
                    expires_at TIMESTAMP,
                    auto_pay_method_id TEXT,
                    granted_by_admin BIGINT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS usage_limits (
                    user_id BIGINT PRIMARY KEY,
                    analyses_used INTEGER NOT NULL DEFAULT 0,
                    questions_used INTEGER NOT NULL DEFAULT 0,
                    reset_date TIMESTAMP NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id SERIAL PRIMARY KEY,
                    payment_id TEXT UNIQUE NOT NULL,
                    user_id BIGINT NOT NULL,
                    amount INTEGER NOT NULL,
                    currency TEXT NOT NULL DEFAULT 'RUB',
                    status TEXT NOT NULL,
                    description TEXT,
                    payment_method_id TEXT,
                    is_recurring BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                )
            """)
            
            # Индексы для подписки
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_plan ON subscriptions(plan)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_expires ON subscriptions(expires_at)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_payment_id ON payments(payment_id)")
            
            # Добавляем новые колонки
            try:
                await conn.execute("ALTER TABLE plants ADD COLUMN IF NOT EXISTS current_state TEXT DEFAULT 'healthy'")
                await conn.execute("ALTER TABLE plants ADD COLUMN IF NOT EXISTS state_changed_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
                await conn.execute("ALTER TABLE plants ADD COLUMN IF NOT EXISTS state_changes_count INTEGER DEFAULT 0")
                await conn.execute("ALTER TABLE plants ADD COLUMN IF NOT EXISTS growth_stage TEXT DEFAULT 'young'")
                await conn.execute("ALTER TABLE plants ADD COLUMN IF NOT EXISTS last_photo_analysis TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
                await conn.execute("ALTER TABLE plants ADD COLUMN IF NOT EXISTS environment_data JSONB")
                await conn.execute("ALTER TABLE plants ADD COLUMN IF NOT EXISTS base_watering_interval INTEGER")
                await conn.execute("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS monthly_photo_reminder BOOLEAN DEFAULT TRUE")
                await conn.execute("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS last_monthly_reminder TIMESTAMP")
                await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarding_completed BOOLEAN DEFAULT FALSE")
                await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS care_style_profile JSONB")
                await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_activity TIMESTAMP")
                await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_action TEXT")
                await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS plants_count INTEGER DEFAULT 0")
                await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS total_waterings INTEGER DEFAULT 0")
                await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS questions_asked INTEGER DEFAULT 0")
                # Флаги контекстных подсказок онбординга
                await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS tip_analysis_shown BOOLEAN DEFAULT FALSE")
                await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS tip_save_shown BOOLEAN DEFAULT FALSE")
                await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS tip_watering_shown BOOLEAN DEFAULT FALSE")
                # UTM-трекинг
                await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS utm_source TEXT")
            except Exception as e:
                logger.info(f"Колонки уже существуют: {e}")
            
            # Временное хранилище анализа фото (черновик перед сохранением растения).
            # Раньше хранилось в RAM (утечка памяти + потеря при рестарте) — перенесено в БД.
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS temp_analyses (
                    user_id BIGINT PRIMARY KEY,
                    data JSONB NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Лог нажатий на кнопки (для аналитики использования функций).
            # Append-only: одна строка на каждое нажатие.
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS button_clicks (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    button TEXT NOT NULL,
                    clicked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Индексы для оптимизации
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_button_clicks_button ON button_clicks (button)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_button_clicks_clicked_at ON button_clicks (clicked_at)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_temp_analyses_created_at ON temp_analyses (created_at)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_plants_user_id ON plants (user_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_plants_state ON plants (current_state)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_plant_state_history_plant_id ON plant_state_history (plant_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_plant_analyses_full_plant_id ON plant_analyses_full (plant_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_plant_qa_history_plant_id ON plant_qa_history (plant_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_plant_problems_log_plant_id ON plant_problems_log (plant_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_plant_user_patterns_plant_id ON plant_user_patterns (plant_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_growing_plants_user_id ON growing_plants (user_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_user_id ON reminders (user_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_next_date ON reminders (next_date, is_active)")
            # Индекс для UTM-трекинга
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_utm_source ON users(utm_source)")
            # === МИГРАЦИЯ: Добавление user_id в care_history ===
            logger.info("🔄 Проверка миграции care_history.user_id...")
            try:
                await conn.execute("ALTER TABLE care_history ADD COLUMN IF NOT EXISTS user_id BIGINT")
                
                # Заполняем существующие записи
                await conn.execute("""
                    UPDATE care_history ch
                    SET user_id = p.user_id
                    FROM plants p
                    WHERE ch.plant_id = p.id
                    AND ch.user_id IS NULL
                """)
                
                # Удаляем записи без user_id (от удаленных растений)
                await conn.execute("DELETE FROM care_history WHERE user_id IS NULL")
                
                logger.info("✅ Миграция care_history.user_id завершена")
            except Exception as e:
                logger.info(f"Миграция care_history уже выполнена: {e}")

            # Миграция: установить plant_type = 'regular' для всех NULL
            try:
                await conn.execute("""
                    UPDATE plants SET plant_type = 'regular' WHERE plant_type IS NULL
                """)
                logger.info("✅ Миграция plant_type: обновлено записей")
            except Exception as e:
                logger.info(f"Миграция plant_type: {e}")

            await conn.execute("CREATE INDEX IF NOT EXISTS idx_care_history_user_id ON care_history(user_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_care_history_date ON care_history(action_date DESC)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_care_history_user_date ON care_history(user_id, action_date DESC)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_care_history_plant_id ON care_history (plant_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_growth_stages_growing_plant_id ON growth_stages (growing_plant_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_growth_diary_growing_plant_id ON growth_diary (growing_plant_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_user_id ON feedback (user_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_last_activity ON users(last_activity DESC)")

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_stats (
                    id SERIAL PRIMARY KEY,
                    stat_date DATE UNIQUE NOT NULL,
                    total_users INTEGER NOT NULL DEFAULT 0,
                    new_users INTEGER NOT NULL DEFAULT 0,
                    active_users INTEGER NOT NULL DEFAULT 0,
                    users_watered INTEGER NOT NULL DEFAULT 0,
                    users_added_plants INTEGER NOT NULL DEFAULT 0,
                    total_waterings INTEGER NOT NULL DEFAULT 0,
                    total_plants_added INTEGER NOT NULL DEFAULT 0,
                    analyses_count INTEGER NOT NULL DEFAULT 0,
                    questions_count INTEGER NOT NULL DEFAULT 0,
                    growing_started INTEGER NOT NULL DEFAULT 0,
                    feedback_count INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            await conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_stats_date ON daily_stats(stat_date DESC)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_stats_created ON daily_stats(created_at DESC)")

            # === ТАБЛИЦА ДЛЯ АДМИН-ПЕРЕПИСКИ ===
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS admin_messages (
                    id SERIAL PRIMARY KEY,
                    from_user_id BIGINT NOT NULL,
                    to_user_id BIGINT NOT NULL,
                    message_text TEXT NOT NULL,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    read BOOLEAN DEFAULT FALSE,
                    context JSONB,
                    FOREIGN KEY (from_user_id) REFERENCES users (user_id) ON DELETE CASCADE,
                    FOREIGN KEY (to_user_id) REFERENCES users (user_id) ON DELETE CASCADE
                )
            """)

            await conn.execute("CREATE INDEX IF NOT EXISTS idx_admin_messages_to ON admin_messages(to_user_id, sent_at DESC)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_admin_messages_from ON admin_messages(from_user_id, sent_at DESC)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_admin_messages_unread ON admin_messages(to_user_id, read) WHERE read = FALSE")

            # === ТАБЛИЦА ТРИГГЕРНЫХ ЦЕПОЧЕК ===
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS trigger_queue (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    chain_type TEXT NOT NULL,
                    step INTEGER NOT NULL,
                    send_at TIMESTAMP NOT NULL,
                    sent BOOLEAN DEFAULT FALSE,
                    sent_at TIMESTAMP,
                    cancelled BOOLEAN DEFAULT FALSE,
                    cancelled_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                )
            """)

            await conn.execute("CREATE INDEX IF NOT EXISTS idx_trigger_queue_pending ON trigger_queue(send_at) WHERE sent = FALSE AND cancelled = FALSE")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_trigger_queue_user_chain ON trigger_queue(user_id, chain_type)")

            # === КРИТИЧНАЯ МИГРАЦИЯ ДЛЯ УНИКАЛЬНОСТИ НАПОМИНАНИЙ ===
            logger.info("🔔 Применение миграции для уникальности напоминаний...")
            
            # Проверяем, существует ли уже constraint
            constraint_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_indexes 
                    WHERE indexname = 'reminders_unique_active'
                )
            """)
            
            if not constraint_exists:
                # Сначала удаляем дубликаты, оставляя самые свежие
                await conn.execute("""
                    DELETE FROM reminders a USING (
                        SELECT MAX(id) as id, user_id, plant_id, reminder_type
                        FROM reminders 
                        WHERE is_active = TRUE
                        GROUP BY user_id, plant_id, reminder_type
                        HAVING COUNT(*) > 1
                    ) b
                    WHERE a.user_id = b.user_id 
                    AND a.plant_id = b.plant_id 
                    AND a.reminder_type = b.reminder_type
                    AND a.is_active = TRUE
                    AND a.id < b.id
                """)
                
                await conn.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS reminders_unique_active 
                    ON reminders (user_id, plant_id, reminder_type) 
                    WHERE is_active = TRUE AND plant_id IS NOT NULL
                """)
                
                logger.info("✅ Уникальный индекс для reminders создан")
            else:
                logger.info("✅ Уникальный индекс для reminders уже существует")

            # === ТРИГГЕР ДЛЯ АВТОМАТИЧЕСКОГО ПОДСЧЕТА РАСТЕНИЙ ===
            logger.info("🌱 Создание триггера для подсчета растений...")
            
            # Функция для обновления счетчика
            await conn.execute("""
                CREATE OR REPLACE FUNCTION update_plants_count()
                RETURNS TRIGGER AS $$
                BEGIN
                    IF TG_OP = 'INSERT' THEN
                        UPDATE users 
                        SET plants_count = (
                            SELECT COUNT(*) 
                            FROM plants 
                            WHERE user_id = NEW.user_id AND plant_type = 'regular'
                        )
                        WHERE user_id = NEW.user_id;
                        RETURN NEW;
                    ELSIF TG_OP = 'DELETE' THEN
                        UPDATE users 
                        SET plants_count = (
                            SELECT COUNT(*) 
                            FROM plants 
                            WHERE user_id = OLD.user_id AND plant_type = 'regular'
                        )
                        WHERE user_id = OLD.user_id;
                        RETURN OLD;
                    END IF;
                    RETURN NULL;
                END;
                $$ LANGUAGE plpgsql;
            """)
            
            # Проверяем существование триггера
            trigger_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_trigger 
                    WHERE tgname = 'plants_count_trigger'
                )
            """)
            
            if not trigger_exists:
                await conn.execute("""
                    CREATE TRIGGER plants_count_trigger
                    AFTER INSERT OR DELETE ON plants
                    FOR EACH ROW
                    EXECUTE FUNCTION update_plants_count();
                """)
                logger.info("✅ Триггер для подсчета растений создан")
            else:
                logger.info("✅ Триггер для подсчета растений уже существует")

            # === ТРИГГЕР ДЛЯ ПОДСЧЕТА ПОЛИВОВ ===
            logger.info("💧 Создание триггера для подсчета поливов...")
            
            await conn.execute("""
                CREATE OR REPLACE FUNCTION update_waterings_count()
                RETURNS TRIGGER AS $$
                BEGIN
                    IF TG_OP = 'INSERT' AND NEW.action_type = 'watered' THEN
                        UPDATE users 
                        SET total_waterings = (
                            SELECT COUNT(*) 
                            FROM care_history
                            WHERE user_id = NEW.user_id
                            AND action_type = 'watered'
                        )
                        WHERE user_id = NEW.user_id;
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
            """)
            
            trigger_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_trigger 
                    WHERE tgname = 'waterings_count_trigger'
                )
            """)
            
            if not trigger_exists:
                await conn.execute("""
                    CREATE TRIGGER waterings_count_trigger
                    AFTER INSERT ON care_history
                    FOR EACH ROW
                    EXECUTE FUNCTION update_waterings_count();
                """)
                logger.info("✅ Триггер для подсчета поливов создан")
            else:
                logger.info("✅ Триггер для подсчета поливов уже существует")

            # === ТРИГГЕР ДЛЯ ПОДСЧЕТА ВОПРОСОВ ===
            logger.info("❓ Создание триггера для подсчета вопросов...")
            
            await conn.execute("""
                CREATE OR REPLACE FUNCTION update_questions_count()
                RETURNS TRIGGER AS $$
                BEGIN
                    IF TG_OP = 'INSERT' THEN
                        UPDATE users 
                        SET questions_asked = (
                            SELECT COUNT(*) 
                            FROM plant_qa_history
                            WHERE user_id = NEW.user_id
                        )
                        WHERE user_id = NEW.user_id;
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
            """)
            
            trigger_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_trigger 
                    WHERE tgname = 'questions_count_trigger'
                )
            """)
            
            if not trigger_exists:
                await conn.execute("""
                    CREATE TRIGGER questions_count_trigger
                    AFTER INSERT ON plant_qa_history
                    FOR EACH ROW
                    EXECUTE FUNCTION update_questions_count();
                """)
                logger.info("✅ Триггер для подсчета вопросов создан")
            else:
                logger.info("✅ Триггер для подсчета вопросов уже существует")

            # === ЗАПОЛНЕНИЕ СУЩЕСТВУЮЩИХ ДАННЫХ ===
            logger.info("🔄 Заполнение last_action для существующих пользователей...")
            
            # Устанавливаем last_action на основе последней активности
            await conn.execute("""
                UPDATE users u
                SET last_action = 'opened_bot'
                WHERE last_action IS NULL
            """)
            
            logger.info("🔄 Пересчет plants_count для существующих пользователей...")
            
            # Пересчитываем растения для всех пользователей
            await conn.execute("""
                UPDATE users u
                SET plants_count = (
                    SELECT COUNT(*) 
                    FROM plants p 
                    WHERE p.user_id = u.user_id AND p.plant_type = 'regular'
                )
            """)
            
            logger.info("🔄 Пересчет total_waterings для существующих пользователей...")
            
            # Пересчитываем поливы для всех пользователей
            await conn.execute("""
                UPDATE users u
                SET total_waterings = (
                    SELECT COUNT(*) 
                    FROM care_history ch
                    JOIN plants p ON ch.plant_id = p.id
                    WHERE p.user_id = u.user_id AND ch.action_type = 'watered'
                )
            """)
            
            logger.info("🔄 Пересчет questions_asked для существующих пользователей...")
            
            # Пересчитываем вопросы для всех пользователей
            await conn.execute("""
                UPDATE users u
                SET questions_asked = (
                    SELECT COUNT(*) 
                    FROM plant_qa_history qa
                    WHERE qa.user_id = u.user_id
                )
            """)
            
            logger.info("✅ Существующие данные обновлены")

            # === МИГРАЦИЯ: Создание подписок для существующих пользователей ===
            logger.info("💳 Миграция подписок для существующих пользователей...")
            await conn.execute("""
                INSERT INTO subscriptions (user_id, plan)
                SELECT user_id, 'free' FROM users
                WHERE user_id NOT IN (SELECT user_id FROM subscriptions)
                ON CONFLICT (user_id) DO NOTHING
            """)
            logger.info("✅ Подписки для существующих пользователей созданы")

            # === МИГРАЦИЯ: Скидка-извинение за сбой (апрель 2026) ===
            logger.info("🎁 Миграция apology-скидки...")
            await conn.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS apology_discount_until TIMESTAMP
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS apology_broadcast_log (
                    user_id BIGINT PRIMARY KEY,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    variant TEXT NOT NULL,
                    blocked BOOLEAN DEFAULT FALSE,
                    status TEXT DEFAULT 'sent',
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)
            # Добавляем status если таблица уже существовала без неё (от тестового запуска).
            # DEFAULT 'sent' — существующие тестовые записи помечаются как уже отправленные.
            await conn.execute("""
                ALTER TABLE apology_broadcast_log 
                ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'sent'
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_apology_log_sent_at 
                ON apology_broadcast_log(sent_at DESC)
            """)
            logger.info("✅ Миграция apology-скидки применена")

            logger.info("✅ Все миграции применены успешно")
    
    def extract_plant_name_from_analysis(self, analysis_text: str) -> str:
        """Извлекает название растения из текста анализа"""
        if not analysis_text:
            return None
        
        lines = analysis_text.split('\n')
        for line in lines:
            if line.startswith("РАСТЕНИЕ:"):
                plant_name = line.replace("РАСТЕНИЕ:", "").strip()
                
                if "(" in plant_name:
                    plant_name = plant_name.split("(")[0].strip()
                
                plant_name = plant_name.split("достоверность:")[0].strip()
                plant_name = plant_name.split("%")[0].strip()
                plant_name = plant_name.replace("🌿", "").strip()
                
                if 3 <= len(plant_name) <= 80 and not plant_name.lower().startswith(("неизвестн", "неопознан", "комнатное растение")):
                    return plant_name
        
        return None
    
    # === МЕТОДЫ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ ===
    
    async def add_user(self, user_id: int, username: str = None, first_name: str = None, utm_source: str = None):
        """Добавить или обновить пользователя"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (user_id, username, first_name, last_activity, last_action, utm_source)
                VALUES ($1, $2, $3, CURRENT_TIMESTAMP, 'opened_bot', $4)
                ON CONFLICT (user_id) 
                DO UPDATE SET 
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_activity = CURRENT_TIMESTAMP,
                    last_action = 'opened_bot'
            """, user_id, username, first_name, utm_source)
            
            await conn.execute("""
                INSERT INTO user_settings (user_id)
                VALUES ($1)
                ON CONFLICT (user_id) DO NOTHING
            """, user_id)
            
            # Создаём запись подписки (free по умолчанию)
            await conn.execute("""
                INSERT INTO subscriptions (user_id, plan)
                VALUES ($1, 'free')
                ON CONFLICT (user_id) DO NOTHING
            """, user_id)
    
    async def update_user_activity(self, user_id: int, action: str):
        """Обновить активность пользователя"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE users 
                SET last_activity = CURRENT_TIMESTAMP,
                    last_action = $2
                WHERE user_id = $1
            """, user_id, action)
    
    async def get_user_reminder_settings(self, user_id: int) -> Optional[Dict]:
        """Получить настройки напоминаний пользователя"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT reminder_time, timezone, reminder_enabled, monthly_photo_reminder
                FROM user_settings
                WHERE user_id = $1
            """, user_id)
            
            if row:
                return dict(row)
            return None
    
    # === МЕТОДЫ ДЛЯ РАСТЕНИЙ С СОСТОЯНИЯМИ ===
    
    async def save_plant(self, user_id: int, analysis: str, photo_file_id: str, plant_name: str = None) -> int:
        """Сохранить растение"""
        async with self.pool.acquire() as conn:
            if not plant_name:
                plant_name = self.extract_plant_name_from_analysis(analysis)
            
            plant_id = await conn.fetchval("""
                INSERT INTO plants (user_id, analysis, photo_file_id, plant_name, last_photo_analysis)
                VALUES ($1, $2, $3, $4, CURRENT_TIMESTAMP)
                RETURNING id
            """, user_id, analysis, photo_file_id, plant_name)
            
            try:
                await conn.execute("""
                    INSERT INTO care_history (plant_id, user_id, action_type, notes)
                    VALUES ($1, $2, 'added', 'Растение добавлено в коллекцию')
                """, plant_id, user_id)
            except Exception as e:
                logger.error(f"Ошибка добавления в историю: {e}")
            
            await self.update_user_activity(user_id, 'added_plant')
            
            return plant_id
    
    async def get_plant_with_state(self, plant_id: int, user_id: int = None) -> Optional[Dict]:
        """Получить растение с информацией о состоянии"""
        async with self.pool.acquire() as conn:
            query = """
                SELECT p.*, 
                       COALESCE(p.custom_name, p.plant_name, 'Растение #' || p.id) as display_name
                FROM plants p
                WHERE p.id = $1
            """
            params = [plant_id]
            
            if user_id:
                query += " AND p.user_id = $2"
                params.append(user_id)
            
            row = await conn.fetchrow(query, *params)
            
            if row:
                return dict(row)
            return None
    
    async def update_plant_state(self, plant_id: int, user_id: int, new_state: str, 
                                change_reason: str = None, photo_file_id: str = None,
                                ai_analysis: str = None, watering_adjustment: int = 0,
                                feeding_adjustment: int = None, recommendations: str = None,
                                manual_event: bool = False, event_type: str = None):
        """Обновить состояние растения"""
        async with self.pool.acquire() as conn:
            current = await conn.fetchrow("""
                SELECT current_state FROM plants WHERE id = $1 AND user_id = $2
            """, plant_id, user_id)
            
            if not current:
                return False
            
            previous_state = current['current_state']
            
            await conn.execute("""
                UPDATE plants 
                SET current_state = $1,
                    state_changed_date = CURRENT_TIMESTAMP,
                    state_changes_count = COALESCE(state_changes_count, 0) + 1
                WHERE id = $2 AND user_id = $3
            """, new_state, plant_id, user_id)
            
            await conn.execute("""
                INSERT INTO plant_state_history 
                (plant_id, user_id, previous_state, new_state, change_reason, 
                 photo_file_id, ai_analysis, watering_adjustment, feeding_adjustment,
                 recommendations, manual_event, event_type)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            """, plant_id, user_id, previous_state, new_state, change_reason,
                photo_file_id, ai_analysis, watering_adjustment, feeding_adjustment,
                recommendations, manual_event, event_type)
            
            if watering_adjustment != 0:
                await conn.execute("""
                    UPDATE plants 
                    SET watering_interval = GREATEST(2, LEAST(15, 
                        COALESCE(watering_interval, 5) + $1))
                    WHERE id = $2
                """, watering_adjustment, plant_id)
            
            return True
    
    async def get_plant_state_history(self, plant_id: int, limit: int = 10) -> List[Dict]:
        """Получить историю изменений состояний"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM plant_state_history
                WHERE plant_id = $1
                ORDER BY change_date DESC
                LIMIT $2
            """, plant_id, limit)
            
            return [dict(row) for row in rows]
    
    async def get_plants_for_monthly_reminder(self) -> List[Dict]:
        """Получить растения для месячного напоминания"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT p.*, 
                       COALESCE(p.custom_name, p.plant_name, 'Растение #' || p.id) as display_name
                FROM plants p
                JOIN user_settings us ON p.user_id = us.user_id
                WHERE p.plant_type = 'regular'
                  AND us.monthly_photo_reminder = TRUE
                  AND (
                    p.last_photo_analysis IS NULL 
                    OR p.last_photo_analysis < CURRENT_TIMESTAMP - INTERVAL '30 days'
                  )
                  AND (
                    us.last_monthly_reminder IS NULL
                    OR us.last_monthly_reminder < CURRENT_TIMESTAMP - INTERVAL '30 days'
                  )
            """)
            
            return [dict(row) for row in rows]
    
    async def mark_monthly_reminder_sent(self, user_id: int):
        """Отметить отправку месячного напоминания"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE user_settings
                SET last_monthly_reminder = CURRENT_TIMESTAMP
                WHERE user_id = $1
            """, user_id)
    
    async def update_plant_name(self, plant_id: int, user_id: int, new_name: str):
        """Обновить название растения"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE plants 
                SET custom_name = $1 
                WHERE id = $2 AND user_id = $3
            """, new_name, plant_id, user_id)
            
            try:
                await conn.execute("""
                    INSERT INTO care_history (plant_id, user_id, action_type, notes)
                    VALUES ($1, $2, 'renamed', $3)
                """, plant_id, user_id, f'Переименовано в "{new_name}"')
            except Exception as e:
                logger.error(f"Ошибка добавления в историю: {e}")
    
    async def update_plant_watering_interval(self, plant_id: int, interval_days: int):
        """Обновить интервал полива"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE plants 
                SET watering_interval = $1 
                WHERE id = $2
            """, interval_days, plant_id)
    
    async def set_base_watering_interval(self, plant_id: int, base_interval: int):
        """Установить базовый интервал полива"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE plants 
                SET base_watering_interval = $1 
                WHERE id = $2
            """, base_interval, plant_id)
    
    async def get_all_plants_for_seasonal_update(self) -> list:
        """Получить все растения для сезонной корректировки через GPT"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    p.id,
                    p.user_id,
                    COALESCE(p.custom_name, p.plant_name, 'Растение #' || p.id) as display_name,
                    p.plant_name,
                    p.watering_interval as current_interval
                FROM plants p
                WHERE p.plant_type = 'regular'
                  AND p.reminder_enabled = TRUE
                ORDER BY p.user_id, p.id
            """)
            return [dict(row) for row in rows]
    
    async def get_plant_by_id(self, plant_id: int, user_id: int = None) -> Optional[Dict]:
        """Получить растение по ID"""
        async with self.pool.acquire() as conn:
            query = """
                SELECT id, user_id, analysis, photo_file_id, plant_name, custom_name,
                       saved_date, last_watered, 
                       COALESCE(watering_count, 0) as watering_count,
                       COALESCE(watering_interval, 5) as watering_interval,
                       COALESCE(reminder_enabled, TRUE) as reminder_enabled,
                       notes, plant_type, growing_id,
                       current_state, state_changed_date, state_changes_count,
                       growth_stage, last_photo_analysis
                FROM plants 
                WHERE id = $1
            """
            params = [plant_id]
            
            if user_id:
                query += " AND user_id = $2"
                params.append(user_id)
            
            row = await conn.fetchrow(query, *params)
            
            if row:
                display_name = row['custom_name'] or row['plant_name']
                if not display_name:
                    extracted_name = self.extract_plant_name_from_analysis(row['analysis'])
                    display_name = extracted_name or f"Растение #{row['id']}"
                
                result = dict(row)
                result['display_name'] = display_name
                return result
            return None
    
    async def get_user_plants(self, user_id: int, limit: int = 10) -> List[Dict]:
        """Получить все растения пользователя"""
        async with self.pool.acquire() as conn:
            regular_rows = await conn.fetch("""
                SELECT id, analysis, photo_file_id, plant_name, custom_name, 
                       saved_date, last_watered, 
                       COALESCE(watering_count, 0) as watering_count,
                       COALESCE(watering_interval, 5) as watering_interval,
                       COALESCE(reminder_enabled, TRUE) as reminder_enabled,
                       notes, plant_type, growing_id,
                       current_state, state_changed_date, state_changes_count
                FROM plants 
                WHERE user_id = $1 AND (plant_type = 'regular' OR plant_type IS NULL)
                ORDER BY saved_date DESC
                LIMIT $2
            """, user_id, limit)

            plants = []
            
            for row in regular_rows:
                display_name = None
                
                if row['custom_name']:
                    display_name = row['custom_name']
                elif row['plant_name']:
                    display_name = row['plant_name']
                else:
                    extracted_name = self.extract_plant_name_from_analysis(row['analysis'])
                    if extracted_name:
                        display_name = extracted_name
                        try:
                            await conn.execute("""
                                UPDATE plants SET plant_name = $1 WHERE id = $2
                            """, extracted_name, row['id'])
                        except:
                            pass
                
                if not display_name or display_name.lower().startswith(("неизвестн", "неопознан")):
                    display_name = f"Растение #{row['id']}"
                
                plant_data = dict(row)
                plant_data['display_name'] = display_name
                plant_data['type'] = 'regular'
                plants.append(plant_data)

            plants.sort(key=lambda x: x['saved_date'], reverse=True)
            
            return plants[:limit]
    
    async def update_watering(self, user_id: int, plant_id: int = None):
        """Отметить полив"""
        async with self.pool.acquire() as conn:
            if plant_id:
                await conn.execute("""
                    UPDATE plants 
                    SET last_watered = CURRENT_TIMESTAMP,
                        watering_count = COALESCE(watering_count, 0) + 1
                    WHERE user_id = $1 AND id = $2
                """, user_id, plant_id)
                
                try:
                    await conn.execute("""
                        INSERT INTO care_history (plant_id, user_id, action_type, notes)
                        VALUES ($1, $2, 'watered', 'Растение полито')
                    """, plant_id, user_id)
                except Exception as e:
                    logger.error(f"Ошибка добавления в историю: {e}")
            else:
                plant_ids = await conn.fetch("""
                    SELECT id FROM plants WHERE user_id = $1
                """, user_id)
                
                await conn.execute("""
                    UPDATE plants 
                    SET last_watered = CURRENT_TIMESTAMP,
                        watering_count = COALESCE(watering_count, 0) + 1
                    WHERE user_id = $1
                """, user_id)
                
                for plant_row in plant_ids:
                    try:
                        await conn.execute("""
                            INSERT INTO care_history (plant_id, user_id, action_type, notes)
                            VALUES ($1, $2, 'watered', 'Растение полито (массовый полив)')
                        """, plant_row['id'], user_id)
                    except Exception as e:
                        logger.error(f"Ошибка добавления в историю: {e}")
            
            await self.update_user_activity(user_id, 'watered_plant')
    
    async def delete_plant(self, user_id: int, plant_id: int):
        """Удалить растение"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                DELETE FROM plants 
                WHERE user_id = $1 AND id = $2
            """, user_id, plant_id)
    
    # === МЕТОДЫ ДЛЯ НАПОМИНАНИЙ (УПРОЩЕННЫЕ) ===
    
    async def create_reminder(self, user_id: int, plant_id: int, reminder_type: str, next_date: datetime):
        """Создать напоминание"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE reminders 
                SET is_active = FALSE 
                WHERE user_id = $1 AND plant_id = $2 AND reminder_type = $3 AND is_active = TRUE
            """, user_id, plant_id, reminder_type)
            
            await conn.execute("""
                INSERT INTO reminders (user_id, plant_id, reminder_type, next_date)
                VALUES ($1, $2, $3, $4)
            """, user_id, plant_id, reminder_type, next_date)
    
    # === МЕТОДЫ ДЛЯ ВЫРАЩИВАНИЯ ===
    
    async def create_growing_plant(self, user_id: int, plant_name: str, growth_method: str, 
                                 growing_plan: str, task_calendar: dict = None, 
                                 photo_file_id: str = None) -> int:
        """Создать выращиваемое растение"""
        async with self.pool.acquire() as conn:
            calendar_json = json.dumps(task_calendar) if task_calendar else None
            
            growing_id = await conn.fetchval("""
                INSERT INTO growing_plants 
                (user_id, plant_name, growth_method, growing_plan, task_calendar, photo_file_id, estimated_completion)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
            """, user_id, plant_name, growth_method, growing_plan, calendar_json, photo_file_id, 
                datetime.now().date() + timedelta(days=90))
            
            await self.create_growth_stages(growing_id, growing_plan)
            
            await conn.execute("""
                INSERT INTO growth_diary (growing_plant_id, user_id, entry_type, description)
                VALUES ($1, $2, 'started', $3)
            """, growing_id, user_id, f"Начато выращивание {plant_name}")
            
            return growing_id
    
    async def create_growth_stages(self, growing_plant_id: int, growing_plan: str):
        """Создать этапы выращивания"""
        stages = self.parse_growing_plan_to_stages(growing_plan)
        
        async with self.pool.acquire() as conn:
            for i, stage in enumerate(stages):
                await conn.execute("""
                    INSERT INTO growth_stages 
                    (growing_plant_id, stage_number, stage_name, stage_description, estimated_duration_days)
                    VALUES ($1, $2, $3, $4, $5)
                """, growing_plant_id, i + 1, stage['name'], stage['description'], stage['duration'])
    
    def parse_growing_plan_to_stages(self, growing_plan: str) -> List[Dict]:
        """Парсит план в этапы"""
        stages = []
        lines = growing_plan.split('\n')
        current_stage = None
        
        for line in lines:
            line = line.strip()
            if line.startswith('🌱 ЭТАП') or line.startswith('🌿 ЭТАП') or line.startswith('🌸 ЭТАП'):
                if current_stage:
                    stages.append(current_stage)
                
                stage_info = line.split(':', 1)
                if len(stage_info) > 1:
                    stage_name = stage_info[1].strip()
                    duration = 7
                    if '(' in stage_name and ')' in stage_name:
                        duration_text = stage_name[stage_name.find('(')+1:stage_name.find(')')]
                        import re
                        numbers = re.findall(r'\d+', duration_text)
                        if numbers:
                            duration = int(numbers[0])
                    
                    current_stage = {
                        'name': stage_name.split('(')[0].strip(),
                        'description': '',
                        'duration': duration
                    }
                    
            elif current_stage and line.startswith('•'):
                current_stage['description'] += line + '\n'
        
        if current_stage:
            stages.append(current_stage)
        
        if not stages:
            stages = [
                {'name': 'Подготовка и посадка', 'description': 'Подготовка и посадка', 'duration': 7},
                {'name': 'Прорастание', 'description': 'Появление всходов', 'duration': 14},
                {'name': 'Рост и развитие', 'description': 'Активный рост', 'duration': 30},
                {'name': 'Взрослое растение', 'description': 'Готово к пересадке', 'duration': 30}
            ]
        
        return stages
    
    async def get_growing_plant_by_id(self, growing_id: int, user_id: int = None) -> Optional[Dict]:
        """Получить выращиваемое растение"""
        async with self.pool.acquire() as conn:
            query = """
                SELECT gp.*, gs.stage_name as current_stage_name, gs.stage_description as current_stage_desc
                FROM growing_plants gp
                LEFT JOIN growth_stages gs ON gp.id = gs.growing_plant_id AND gs.stage_number = gp.current_stage + 1
                WHERE gp.id = $1
            """
            params = [growing_id]
            
            if user_id:
                query += " AND gp.user_id = $2"
                params.append(user_id)
            
            row = await conn.fetchrow(query, *params)
            
            if row:
                return dict(row)
            return None
    
    async def create_growing_reminder(self, growing_id: int, user_id: int, reminder_type: str, 
                                    next_date: datetime, stage_number: int = None, task_day: int = None):
        """Создать напоминание для выращивания"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE reminders 
                SET is_active = FALSE 
                WHERE growing_plant_id = $1 AND reminder_type = $2 AND is_active = TRUE
            """, growing_id, reminder_type)
            
            await conn.execute("""
                INSERT INTO reminders 
                (user_id, growing_plant_id, reminder_type, next_date, stage_number, task_day)
                VALUES ($1, $2, $3, $4, $5, $6)
            """, user_id, growing_id, reminder_type, next_date, stage_number, task_day)
    
    # === МЕТОДЫ ДЛЯ ОБРАТНОЙ СВЯЗИ ===
    
    async def save_feedback(self, user_id: int, username: str, feedback_type: str, 
                          message: str, photo_file_id: str = None, context_data: str = None) -> int:
        """Сохранить обратную связь"""
        async with self.pool.acquire() as conn:
            feedback_id = await conn.fetchval("""
                INSERT INTO feedback (user_id, username, feedback_type, message, photo_file_id, context_data)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
            """, user_id, username, feedback_type, message, photo_file_id, context_data)
            
            return feedback_id
    
    # === МЕТОДЫ ДЛЯ СТАТИСТИКИ ===
    
    async def get_user_stats(self, user_id: int) -> Dict:
        """Статистика пользователя"""
        async with self.pool.acquire() as conn:
            regular_stats = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total_plants,
                    COUNT(CASE WHEN last_watered IS NOT NULL THEN 1 END) as watered_plants,
                    COALESCE(SUM(watering_count), 0) as total_waterings,
                    COUNT(CASE WHEN reminder_enabled = TRUE THEN 1 END) as plants_with_reminders,
                    MIN(saved_date) as first_plant_date,
                    MAX(last_watered) as last_watered_date
                FROM plants 
                WHERE user_id = $1
            """, user_id)
            
            feedback_stats = await conn.fetchrow("""
                SELECT COUNT(*) as total_feedback
                FROM feedback 
                WHERE user_id = $1
            """, user_id)
            
            return {
                'total_plants': regular_stats['total_plants'] or 0,
                'watered_plants': regular_stats['watered_plants'] or 0,
                'total_waterings': regular_stats['total_waterings'] or 0,
                'plants_with_reminders': regular_stats['plants_with_reminders'] or 0,
                'first_plant_date': regular_stats['first_plant_date'],
                'last_watered_date': regular_stats['last_watered_date'],
                'total_feedback': feedback_stats['total_feedback'] or 0
            }
    
    # === МЕТОДЫ ДЛЯ ПОЛНОГО КОНТЕКСТА РАСТЕНИЙ ===
    
    async def save_full_analysis(self, plant_id: int, user_id: int, photo_file_id: str,
                                full_analysis: str, confidence: float, identified_species: str,
                                detected_state: str, detected_problems: dict = None,
                                recommendations: dict = None, watering_advice: str = None,
                                lighting_advice: str = None) -> int:
        """Сохранить полный анализ растения"""
        async with self.pool.acquire() as conn:
            analysis_id = await conn.fetchval("""
                INSERT INTO plant_analyses_full 
                (plant_id, user_id, photo_file_id, full_analysis, confidence, 
                 identified_species, detected_state, detected_problems, recommendations,
                 watering_advice, lighting_advice)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                RETURNING id
            """, plant_id, user_id, photo_file_id, full_analysis, confidence,
                identified_species, detected_state, 
                json.dumps(detected_problems) if detected_problems else None,
                json.dumps(recommendations) if recommendations else None,
                watering_advice, lighting_advice)
            
            await self.update_user_activity(user_id, 'sent_photo')
            
            return analysis_id
    
    async def get_plant_analyses_history(self, plant_id: int, limit: int = 10) -> List[Dict]:
        """Получить историю анализов растения"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM plant_analyses_full
                WHERE plant_id = $1
                ORDER BY analysis_date DESC
                LIMIT $2
            """, plant_id, limit)
            
            return [dict(row) for row in rows]
    
    # === ВРЕМЕННОЕ ХРАНИЛИЩЕ АНАЛИЗА ФОТО (черновик перед сохранением) ===

    async def save_temp_analysis(self, user_id: int, data: dict, ttl_hours: int = 24):
        """Сохранить (перезаписать) черновик анализа фото пользователя.
        Заодно чистит протухшие записи старше ttl_hours."""
        payload = json.dumps(data, default=str, ensure_ascii=False)
        async with self.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM temp_analyses WHERE created_at < CURRENT_TIMESTAMP - ($1 || ' hours')::interval",
                str(ttl_hours)
            )
            await conn.execute("""
                INSERT INTO temp_analyses (user_id, data, created_at)
                VALUES ($1, $2::jsonb, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id) DO UPDATE
                SET data = EXCLUDED.data, created_at = EXCLUDED.created_at
            """, user_id, payload)

    async def get_temp_analysis(self, user_id: int, ttl_hours: int = 24) -> Optional[Dict]:
        """Получить черновик анализа. Возвращает None, если его нет или он протух."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT data FROM temp_analyses
                WHERE user_id = $1
                  AND created_at >= CURRENT_TIMESTAMP - ($2 || ' hours')::interval
            """, user_id, str(ttl_hours))
        if not row:
            return None
        raw = row['data']
        return json.loads(raw) if isinstance(raw, str) else raw

    async def delete_temp_analysis(self, user_id: int):
        """Удалить черновик анализа пользователя."""
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM temp_analyses WHERE user_id = $1", user_id)

    async def log_button_click(self, user_id: int, button: str):
        """Записать нажатие на кнопку (для аналитики использования функций)."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO button_clicks (user_id, button) VALUES ($1, $2)",
                user_id, button
            )

    async def save_qa_interaction(self, plant_id: int, user_id: int, question: str,
                                 answer: str, context_used: dict = None) -> int:
        """Сохранить вопрос-ответ"""
        async with self.pool.acquire() as conn:
            qa_id = await conn.fetchval("""
                INSERT INTO plant_qa_history 
                (plant_id, user_id, question_text, answer_text, context_used)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
            """, plant_id, user_id, question, answer,
                json.dumps(context_used) if context_used else None)
            
            await self.update_user_activity(user_id, 'asked_question')
            
            return qa_id
    
    async def get_plant_qa_history(self, plant_id: int, limit: int = 10) -> List[Dict]:
        """Получить историю вопросов о растении"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM plant_qa_history
                WHERE plant_id = $1
                ORDER BY question_date DESC
                LIMIT $2
            """, plant_id, limit)
            
            return [dict(row) for row in rows]
    
    async def log_plant_problem(self, plant_id: int, user_id: int, problem_type: str,
                               description: str, suspected_cause: str = None) -> int:
        """Зафиксировать проблему растения"""
        async with self.pool.acquire() as conn:
            problem_id = await conn.fetchval("""
                INSERT INTO plant_problems_log 
                (plant_id, user_id, problem_type, problem_description, suspected_cause)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
            """, plant_id, user_id, problem_type, description, suspected_cause)
            
            return problem_id
    
    async def get_plant_problems_history(self, plant_id: int, limit: int = 20) -> List[Dict]:
        """Получить историю проблем растения"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM plant_problems_log
                WHERE plant_id = $1
                ORDER BY problem_date DESC
                LIMIT $2
            """, plant_id, limit)
            
            return [dict(row) for row in rows]
    
    async def get_unresolved_problems(self, plant_id: int) -> List[Dict]:
        """Получить нерешенные проблемы"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM plant_problems_log
                WHERE plant_id = $1 AND resolved = FALSE
                ORDER BY problem_date DESC
            """, plant_id)
            
            return [dict(row) for row in rows]
    
    async def save_user_pattern(self, plant_id: int, user_id: int, pattern_type: str,
                               pattern_data: dict, confidence: float = 0.5):
        """Сохранить паттерн ухода пользователя"""
        async with self.pool.acquire() as conn:
            existing = await conn.fetchrow("""
                SELECT id, occurrences, confidence FROM plant_user_patterns
                WHERE plant_id = $1 AND user_id = $2 AND pattern_type = $3
            """, plant_id, user_id, pattern_type)
            
            if existing:
                new_confidence = min(1.0, existing['confidence'] + 0.1)
                await conn.execute("""
                    UPDATE plant_user_patterns
                    SET pattern_data = $1,
                        confidence = $2,
                        occurrences = occurrences + 1,
                        last_updated = CURRENT_TIMESTAMP
                    WHERE id = $3
                """, json.dumps(pattern_data), new_confidence, existing['id'])
            else:
                await conn.execute("""
                    INSERT INTO plant_user_patterns
                    (plant_id, user_id, pattern_type, pattern_data, confidence)
                    VALUES ($1, $2, $3, $4, $5)
                """, plant_id, user_id, pattern_type, json.dumps(pattern_data), confidence)
    
    async def get_user_patterns(self, plant_id: int, min_confidence: float = 0.3) -> List[Dict]:
        """Получить паттерны ухода пользователя"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM plant_user_patterns
                WHERE plant_id = $1 AND confidence >= $2
                ORDER BY confidence DESC, last_updated DESC
            """, plant_id, min_confidence)
            
            return [dict(row) for row in rows]
    
    async def get_plant_environment(self, plant_id: int) -> Optional[Dict]:
        """Получить условия содержания растения"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM plant_environment WHERE plant_id = $1
            """, plant_id)
            
            if row:
                return dict(row)
            return None
    
    
    # === МЕТОДЫ ДЛЯ АДМИН-ПЕРЕПИСКИ ===
    
    async def send_admin_message(self, from_user_id: int, to_user_id: int, message_text: str, context: dict = None) -> int:
        """Отправить сообщение (от админа к пользователю или наоборот)"""
        async with self.pool.acquire() as conn:
            message_id = await conn.fetchval("""
                INSERT INTO admin_messages (from_user_id, to_user_id, message_text, context)
                VALUES ($1, $2, $3, $4)
                RETURNING id
            """, from_user_id, to_user_id, message_text, 
                json.dumps(context) if context else None)
            
            return message_id
    
    async def get_user_messages(self, user_id: int, limit: int = 50) -> List[Dict]:
        """Получить все сообщения пользователя (входящие и исходящие)"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    am.*,
                    u_from.username as from_username,
                    u_from.first_name as from_first_name,
                    u_to.username as to_username,
                    u_to.first_name as to_first_name
                FROM admin_messages am
                JOIN users u_from ON am.from_user_id = u_from.user_id
                JOIN users u_to ON am.to_user_id = u_to.user_id
                WHERE am.from_user_id = $1 OR am.to_user_id = $1
                ORDER BY am.sent_at DESC
                LIMIT $2
            """, user_id, limit)
            
            return [dict(row) for row in rows]
    
    async def get_unread_messages(self, user_id: int) -> List[Dict]:
        """Получить непрочитанные сообщения для пользователя"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    am.*,
                    u_from.username as from_username,
                    u_from.first_name as from_first_name
                FROM admin_messages am
                JOIN users u_from ON am.from_user_id = u_from.user_id
                WHERE am.to_user_id = $1 
                AND am.read = FALSE
                ORDER BY am.sent_at ASC
            """, user_id)
            
            return [dict(row) for row in rows]
    
    async def mark_message_read(self, message_id: int):
        """Отметить сообщение как прочитанное"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE admin_messages
                SET read = TRUE
                WHERE id = $1
            """, message_id)
    
    async def mark_all_messages_read(self, user_id: int):
        """Отметить все сообщения пользователя как прочитанные"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE admin_messages
                SET read = TRUE
                WHERE to_user_id = $1 AND read = FALSE
            """, user_id)
    
    async def get_user_info_by_id(self, user_id: int) -> Optional[Dict]:
        """Получить информацию о пользователе по ID"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT user_id, username, first_name, created_at, last_activity,
                       plants_count, total_waterings, questions_asked
                FROM users
                WHERE user_id = $1
            """, user_id)
            
            if row:
                return dict(row)
            return None
    
    async def close(self):
        """Закрыть соединения"""
        if self.pool:
            await self.pool.close()
            logger.info("✅ База данных закрыта")

# Глобальный экземпляр
db = None

async def init_database():
    """Инициализация базы данных"""
    global db
    db = PlantDatabase()
    await db.init_pool()
    return db

async def get_db():
    """Получить экземпляр базы данных"""
    global db
    if db is None:
        db = await init_database()
    return db
