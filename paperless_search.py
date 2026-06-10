import os
import re
import requests
import unicodedata
import time
import threading
import sys
from modules.logger import app_logger
from modules.config_manager import ConfigManager

# Listas de palabras clave por defecto (Espanol)
DEFAULT_KEYWORDS = [
    "factura", "facturas", "contrato", "contratos", "documento", "documentos", 
    "recibo", "recibos", "nomina", "nominas", "alquiler", "alquileres", "pdf", "pdfs", 
    "justificante", "justificantes", "acuerdo", "acuerdos", "certificado", "certificados", 
    "escritura", "escrituras", "archivo", "archivos", "fichero", "ficheros",
    "cv", "curriculum", "curriculums", "curriculo", "curriculos"
]
DEFAULT_RETRIEVAL_VERBS = [
    "muestra", "muestrame", "busca", "buscame", "encuentra", "encuentrame", 
    "donde", "dame", "recupera", "ver", "enseña", "enseñame", "consigue", "trae", "traeme"
]
DEFAULT_EXCLUDE_WORDS = ["haz", "hazme", "crea", "crear", "inventa", "redacta", "escribe", "explicame", "ejemplo", "modelo", "plantilla", "como hacer", "ficticia", "ficticio"]

# Lista de stop-words por defecto en espanol (incluyendo conectores, verbos auxiliares y ruido relacional)
DEFAULT_STOP_WORDS = [
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "y", "o", "en", "para", "por", "con", "sobre", 
    "a", "al", "mi", "mis", "tu", "tus", "su", "sus", "favor", "porfavor", "por-favor", "que", "se", "me", "le", "les", "te",
    "este", "esta", "estos", "estas", "es", "son", "relacionado", "relacionados", "relacionada", "relacionadas", 
    "referente", "referentes", "asociado", "asociados", "asociada", "asociadas", "acerca", "relativo", "relativos", 
    "tematica", "bajo", "trata", "tratan", "habla", "hablan", "tengan", "tenga", "ver"
]

# Sustantivos contenedores genericos que suelen preceder al termino de busqueda y ensucian los resultados
DEFAULT_GENERIC_CONTAINERS = [
    "documento", "documentos", "archivo", "archivos", "fichero", "ficheros", 
    "pdf", "pdfs", "pagina", "paginas", "hoja", "hojas", "texto", "textos", 
    "justificante", "justificantes", "papel", "papeles"
]

SPANISH_TO_ENGLISH_DICT = {
    "factura": "invoice",
    "facturas": "invoices",
    "nomina": "payslip",
    "nominas": "payslips",
    "contrato": "contract",
    "contratos": "contracts",
    "alquiler": "rent",
    "alquileres": "rentals",
    "recibo": "receipt",
    "recibos": "receipts",
    "justificante": "proof",
    "justificantes": "proofs",
    "acuerdo": "agreement",
    "acuerdos": "agreements",
    "certificado": "certificate",
    "certificados": "certificates",
    "seguro": "insurance",
    "seguros": "insurance",
    "poliza": "policy",
    "polizas": "policies",
    "luz": "electricity",
    "agua": "water",
    "gas": "gas",
    "telefono": "phone",
    "movil": "mobile",
    "internet": "internet",
    "comunidad": "community",
    "banco": "bank",
    "bancario": "banking",
    "declaracion": "tax return",
    "impuesto": "tax",
    "impuestos": "taxes",
    "dron": "drone",
    "drones": "drones",
    "operador": "operator",
    "cv": "cv",
    "curriculum": "cv",
    "curriculo": "cv"
}

def _translate_query_to_english(search_term: str) -> str:
    """Traduce palabras clave comunes de español a inglés para permitir la búsqueda cruzada."""
    words = search_term.split()
    translated_words = []
    for w in words:
        w_clean = w.lower().strip()
        translated_words.append(SPANISH_TO_ENGLISH_DICT.get(w_clean, w))
    return " ".join(translated_words)

# Configuracion de rutas para el clasificador local BERT
MODEL_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "models", "lemoe_ppc"))
HF_API_URL = "https://huggingface.co/api/models/lemoelink/LEMoEPPC-onnx"
HF_RESOLVE_URL = "https://huggingface.co/lemoelink/LEMoEPPC-onnx/resolve/main"

