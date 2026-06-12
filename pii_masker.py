import re
import unicodedata
from modules.logger import app_logger
from modules.config_manager import ConfigManager

# Patrones regex para deteccion de PII estructurada
_PATTERNS = [
    # DNI/NIE espanol
    (re.compile(r'\b\d{8}[A-HJ-NP-TV-Z]\b', re.IGNORECASE), '[ID_DOC]'),
    (re.compile(r'\b[XYZ]\d{7}[A-Z]\b', re.IGNORECASE), '[ID_DOC]'),
    # Pasaporte generico (letra + 6-9 digitos)
    (re.compile(r'\b[A-Z]{1,2}\d{6,9}\b'), '[PASSPORT]'),
    # IBAN (cualquier pais)
    (re.compile(r'\b[A-Z]{2}\d{2}[\s\-]?(?:\d{4}[\s\-]?){3,6}\d{1,4}\b', re.IGNORECASE), '[BANK_ACCOUNT]'),
    # Tarjeta de credito (Luhn no verificado, pero formato correcto)
    (re.compile(r'\b(?:\d{4}[\s\-]?){3}\d{4}\b'), '[CARD_NUMBER]'),
    # Numero de la Seguridad Social espanola
    (re.compile(r'\b\d{2}[\s/]?\d{8}[\s/]?\d{2}\b'), '[SSN]'),
    # Email
    (re.compile(r'\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b'), '[EMAIL]'),
    # Telefono espanol (6xx, 7xx, 8xx, 9xx) y formatos internacionales (+34...)
    (re.compile(r'(?:\+34[\s\-]?)?(?:6|7|8|9)\d{2}[\s\-]?\d{3}[\s\-]?\d{3}\b'), '[PHONE]'),
    # IPv4
    (re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'), '[IP_ADDRESS]'),
    # Coordenadas GPS simples
    (re.compile(r'\b-?\d{1,2}\.\d{4,},\s*-?\d{1,3}\.\d{4,}\b'), '[COORDINATES]'),
]


def _get_config() -> dict:
    cfg = ConfigManager().get("pii_masker", {})
    return {
        "enabled":       cfg.get("enabled", True),
        "use_spacy":     cfg.get("use_spacy", False),   # NER para nombres propios
        "spacy_model":   cfg.get("spacy_model", "es_core_news_sm"),
        "mask_names":    cfg.get("mask_names", False),  # requiere use_spacy=true
        "force_enabled": cfg.get("force_enabled", False),
    }


# Cache del modelo spacy (carga costosa, se hace una sola vez)
_nlp = None


def _load_spacy(model_name: str):
    global _nlp
    if _nlp is not None:
        return _nlp
    try:
        import spacy
        _nlp = spacy.load(model_name)
        app_logger.info(f"pii_masker: modelo spacy '{model_name}' cargado.")
    except Exception as e:
        app_logger.warning(f"pii_masker: no se pudo cargar spacy ({e}). NER desactivado.")
        _nlp = False  # False indica intento fallido, no volver a intentar
    return _nlp


def _mask_with_regex(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _mask_with_spacy(text: str, model_name: str) -> str:
    nlp = _load_spacy(model_name)
    if not nlp:
        return text
    doc = nlp(text)
    # Reconstruir el texto reemplazando entidades de tipo persona y organizacion
    result = text
    # Procesar en orden inverso para no desplazar los indices
    entities = [(ent.start_char, ent.end_char, ent.label_) for ent in doc.ents]
    for start, end, label in sorted(entities, reverse=True):
        if label == "PER":
            result = result[:start] + "[PERSON_NAME]" + result[end:]
        elif label == "LOC":
            result = result[:start] + "[LOCATION]" + result[end:]
    return result


def _mask(text: str, cfg: dict) -> str:
    text = _mask_with_regex(text)
    if cfg["use_spacy"] and cfg["mask_names"]:
        text = _mask_with_spacy(text, cfg["spacy_model"])
    return text


def override_route(messages: list) -> str | None:
    # No-op en modo override_route para evitar enmascarar en local
    return None


def before_expert(messages: list, expert_config: dict) -> None:
    cfg = _get_config()
    if not cfg["enabled"]:
        return

    # Solo filtrar si el tipo de experto es 'api' (nube), o si se fuerza por configuracion
    is_cloud = expert_config.get("type", "").lower() == "api"
    force_enabled = cfg.get("force_enabled", False)

    if not is_cloud and not force_enabled:
        return

    if not isinstance(messages, list):
        return

    masked_count = 0
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content", "")
        if not isinstance(content, str) or not content:
            continue
        masked = _mask(content, cfg)
        if masked != content:
            msg["content"] = masked
            masked_count += 1

    if masked_count:
        app_logger.info(
            f"pii_masker: PII enmascarada para el experto '{expert_config.get('label', 'unknown')}' "
            f"(tipo: {expert_config.get('type')}) en {masked_count} mensaje(s)."
        )
