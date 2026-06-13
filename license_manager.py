import os
import sys
import json
import time
import importlib.util
import threading
import warnings
from datetime import datetime, timedelta, timezone

try:
    import types
    # Polyfill para Python 3.13+ donde se eliminó 'imghdr', requerido por 'pgpy'
    if 'imghdr' not in sys.modules:
        sys.modules['imghdr'] = types.ModuleType('imghdr')
        
    import pgpy
    import requests
except ImportError as e:
    if app_logger:
        app_logger.error(f"Error importing pgpy/requests: {e}")
    pgpy = None
    requests = None

# We import the PluginManager singleton from the core to inject/remove the business plugins
try:
    from modules.plugin_manager import PluginManager
    from modules.logger import app_logger
except ImportError:
    PluginManager = None
    app_logger = None

# --- Configuration Constants ---
LICENSE_FILE = os.path.join("config", "licencia.asc")
GRACE_FILE = os.path.join("config", ".license_grace")
BIS_PLUGINS_DIR = os.path.join("plugins", "bis")
BIS_TOOLS_DIR = os.path.join("tools", "bis")
GPG_SERVER = "https://keys.lemoe.link/claves/"

# Time constants
ONE_HOUR = 3600
GRACE_PERIOD_DAYS = 30

class LicenseManager:
    def __init__(self):
        self.last_check = 0
        self.is_valid = False
        self.grace_active = False
        self.grace_start = None
        self.plugins_loaded = False
        self.lock = threading.Lock()

    def check_license(self):
        """Main validation logic for the license."""
        if not pgpy or not requests:
            if app_logger:
                app_logger.error("license_manager: 'pgpy' or 'requests' not installed. License validation failed.")
            self._handle_failure()
            return

        if not os.path.exists(LICENSE_FILE):
            # No license file present: standard open-source mode, exit silently.
            return

        try:
            # 1. Parse the local cleartext signature
            msg = pgpy.PGPMessage.from_file(LICENSE_FILE)
            payload_str = str(msg.message)
            license_data = json.loads(payload_str)
            
            fingerprint = license_data.get("fingerprint")
            expires_at_str = license_data.get("expires_at")
            
            if not fingerprint or not expires_at_str:
                raise ValueError("License missing 'fingerprint' or 'expires_at'.")

            expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)

            # 2. Check offline expiration
            if now > expires_at:
                if app_logger:
                    app_logger.warning("license_manager: License expired locally.")
                self._handle_failure()
                return

            # 3. Check online against GPG server (with 1 hour cache)
            if time.time() - self.last_check > ONE_HOUR:
                try:
                    resp = requests.get(f"{GPG_SERVER}{fingerprint}.asc", timeout=5)
                    
                    if resp.status_code == 404:
                        if app_logger:
                            app_logger.error("license_manager: Key NOT FOUND (404) on Keyserver. License has been REVOKED.")
                        self._handle_failure()
                        return
                        
                    if resp.status_code == 200:
                        # Suppress PGPy TODO warnings to keep logs clean
                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore")
                            pub_key, _ = pgpy.PGPKey.from_blob(resp.text)
                            
                            # Verify the signature
                            valid_signature = False
                            for sig in msg.signatures:
                                try:
                                    pub_key.verify(msg)
                                    valid_signature = True
                                    break
                                except pgpy.errors.PgpError:
                                    pass
                        
                        if not valid_signature:
                            if app_logger:
                                app_logger.error("license_manager: Cryptographic signature verification failed!")
                            self._handle_failure()
                            return
                        
                        # We don't check pub_key.is_revoked because PGPy doesn't implement it yet,
                        # and our revocation logic is already handled by the 404 Not Found check above.
                    else:
                        if app_logger:
                            app_logger.info(f"license_manager: Could not reach GPG server (HTTP {resp.status_code}). Relying on offline validation.")
                except Exception as e:
                    if app_logger:
                        app_logger.warning(f"license_manager: Offline mode. GPG Server check failed: {e}")
                
                # Update cache time
                self.last_check = time.time()

            # If we reach here, license is valid
            self._handle_success(license_data)

        except Exception as e:
            if app_logger:
                app_logger.error(f"license_manager: Error processing license: {e}")
            self._handle_failure()

    def _handle_success(self, license_data):
        self.is_valid = True
        self.grace_active = False
        
        if os.path.exists(GRACE_FILE):
            os.remove(GRACE_FILE)
            
        if app_logger:
            app_logger.info(f"license_manager: Valid Business License for {license_data.get('client_name')}.")
        
        self.load_business_plugins()

    def _handle_failure(self):
        """Called only when a license file exists but validation failed (expired, revoked, etc.)."""
        self.is_valid = False
        now = datetime.now(timezone.utc)
        
        # Read or create grace period file
        if os.path.exists(GRACE_FILE):
            with open(GRACE_FILE, "r") as f:
                grace_str = f.read().strip()
                try:
                    self.grace_start = datetime.fromisoformat(grace_str)
                except ValueError:
                    self.grace_start = now
        else:
            self.grace_start = now
            try:
                with open(GRACE_FILE, "w") as f:
                    f.write(now.isoformat())
            except Exception:
                pass

        days_in_grace = (now - self.grace_start).days
        
        if days_in_grace <= GRACE_PERIOD_DAYS:
            self.grace_active = True
            if app_logger:
                app_logger.warning(f"license_manager: GRACE PERIOD ACTIVE. Business features will stop working in {GRACE_PERIOD_DAYS - days_in_grace} days.")
            self.load_business_plugins()
        else:
            self.grace_active = False
            if app_logger:
                app_logger.error("license_manager: GRACE PERIOD EXPIRED. Disabling Business Plugins.")
            self.unload_business_plugins()

    def load_business_plugins(self):
        with self.lock:
            if self.plugins_loaded or not PluginManager:
                return
            
            pm = PluginManager()
            
            # Load business plugins
            if os.path.exists(BIS_PLUGINS_DIR):
                for filename in sorted(os.listdir(BIS_PLUGINS_DIR)):
                    if filename.startswith("__") or not (filename.endswith(".py") or filename.endswith(".so") or filename.endswith(".pyd")):
                        continue
                    
                    plugin_name = filename.rsplit('.', 1)[0]
                    # En Linux los binarios solemos tener un sufijo extra (ej. modulo.cpython-310-x86_64-linux-gnu.so)
                    # Lo limpiamos para que el nombre del modulo sea el correcto
                    plugin_name = plugin_name.split('.')[0]
                    namespace_key = f"l3mcore_plugin.bis.{plugin_name}"
                    
                    if namespace_key in sys.modules:
                        continue
                        
                    file_path = os.path.join(BIS_PLUGINS_DIR, filename)
                    try:
                        spec = importlib.util.spec_from_file_location(namespace_key, file_path)
                        if spec and spec.loader:
                            module = importlib.util.module_from_spec(spec)
                            sys.modules[namespace_key] = module
                            spec.loader.exec_module(module)
                            pm._plugins.append(module)
                            
                            accepts_label = False
                            if hasattr(module, 'after_generation'):
                                try:
                                    import inspect
                                    sig = inspect.signature(module.after_generation)
                                    accepts_label = len(sig.parameters) >= 2
                                except Exception:
                                    pass
                            pm._plugin_accepts_label.append(accepts_label)
                            
                            if app_logger:
                                app_logger.info(f"license_manager: Injected business plugin '{plugin_name}'")
                    except Exception as e:
                        if app_logger:
                            app_logger.error(f"license_manager: Failed to inject plugin {plugin_name}: {e}")

            # Load business tools
            if os.path.exists(BIS_TOOLS_DIR):
                for filename in sorted(os.listdir(BIS_TOOLS_DIR)):
                    if filename.startswith("__") or not (filename.endswith(".py") or filename.endswith(".so") or filename.endswith(".pyd")):
                        continue
                    
                    tool_name = filename.rsplit('.', 1)[0].split('.')[0]
                    namespace_key = f"l3mcore_tool.bis.{tool_name}"
                    
                    if namespace_key in sys.modules:
                        continue
                        
                    file_path = os.path.join(BIS_TOOLS_DIR, filename)
                    try:
                        spec = importlib.util.spec_from_file_location(namespace_key, file_path)
                        if spec and spec.loader:
                            module = importlib.util.module_from_spec(spec)
                            sys.modules[namespace_key] = module
                            spec.loader.exec_module(module)
                            pm._tools.append(module)
                            
                            if app_logger:
                                app_logger.info(f"license_manager: Injected business tool '{tool_name}'")
                    except Exception as e:
                        if app_logger:
                            app_logger.error(f"license_manager: Failed to inject tool {tool_name}: {e}")
                            
            self.plugins_loaded = True

    def unload_business_plugins(self):
        with self.lock:
            if not self.plugins_loaded or not PluginManager:
                return
                
            pm = PluginManager()
            
            # Remove from PluginManager's internal lists
            pm._plugins = [p for p in pm._plugins if not p.__name__.startswith("l3mcore_plugin.bis.")]
            pm._tools = [t for t in pm._tools if not t.__name__.startswith("l3mcore_tool.bis.")]
            
            # Remove from sys.modules
            keys_to_remove = [k for k in sys.modules.keys() if k.startswith("l3mcore_plugin.bis.") or k.startswith("l3mcore_tool.bis.")]
            for k in keys_to_remove:
                sys.modules.pop(k, None)
                
            self.plugins_loaded = False
            if app_logger:
                app_logger.info("license_manager: All Business Plugins and Tools unloaded from memory.")

# Singleton instance
_license_manager = LicenseManager()

def on_startup(core_context: dict):
    """Called once when l3mcore starts."""
    _license_manager.check_license()

def before_routing(prompt: str) -> str:
    """Periodically checks the license in the background during requests."""
    # Run the check in a non-blocking thread to avoid slowing down routing
    if time.time() - _license_manager.last_check > ONE_HOUR:
        threading.Thread(target=_license_manager.check_license, daemon=True).start()
        
    return prompt