FILES_TO_DOWNLOAD = [
    "model.onnx",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "config.json",
    "vocab.txt"
]

# Configuracion de rutas para el destilador local DeBERTa (safetensors)
DISTILLER_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "models", "lemoe_query_distiller"))
HF_API_URL_DISTILLER = "https://huggingface.co/api/models/lemoelink/lemoe-query-distiller"
HF_RESOLVE_URL_DISTILLER = "https://huggingface.co/lemoelink/lemoe-query-distiller/resolve/main"

FILES_TO_DOWNLOAD_DISTILLER = [
    "model.safetensors",
    "config.json",
    "added_tokens.json",
    "special_tokens_map.json",
    "spm.model",
    "tokenizer.json",
    "tokenizer_config.json"
]

_classifier_session = None
_classifier_tokenizer = None
_classifier_loaded = False

_distiller_model = None
_distiller_tokenizer = None
_distiller_loaded = False

_classifier_lock = threading.Lock()
_is_downloading = False

# Deteccion de entorno de pruebas para evitar descargas o ejecucion de hilos en tests unitarios o scripts
_is_testing = not sys.argv or any(x in sys.argv[0] for x in ["pytest", "unittest", "test_"]) or sys.argv[0] == "-"

def _remove_accents(text: str) -> str:
    """Elimina acentos y dieresis de un texto para una comparacion robusta en idiomas latinos."""
    nfkd_form = unicodedata.normalize('NFKD', text)
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)])

def _get_config() -> dict:
    """Carga la configuracion desde el ConfigManager o Variables de Entorno."""
    cfg = ConfigManager().get("paperless", {})
    return {
        "api_url": os.getenv("PAPERLESS_API_URL", cfg.get("api_url", "")).rstrip("/"),
        "web_url": os.getenv("PAPERLESS_WEB_URL", cfg.get("web_url", cfg.get("api_url", ""))).rstrip("/"),
        "api_token": os.getenv("PAPERLESS_API_TOKEN", cfg.get("api_token", "")),
        "trigger_keywords": cfg.get("trigger_keywords", DEFAULT_KEYWORDS),
        "retrieval_verbs": cfg.get("retrieval_verbs", DEFAULT_RETRIEVAL_VERBS),
        "exclude_words": cfg.get("exclude_words", DEFAULT_EXCLUDE_WORDS),
        "stop_words": cfg.get("stop_words", DEFAULT_STOP_WORDS),
        "generic_containers": cfg.get("generic_containers", DEFAULT_GENERIC_CONTAINERS),
        "limit_results": int(cfg.get("limit_results", 3)),
        "max_chars": int(cfg.get("max_chars_per_doc", 2500)),
        "use_semantic_router": cfg.get("use_semantic_router", False)
    }

# ------------------------------------------------------------------ Descarga y Actualizaciones

