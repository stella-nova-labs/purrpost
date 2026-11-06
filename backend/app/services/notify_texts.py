"""Bot message texts (Russian; the Mini App has its own i18n dictionary)."""

from __future__ import annotations

JOB_NAMES = {
    "candidates": "Варианты внешности",
    "refsheet": "Референс-лист",
    "train": "Обучение LoRA",
    "test_images": "Тестовые картинки",
    "plan": "Черновик поста",
    "regen_images": "Перегенерация картинок",
    "publish": "Публикация",
}

ERRORS = {
    "budget_exceeded": "закончился месячный бюджет",
    "fal_auth": "ключ fal.ai не подходит",
    "fal_not_configured": "не настроен ключ fal.ai",
    "anthropic_auth": "ключ Anthropic не подходит",
    "anthropic_not_configured": "не настроен ключ Anthropic",
    "llm_refused": "модель отказалась выполнять запрос",
    "llm_bad_json": "модель вернула ответ, который не удалось разобрать",
    "content_blocked": "в описании есть реальные люди, бренды или чужие персонажи",
    "fal_timeout": "fal.ai слишком долго отвечал",
    "internal_error": "внутренняя ошибка",
}


def error_text(code: str) -> str:
    return ERRORS.get(code, code)


def job_failed(kind: str, code: str) -> str:
    if code == "budget_exceeded":
        return f"{JOB_NAMES.get(kind, kind)}: не получилось, {error_text(code)}."
    return f"{JOB_NAMES.get(kind, kind)}: не получилось — {error_text(code)}. Попробуйте ещё раз в приложении."
