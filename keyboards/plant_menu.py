from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

def plant_control_menu(plant_id: int):
    """Меню управления растением"""
    keyboard = [
        [InlineKeyboardButton(text="📸 Обновить состояние", callback_data=f"update_state_{plant_id}")],
        [InlineKeyboardButton(text="📊 История изменений", callback_data=f"view_state_history_{plant_id}")],
        [InlineKeyboardButton(text="🤖 Спросить ИИ о растении", callback_data=f"ask_about_plant_{plant_id}")],
        [InlineKeyboardButton(text="💧 Полить сейчас", callback_data=f"water_plant_{plant_id}")],
        [InlineKeyboardButton(text="✏️ Изменить название", callback_data=f"rename_plant_{plant_id}")],
        [InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"delete_plant_{plant_id}")],
        [InlineKeyboardButton(text="🌿 К коллекции", callback_data="my_plants")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def plant_analysis_actions(needs_retry: bool = False):
    """Действия после анализа растения"""
    keyboard = [
        [InlineKeyboardButton(text="✅ Добавить в коллекцию", callback_data="save_plant")],
        [InlineKeyboardButton(text="🤖 Спросить ИИ о растении", callback_data="ask_about")],
    ]
    
    if needs_retry:
        keyboard.insert(1, [InlineKeyboardButton(text="🔄 Повторный анализ", callback_data="reanalyze")])
    
    keyboard.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def watering_reminder_actions(plant_id: int):
    """Действия в напоминании о поливе"""
    keyboard = [
        [InlineKeyboardButton(text="💧 Полил(а)!", callback_data=f"water_plant_{plant_id}")],
        [InlineKeyboardButton(text="⏰ Напомнить завтра", callback_data=f"snooze_{plant_id}")],
        [InlineKeyboardButton(text="📸 Обновить состояние", callback_data=f"update_state_{plant_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def delete_confirmation(plant_id: int):
    """Подтверждение удаления"""
    keyboard = [
        [InlineKeyboardButton(text="❌ Да, удалить", callback_data=f"confirm_delete_plant_{plant_id}")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data=f"edit_plant_{plant_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