def _download_file_stream(url: str, dest_path: str):
    """Descarga un archivo via HTTP en streaming para evitar consumo de memoria excesivo en CPU."""
    response = requests.get(url, stream=True, timeout=30)
    response.raise_for_status()
    temp_path = dest_path + ".tmp"
    with open(temp_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
    os.replace(temp_path, dest_path)

def _update_last_check_time_for(model_dir: str):
    """Actualiza la marca temporal de ultima comprobacion para un modelo especifico."""
    last_check_path = os.path.join(model_dir, "last_check.txt")
    try:
        with open(last_check_path, "w") as f:
            f.write(str(time.time()))
    except Exception as e:
        app_logger.warning(f"paperless_search: No se pudo escribir last_check.txt en {model_dir}: {e}")

def _needs_update_check_for(model_dir: str, files_list: list) -> bool:
    """Verifica si ha pasado el periodo de 7 dias o faltan archivos para un modelo especifico."""
    for f in files_list:
        if not os.path.exists(os.path.join(model_dir, f)):
            return True
            
    sha_path = os.path.join(model_dir, "sha.txt")
    if not os.path.exists(sha_path):
        return True
        
    last_check_path = os.path.join(model_dir, "last_check.txt")
    if not os.path.exists(last_check_path):
        return True
        
    try:
        with open(last_check_path, "r") as f:
            last_check_ts = float(f.read().strip())
        # 7 dias en segundos = 604800
        if time.time() - last_check_ts > 604800:
            return True
    except Exception:
        return True
        
    return False

def _perform_update_for(model_name_log: str, model_dir: str, hf_api_url: str, hf_resolve_url: str, files_list: list, reload_callback):
    """Realiza la descarga/actualizacion de un modelo especifico desde Hugging Face de forma atoma y no bloqueante."""
    os.makedirs(model_dir, exist_ok=True)
    
    try:
        resp = requests.get(hf_api_url, timeout=10)
        resp.raise_for_status()
        remote_sha = resp.json().get("sha", "")
    except Exception as e:
        app_logger.warning(f"paperless_search: No se pudo obtener metadatos de Hugging Face para {model_name_log}: {e}")
        if all(os.path.exists(os.path.join(model_dir, f)) for f in files_list):
            _update_last_check_time_for(model_dir)
            return
        else:
            raise RuntimeError(f"No se pueden descargar los archivos del modelo {model_name_log}: HF no accesible: {e}")

    local_sha = ""
    sha_path = os.path.join(model_dir, "sha.txt")
    if os.path.exists(sha_path):
        try:
            with open(sha_path, "r") as f:
                local_sha = f.read().strip()
        except Exception:
            pass
            
    all_files_exist = all(os.path.exists(os.path.join(model_dir, f)) for f in files_list)
    
    if all_files_exist and local_sha == remote_sha and remote_sha:
        app_logger.info(f"paperless_search: El modelo {model_name_log} esta al dia.")
        _update_last_check_time_for(model_dir)
        return

    app_logger.info(f"paperless_search: Descargando {model_name_log} desde Hugging Face ({remote_sha})...")
    
    temp_download_dir = os.path.join(model_dir, "temp_download")
    os.makedirs(temp_download_dir, exist_ok=True)
    
    try:
        for filename in files_list:
            url = f"{hf_resolve_url}/{filename}"
            dest = os.path.join(temp_download_dir, filename)
            app_logger.info(f"paperless_search: Descargando {filename} para {model_name_log}...")
            _download_file_stream(url, dest)
            
        for filename in files_list:
            src = os.path.join(temp_download_dir, filename)
            dst = os.path.join(model_dir, filename)
            os.replace(src, dst)
            
        with open(sha_path, "w") as f:
            f.write(remote_sha)
            
        _update_last_check_time_for(model_dir)
        app_logger.info(f"paperless_search: Modelo {model_name_log} descargado y actualizado con exito.")
        reload_callback()
        
    finally:
        try:
            if os.path.exists(temp_download_dir):
                import shutil
                shutil.rmtree(temp_download_dir)
        except Exception:
            pass

def _load_classifier():
    """Carga en memoria el modelo ONNX y el tokenizador de transformers."""
    global _classifier_session, _classifier_tokenizer, _classifier_loaded
    with _classifier_lock:
        if _classifier_session is not None:
            _classifier_loaded = True
            return
            
        model_path = os.path.join(MODEL_DIR, "model.onnx")
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Archivo de modelo no encontrado en {model_path}")
            
        import onnxruntime as ort
        from transformers import AutoTokenizer
        
        # Limitar hilos para evitar contencion de CPU en HP EliteDesk
        sess_opts = ort.SessionOptions()
        sess_opts.log_severity_level = 3
        sess_opts.intra_op_num_threads = 2
        sess_opts.inter_op_num_threads = 1
        
        app_logger.info("paperless_search: Cargando clasificador BERT en ONNX...")
        _classifier_tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
        _classifier_session = ort.InferenceSession(model_path, sess_options=sess_opts)
        _classifier_loaded = True
        app_logger.info("paperless_search: Clasificador BERT en ONNX cargado exitosamente.")

def _reload_classifier_session():
    """Recarga el clasificador en memoria de forma segura."""
    global _classifier_session, _classifier_tokenizer, _classifier_loaded
    with _classifier_lock:
        _classifier_session = None
        _classifier_tokenizer = None
        _classifier_loaded = False
    try:
        _load_classifier()
    except Exception as e:
        app_logger.error(f"paperless_search: Error al recargar clasificador: {e}")

def _load_distiller():
    """Carga en memoria el destilador DeBERTa safetensors para etiquetado de tokens."""
    global _distiller_model, _distiller_tokenizer, _distiller_loaded
    with _classifier_lock:
        if _distiller_model is not None:
            _distiller_loaded = True
            return
            
        model_path = os.path.join(DISTILLER_DIR, "model.safetensors")
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Archivo de modelo no encontrado en {model_path}")
            
        from transformers import AutoTokenizer, AutoModelForTokenClassification
        import torch
        
        # Optimizar numero de hilos en CPU para PyTorch
        torch.set_num_threads(2)
        
        app_logger.info("paperless_search: Cargando destilador de consultas DeBERTa...")
        _distiller_tokenizer = AutoTokenizer.from_pretrained(DISTILLER_DIR)
        _distiller_model = AutoModelForTokenClassification.from_pretrained(DISTILLER_DIR)
        _distiller_model.eval()
        
        # Desactivar calculo de gradientes para optimizar la inferencia
        for param in _distiller_model.parameters():
            param.requires_grad = False
            
        _distiller_loaded = True
        app_logger.info("paperless_search: Destilador de consultas DeBERTa cargado exitosamente.")

def _reload_distiller_session():
    """Recarga el destilador en memoria de forma segura."""
    global _distiller_model, _distiller_tokenizer, _distiller_loaded
    with _classifier_lock:
        _distiller_model = None
        _distiller_tokenizer = None
        _distiller_loaded = False
    try:
        _load_distiller()
    except Exception as e:
        app_logger.error(f"paperless_search: Error al recargar destilador: {e}")

def _check_and_update_model_loop():
    """Bucle en segundo plano ejecutado en un hilo demonio."""
    global _is_downloading
    
    # Optimización: Si el enrutador semántico está desactivado en la configuración, 
    # evitamos descargar y cargar en memoria los modelos locales BERT/DeBERTa para ahorrar RAM.
    config = _get_config()
    if not config.get("use_semantic_router", False):
        app_logger.info("paperless_search: Enrutador semántico desactivado en la configuración. Saltando carga de modelos locales (BERT/DeBERTa) para optimizar recursos.")
        return

    # 1. Intentar cargar localmente los modelos si ya existen
    try:
        if not _needs_update_check_for(MODEL_DIR, FILES_TO_DOWNLOAD):
            _load_classifier()
    except Exception as e:
        app_logger.error(f"paperless_search: Error al cargar clasificador existente: {e}")
        
    try:
        if not _needs_update_check_for(DISTILLER_DIR, FILES_TO_DOWNLOAD_DISTILLER):
            _load_distiller()
    except Exception as e:
        app_logger.error(f"paperless_search: Error al cargar destilador existente: {e}")

    # Espera inicial para no ralentizar la respuesta del arranque
    time.sleep(2)
    
    with _classifier_lock:
        _is_downloading = True
        
    try:
        # 2. Descargar o actualizar modelos en segundo plano
        try:
            _perform_update_for(
                model_name_log="Clasificador BERT",
                model_dir=MODEL_DIR,
                hf_api_url=HF_API_URL,
                hf_resolve_url=HF_RESOLVE_URL,
                files_list=FILES_TO_DOWNLOAD,
                reload_callback=_reload_classifier_session
            )
        except Exception as e:
            app_logger.error(f"paperless_search: Error en la descarga/actualizacion del Clasificador: {e}")
            
        try:
            _perform_update_for(
                model_name_log="Destilador DeBERTa",
                model_dir=DISTILLER_DIR,
                hf_api_url=HF_API_URL_DISTILLER,
                hf_resolve_url=HF_RESOLVE_URL_DISTILLER,
                files_list=FILES_TO_DOWNLOAD_DISTILLER,
                reload_callback=_reload_distiller_session
            )
        except Exception as e:
            app_logger.error(f"paperless_search: Error en la descarga/actualizacion del Destilador: {e}")
    finally:
        with _classifier_lock:
            _is_downloading = False

    # Bucle periodico
    while True:
        try:
            time.sleep(43200) # Cada 12 horas
            if _needs_update_check_for(MODEL_DIR, FILES_TO_DOWNLOAD):
                _perform_update_for(
                    model_name_log="Clasificador BERT",
                    model_dir=MODEL_DIR,
                    hf_api_url=HF_API_URL,
                    hf_resolve_url=HF_RESOLVE_URL,
                    files_list=FILES_TO_DOWNLOAD,
                    reload_callback=_reload_classifier_session
                )
            if _needs_update_check_for(DISTILLER_DIR, FILES_TO_DOWNLOAD_DISTILLER):
                _perform_update_for(
                    model_name_log="Destilador DeBERTa",
                    model_dir=DISTILLER_DIR,
                    hf_api_url=HF_API_URL_DISTILLER,
                    hf_resolve_url=HF_RESOLVE_URL_DISTILLER,
                    files_list=FILES_TO_DOWNLOAD_DISTILLER,
                    reload_callback=_reload_distiller_session
                )
        except Exception as e:
            app_logger.error(f"paperless_search: Error en bucle periodico de actualizacion: {e}")

def _start_model_update_thread():
    """Inicia el hilo demonio de gestion del modelo."""
    thread = threading.Thread(target=_check_and_update_model_loop, daemon=True, name="l3mcore_Model_Updater")
    thread.start()

# ------------------------------------------------------------------ Clasificacion e Inferencia

def _classify_intent_bert(text: str) -> bool:
    """
    Clasifica la consulta del usuario utilizando el modelo BERT local en ONNX.
    Devuelve True si la prediccion es 1 (Documento), False si es 0 (General).
    """
    global _classifier_session, _classifier_tokenizer, _classifier_loaded
    if not _classifier_loaded or _classifier_session is None:
        return False
        
    try:
        import numpy as np
        
        inputs = _classifier_tokenizer(
            text,
            return_tensors="np",
            padding=True,
            truncation=True,
            max_length=512
        )
        
        ort_inputs = {}
        for inp in _classifier_session.get_inputs():
            if inp.name in inputs:
                ort_inputs[inp.name] = inputs[inp.name].astype(np.int64)
                
        outputs = _classifier_session.run(None, ort_inputs)
        logits = outputs[0]
        pred = int(np.argmax(logits, axis=-1)[0])
        
        app_logger.info(f"paperless_search BERT: '{text[:60]}' -> clase {pred} (logits: {logits.tolist()})")
        return pred == 1
        
    except Exception as e:
        app_logger.error(f"paperless_search BERT: Error en inferencia de clasificacion: {e}")
        return False

def _clean_search_query_bert(text: str) -> str:
    """
    Limpia la consulta del usuario utilizando el modelo de destilacion DeBERTa (safetensors).
    Mapea las predicciones de sub-tokens a las palabras originales usando compensacion de caracteres.
    """
    global _distiller_model, _distiller_tokenizer, _distiller_loaded
    if not _distiller_loaded or _distiller_model is None or _distiller_tokenizer is None:
        return text
        
    try:
        import torch
        
        # Generar tensores y enviarlos al dispositivo del modelo
        inputs = _distiller_tokenizer(text, return_tensors="pt", truncation=True).to(_distiller_model.device)
        
        with torch.no_grad():
            outputs = _distiller_model(**inputs)
            
        logits = outputs.logits
        predictions = torch.argmax(logits, dim=-1)[0].cpu().numpy()
        
        word_ids = inputs.word_ids()
        word_preds = {}
        
        # Mapear la prediccion del primer sub-token a la palabra completa
        for idx, word_id in enumerate(word_ids):
            if word_id is None:
                continue
            if word_id not in word_preds:
                word_preds[word_id] = predictions[idx]
                
        # Reconstruir la consulta final cortando los caracteres exactos de la consulta original
        keep_words = []
        for word_id, pred in word_preds.items():
            if pred == 1:
                start_char, end_char = inputs.word_to_chars(word_id)
                keep_words.append(text[start_char:end_char])
                
        cleaned_query = " ".join(keep_words).strip()
        app_logger.info(f"paperless_search Distiller BERT: '{text[:60]}' -> '{cleaned_query}'")
        return cleaned_query if cleaned_query else text
        
    except Exception as e:
        app_logger.error(f"paperless_search Distiller BERT: Error al destilar la consulta: {e}")
        return text

def _clean_search_query_classic(text: str, config: dict) -> str:
    """
    Limpia la consulta del usuario usando reglas clasicas de filtrado.
    Sirve como capa de respaldo si el destilador DeBERTa aun no se ha cargado.
    """
    normalized = _remove_accents(text.lower())
    for kw in config["trigger_keywords"]:
        normalized_kw = _remove_accents(kw.lower())
        pattern = rf"\b{re.escape(normalized_kw)}\b\s+(de|del)\s+(.+)"
        match = re.search(pattern, normalized)
        if match:
            extracted_subject = match.group(2).strip()
            cleaned_subject = re.sub(r"[¿?¡!\.,:;\-_]", " ", extracted_subject)
            subject_words = cleaned_subject.split()
            
            stop_words_set = set(_remove_accents(w.lower()) for w in config["stop_words"])
            filtered_subject = [w for w in subject_words if w not in stop_words_set]
            if filtered_subject:
                return " ".join(filtered_subject).strip()

    cleaned = re.sub(r"[¿?¡!\.,:;\-_]", " ", normalized)
    words = cleaned.split()
    
    stop_words_set = set(_remove_accents(w.lower()) for w in config["stop_words"])
    verbs_set = set(_remove_accents(w.lower()) for w in config["retrieval_verbs"])
    containers_set = set(_remove_accents(w.lower()) for w in config["generic_containers"])
    exclude_set = stop_words_set.union(verbs_set).union(containers_set)
    
    filtered_words = [w for w in words if w not in exclude_set]
    result = " ".join(filtered_words).strip()
    return result if result else text

def _is_retrieval_intent_linguistic(text: str, config: dict) -> bool:
    """
    Analizador lingüístico de respaldo cuando el clasificador BERT aún no se ha cargado.
    """
    text_normalized = _remove_accents(text.lower())
    for excl in config["exclude_words"]:
        normalized_excl = _remove_accents(excl.lower())
        if re.search(rf"\b{re.escape(normalized_excl)}\b", text_normalized):
            return False

    has_keyword = False
    for kw in config["trigger_keywords"]:
        normalized_kw = _remove_accents(kw.lower())
        if re.search(rf"\b{re.escape(normalized_kw)}\b", text_normalized):
            has_keyword = True
            break

    has_verb = False
    for verb in config["retrieval_verbs"]:
        normalized_verb = _remove_accents(verb.lower())
        if re.search(rf"\b{re.escape(normalized_verb)}\b", text_normalized):
            has_verb = True
            break
            
    is_direct_question = any(q in text_normalized for q in [
        "cuanto es", "cuanto fue", "de cuanto", "a cuanto", "donde esta", "donde encuentro", 
        "donde se encuentra", "donde puedo encontrar", "tienes la", "tienes el", "tienes alguna", 
        "tienes alguno", "dame la", "dame el", "cual es", "cual fue", "cuales son", "cuando vence", 
        "cuando caduca", "cuando se pago", "fecha de", "quien es", "quien firmo", "de quien es",
        "how much", "where is", "do you have"
    ])

    if has_keyword and (has_verb or is_direct_question or len(text_normalized.split()) <= 4):
        return True

    return False

def _is_retrieval_intent(text: str, config: dict) -> bool:
    """
    Analiza si la consulta del usuario corresponde a una petición de búsqueda de documentos.
    Usa el clasificador BERT local si el enrutador semántico está activo. Si no, usa el backup lingüístico.
    """
    if text.strip().startswith("### Task:") or "### Guidelines:" in text or "<chat history>" in text or "<chat_history>" in text:
        return False

    # Filtro inmediato basado en palabras excluidas para evitar falsos positivos semánticos (ej: crear/redactar una plantilla)
    text_normalized = _remove_accents(text.lower())
    for excl in config["exclude_words"]:
        normalized_excl = _remove_accents(excl.lower())
        if re.search(rf"\b{re.escape(normalized_excl)}\b", text_normalized):
            return False

    if config.get("use_semantic_router", False) and _classifier_loaded:
        pred = _classify_intent_bert(text)
        if pred:
            return True
        # Fallback lingüístico secundario si BERT da falso negativo
        return _is_retrieval_intent_linguistic(text, config)
    else:
        if not _classifier_loaded and config.get("use_semantic_router", False):
            app_logger.warning("paperless_search: Clasificador BERT activo pero no cargado aún. Usando fallback lingüístico temporal.")
        return _is_retrieval_intent_linguistic(text, config)

def _clean_search_query(text: str, config: dict) -> str:
    """
    Limpia la consulta del usuario. Usa DeBERTa si el enrutador semántico está activo. Si no,
    utiliza el fallback clásico basado en reglas heurísticas.
    """
    if config.get("use_semantic_router", False) and _distiller_loaded:
        return _clean_search_query_bert(text)
    else:
        return _clean_search_query_classic(text, config)

def _prune_old_contexts(messages: list, keep_most_recent: bool = True):
    """
    Elimina los bloques de contexto [CONTEXTO DE DOCUMENTOS DE PAPERLESS-NGX] antiguos del historial de mensajes.
    Si keep_most_recent es True, no se poda el último mensaje que contenga dicho contexto.
    Si keep_most_recent es False, se podan todos.
    """
    found_recent = False
    # Recorremos al revés desde el penúlt mensaje
    for i in range(len(messages) - 2, -1, -1):
        msg = messages[i]
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        
        marker = "[CONTEXTO DE DOCUMENTOS DE PAPERLESS-NGX]"
        if marker in content:
            if keep_most_recent and not found_recent:
                # Conservar este (es el más reciente de los antiguos/activos)
                found_recent = True
                continue
            
            # Podar este y todos los anteriores
            parts = content.split(marker)
            msg["content"] = parts[0].strip()
            app_logger.info(f"paperless_search: Podado contexto antiguo del mensaje {i} en el historial.")

def _expand_synonyms(text: str) -> str:
    """Expande sinónimos específicos como dron/drones -> (dron OR drones OR UAS)."""
    words = text.split()
    expanded = []
    for w in words:
        w_clean = w.lower().strip("()")
        if w_clean in ("dron", "drones"):
            expanded.append("(dron OR drones OR UAS)")
        else:
            expanded.append(w)
    return " ".join(expanded)

def override_route(messages: list) -> str | None:
    """
    Hook de l3mcore para interceptar la conversacion antes del enrutamiento.
    """
    if not isinstance(messages, list) or not messages:
        return None

    last_message = messages[-1]
    if not isinstance(last_message, dict) or last_message.get("role") != "user":
        return None

    content_raw = last_message.get("content", "")
    if not isinstance(content_raw, str) or not content_raw.strip():
        return None

    # Limpiar formato de bordes (markdown de cursivas/negritas, comillas, backticks y viñetas)
    content = content_raw.strip()
    content = re.sub(r'^\s*[-*+•]\s+', '', content)  # strip list bullets
    content = content.replace('`', '')             # strip backticks
    content = content.strip().strip("_*\"'[]{}()¿?¡!.,")

    # Evitar interceptar consultas de tareas tecnicas del frontend
    if content.strip().startswith("### Task:") or "### Guidelines:" in content or "<chat history>" in content or "<chat_history>" in content:
        return None

    config = _get_config()
    if not config["api_url"] or not config["api_token"]:
        return None

    # 1. Verificar la intencion usando clasificador obligatorio
    if not _is_retrieval_intent(content, config):
        # Es consulta de seguimiento o no relacionada. Limpiamos contextos antiguos pero mantenemos el último activo
        _prune_old_contexts(messages, keep_most_recent=True)
        return None

    # 2. Limpieza de la consulta extraida para el motor de busqueda
    search_term = _clean_search_query(content, config)
    search_term_expanded = _expand_synonyms(search_term)
    app_logger.info(f"paperless_search: Intencion de busqueda confirmada. Buscando en Paperless: '{search_term_expanded}'")

    # 3. Realizar busqueda en la API de Paperless-ngx
    headers = {
        "Authorization": f"Token {config['api_token']}",
        "Accept": "application/json"
    }
    
    params = {
        "query": search_term_expanded,
        "page_size": config["limit_results"]
    }

    try:
        search_url = f"{config['api_url']}/api/documents/"
        response = requests.get(search_url, headers=headers, params=params, timeout=8)
        response.raise_for_status()
        
        results = response.json().get("results", [])
        if not results:
            # Reintento con búsqueda flexibilizada usando operador AND si hay múltiples palabras
            words = [w.strip() for w in search_term.split() if w.strip()]
            if len(words) > 1:
                words_expanded = [_expand_synonyms(w) for w in words]
                query_and = " AND ".join(words_expanded)
                app_logger.info(f"paperless_search: Primer intento vacío. Reintentando búsqueda flexibilizada con AND: '{query_and}'")
                params["query"] = query_and
                response = requests.get(search_url, headers=headers, params=params, timeout=8)
                response.raise_for_status()
                results = response.json().get("results", [])

        if not results:
            # Reintento con traducción al inglés para búsqueda cruzada
            translated_term = _translate_query_to_english(search_term)
            if translated_term != search_term:
                translated_term_expanded = _expand_synonyms(translated_term)
                app_logger.info(f"paperless_search: Búsqueda en español vacía. Reintentando traducción al inglés: '{translated_term_expanded}'")
                params["query"] = translated_term_expanded
                response = requests.get(search_url, headers=headers, params=params, timeout=8)
                response.raise_for_status()
                results = response.json().get("results", [])
                
                # Si falla, probamos flexibilizada con AND en inglés
                if not results:
                    words = [w.strip() for w in translated_term.split() if w.strip()]
                    if len(words) > 1:
                        words_expanded = [_expand_synonyms(w) for w in words]
                        query_and_en = " AND ".join(words_expanded)
                        app_logger.info(f"paperless_search: Reintentando traducción flexibilizada con AND en inglés: '{query_and_en}'")
                        params["query"] = query_and_en
                        response = requests.get(search_url, headers=headers, params=params, timeout=8)
                        response.raise_for_status()
                        results = response.json().get("results", [])

        if not results:
            app_logger.info("paperless_search: No se encontraron documentos correspondientes.")
            return "document-expert"

        # Como encontramos nuevos resultados de búsqueda, limpiamos todos los contextos anteriores del historial
        _prune_old_contexts(messages, keep_most_recent=False)

        # 4. Formatear la informacion del documento
        context_blocks = []
        for doc in results:
            doc_id = doc.get("id")
            title = doc.get("title")
            ocr_text = doc.get("content", "")[:config["max_chars"]].strip()
            
            details_url = f"{config['web_url']}/documents/{doc_id}/details"
            download_url = f"{config['web_url']}/api/documents/{doc_id}/download/"
            
            doc_block = (
                f"--- DOCUMENTO RELEVANTE ENCONTRADO ---\n"
                f"Título: {title}\n"
                f"Enlace de Visualización: {details_url}\n"
                f"Enlace de Descarga Directa: {download_url}\n"
                f"Contenido Extraído (OCR):\n{ocr_text}\n"
            )
            context_blocks.append(doc_block)

        context_string = "\n".join(context_blocks)
        
        system_instruction = (
            "\n\n[CONTEXTO DE DOCUMENTOS DE PAPERLESS-NGX]\n"
            "El sistema ha recuperado los siguientes documentos reales del archivo personal del usuario. "
            "Responde a su petición utilizando este contenido. Es obligatorio que:\n"
            "1. Proporciones un resumen estructurado, conciso y claro de lo que trata cada documento encontrado para que el usuario no tenga que abrirlo si solo busca una visión general.\n"
            "2. Cites los datos exactos que aparezcan en el texto (ej. importes, fechas, nombres de proyectos, versiones, etc.).\n"
            "3. Proporciones siempre de forma visible y obligatoria el 'Enlace de Visualización' o el 'Enlace de Descarga Directa' "
            "empleando enlaces markdown limpios en tu respuesta (ej. [Ver Documento](url) o [Descargar](url)).\n"
            "4. Si la información solicitada no aparece en estos documentos, indícalo con amabilidad.\n\n"
        )
        
        last_message["content"] = f"{content}{system_instruction}{context_string}\n"
        app_logger.info(f"paperless_search: Inyectado contexto de {len(results)} documentos en la consulta del usuario.")
        return "document-expert"

    except Exception as e:
        app_logger.error(f"paperless_search: Error en la conexión con la API de Paperless-ngx: {e}")
        return "document-expert"

# Inicializacion al cargar el plugin
def _initialize_model_on_import():
    if _is_testing:
        app_logger.info("paperless_search: Entorno de pruebas detectado. Saltando inicializacion automatica del modelo.")
        return
    _start_model_update_thread()

_initialize_model_on_import()
