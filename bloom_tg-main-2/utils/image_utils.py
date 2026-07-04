import logging
from io import BytesIO
from PIL import Image

logger = logging.getLogger(__name__)

async def optimize_image_for_analysis(image_data: bytes, high_quality: bool = True) -> bytes:
    """Оптимизация изображения для анализа"""
    try:
        # Если получили BytesIO - конвертируем в bytes
        if isinstance(image_data, BytesIO):
            image_data = image_data.getvalue()
        
        image = Image.open(BytesIO(image_data))
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        if high_quality:
            if max(image.size) < 1024:
                ratio = 1024 / max(image.size)
                new_size = (int(image.size[0] * ratio), int(image.size[1] * ratio))
                image = image.resize(new_size, Image.Resampling.LANCZOS)
            elif max(image.size) > 2048:
                image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
        else:
            if max(image.size) > 1024:
                image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
        
        output = BytesIO()
        quality = 95 if high_quality else 85
        image.save(output, format='JPEG', quality=quality, optimize=True)
        
        # ИСПРАВЛЕНО: возвращаем bytes, а не BytesIO объект
        return output.getvalue()
    except Exception as e:
        logger.error(f"Ошибка оптимизации изображения: {e}", exc_info=True)
        # В случае ошибки возвращаем исходные данные как bytes
        if isinstance(image_data, BytesIO):
            return image_data.getvalue()
        return image_data
