from aiogram.fsm.state import State, StatesGroup


class PlantStates(StatesGroup):
    """Состояния для работы с растениями"""
    waiting_question = State()
    editing_plant_name = State()
    onboarding_welcome = State()
    onboarding_demo = State()
    onboarding_quick_start = State()
    waiting_state_update_photo = State()
    waiting_last_watering = State()  # Ожидание выбора даты последнего полива


class PromoStates(StatesGroup):
    """Состояния для ввода промокода"""
    waiting_promo_code = State()


class FeedbackStates(StatesGroup):
    """Состояния для обратной связи"""
    choosing_type = State()
    writing_message = State()


class AdminStates(StatesGroup):
    """Состояния для админ-переписки"""
    waiting_user_reply = State()
    waiting_admin_reply = State()


class AdminPromoStates(StatesGroup):
    """Состояния мастера создания промокода в /admin"""
    waiting_code = State()
    waiting_value = State()
    waiting_limit = State()
    waiting_days = State()
