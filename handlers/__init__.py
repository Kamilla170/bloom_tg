"""
Handlers package - все обработчики бота
"""

from . import commands
from . import photo
from . import callbacks
from . import plants
from . import questions
from . import feedback
from . import onboarding
from . import admin
from . import admin_panel
from . import subscription

__all__ = [
    'commands',
    'photo',
    'callbacks',
    'plants',
    'questions',
    'feedback',
    'onboarding',
    'admin',
    'admin_panel',
    'subscription',
]
