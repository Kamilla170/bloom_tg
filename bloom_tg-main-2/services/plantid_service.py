import logging
import base64
import httpx

from config import PLANTID_API_KEY

logger = logging.getLogger(__name__)

PLANTID_API_URL = "https://api.plant.id/v3/identification"
PLANTHEALTH_API_URL = "https://api.plant.id/v3/health_assessment"


async def identify_with_plantid(image_data: bytes, include_similar: bool = False) -> dict:
    """Идентификация растения через Plant.id API"""
    if not PLANTID_API_KEY:
        logger.warning("Plant.id API key не установлен")
        return {"success": False, "error": "API key отсутствует"}
    
    try:
        # Конвертируем изображение в base64
        base64_image = base64.b64encode(image_data).decode('utf-8')
        
        # Параметры запроса
        params = {
            'details': 'common_names,url,description,taxonomy',
            'language': 'ru'
        }
        
        if include_similar:
            params['details'] += ',similar_images'
        
        # Тело запроса
        payload = {
            'images': [base64_image],
            'latitude': 55.7558,  # Москва (опционально)
            'longitude': 37.6173,
            'similar_images': include_similar
        }
        
        # Отправляем запрос
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                PLANTID_API_URL,
                params=params,
                json=payload,
                headers={
                    'Api-Key': PLANTID_API_KEY,
                    'Content-Type': 'application/json'
                }
            )
            
            response.raise_for_status()
            data = response.json()
        
        # Парсим ответ
        if not data.get('result') or not data['result'].get('classification'):
            return {"success": False, "error": "Нет результатов классификации"}
        
        classification = data['result']['classification']
        suggestions = classification.get('suggestions', [])
        
        if not suggestions:
            return {"success": False, "error": "Растение не определено"}
        
        # Берем лучший результат
        best_match = suggestions[0]
        
        result = {
            "success": True,
            "species": best_match.get('name', 'Unknown'),
            "common_names": best_match.get('details', {}).get('common_names', []),
            "probability": best_match.get('probability', 0) * 100,  # В процентах
            "scientific_name": best_match.get('name', ''),
            "taxonomy": best_match.get('details', {}).get('taxonomy', {}),
            "description": best_match.get('details', {}).get('description', {}).get('value', ''),
            "url": best_match.get('details', {}).get('url', ''),
            "is_plant": data['result'].get('is_plant', {}).get('binary', True),
            "similar_images": []
        }
        
        # Добавляем похожие изображения если запрашивали
        if include_similar and best_match.get('similar_images'):
            result['similar_images'] = [
                img.get('url') for img in best_match['similar_images'][:3]
            ]
        
        logger.info(f"✅ Plant.id: {result['species']} ({result['probability']:.1f}%)")
        return result
        
    except httpx.TimeoutException:
        logger.error("❌ Plant.id timeout")
        return {"success": False, "error": "Timeout"}
    except httpx.HTTPStatusError as e:
        logger.error(f"❌ Plant.id HTTP error: {e.response.status_code}")
        return {"success": False, "error": f"HTTP {e.response.status_code}"}
    except Exception as e:
        logger.error(f"❌ Plant.id error: {e}")
        return {"success": False, "error": str(e)}


async def diagnose_with_planthealth(image_data: bytes) -> dict:
    """Диагностика болезней через Plant.health API"""
    if not PLANTID_API_KEY:
        return {"success": False, "error": "API key отсутствует"}
    
    try:
        # Конвертируем изображение в base64
        base64_image = base64.b64encode(image_data).decode('utf-8')
        
        # Параметры запроса
        params = {
            'details': 'description,treatment',
            'language': 'ru'
        }
        
        # Тело запроса
        payload = {
            'images': [base64_image]
        }
        
        # Отправляем запрос
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                PLANTHEALTH_API_URL,
                params=params,
                json=payload,
                headers={
                    'Api-Key': PLANTID_API_KEY,
                    'Content-Type': 'application/json'
                }
            )
            
            response.raise_for_status()
            data = response.json()
        
        # Проверяем здоровье растения
        is_healthy = data.get('result', {}).get('is_healthy', {}).get('binary', True)
        
        if is_healthy:
            return {
                "success": True,
                "is_healthy": True,
                "diseases": []
            }
        
        # Парсим болезни
        disease_data = data.get('result', {}).get('disease', {})
        suggestions = disease_data.get('suggestions', [])
        
        diseases = []
        for suggestion in suggestions[:3]:  # Топ-3 болезни
            disease = {
                "name": suggestion.get('name', 'Unknown'),
                "probability": suggestion.get('probability', 0) * 100,
                "description": suggestion.get('details', {}).get('description', ''),
                "treatment": suggestion.get('details', {}).get('treatment', {}).get('chemical', []),
                "category": suggestion.get('details', {}).get('common_names', [])
            }
            diseases.append(disease)
        
        logger.info(f"🦠 Plant.health: {len(diseases)} проблем найдено")
        
        return {
            "success": True,
            "is_healthy": False,
            "diseases": diseases
        }
        
    except httpx.TimeoutException:
        logger.error("❌ Plant.health timeout")
        return {"success": False, "error": "Timeout"}
    except Exception as e:
        logger.error(f"❌ Plant.health error: {e}")
        return {"success": False, "error": str(e)}


async def get_plant_details(species_name: str) -> dict:
    """Получить детальную информацию о растении (если нужно)"""
    # Эта функция может быть расширена для получения
    # дополнительной информации об уходе из Plant.id базы
    return {
        "success": False,
        "error": "Not implemented yet"
    }
