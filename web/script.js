document.addEventListener('DOMContentLoaded', () => {
    // Determine active language
    const lang = document.documentElement.lang === 'en' ? 'en' : 'es';
    
    // Core Elements
    const pluginsContainer = document.getElementById('plugins-container');
    const searchInput = document.getElementById('plugin-search-input');
    const filterButtons = document.querySelectorAll('.filter-btn');
    const loader = document.getElementById('plugins-loader');

    // Global state
    let allPlugins = [];
    let activeCategory = 'all';
    let searchQuery = '';
    let pluginsMetadata = {};
    let codeCache = {}; // Cache to avoid duplicate network fetches for python source codes

    // Static fallback dictionary in case both GitHub's plugins.json and local plugins.json fetches fail
    const fallbackMetadata = {
        "image_router.py": {
            "name_es": "Enrutador de Imágenes (Vision)",
            "name_en": "Image Router (Vision)",
            "category": "routing",
            "icon": "fa-solid fa-eye",
            "description_es": "Detecta automáticamente cuando envías una imagen en la conversación y desvía la petición a un experto de visión (como un modelo multimodal) de forma transparente.",
            "description_en": "Automatically detects when you send an image in the conversation and routes the request to a vision expert (such as a multimodal model) seamlessly.",
            "features_es": [
                "Inspección de imágenes codificadas en base64 (data-URIs)",
                "Validación de esquemas de URLs externas (HTTP/HTTPS) por seguridad",
                "Advertencias automáticas ante cargas pesadas para proteger el backend",
                "Redirección forzada inmediata al experto 'image-expert'"
            ],
            "features_en": [
                "Inspection of base64-encoded images (data-URIs)",
                "Validation of external URL schemes (HTTP/HTTPS) for security",
                "Automatic warnings for large payloads to protect the backend",
                "Immediate forced redirection to the 'image-expert' expert"
            ]
        },
        "system_time.py": {
            "name_es": "Inyección de Hora del Sistema",
            "name_en": "System Time Injection",
            "category": "context",
            "icon": "fa-solid fa-clock",
            "description_es": "Inyecta un mensaje del sistema con la fecha y hora local del servidor al inicio de la conversación, dando al LLM conciencia temporal completa.",
            "description_en": "Injects a system message with the local date and time of the server at the start of the conversation, giving the LLM full temporal awareness.",
            "features_es": [
                "Inyección silenciosa que no interfiere con el enrutamiento semántico normal",
                "Formato de fecha y hora totalmente personalizable a través de ConfigManager",
                "Evita que el modelo invente o desvaríe al preguntarle sobre fechas u horas actuales"
            ],
            "features_en": [
                "Silent injection that does not interfere with normal semantic routing",
                "Fully customizable date and time format through the ConfigManager",
                "Prevents the model from hallucinating when asked about current dates or times"
            ]
        },
        "user_profile.py": {
            "name_es": "Perfil de Usuario",
            "name_en": "User Profile Context",
            "category": "context",
            "icon": "fa-solid fa-user-gear",
            "description_es": "Carga e inyecta las preferencias y el perfil del usuario (nombre, intereses, tecnologías preferidas) como contexto inicial de sistema.",
            "description_en": "Loads and injects user preferences and profile (name, interests, preferred technologies) as initial system context.",
            "features_es": [
                "Inyección limpia del perfil del usuario cargado desde ConfigManager",
                "Permite respuestas de IA personalizadas basadas en tus conocimientos e intereses",
                "Funciona silenciosamente en segundo plano sin alterar el flujo de la petición"
            ],
            "features_en": [
                "Clean injection of the user profile loaded from ConfigManager",
                "Enables customized AI responses based on your background and interests",
                "Works silently in the background without altering the request flow"
            ]
        }
    };

    // Initialize application
    init();

    async function init() {
        try {
            // Step 1: Fetch metadata file (plugins.json)
            await loadMetadata();
            
            // Step 2: Fetch files in GitHub repo
            await loadPluginsFromGitHub();
        } catch (error) {
            console.error('Initialization failed:', error);
            showErrorState();
        }
    }

    // Attempt to load metadata from GitHub, fallback to local file, fallback to static object
    async function loadMetadata() {
        const githubUrl = 'https://raw.githubusercontent.com/lemoelink/plugins/main/plugins.json';
        const localUrl = 'plugins.json';

        try {
            console.log('Fetching plugins.json from GitHub...');
            const response = await fetch(githubUrl);
            if (!response.ok) throw new Error('GitHub plugins.json fetch failed');
            pluginsMetadata = await response.json();
            console.log('Successfully loaded metadata from GitHub.');
        } catch (githubErr) {
            console.warn('Could not fetch plugins.json from GitHub, attempting local fallback...', githubErr);
            try {
                const response = await fetch(localUrl);
                if (!response.ok) throw new Error('Local plugins.json fetch failed');
                pluginsMetadata = await response.json();
                console.log('Successfully loaded metadata from local fallback.');
            } catch (localErr) {
                console.warn('Could not fetch local plugins.json, using built-in fallbacks...', localErr);
                pluginsMetadata = fallbackMetadata;
            }
        }
    }

    // Fetch the list of files inside github.com/lemoelink/plugins
    async function loadPluginsFromGitHub() {
        const repoContentsUrl = 'https://api.github.com/repos/lemoelink/plugins/contents';

        try {
            const response = await fetch(repoContentsUrl);
            if (!response.ok) {
                throw new Error(`GitHub API returned status ${response.status}`);
            }
            
            const files = await response.json();
            
            // Filter only Python files (.py) and process them
            allPlugins = files
                .filter(file => file.type === 'file' && file.name.endsWith('.py'))
                .map(file => {
                    const filename = file.name;
                    // Check if we have rich metadata for this filename
                    const meta = pluginsMetadata[filename] || {};
                    
                    // Setup default attributes if metadata is missing
                    return {
                        filename: filename,
                        downloadUrl: file.download_url,
                        htmlUrl: file.html_url,
                        title: lang === 'en' 
                            ? (meta.name_en || formatFilenameToTitle(filename)) 
                            : (meta.name_es || formatFilenameToTitle(filename)),
                        description: lang === 'en'
                            ? (meta.description_en || 'Custom LeMoE python plugin. Inspect the code to view its hooks and implementations.')
                            : (meta.description_es || 'Plugin personalizado de Python para LeMoE. Inspecciona el código para ver sus hooks e implementaciones.'),
                        category: meta.category || 'utils',
                        icon: meta.icon || 'fa-solid fa-puzzle-piece',
                        features: lang === 'en'
                            ? (meta.features_en || ['Modular python hook deployment', 'Integrates with LeMoE API workflows'])
                            : (meta.features_es || ['Despliegue de hooks de python modulares', 'Integración con los flujos de la API de LeMoE'])
                    };
                });

            console.log(`Loaded ${allPlugins.length} plugins.`);
            renderPlugins();
        } catch (apiErr) {
            console.error('Error calling GitHub contents API, utilizing static mock dataset...', apiErr);
            // If the GitHub rate-limit or network blocks us, load a mock dynamic list using keys of metadata
            allPlugins = Object.keys(pluginsMetadata).map(filename => {
                const meta = pluginsMetadata[filename];
                return {
                    filename: filename,
                    downloadUrl: `https://raw.githubusercontent.com/lemoelink/plugins/main/${filename}`,
                    htmlUrl: `https://github.com/lemoelink/plugins/blob/main/${filename}`,
                    title: lang === 'en' ? meta.name_en : meta.name_es,
                    description: lang === 'en' ? meta.description_en : meta.description_es,
                    category: meta.category || 'utils',
                    icon: meta.icon || 'fa-solid fa-puzzle-piece',
                    features: lang === 'en' ? meta.features_en : meta.features_es
                };
            });
            renderPlugins();
        }
    }

    // Helper: Turn system_time.py into "System Time"
    function formatFilenameToTitle(filename) {
        const raw = filename.replace('.py', '');
        return raw.split('_')
            .map(word => word.charAt(0).toUpperCase() + word.slice(1))
            .join(' ');
    }

    // Lightweight, clean regex-based syntax highlighter for Python code
    function highlightPython(code) {
        // Escape HTML tags to prevent XSS/injection
        let escaped = code
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");
            
        // Highlight Comments (# comment)
        escaped = escaped.replace(/(#.*)/g, '<span class="code-comment">$1</span>');
        
        // Highlight Keywords (def, class, import, return, if, etc.)
        escaped = escaped.replace(/\b(def|class|return|if|else|elif|for|in|while|import|from|as|try|except|raise|not|is|and|or|None|True|False)\b/g, '<span class="code-keyword">$1</span>');
        
        // Highlight Strings ('string' or "string")
        escaped = escaped.replace(/(".*?"|'.*?')/g, '<span class="code-string">$1</span>');
        
        return escaped;
    }

    // Render the grid cards as tabular rows based on search filters
    function renderPlugins() {
        // Clear loader
        pluginsContainer.innerHTML = '';

        // Filter elements
        const filtered = allPlugins.filter(plugin => {
            const matchesCategory = activeCategory === 'all' || plugin.category === activeCategory;
            
            const normalizedQuery = searchQuery.toLowerCase().trim();
            const matchesSearch = normalizedQuery === '' || 
                plugin.title.toLowerCase().includes(normalizedQuery) ||
                plugin.filename.toLowerCase().includes(normalizedQuery) ||
                plugin.description.toLowerCase().includes(normalizedQuery);

            return matchesCategory && matchesSearch;
        });

        if (filtered.length === 0) {
            renderEmptyState();
            return;
        }

        // Generate Rows
        filtered.forEach((plugin, index) => {
            const row = document.createElement('article');
            row.className = 'plugin-row';
            row.style.animation = `fadeIn 0.3s forwards ${index * 0.05}s`;
            
            // Row content
            row.innerHTML = `
                <div class="plugin-row-main">
                    <div class="plugin-icon-box">
                        <i class="${plugin.icon}"></i>
                    </div>
                    <div class="plugin-details">
                        <div class="plugin-meta">
                            <h3 class="plugin-title">${plugin.title}</h3>
                            <span class="plugin-filename">${plugin.filename}</span>
                        </div>
                        <p class="plugin-description">${plugin.description}</p>
                    </div>
                </div>
                <div class="plugin-row-actions">
                    <a href="${plugin.downloadUrl}" download class="btn-primary" id="download-${plugin.filename.replace('.', '-')}" title="${lang === 'en' ? 'Download' : 'Descargar'}">
                        <i class="fa-solid fa-download"></i> ${lang === 'en' ? 'Download' : 'Descargar'}
                    </a>
                    <button class="btn-secondary inspect-code-btn" data-filename="${plugin.filename}" data-url="${plugin.downloadUrl}" id="inspect-${plugin.filename.replace('.', '-')}" title="${lang === 'en' ? 'View Code' : 'Ver Código'}">
                        <i class="fa-solid fa-code"></i> ${lang === 'en' ? 'View Code' : 'Ver Código'}
                    </button>
                </div>
                <div class="code-inspector-panel" id="panel-${plugin.filename.replace('.', '-')}">
                    <div class="code-inspector-header">
                        <div class="code-title">
                            <i class="fa-regular fa-file-code" style="color: var(--text-secondary);"></i>
                            <span>${plugin.filename}</span>
                        </div>
                        <button class="code-copy-btn" data-target="panel-${plugin.filename.replace('.', '-')}">
                            <i class="fa-regular fa-copy"></i> <span>${lang === 'en' ? 'Copy' : 'Copiar'}</span>
                        </button>
                    </div>
                    <div class="code-pre-container">
                        <pre><code id="code-box-${plugin.filename.replace('.', '-')}">${lang === 'en' ? '# Loading python code...' : '# Cargando código python...'}</code></pre>
                    </div>
                </div>
            `;

            pluginsContainer.appendChild(row);
        });

        // Attach event listeners to newly created "View Code" buttons
        attachInspectListeners();
    }

    // Attach expand/collapse event listeners
    function attachInspectListeners() {
        const buttons = pluginsContainer.querySelectorAll('.inspect-code-btn');
        buttons.forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const filename = btn.getAttribute('data-filename');
                const rawUrl = btn.getAttribute('data-url');
                const panelId = `panel-${filename.replace('.', '-')}`;
                const codeBoxId = `code-box-${filename.replace('.', '-')}`;
                
                const panel = document.getElementById(panelId);
                const codeBox = document.getElementById(codeBoxId);

                // Toggle visibility
                if (panel.style.display === 'block') {
                    panel.style.display = 'none';
                    btn.classList.remove('active-inspector');
                    btn.innerHTML = `<i class="fa-solid fa-code"></i> ${lang === 'en' ? 'View Code' : 'Ver Código'}`;
                } else {
                    panel.style.display = 'block';
                    btn.classList.add('active-inspector');
                    btn.innerHTML = `<i class="fa-solid fa-circle-chevron-up"></i> ${lang === 'en' ? 'Hide Code' : 'Ocultar'}`;
                    
                    // Fetch source code if not in cache
                    if (!codeCache[filename]) {
                        try {
                            codeBox.textContent = lang === 'en' ? '# Loading python source...' : '# Cargando código fuente...';
                            const response = await fetch(rawUrl);
                            if (!response.ok) throw new Error('Code fetch failed');
                            const pythonText = await response.text();
                            codeCache[filename] = pythonText;
                            codeBox.innerHTML = highlightPython(pythonText);
                        } catch (err) {
                            console.error('Failed to load plugin code', err);
                            codeBox.innerHTML = lang === 'en' 
                                ? `<span class="code-comment"># Error loading source code from GitHub.\n# You can view it directly here:\n# ${rawUrl}</span>`
                                : `<span class="code-comment"># Error al cargar el código fuente desde GitHub.\n# Puedes visualizarlo directamente en este enlace:\n# ${rawUrl}</span>`;
                        }
                    } else {
                        // Load from memory cache
                        codeBox.innerHTML = highlightPython(codeCache[filename]);
                    }
                }
            });
        });

        // Attach copy to clipboard event listeners
        const copyBtns = pluginsContainer.querySelectorAll('.code-copy-btn');
        copyBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const panelId = btn.getAttribute('data-target');
                const codeBox = document.querySelector(`#${panelId} code`);
                const codeText = codeBox.textContent;

                navigator.clipboard.writeText(codeText).then(() => {
                    const label = btn.querySelector('span');
                    const originalHTML = btn.innerHTML;
                    
                    btn.innerHTML = `<i class="fa-solid fa-circle-check" style="color: #10b981;"></i> <span>${lang === 'en' ? 'Copied!' : '¡Copiado!'}</span>`;
                    btn.style.borderColor = '#10b981';
                    
                    setTimeout(() => {
                        btn.innerHTML = originalHTML;
                        btn.style.borderColor = '';
                    }, 2000);
                }).catch(err => {
                    console.error('Could not copy text: ', err);
                });
            });
        });
    }

    // Render an empty results state
    function renderEmptyState() {
        pluginsContainer.innerHTML = `
            <div class="empty-state">
                <i class="fa-solid fa-magnifying-glass-minus"></i>
                <h3>${lang === 'en' ? 'No plugins match your criteria' : 'Sin plugins que coincidan con la búsqueda'}</h3>
                <p>${lang === 'en' ? 'Try adjusting your search keywords or switching category filters.' : 'Intenta ajustar tus palabras clave o cambiar de categoría.'}</p>
            </div>
        `;
    }

    // Render a high-fidelity error state
    function showErrorState() {
        pluginsContainer.innerHTML = `
            <div class="empty-state" style="border-color: #ef4444;">
                <i class="fa-solid fa-triangle-exclamation" style="color: #ef4444;"></i>
                <h3 style="color: #ef4444;">${lang === 'en' ? 'Connection Error' : 'Error de Conexión'}</h3>
                <p>${lang === 'en' ? 'Could not load plugins from GitHub repository. Please check your internet connection or try again later.' : 'No se pudo conectar con el repositorio de GitHub. Por favor comprueba tu conexión a internet o reintenta más tarde.'}</p>
                <button class="btn-primary" onclick="window.location.reload()" style="margin-top: 1rem;">
                    <i class="fa-solid fa-rotate-right"></i> ${lang === 'en' ? 'Retry' : 'Reintentar'}
                </button>
            </div>
        `;
    }

    // Search input handler with basic debouncing
    let searchTimeout = null;
    searchInput.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchQuery = e.target.value;
        searchTimeout = setTimeout(() => {
            renderPlugins();
        }, 150);
    });

    // Category filter click handler
    filterButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            // Remove active classes
            filterButtons.forEach(b => b.classList.remove('active'));
            
            // Set active class
            btn.classList.add('active');
            
            // Update filter status
            activeCategory = btn.getAttribute('data-category');
            renderPlugins();
        });
    });
});
