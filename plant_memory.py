"""
Plant Memory Manager - Система управления полным контекстом растений
Обеспечивает долгосрочную память AI по каждому растению
"""

import logging
import json
from datetime import datetime
from typing import Dict, List

logger = logging.getLogger(__name__)

class PlantMemoryManager:
    """Менеджер памяти растений"""
    
    def __init__(self):
        self.context_cache = {}  # Кэш контекста в памяти
    
    async def build_full_context(self, plant_id: int, user_id: int, 
                                include_analyses: int = 5,
                                include_qa: int = 10,
                                include_problems: bool = True) -> Dict:
        """Построить полный контекст растения"""
        try:
            # ИСПРАВЛЕНИЕ: Импорт внутри функции во избежание циклических импортов
            from database import get_db
            
            db = await get_db()
            
            # Базовая информация о растении
            plant_info = await db.get_plant_with_state(plant_id, user_id)
            if not plant_info:
                logger.warning(f"Растение {plant_id} не найдено")
                return {}
            
            context = {
                "plant_id": plant_id,
                "plant_name": plant_info.get('display_name', 'Неизвестное'),
                "species": plant_info.get('plant_name'),
                "added_date": plant_info.get('saved_date'),
                "current_state": plant_info.get('current_state', 'healthy'),
                "state_changed_date": plant_info.get('state_changed_date'),
                "growth_stage": plant_info.get('growth_stage', 'young'),
                "days_in_collection": 0,
                
                # История ухода
                "watering_info": {
                    "last_watered": plant_info.get('last_watered'),
                    "watering_count": plant_info.get('watering_count', 0),
                    "watering_interval": plant_info.get('watering_interval', 5),
                    "total_waterings": plant_info.get('watering_count', 0)
                },
                
                # История анализов
                "analyses_history": [],
                
                # История состояний
                "state_history": [],
                
                # Вопросы и ответы
                "qa_history": [],
                
                # Проблемы
                "problems": {
                    "current": [],
                    "resolved": [],
                    "recurring": []
                },
                
                # Паттерны пользователя
                "user_patterns": [],
                
                # Условия содержания
                "environment": {}
            }
            
            # ИСПРАВЛЕНИЕ: Безопасное вычисление дней в коллекции
            if plant_info.get('saved_date'):
                try:
                    context["days_in_collection"] = (datetime.now() - plant_info['saved_date']).days
                except Exception as e:
                    logger.error(f"Ошибка вычисления дней: {e}")
                    context["days_in_collection"] = 0
            
            # Загружаем историю анализов
            if include_analyses > 0:
                try:
                    analyses = await db.get_plant_analyses_history(plant_id, limit=include_analyses)
                    context["analyses_history"] = self._format_analyses(analyses)
                except Exception as e:
                    logger.error(f"Ошибка загрузки анализов: {e}")
            
            # Загружаем историю состояний
            try:
                state_history = await db.get_plant_state_history(plant_id, limit=20)
                context["state_history"] = self._format_state_history(state_history)
            except Exception as e:
                logger.error(f"Ошибка загрузки истории состояний: {e}")
            
            # Загружаем Q&A историю
            if include_qa > 0:
                try:
                    qa_history = await db.get_plant_qa_history(plant_id, limit=include_qa)
                    context["qa_history"] = self._format_qa_history(qa_history)
                except Exception as e:
                    logger.error(f"Ошибка загрузки Q&A: {e}")
            
            # Загружаем проблемы
            if include_problems:
                try:
                    all_problems = await db.get_plant_problems_history(plant_id, limit=20)
                    unresolved = await db.get_unresolved_problems(plant_id)
                    
                    context["problems"]["current"] = [dict(p) for p in unresolved]
                    context["problems"]["resolved"] = [
                        dict(p) for p in all_problems if p.get('resolved')
                    ]
                    context["problems"]["recurring"] = self._find_recurring_problems(all_problems)
                except Exception as e:
                    logger.error(f"Ошибка загрузки проблем: {e}")
            
            # Загружаем паттерны пользователя
            try:
                patterns = await db.get_user_patterns(plant_id)
                context["user_patterns"] = self._format_patterns(patterns)
            except Exception as e:
                logger.error(f"Ошибка загрузки паттернов: {e}")
            
            # Загружаем условия содержания
            try:
                environment = await db.get_plant_environment(plant_id)
                if environment:
                    context["environment"] = dict(environment)
            except Exception as e:
                logger.error(f"Ошибка загрузки условий: {e}")
            
            # Кэшируем контекст
            self.context_cache[f"{user_id}_{plant_id}"] = {
                "context": context,
                "timestamp": datetime.now()
            }
            
            logger.info(f"✅ Построен полный контекст для растения {plant_id}")
            return context
            
        except Exception as e:
            logger.error(f"❌ Критическая ошибка построения контекста: {e}", exc_info=True)
            return {}
    
    def _format_analyses(self, analyses: List[Dict]) -> List[Dict]:
        """Форматировать историю анализов"""
        formatted = []
        for analysis in analyses:
            try:
                formatted.append({
                    "date": analysis.get('analysis_date'),
                    "confidence": analysis.get('confidence', 0),
                    "detected_state": analysis.get('detected_state'),
                    "problems": analysis.get('detected_problems'),
                    "summary": self._summarize_analysis(analysis.get('full_analysis', ''))
                })
            except Exception as e:
                logger.error(f"Ошибка форматирования анализа: {e}")
                continue
        return formatted
    
    def _format_state_history(self, history: List[Dict]) -> List[Dict]:
        """Форматировать историю состояний"""
        formatted = []
        for entry in history:
            try:
                formatted.append({
                    "date": entry.get('change_date'),
                    "from": entry.get('previous_state'),
                    "to": entry.get('new_state', 'unknown'),
                    "reason": entry.get('change_reason'),
                    "adjustments": {
                        "watering": entry.get('watering_adjustment', 0),
                        "feeding": entry.get('feeding_adjustment')
                    }
                })
            except Exception as e:
                logger.error(f"Ошибка форматирования истории: {e}")
                continue
        return formatted
    
    def _format_qa_history(self, qa_list: List[Dict]) -> List[Dict]:
        """Форматировать историю Q&A"""
        formatted = []
        for qa in qa_list:
            try:
                formatted.append({
                    "date": qa.get('question_date'),
                    "question": qa.get('question_text', ''),
                    "answer_summary": self._summarize_text(qa.get('answer_text', ''), max_length=150),
                    "feedback": qa.get('user_feedback'),
                    "action_taken": qa.get('follow_up_action'),
                    "resolved": qa.get('problem_resolved', False)
                })
            except Exception as e:
                logger.error(f"Ошибка форматирования Q&A: {e}")
                continue
        return formatted
    
    def _format_patterns(self, patterns: List[Dict]) -> List[Dict]:
        """Форматировать паттерны пользователя"""
        formatted = []
        for pattern in patterns:
            try:
                # ИСПРАВЛЕНИЕ: Правильная обработка JSONB данных
                pattern_data = pattern.get('pattern_data')
                
                # Если это строка JSON, парсим
                if isinstance(pattern_data, str):
                    try:
                        pattern_data = json.loads(pattern_data)
                    except:
                        pattern_data = {"raw": pattern_data}
                
                # Если None, устанавливаем пустой dict
                if pattern_data is None:
                    pattern_data = {}
                
                formatted.append({
                    "type": pattern.get('pattern_type', 'unknown'),
                    "data": pattern_data,
                    "confidence": pattern.get('confidence', 0.0),
                    "occurrences": pattern.get('occurrences', 0)
                })
            except Exception as e:
                logger.error(f"Ошибка форматирования паттерна: {e}")
                continue
        return formatted
    
    def _find_recurring_problems(self, problems: List[Dict]) -> List[Dict]:
        """Найти повторяющиеся проблемы"""
        try:
            problem_counts = {}
            for problem in problems:
                ptype = problem.get('problem_type')
                if not ptype:
                    continue
                    
                if ptype not in problem_counts:
                    problem_counts[ptype] = []
                problem_counts[ptype].append(problem)
            
            recurring = []
            for ptype, occurrences in problem_counts.items():
                if len(occurrences) >= 2:
                    # ИСПРАВЛЕНИЕ: Безопасное получение дат
                    dates = []
                    for p in occurrences:
                        if p.get('problem_date'):
                            dates.append(p['problem_date'])
                    
                    recurring.append({
                        "problem_type": ptype,
                        "occurrences": len(occurrences),
                        "dates": dates,
                        "last_occurrence": dates[0] if dates else None
                    })
            
            return recurring
        except Exception as e:
            logger.error(f"Ошибка поиска повторяющихся проблем: {e}")
            return []
    
    def _summarize_analysis(self, full_text: str, max_length: int = 200) -> str:
        """Сократить анализ до резюме"""
        if not full_text:
            return ""
        
        if len(full_text) <= max_length:
            return full_text
        
        # Берем первые строки до ПОЛИВ_АНАЛИЗ
        lines = full_text.split('\n')
        summary = []
        for line in lines[:10]:
            if line.startswith(("РАСТЕНИЕ:", "СОСТОЯНИЕ:", "ТЕКУЩЕЕ_СОСТОЯНИЕ:")):
                summary.append(line)
        
        return '\n'.join(summary) if summary else full_text[:max_length]
    
    def _summarize_text(self, text: str, max_length: int = 150) -> str:
        """Сократить текст"""
        if not text:
            return ""
        
        if len(text) <= max_length:
            return text
        return text[:max_length] + "..."
    
    async def format_context_for_ai(self, plant_id: int, user_id: int,
                                   focus: str = "general") -> str:
        """Форматировать контекст для отправки AI"""
        try:
            context = await self.build_full_context(plant_id, user_id)
            
            if not context:
                return ""
            
            if focus == "general":
                return self._format_general_context(context)
            elif focus == "problem":
                return self._format_problem_context(context)
            elif focus == "care":
                return self._format_care_context(context)
            else:
                return self._format_general_context(context)
        except Exception as e:
            logger.error(f"Ошибка форматирования контекста для AI: {e}")
            return ""
    
    def _format_general_context(self, context: Dict) -> str:
        """Форматировать общий контекст"""
        try:
            lines = []
            
            # Базовая информация
            lines.append(f"РАСТЕНИЕ: {context.get('plant_name', 'Неизвестное')} ({context.get('species', 'N/A')})")
            lines.append(f"В КОЛЛЕКЦИИ: {context.get('days_in_collection', 0)} дней")
            lines.append(f"ТЕКУЩЕЕ СОСТОЯНИЕ: {context.get('current_state', 'unknown')}")
            lines.append(f"ЭТАП РОСТА: {context.get('growth_stage', 'unknown')}")
            lines.append("")
            
            # Полив
            watering = context.get('watering_info', {})
            if watering.get('last_watered'):
                try:
                    days_ago = (datetime.now() - watering['last_watered']).days
                    lines.append(f"ПОЛИВ: последний {days_ago} дней назад, интервал {watering.get('watering_interval', 5)} дней")
                except:
                    lines.append(f"ПОЛИВ: интервал {watering.get('watering_interval', 5)} дней")
            lines.append("")
            
            # История состояний (последние 3)
            state_history = context.get('state_history', [])
            if state_history:
                lines.append("ИСТОРИЯ СОСТОЯНИЙ:")
                for state in state_history[:3]:
                    try:
                        date_str = state.get('date', datetime.now()).strftime('%d.%m')
                        from_state = state.get('from') or 'начало'
                        to_state = state.get('to', 'unknown')
                        lines.append(f"  {date_str}: {from_state} → {to_state}")
                        if state.get('reason'):
                            lines.append(f"    Причина: {state['reason']}")
                    except Exception as e:
                        logger.error(f"Ошибка форматирования истории: {e}")
                        continue
                lines.append("")
            
            # Текущие проблемы
            current_problems = context.get('problems', {}).get('current', [])
            if current_problems:
                lines.append("ТЕКУЩИЕ ПРОБЛЕМЫ:")
                for problem in current_problems[:3]:
                    problem_type = problem.get('problem_type', 'unknown')
                    problem_desc = problem.get('problem_description', '')
                    lines.append(f"  - {problem_type}: {problem_desc}")
                    if problem.get('solution_tried'):
                        lines.append(f"    Попытка решения: {problem['solution_tried']}")
                lines.append("")
            
            # Повторяющиеся проблемы
            recurring = context.get('problems', {}).get('recurring', [])
            if recurring:
                lines.append("ПОВТОРЯЮЩИЕСЯ ПРОБЛЕМЫ:")
                for rec in recurring:
                    problem_type = rec.get('problem_type', 'unknown')
                    occurrences = rec.get('occurrences', 0)
                    lines.append(f"  - {problem_type} (повторялось {occurrences} раз)")
                lines.append("")
            
            # Паттерны ухода
            patterns = context.get('user_patterns', [])
            if patterns:
                lines.append("ПАТТЕРНЫ УХОДА ПОЛЬЗОВАТЕЛЯ:")
                for pattern in patterns[:3]:
                    if pattern.get('confidence', 0) > 0.5:
                        pattern_type = pattern.get('type', 'unknown')
                        pattern_data = pattern.get('data', {})
                        lines.append(f"  - {pattern_type}: {pattern_data}")
                lines.append("")
            
            # Предыдущие вопросы (последние 3)
            qa_history = context.get('qa_history', [])
            if qa_history:
                lines.append("ПРЕДЫДУЩИЕ ВОПРОСЫ:")
                for qa in qa_history[:3]:
                    try:
                        date_str = qa.get('date', datetime.now()).strftime('%d.%m')
                        question = qa.get('question', '')
                        lines.append(f"  {date_str}: {question}")
                        if qa.get('action_taken'):
                            lines.append(f"    Действие: {qa['action_taken']}")
                        if qa.get('resolved'):
                            lines.append("    ✓ Решено")
                    except Exception as e:
                        logger.error(f"Ошибка форматирования Q&A: {e}")
                        continue
                lines.append("")
            
            return '\n'.join(lines)
        except Exception as e:
            logger.error(f"Ошибка форматирования общего контекста: {e}")
            return f"РАСТЕНИЕ: {context.get('plant_name', 'Неизвестное')}\nОшибка загрузки полного контекста"
    
    def _format_problem_context(self, context: Dict) -> str:
        """Форматировать контекст с фокусом на проблемы"""
        lines = []
        
        lines.append(f"РАСТЕНИЕ: {context.get('plant_name', 'Неизвестное')}")
        lines.append(f"СОСТОЯНИЕ: {context.get('current_state', 'unknown')}")
        lines.append("")
        
        # Детальная история проблем
        current_problems = context.get('problems', {}).get('current', [])
        if current_problems:
            lines.append("=== ТЕКУЩИЕ ПРОБЛЕМЫ ===")
            for problem in current_problems:
                lines.append(f"\nПроблема: {problem.get('problem_type', 'unknown')}")
                lines.append(f"Описание: {problem.get('problem_description', '')}")
                if problem.get('suspected_cause'):
                    lines.append(f"Предполагаемая причина: {problem['suspected_cause']}")
                if problem.get('solution_tried'):
                    lines.append(f"Что уже пробовали: {problem['solution_tried']}")
                    if problem.get('result'):
                        lines.append(f"Результат: {problem['result']}")
        
        return '\n'.join(lines)
    
    def _format_care_context(self, context: Dict) -> str:
        """Форматировать контекст с фокусом на уход"""
        lines = []
        
        lines.append(f"РАСТЕНИЕ: {context.get('plant_name', 'Неизвестное')}")
        lines.append(f"ВОЗРАСТ В КОЛЛЕКЦИИ: {context.get('days_in_collection', 0)} дней")
        lines.append("")
        
        # Детальная информация о поливе
        watering = context.get('watering_info', {})
        lines.append("=== ИСТОРИЯ ПОЛИВА ===")
        lines.append(f"Всего поливов: {watering.get('total_waterings', 0)}")
        lines.append(f"Интервал: {watering.get('watering_interval', 5)} дней")
        
        return '\n'.join(lines)
    
    def clear_cache(self, user_id: int = None, plant_id: int = None):
        """Очистить кэш контекста"""
        try:
            if user_id and plant_id:
                key = f"{user_id}_{plant_id}"
                if key in self.context_cache:
                    del self.context_cache[key]
            elif user_id:
                # Очистить все растения пользователя
                keys_to_delete = [k for k in self.context_cache.keys() if k.startswith(f"{user_id}_")]
                for key in keys_to_delete:
                    del self.context_cache[key]
            else:
                # Очистить весь кэш
                self.context_cache.clear()
        except Exception as e:
            logger.error(f"Ошибка очистки кэша: {e}")


# Глобальный экземпляр
memory_manager = PlantMemoryManager()

async def get_plant_context(plant_id: int, user_id: int, focus: str = "general") -> str:
    """Получить контекст растения для AI"""
    try:
        return await memory_manager.format_context_for_ai(plant_id, user_id, focus)
    except Exception as e:
        logger.error(f"Ошибка получения контекста: {e}")
        return ""

async def save_interaction(plant_id: int, user_id: int, question: str, answer: str, context_used: dict = None):
    """Сохранить взаимодействие с растением"""
    try:
        # ИСПРАВЛЕНИЕ: Импорт внутри функции
        from database import get_db
        
        db = await get_db()
        await db.save_qa_interaction(plant_id, user_id, question, answer, context_used)
        memory_manager.clear_cache(user_id, plant_id)
    except Exception as e:
        logger.error(f"Ошибка сохранения взаимодействия: {e}")
