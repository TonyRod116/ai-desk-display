(() => {
  'use strict';
  const words = {
    en: { connecting:'CONNECTING', online:'LOCAL · LIVE', partial:'PARTIAL DATA', offline:'RECONNECTING', scene:'SCENE', choose_scene:'Choose a background', close:'Close',
      usage:'YOUR AI USAGE · WEEKLY REMAINING', weekly_left:'WEEKLY LEFT', left:'left', reset_in:'RESET IN', five_hour:'5-HOUR LIMIT', credits:'CREDITS', computer:'YOUR COMPUTER', memory_touch:'TOUCH TO FREE MEMORY', memory_scope:'Only idle Slack / OneDrive', memory_working:'Checking idle apps…', memory_done:'Optimized', memory_nothing:'No eligible idle apps found', memory_unavailable:'Unavailable; no changes made', memory_unknown:'Result unknown; wait before retrying', memory_busy:'Already checking…', memory_cooldown:'Please wait before retrying', memory_available:'Available',
      memory:'MEMORY', free:'free', of:'of', cloud_unavailable:'Cloud quota unavailable', manual:'Manual', full_screen:'Enter full screen', exit_full_screen:'Exit full screen',
      full_screen_failed:'Full screen is not available in this browser.', unavailable:'Unavailable', remaining:'remaining', resets:'saved resets', old:'last known',
      awake_on:'SCREEN ON', awake_blocked:'MAY SLEEP', awake_unsupported:'MAY SLEEP',
      awake_on_title:'The screen stays on while this page is full screen.', awake_blocked_title:'The browser refused to keep the screen on; it may turn off.',
      awake_unsupported_title:'This browser cannot keep the screen on; it may turn off.',
      settings:'Settings', computer_open:'Open the computer details', picture_on:'Hide the numbers', picture_off:'Show the numbers',
      update:'UPDATE', update_title:'A new version of this page is ready: tap to load it', auto_every:'Change every', pool_rotate:'Scenes in the rotation', pool_dawn:'Scenes at dawn', pool_day:'Scenes by day', pool_dusk:'Scenes at dusk', pool_night:'Scenes at night', pool_all:'All', pool_suggested:'Suggested', pool_count:'of', pool_hint:'Tap to add or remove scenes. At least one stays on.', pool_reset:'Use the suggested ones', pool_done:'Done', app_update:'APP UPDATE', app_update_title:'A new version of the app is ready: tap to install it', app_update_ready:'App update', app_update_button:'Update the app', app_up_to_date:'App is up to date', app_state_downloading:'Downloading the app update…', app_state_confirm:'Confirm on the Android screen to finish', app_state_done:'App updated: open it again if it closed', app_state_failed:'The app update did not work: try again, or install it from Chrome', app_state_busy:'An update is already running', more:'DETAILS', most_active:'MOST ACTIVE', battery:'BATTERY', charging:'charging', plugged:'plugged in', uptime:'UP',
      network:'NETWORK', down:'DOWN', up:'UP', disks:'DISKS', last_hour_note:'The trend lines show the last hour.',
      page_home:'Home', page_computer:'Computer', page_remote:'Small screen',
      remote_title:'SMALL SCREEN', remote_note:'This only changes the small screen. The tablet has its own settings (the gear).', remote_screen:'SCREEN', remote_rotation:'ROTATION',
      remote_speed:'SPEED', remote_night:'NIGHT MODE', never:'Never', every_30:'30 min', every_60:'1 hour', slower:'Slower', normal:'Normal', faster:'Faster', on:'On', off:'Off',
      sent:'Sent to the small screen', err_invalid:'That value is not allowed', err_busy:'Wait a moment and try again', err_rejected:'The small screen refused it',
      err_timeout:'No answer yet: it may still change', err_unavailable:'The small screen did not answer', connected:'CONNECTED', board_offline:'NOT REACHABLE', board_none:'NOT SET UP',
      board_old:'Update the small screen to enable these controls.', night_times:'Night schedule:',
      settings_scene:'SCENES', scene_mode:'Automatic scene', scene_auto_day:'By time of day', scene_auto_rotate:'Rotate', auto_short:'Auto', auto_minutes:'Exact minutes', photo_seconds:'Seconds per photo',
      scene_photos:'Photos', auto_day_title:'Auto · time of day', auto_rotate_title:'Auto · rotate',
      settings_night:'NIGHT MODE', night_on:'Dim at night', night_from:'From', night_to:'To', night_level:'Brightness at night', night_clock:'Clock only',
      settings_sound:'SOUND AND ALERTS', sound_on:'Sounds', sound_volume:'Volume', sound_night:'Sound at night', alert_quota:'Alert under (% left)', alert_disk:'Disk alert under (% free)',
      alert_resets:'Alert on resets', sound_test:'Test sound', settings_motion:'MOTION', motion_auto:'Follow Android', motion_on:'Always', motion_off:'Still',
      settings_place:'PLACE (SUNRISE, SUNSET AND WEATHER)', weather_on:'Weather beside the clock', latitude:'Latitude', longitude:'Longitude', settings_app:'APP', app_install:'Install the app', app_version:'App version',
      app_none:'Running in the browser', local_scenes:'Scenes on this tablet', local_ready:'Ready offline', local_saving:'Saving…', local_waiting:'Waiting for the PC', local_storage:'Not enough space', local_sign_in:'Sign in to save scenes', local_save:'Save / update scenes', local_files:'files', local_note:'Scenes, clock and display settings work offline. Live quotas, weather and PC controls need the PC.', memory_pc:'PC CONNECTION REQUIRED', settings_about:'ABOUT', language:'Language',
      alert_week:'week', alert_five:'5 h', alert_renewed:'renewed', alert_full:'almost full', alert_sound_hint:'Tap once anywhere to enable sound.' },
    es: { connecting:'CONECTANDO', online:'LOCAL · EN VIVO', partial:'DATOS PARCIALES', offline:'RECONECTANDO', scene:'ESCENA', choose_scene:'Elige un fondo', close:'Cerrar',
      usage:'TUS IA · RESTANTE SEMANAL', weekly_left:'RESTANTE SEMANAL', left:'restante', reset_in:'SE RENUEVA EN', five_hour:'LÍMITE DE 5 HORAS', credits:'CRÉDITOS', computer:'TU ORDENADOR', memory_touch:'TOCA PARA LIBERAR MEMORIA', memory_scope:'Solo Slack / OneDrive inactivos', memory_working:'Comprobando aplicaciones…', memory_done:'Optimizados', memory_nothing:'No hay apps aptas e inactivas', memory_unavailable:'No disponible; no se ha cambiado nada', memory_unknown:'Resultado desconocido; espera antes de reintentar', memory_busy:'Ya se está comprobando…', memory_cooldown:'Espera antes de volver a intentarlo', memory_available:'Disponible',
      memory:'MEMORIA', free:'libres', of:'de', cloud_unavailable:'Cuota de nube no disponible', manual:'Manual', full_screen:'Entrar en pantalla completa', exit_full_screen:'Salir de pantalla completa',
      full_screen_failed:'La pantalla completa no está disponible en este navegador.', unavailable:'No disponible', remaining:'restante', resets:'resets guardados', old:'último dato conocido',
      awake_on:'PANTALLA ENCENDIDA', awake_blocked:'PUEDE APAGARSE', awake_unsupported:'PUEDE APAGARSE',
      awake_on_title:'La pantalla se mantiene encendida mientras esta página está a pantalla completa.', awake_blocked_title:'El navegador no ha permitido mantener la pantalla encendida; puede apagarse.',
      awake_unsupported_title:'Este navegador no puede mantener la pantalla encendida; puede apagarse.',
      settings:'Ajustes', computer_open:'Abrir los detalles del ordenador', picture_on:'Ocultar los números', picture_off:'Mostrar los números',
      update:'ACTUALIZAR', update_title:'Hay una versión nueva de esta página: toca para cargarla', auto_every:'Cambiar cada', pool_rotate:'Escenas de la rotación', pool_dawn:'Escenas al amanecer', pool_day:'Escenas de día', pool_dusk:'Escenas al atardecer', pool_night:'Escenas de noche', pool_all:'Todas', pool_suggested:'Sugeridas', pool_count:'de', pool_hint:'Toca para añadir o quitar escenas. Siempre queda al menos una.', pool_reset:'Usar las sugeridas', pool_done:'Hecho', app_update:'ACTUALIZAR APP', app_update_title:'Hay una versión nueva de la app: toca para instalarla', app_update_ready:'Actualización de la app', app_update_button:'Actualizar la app', app_up_to_date:'La app está al día', app_state_downloading:'Descargando la actualización de la app…', app_state_confirm:'Confirma en la pantalla de Android para terminar', app_state_done:'App actualizada: ábrela otra vez si se ha cerrado', app_state_failed:'La actualización de la app no ha funcionado: prueba otra vez o instálala desde Chrome', app_state_busy:'Ya hay una actualización en marcha', more:'DETALLES', most_active:'LO QUE MÁS GASTA', battery:'BATERÍA', charging:'cargando', plugged:'enchufado', uptime:'ENCENDIDO',
      network:'RED', down:'BAJADA', up:'SUBIDA', disks:'DISCOS', last_hour_note:'Las líneas muestran la última hora.',
      page_home:'Inicio', page_computer:'Ordenador', page_remote:'Pantalla pequeña',
      remote_title:'PANTALLA PEQUEÑA', remote_note:'Esto solo cambia la pantalla pequeña. La tablet tiene sus propios ajustes (la rueda).', remote_screen:'PANTALLA', remote_rotation:'ROTACIÓN',
      remote_speed:'VELOCIDAD', remote_night:'MODO NOCHE', never:'Nunca', every_30:'30 min', every_60:'1 hora', slower:'Más lenta', normal:'Normal', faster:'Más rápida', on:'Sí', off:'No',
      sent:'Enviado a la pantalla pequeña', err_invalid:'Ese valor no está permitido', err_busy:'Espera un momento y vuelve a probar', err_rejected:'La pantalla pequeña lo ha rechazado',
      err_timeout:'Aún sin respuesta: puede que cambie igualmente', err_unavailable:'La pantalla pequeña no ha respondido', connected:'CONECTADA', board_offline:'NO RESPONDE', board_none:'SIN CONFIGURAR',
      board_old:'Actualiza la pantalla pequeña para activar estos controles.', night_times:'Horario de noche:',
      settings_scene:'ESCENAS', scene_mode:'Escena automática', scene_auto_day:'Según la hora', scene_auto_rotate:'Rotar', auto_short:'Auto', auto_minutes:'Minutos exactos', photo_seconds:'Segundos por foto',
      scene_photos:'Fotos', auto_day_title:'Auto · según la hora', auto_rotate_title:'Auto · rotar',
      settings_night:'MODO NOCHE', night_on:'Atenuar de noche', night_from:'Desde', night_to:'Hasta', night_level:'Brillo de noche', night_clock:'Solo la hora',
      settings_sound:'SONIDO Y AVISOS', sound_on:'Sonidos', sound_volume:'Volumen', sound_night:'Sonido de noche', alert_quota:'Avisar por debajo de (% restante)', alert_disk:'Avisar disco por debajo de (% libre)',
      alert_resets:'Avisar de renovaciones', sound_test:'Probar sonido', settings_motion:'MOVIMIENTO', motion_auto:'Como Android', motion_on:'Siempre', motion_off:'Quieto',
      settings_place:'LUGAR (AMANECER, ATARDECER Y TIEMPO)', weather_on:'Tiempo junto a la hora', latitude:'Latitud', longitude:'Longitud', settings_app:'APP', app_install:'Instalar la app', app_version:'Versión de la app',
      app_none:'Usando el navegador', local_scenes:'Escenas en esta tablet', local_ready:'Listas sin conexión', local_saving:'Guardando…', local_waiting:'Esperando al ordenador', local_storage:'No hay espacio suficiente', local_sign_in:'Inicia sesión para guardar', local_save:'Guardar / actualizar escenas', local_files:'archivos', local_note:'Escenas, reloj y ajustes funcionan sin conexión. Las cuotas actuales, el tiempo y los controles del PC necesitan el ordenador.', memory_pc:'REQUIERE CONEXIÓN AL PC', settings_about:'ACERCA DE', language:'Idioma',
      alert_week:'semana', alert_five:'5 h', alert_renewed:'renovada', alert_full:'casi lleno', alert_sound_hint:'Toca una vez en cualquier sitio para activar el sonido.' }
  };
  const $ = (selector, root = document) => root.querySelector(selector);
  const clock = $('#clock'), date = $('#date');
  const weatherBox = $('#weather'), wxIcon = $('#wx-icon'), wxTemp = $('#wx-temp'), wxText = $('#wx-text');
  const fullButton = $('#fullscreen'), fullStatus = $('#fullscreen-status');
  const awakeChip = $('#awake'), awakeText = $('#awake-text'), updateChip = $('#update'), appUpdateChip = $('#app-update');
  const slot = $('#slot'), dock = $('#dock'), stageBox = $('#stage'), intro = $('#intro'), machine = $('#machine'), pager = $('#pager');
  const sceneNames = { city:['Cyberpunk City','Ciudad Cyberpunk'], paradise:['Paradise','Paraíso'], surf:['Tidal Rush','Tidal Rush'],
    'token-run':['Token Run','Token Run'], 'city-iso':['Isometric City','Ciudad isométrica'], fighting:['Versus','Versus'],
    'blue-lightning':['Blue Lightning','Blue Lightning'], 'game-boy':['Game Boy','Game Boy'],
    'neon-city':['Neon City','Neon City'], 'neon-district':['Cozy Mountain Home','Casa acogedora en la montaña'], 'violet-horizon':['Violet Horizon','Violet Horizon'],
    'infinite-express':['Infinite Express','El expreso infinito'], 'midnight-video-club':['Peaceful House','Casa tranquila'] };
  const sceneOpen = $('#scene-open'), sceneDialog = $('#scene-dialog'), sceneClose = $('#scene-close'), sceneGrid = $('#scene-grid');
  const settingsDialog = $('#settings-dialog'), settingsOpen = $('#settings-open'), settingsClose = $('#settings-close');
  let availableScenes = [], sceneInfo = {}, selectedScene = 'city', stage = null, activeSceneVariant = '';
  let language = 'en', latest = null, connection = 'connecting', inflight = false;
  const reducedMotion = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };
  const getStored = (key) => { try { return localStorage.getItem(key); } catch (_) { return null; } };
  const setStored = (key, value) => { try { localStorage.setItem(key, value); } catch (_) {} };
  const valid = (v) => typeof v === 'number' && Number.isFinite(v);
  const percent = (v) => valid(v) && v >= 0 && v <= 100 ? Math.round(v) : null;
  const showPercent = (v) => percent(v) === null ? '—' : percent(v) + '%';
  // Free space below 5 % is critical, below 10 % low, below 20 % a warning. Quota "remaining" uses the same colours.
  const freeLevel = (value) => value < 5 ? 'critical' : value < 10 ? 'low' : value < 20 ? 'warning' : 'healthy';
  // The quota bars have a finer scale than the disks (Tony, 2026-11-09: the Claude five hours were at 26 % and still green): green from 60, lime from 40, yellow from 25, orange from 12, red below.
  const quotaLevel = (value) => value < 12 ? 'critical' : value < 25 ? 'low' : value < 40 ? 'warning' : value < 60 ? 'good' : 'healthy';
  const timeLeft = (epoch) => {
    if (!valid(epoch) || epoch * 1000 <= Date.now()) return '—';
    let minutes = Math.ceil((epoch * 1000 - Date.now()) / 60000);
    const days = Math.floor(minutes / 1440); minutes %= 1440;
    const hours = Math.floor(minutes / 60); minutes %= 60;
    if (days) return days + 'd ' + hours + 'h';
    if (hours) return hours + 'h ' + minutes + 'm';
    return minutes + 'm';
  };
  const el = (tag, className, text) => { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; };

  /* The native shell (an Android app around this page) offers a few things a browser cannot: the real backlight, a lasting full screen and the
     certificate pinned. Without it everything below still works; each call is guarded. */
  const bridge = window.AiDeskApp && typeof window.AiDeskApp.version === 'function' ? window.AiDeskApp : null;
  const native = (name, ...args) => { try { return bridge && typeof bridge[name] === 'function' ? bridge[name](...args) : undefined; } catch (_) { return undefined; } };
  const localApp = Boolean(bridge && typeof bridge.offlineStatus === 'function');
  function offlineInfo() {
    if (!localApp) return null;
    try {
      const value = JSON.parse(native('offlineStatus') || '{}');
      return { state: ['ready','saving','waiting','storage','sign_in'].includes(value.state) ? value.state : 'waiting',
        ready: value.ready === true, busy: value.busy === true, revision: typeof value.revision === 'string' && /^[a-f0-9]{64}$/.test(value.revision) ? value.revision : '',
        done: Number.isInteger(value.done) && value.done >= 0 && value.done <= 256 ? value.done : 0,
        count: Number.isInteger(value.count) && value.count >= 0 && value.count <= 256 ? value.count : 0,
        bytes: valid(value.bytes) && value.bytes >= 0 && value.bytes <= 2 * 1024 ** 3 ? value.bytes : 0,
        total: valid(value.total) && value.total >= 0 && value.total <= 2 * 1024 ** 3 ? value.total : 0 };
    } catch (_) { return { state:'waiting', ready:false, busy:false }; }
  }

  /* The tablet's OWN settings, kept on the PC (the small screen has its own, in its own control room). These are the defaults until they arrive. */
  const DEFAULT_SETTINGS = { scene: 'auto', motion: 'auto', auto: { mode: 'daypart', minutes: 20, rotate: [], parts: { dawn: [], day: [], dusk: [], night: [] } }, night: { enabled: true, start: '23:00', end: '07:30', level: 25, clock_only: false },
    sound: { enabled: true, volume: 60, at_night: false }, alerts: { quota: 10, disk: 5, resets: true }, photos: { seconds: 20 }, place: { lat: 41.39, lon: 2.17 }, weather: { enabled: false } };
  function cleanSettings(value, schema = DEFAULT_SETTINGS, prefix = '') {
    const out = {};
    if (!value || typeof value !== 'object' || Array.isArray(value)) return out;
    const limits = {'auto.minutes':[5,240], 'night.level':[5,100], 'sound.volume':[0,100], 'alerts.quota':[5,30], 'alerts.disk':[2,15], 'photos.seconds':[5,300], 'place.lat':[-90,90], 'place.lon':[-180,180]};
    for (const [key, item] of Object.entries(value)) {
      if (!Object.hasOwn(schema, key)) continue;
      const expected = schema[key], path = prefix ? prefix + '.' + key : key;
      if (Array.isArray(expected)) {
        if (Array.isArray(item) && item.length <= 40 && item.every(x => typeof x === 'string' && /^[a-z0-9-]{1,40}$/.test(x))) out[key] = [...new Set(item)];
      } else if (expected && typeof expected === 'object') {
        const nested = cleanSettings(item, expected, path); if (Object.keys(nested).length) out[key] = nested;
      } else if (typeof item === typeof expected) {
        if (typeof item === 'number' && (!Number.isFinite(item) || (limits[path] && (item < limits[path][0] || item > limits[path][1])))) continue;
        if (typeof item === 'string' && (item.length > 64 || ((path === 'night.start' || path === 'night.end') && !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(item)))) continue;
        if (path === 'motion' && !['auto','on','off'].includes(item)) continue;
        if (path === 'auto.mode' && !['daypart','rotate'].includes(item)) continue;
        if (path === 'scene' && !/^(?:auto|photos|[a-z0-9-]{1,40})$/.test(item)) continue;
        out[key] = item;
      }
    }
    return out;
  }
  function storedSettings(key) {
    try { const raw = getStored(key); return raw && raw.length <= 20000 ? cleanSettings(JSON.parse(raw)) : {}; } catch (_) { return {}; }
  }
  let settings = mergeSettings(JSON.parse(JSON.stringify(DEFAULT_SETTINGS)), storedSettings('tablet-settings-v1')), settingsLoaded = false,
    pendingPatch = storedSettings('tablet-settings-pending-v1'), patchTimer = 0, sendingSettings = false, settingsInFlight = {}, settingsRevision = 0;
  function keepSettings() {
    setStored('tablet-settings-v1', JSON.stringify(settings));
    setStored('tablet-settings-pending-v1', JSON.stringify(assignDeep(JSON.parse(JSON.stringify(settingsInFlight)), pendingPatch)));
  }
  function mergeSettings(base, incoming) {
    for (const [key, value] of Object.entries(incoming || {})) {
      if (!Object.hasOwn(base, key)) continue;
      if (value && typeof value === 'object' && !Array.isArray(value) && base[key] && typeof base[key] === 'object') mergeSettings(base[key], value); else base[key] = value;
    }
    return base;
  }
  function assignDeep(target, source) {          // collects what changed since the last send, nested like the settings themselves
    for (const [key, value] of Object.entries(source)) {
      if (value && typeof value === 'object' && !Array.isArray(value)) assignDeep(target[key] = target[key] || {}, value); else target[key] = value;
    }
    return target;
  }
  function setSetting(path, value) {
    const keys = path.split('.'), patch = {};
    let into = settings, out = patch;
    keys.forEach((key, i) => {
      if (i === keys.length - 1) { into[key] = value; out[key] = value; } else { into = into[key]; out[key] = out[key] || {}; out = out[key]; }
    });
    assignDeep(pendingPatch, patch);
    settingsRevision++;
    keepSettings();
    clearTimeout(patchTimer);
    patchTimer = setTimeout(sendSettings, 350);
    settingsChanged(path);
  }
  async function sendSettings() {
    if (sendingSettings || !Object.keys(pendingPatch).length) return;
    sendingSettings = true;
    const patch = pendingPatch; settingsInFlight = patch; pendingPatch = {}; keepSettings();
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 4000);
    try {
      const response = await fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch), cache: 'no-store', signal: controller.signal });
      if (!response.ok) throw new Error('settings unavailable');
    } catch (_) { pendingPatch = assignDeep(patch, pendingPatch); } // a newer local choice always wins
    finally { clearTimeout(timer); sendingSettings = false; settingsInFlight = {}; keepSettings(); }
  }
  async function loadSettings() {
    const requestedRevision = settingsRevision;
    const dirtyWhenRequested = assignDeep(JSON.parse(JSON.stringify(settingsInFlight)), pendingPatch);
    try {
      const response = await fetch('/api/settings', { cache: 'no-store' });
      if (response.status === 401) { window.location.replace('/login'); return; }
      if (response.ok) {
        const incoming = cleanSettings((await response.json()).settings);
        if (requestedRevision === settingsRevision) {
          settings = mergeSettings(JSON.parse(JSON.stringify(DEFAULT_SETTINGS)), incoming);
          mergeSettings(settings, dirtyWhenRequested);
          mergeSettings(settings, assignDeep(JSON.parse(JSON.stringify(settingsInFlight)), pendingPatch));
        }
        keepSettings(); settingsLoaded = true; settingsChanged('*'); sendSettings();
      }
    } catch (_) { /* the tablet's last display settings stay */ }
  }
  function settingsChanged(path) {
    if (path === '*' || path === 'motion') applyMotion();
    if (path === '*' || path === 'scene' || path.startsWith('auto.') || path.startsWith('photos.') || path.startsWith('place.')) { resolveScene(); }
    if (path === '*' || path.startsWith('night.')) tickNight();
    if (path === '*' || path.startsWith('weather.')) renderWeather();
    if (path.startsWith('place.') || path === 'weather.enabled') setTimeout(loadWeather, 2500);       // the PC looks at the new place within seconds
    sceneLabel();
  }
  const wordsNow = () => words[language];

  function updateTime() {
    const now = new Date(), locale = language === 'es' ? 'es-ES' : 'en-GB';
    clock.textContent = new Intl.DateTimeFormat(locale, {hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(now);
    clock.dateTime = now.toISOString();
    date.textContent = new Intl.DateTimeFormat(locale, {weekday:'long',day:'numeric',month:'long'}).format(now);
  }
  /* The outside weather beside the clock: the PC fetches it (tablet_weather.py), the page asks for it every 5 minutes and draws an icon and a few words. A reading that
     is missing, old or switched off shows nothing at all: unknown is never a number. */
  let weatherNow = null, weatherAt = 0;
  function renderWeather() {
    const reading = weatherNow && { ...weatherNow, age: (Number(weatherNow.age) || 0) + (Date.now() - weatherAt) / 1000 };
    const view = window.TabletWeather && settings.weather && settings.weather.enabled !== false ? TabletWeather.view(reading, language) : null;
    if (stage && stage.setWeather) stage.setWeather(view ? { code: reading.code } : null);
    weatherBox.hidden = !view;
    if (!view) return;
    wxIcon.innerHTML = TabletWeather.svg(view.icon, view.day);          // fixed markup picked from the module's own table, never text from the network
    wxTemp.textContent = view.temp; wxText.textContent = view.text; weatherBox.setAttribute('aria-label', view.label);
  }
  async function loadWeather() {
    try {
      const response = await fetch('/api/weather', { cache: 'no-store' });
      if (response.status === 401) { window.location.replace('/login'); return; }
      const body = response.ok ? await response.json() : null;
      weatherNow = body && body.weather && typeof body.weather === 'object' ? body.weather : null; weatherAt = Date.now();
    } catch (_) { /* the last reading ages out by itself */ }
    renderWeather(); if (typeof fit === 'function') fit();
  }
  function updateFull() {
    const active = Boolean(document.fullscreenElement);
    const label = words[language][active ? 'exit_full_screen' : 'full_screen'];
    fullButton.setAttribute('aria-label',label); fullButton.title = label;
    fullButton.setAttribute('aria-pressed',String(active));
  }

  /* Keep the screen on while the page is full screen. The Screen Wake Lock needs a secure page, can be refused (battery saver, a manual
     lock) and is released by the system when the page is hidden: it is asked for again whenever the page is visible and full screen. In the app
     the window itself keeps the screen on. */
  let wakeLock = null, wakeRetry = 0, wakeTimer = 0, awakeState = 'off';
  function setAwake(state) {
    awakeState = state;
    awakeChip.hidden = Boolean(bridge) || !document.fullscreenElement || state === 'off';       // in the app the screen is always on: nothing to say
    awakeChip.dataset.state = state === 'on' ? 'ok' : state === 'off' ? 'off' : 'blocked';
    awakeText.textContent = state === 'off' ? '' : words[language]['awake_' + state];
    awakeChip.title = state === 'off' ? '' : words[language]['awake_' + state + '_title'];
    fit();
  }
  function scheduleAwake(ms) { clearTimeout(wakeTimer); wakeTimer = setTimeout(keepAwake, ms); }
  async function keepAwake() {
    clearTimeout(wakeTimer);
    if (bridge) { native('keepAwake', true); setAwake('on'); return; }       // the app's window itself keeps the screen on
    if (!document.fullscreenElement || document.hidden) return;
    if (!('wakeLock' in navigator) || !window.isSecureContext) { setAwake('unsupported'); return; }
    if (wakeLock && !wakeLock.released) { setAwake('on'); return; }
    try {
      const lock = await navigator.wakeLock.request('screen');
      if (!document.fullscreenElement || document.hidden) { lock.release().catch(() => {}); return; }   // left full screen while waiting
      wakeLock = lock; wakeRetry = 0; setAwake('on');
      lock.addEventListener('release', () => {
        if (wakeLock === lock) wakeLock = null;
        if (document.fullscreenElement && !document.hidden) scheduleAwake(1500); else setAwake('off');
      });
    } catch (_) {
      wakeLock = null; setAwake('blocked'); scheduleAwake(Math.min(60000, 5000 * 2 ** wakeRetry++));
    }
  }
  function letSleep() {
    clearTimeout(wakeTimer); wakeRetry = 0;
    const lock = wakeLock; wakeLock = null;
    if (lock) lock.release().catch(() => {});
    setAwake('off');
  }

  /* The scene stage (another file) draws the picture or video with its look; without it, or for a scene it does not describe, the plain
     picture is shown as before. The areas tell it where the picture may go: the whole screen down to the dock for realistic scenes, the
     free slot above the clock for pixel scenes, which are shown whole on a monitor. Positions come from the layout (offsets), not from where a
     page happens to be scrolled to, so swiping to another page never moves the picture. */
  function sceneArea(look) {
    const base = pager.getBoundingClientRect(), width = window.innerWidth, home = $('#page-home');
    if (look === 'crt' || look === 'lcd') {
      const margin = Math.round(Math.min(slot.offsetWidth, slot.offsetHeight) * .025);
      return { left: base.left + home.offsetLeft + slot.offsetLeft + margin, top: base.top + slot.offsetTop + margin, width: Math.max(32, slot.offsetWidth - 2 * margin), height: Math.max(32, slot.offsetHeight - 2 * margin) };
    }
    const dockHidden = document.body.classList.contains('picture') || document.body.classList.contains('night-clock');
    return { left: 0, top: 0, width, height: Math.max(160, dockHidden ? window.innerHeight : base.top + dock.offsetTop + 44) };
  }
  function currentInfo() { return photoMode ? photoInfo : displayInfo(selectedScene); }
  function updateArea() {
    const info = currentInfo();
    if (stage && info) stage.setArea(sceneArea(info.look));
  }
  /* The page never scrolls. It reads the height that is really visible (a browser's 100dvh can differ from it) and, when anything would not fit
     (a larger system font, an unusual screen), lowers --fit until everything does: all sizes shrink together, nothing is cut off or hidden. */
  const root = document.documentElement, shell = $('.display'), ruler = $('#ruler');
  let fitScale = 1, fitFirst = 0, fitBusy = false;
  const overflowOf = () => [shell, ...document.querySelectorAll('.page, .sheet')].reduce((worst, box) => [Math.max(worst[0], box.scrollHeight - box.clientHeight), Math.max(worst[1], box.scrollWidth - box.clientWidth)], [0, 0]);
  const ratioOf = (boxes) => boxes.reduce((worst, box) => Math.max(worst, box.scrollHeight / Math.max(1, box.clientHeight), box.scrollWidth / Math.max(1, box.clientWidth)), 1);
  /* Shrinks one part (the shell, or a single page) until its boxes stop overflowing. Every page has its own factor, so a dense page never makes Home smaller. */
  function fitPart(node, boxes) {
    node.style.setProperty('--fit', '1');
    const first = boxes.reduce((worst, box) => Math.max(worst, box.scrollHeight - box.clientHeight), 0);
    let scale = 1;
    for (let step = 0; step < 8; step++) {
      const ratio = ratioOf(boxes);
      if (ratio <= 1.001) break;
      scale = Math.max(.4, scale * Math.min(.99, 1 / ratio));
      node.style.setProperty('--fit', scale.toFixed(3));
    }
    return { scale, first };
  }
  /* The top bar gives up its least important words one level at a time (the name, then the labels and the connection text, then the mark) until it fits. */
  const topbar = $('.topbar');
  function fitTopbar() {
    for (let level = 0; level <= 3; level++) {
      topbar.dataset.compact = String(level);
      if (topbar.scrollWidth <= topbar.clientWidth + 1) return;
    }
  }
  function fit() {
    if (fitBusy || window.innerHeight < 200 || window.innerWidth < 200) return;   // a window that is not really there yet (a page being opened): wait for the next resize
    fitBusy = true;
    try {
      root.style.setProperty('--app-h', window.innerHeight + 'px');
      fitTopbar();
      const parts = [fitPart(root, [shell])];
      document.querySelectorAll('.page').forEach((page) => parts.push(fitPart(page, [page, ...page.querySelectorAll('.sheet')])));
      fitScale = Math.min(...parts.map((part) => part.scale));
      fitFirst = Math.max(...parts.map((part) => part.first));
    } finally { fitBusy = false; }
    alignPage();
    updateArea();
  }
  /* What this screen really is, sent to this same server (sizes, switches and fixed words only; never a reading, an account or a password),
     so the layout and the animation can be judged from the real tablet instead of from a simulation. */
  function measure(why) {
    const unit = (ruler.getBoundingClientRect().height / 100) || 1;
    const box = (node) => node ? Math.round(node.getBoundingClientRect().height / unit * 10) / 10 : 0;
    const [tall, wide] = overflowOf(), status = stage && stage.status ? stage.status() : null, info = currentInfo();
    const out = { why, vw: innerWidth, vh: innerHeight, sw: screen.width, sh: screen.height, dpr: devicePixelRatio, fit: fitScale, u: Math.round(unit * 1000) / 1000,
      ovh: tall, ovw: wide, ovh0: fitFirst, fs: Boolean(document.fullscreenElement), secure: window.isSecureContext, hidden: document.hidden, rm: reducedMotion.matches,
      glass: document.body.classList.contains('glass'), wake: 'wakeLock' in navigator ? awakeState : 'none', scene: Object.hasOwn(sceneNames, selectedScene) ? selectedScene : 'city', look: info ? info.look : 'plain',
      boxes: { topbar: box($('.topbar')), slot: box(slot), intro: box($('.intro')), dock: box(dock), quota: box($('.quota-grid')), band: box($('.session-band')),
        machine: box($('#machine')), disks: box($('#disks')) },
      ua: (navigator.userAgent.match(/Android [\d.]+|Chrome\/[\d.]+|Firefox\/[\d.]+|SamsungBrowser\/[\d.]+|Edg\/[\d.]+/g) || []).join(' '),
      cores: navigator.hardwareConcurrency || 0, mem: navigator.deviceMemory || 0, plat: platInfo };
    if (bridge) { out.app = String(native('version') || ''); out.bat = String(native('battery') || ''); const lux = Number(native('light')); if (Number.isFinite(lux)) out.lux = lux; }
    const local = offlineInfo();
    if (local) Object.assign(out, {offline_state:local.state, offline_ready:local.ready, offline_done:local.done, offline_count:local.count, offline_bytes:local.bytes, offline_total:local.total});
    if (window.visualViewport) out.vvs = window.visualViewport.scale;
    if (status) {
      Object.assign(out, { renderer: status.renderer, tier: status.tier, level: status.level, scale: status.scale, fps: status.fps, dropped: status.dropped, motion: status.motion,
        paused: status.paused, video: status.video, ready: status.ready, blocked: Boolean(status.blocked), gpu: status.gpu || '', media: status.media, canvas: status.canvas,
        clip: status.clip, notes: status.notes });
      if (status.error) out.error = status.error;
    }
    return out;
  }
  // the real Android version and model (Chrome's user agent hides them): only for the report, to know what this tablet is
  let platInfo = '';
  if (navigator.userAgentData && navigator.userAgentData.getHighEntropyValues) navigator.userAgentData.getHighEntropyValues(['platformVersion', 'model']).then((v) => { platInfo = ((v.platformVersion || '') + ' ' + (v.model || '')).trim(); }).catch(() => {});
  let reportTimer = 0;
  function report(why, delay = 0) {
    clearTimeout(reportTimer);
    reportTimer = setTimeout(() => {
      try {
        fetch('/api/report', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(measure(why)), cache: 'no-store', keepalive: true }).catch(() => {});
      } catch (_) { /* a report that cannot be sent is not a problem for the page */ }
    }, delay);
  }
  const fxFlag = new URLSearchParams(window.location.search).get('fx');
  const glassAllowed = !['off', 'low', 'css'].includes(fxFlag);
  function setGlass(on) { document.body.classList.toggle('glass', glassAllowed && on); }
  // The stage tells the page when it has to lower itself (tier light, low or css): the blurred glass over the picture goes first.
  // The real tablet has an old Mali-T860: a blurred glass over a moving picture is too much for such a GPU, so on those the dock is plain from the start.
  const WEAK_GPU = /Mali-T[0-9]{3}|Mali-4[0-9]{2}|Adreno \(TM\) [2-4][0-9]{2}|PowerVR|Vivante|VideoCore/i;
  let weakGpu = false;
  function onStage(status) {
    if (!status) return;
    if (status.gpu && !weakGpu && WEAK_GPU.test(status.gpu)) weakGpu = true;
    setGlass(!weakGpu && !status.live && !['light', 'low', 'css'].includes(status.tier));      // live effects redraw the canvas 30 times a second: the glass would be re-blurred each time
  }
  const effectiveMotion = () => settings.motion === 'on' ? true : settings.motion === 'off' ? false : !reducedMotion.matches;
  function applyMotion() { if (stage) stage.setMotion(effectiveMotion()); }
  /* Two stages share the screen: the photo stage (pictures, videos, live effects) and the game stage (real-time pixel scenes, stage-game.js). The page talks to one
     object; each scene goes to the stage its look asks for, and the other one is cleared. */
  function routeStages(photo, game) {
    let active = photo || game;
    const each = (fn) => { for (const s of [photo, game]) if (s) { try { fn(s); } catch (_) { /* one stage failing must not take the other down */ } } };
    return {
      show(info) {
        const toGame = Boolean(game && info && info.look === 'game');
        if (toGame) { if (photo) photo.show(null); active = game; game.show(info); } else { if (game) game.show(null); active = photo || game; if (photo) photo.show(info); }
      },
      setArea: (rect) => each((s) => s.setArea(rect)), setMotion: (on) => each((s) => s.setMotion(on)),
      setQuality: (q) => each((s) => { if (s.setQuality) s.setQuality(q); }), setLive: (on) => each((s) => { if (s.setLive) s.setLive(on); }),
      pause: () => each((s) => s.pause()), resume: () => each((s) => s.resume()),
      setReadings: (latest) => each((s) => { if (s.setReadings) s.setReadings(latest); }),
      setWeather: (latest) => each((s) => { if (s.setWeather) s.setWeather(latest); }),
      poke: (x, y) => { if (active && active.poke) active.poke(x, y); },
      status: () => (active ? active.status() : { renderer: 'plain', tier: 'plain' }),
    };
  }
  function createStage() {
    setGlass(true);
    let photo = null, game = null;
    if (window.SceneStage && typeof window.SceneStage.create === 'function') { try { photo = window.SceneStage.create(stageBox, { onStatus: onStage }); } catch (_) { photo = null; } }
    if (window.TabletGames && typeof window.TabletGames.create === 'function') { try { game = window.TabletGames.create(stageBox, { onStatus: onStage }); } catch (_) { game = null; } }
    stage = photo || game ? routeStages(photo, game) : null;
    if (stage) { applyMotion(); renderWeather(); }
  }
  function setLanguage(next) {
    language = next === 'es' ? 'es' : 'en';
    document.documentElement.lang = language;
    document.querySelectorAll('[data-i18n]').forEach((n) => { n.textContent = words[language][n.dataset.i18n] || n.textContent; });
    sceneClose.setAttribute('aria-label',words[language].close); settingsClose.setAttribute('aria-label',words[language].close);
    settingsOpen.setAttribute('aria-label',words[language].settings); updateChip.title = words[language].update_title; appUpdateChip.title = words[language].app_update_title; machine.setAttribute('aria-label',words[language].computer_open);
    $('#dots').querySelectorAll('button').forEach((b) => b.setAttribute('aria-label', words[language]['page_' + b.dataset.page]));
    setStored('tablet-preview-language',language); updateFull(); updateTime(); renderWeather(); sceneLabel(); setAwake(awakeState); pictureLabel(); render();
    if (window.TabletPanels) { TabletPanels.renderRemote(); if (settingsDialog.open) TabletPanels.renderSettings(); }
  }
  function sceneLabel() {
    const known = Object.hasOwn(sceneNames, selectedScene) ? sceneNames[selectedScene][language === 'es' ? 1 : 0] : '';
    const name = photoMode ? words[language].scene_photos : settings.scene === 'auto' ? words[language].auto_short + ' · ' + known : known;
    $('#scene-name').textContent = name;
    sceneOpen.setAttribute('aria-label',words[language].choose_scene + ': ' + name);
    fitTopbar();                      // a longer name can make the bar overflow: it gives up its least important words
  }
  function sceneVariant(scene) {
    if (!['infinite-express', 'midnight-video-club', 'neon-district'].includes(scene) || !window.TabletSchedule) return '';
    const now = Date.now(), sun = TabletSchedule.sunTimes(now, settings.place.lat, settings.place.lon);
    const part = TabletSchedule.daypart(now, sun);
    return sceneInfo[scene + '-' + part] ? part : '';
  }
  function displayInfo(scene) {
    const variant = sceneVariant(scene);
    return (variant && sceneInfo[scene + '-' + variant]) || sceneInfo[scene];
  }
  function setScene(scene, save = true) {
    selectedScene = Object.hasOwn(sceneNames,scene) ? scene : 'city';
    activeSceneVariant = sceneVariant(selectedScene);
    document.body.dataset.scene = selectedScene;
    const landscape = $('#landscape'), info = displayInfo(selectedScene);
    if (stage && info) {
      document.body.dataset.look = info.look;
      document.body.classList.add('stage-on');
      const savedPack = localApp && offlineInfo();
      stage.show(Object.assign({ name: selectedScene }, info, { resourceRevision: savedPack && savedPack.ready ? savedPack.revision : '' }));
      updateArea();
    } else {
      if (stage) stage.show(null);
      delete document.body.dataset.look;
      document.body.classList.remove('stage-on');
      if (availableScenes.includes(selectedScene)) {
        const picture = info && (info.still || (info.media && info.media.kind === 'image' && info.media.url)) || `/assets/scene-${selectedScene}.webp`;
        landscape.style.setProperty('--scene-image',`url("${picture}")`);
        landscape.style.setProperty('--scene-still',`url("${picture}")`);
      } else {
        landscape.style.removeProperty('--scene-image'); landscape.style.removeProperty('--scene-still');
      }
    }
    sceneLabel();
    if (save) report('scene', 5000);
  }

  /* Which scene is on: one the user chose, one that suits the time of day (computed here from the place, no internet) or a rotation, or the photos. */
  let photoMode = false, photoInfo = null, photos = [], photoIndex = 0, photoTimer = 0, scenePulse = 0;
  function resolveScene() {
    if (!availableScenes.length && settings.scene !== 'photos') return;
    if (settings.scene === 'photos' && photos.length) { startPhotos(); return; }
    stopPhotos();
    let target = settings.scene;
    if (target === 'auto' || target === 'photos') target = window.TabletSchedule ? TabletSchedule.autoScene({ now: Date.now(), lat: settings.place.lat, lon: settings.place.lon, mode: settings.auto.mode, minutes: settings.auto.minutes, available: availableScenes, rotate: settings.auto.rotate, parts: settings.auto.parts }) : availableScenes[0];
    if (!availableScenes.includes(target)) target = availableScenes.includes('city') ? 'city' : availableScenes[0];
    if (target && availableScenes.includes(target) && (target !== selectedScene || !document.body.classList.contains('stage-on') || sceneVariant(target) !== activeSceneVariant)) setScene(target, false);
    sceneLabel();
  }
  function showPhoto() {
    if (!photoMode || !photos.length || !stage) return;
    const photo = photos[photoIndex % photos.length]; photoIndex += 1;
    photoInfo = { name: 'photo', look: 'photo', media: { kind: 'image', url: photo.url, width: photo.width, height: photo.height }, focus: photo.focus || [.5, .5], rate: 1 };
    document.body.dataset.scene = 'photos'; document.body.dataset.look = 'photo'; document.body.classList.add('stage-on');
    stage.show(photoInfo); updateArea();
  }
  function startPhotos() {
    if (photoMode) { clearInterval(photoTimer); photoTimer = setInterval(showPhoto, Math.max(5, settings.photos.seconds) * 1000); return; }
    photoMode = true; photoIndex = Math.floor(Math.random() * photos.length); showPhoto();
    clearInterval(photoTimer); photoTimer = setInterval(showPhoto, Math.max(5, settings.photos.seconds) * 1000); sceneLabel();
  }
  function stopPhotos() { if (!photoMode) return; photoMode = false; photoInfo = null; clearInterval(photoTimer); }
  async function loadPhotos() {
    try {
      const response = await fetch('/api/photos', { cache: 'no-store' });
      if (!response.ok) return;
      const result = await response.json();
      photos = Array.isArray(result.photos) ? result.photos.filter((p) => p && typeof p.url === 'string') : [];
    } catch (_) { photos = []; }
    resolveScene();
  }
  function chooseScene(name) {
    if (name === 'auto-day') { setSetting('auto.mode', 'daypart'); setSetting('scene', 'auto'); } else if (name === 'auto-rotate') { setSetting('auto.mode', 'rotate'); setSetting('scene', 'auto'); }
    else setSetting('scene', name);
    report('scene', 5000);
  }
  /* Which scenes the automatic modes may show (Tony, 2026-11-10): one list for the rotation and one for each part of the day. An empty list means the suggested scenes
     (all of them for the rotation, the built-in ones for a part of the day); the dialog shows what is really in use and never lets the last scene be switched off. */
  const POOL_PATHS = { rotate: 'auto.rotate', dawn: 'auto.parts.dawn', day: 'auto.parts.day', dusk: 'auto.parts.dusk', night: 'auto.parts.night' };
  const poolOf = (which) => which === 'rotate' ? settings.auto.rotate : settings.auto.parts[which];
  const suggestedPool = (which) => which === 'rotate' ? availableScenes.slice() : (window.TabletSchedule ? TabletSchedule.POOLS[which] : []).filter((name) => availableScenes.includes(name));
  function activePool(which) { const mine = (poolOf(which) || []).filter((name) => availableScenes.includes(name)); return mine.length ? mine : suggestedPool(which); }
  function poolSummary(which) {
    const mine = (poolOf(which) || []).filter((name) => availableScenes.includes(name)), w = words[language];
    if (!mine.length) return which === 'rotate' ? w.pool_all + ' (' + availableScenes.length + ')' : w.pool_suggested + ' (' + suggestedPool(which).length + ')';
    return mine.length + ' ' + w.pool_count + ' ' + availableScenes.length;
  }
  function choosePool(which) {
    if (!Object.hasOwn(POOL_PATHS, which)) return;
    const dialog = $('#pool-dialog'), grid = $('#pool-grid'), w = words[language];
    $('#pool-title').textContent = w['pool_' + which];
    const draw = () => {
      const active = activePool(which);
      grid.replaceChildren();
      for (const name of availableScenes) {
        const on = active.includes(name), button = el('button', 'scene-option'); button.type = 'button'; button.setAttribute('aria-pressed', String(on));
        const picture = el('img'); picture.src = '/assets/thumb-' + name + '.webp'; picture.alt = '';
        button.append(picture, el('span', '', sceneNames[name][language === 'es' ? 1 : 0]), el('i', 'pool-check', on ? '✓' : ''));
        button.addEventListener('click', () => {
          const now = activePool(which), next = on ? now.filter((n) => n !== name) : availableScenes.filter((n) => n === name || now.includes(n));
          if (!next.length) return;                                    // the last scene stays on
          setSetting(POOL_PATHS[which], next); draw();
        });
        grid.append(button);
      }
    };
    $('#pool-reset').onclick = () => { setSetting(POOL_PATHS[which], []); draw(); };
    $('#pool-reset').textContent = w.pool_reset; $('#pool-hint').textContent = w.pool_hint; $('#pool-close').textContent = w.pool_done;
    draw(); dialog.onclose = () => { if (window.TabletPanels && settingsDialog.open) TabletPanels.renderSettings(); };
    dialog.showModal();
  }
  function showScenes() {
    sceneGrid.replaceChildren();
    const tile = (id, image, label, pressed) => {
      const button = el('button', 'scene-option'); button.type = 'button'; button.setAttribute('aria-pressed', String(pressed));
      if (image) { const picture = el('img'); picture.src = image; picture.alt = ''; button.append(picture); } else button.append(el('div', 'scene-glyph', id === 'photos' ? '▦' : id === 'auto-rotate' ? '⟳' : '☀'));
      button.append(el('span', '', label)); button.addEventListener('click', () => { chooseScene(id); sceneDialog.close(); }); sceneGrid.append(button);
    };
    tile('auto-day', null, words[language].auto_day_title, settings.scene === 'auto' && settings.auto.mode === 'daypart');
    tile('auto-rotate', null, words[language].auto_rotate_title, settings.scene === 'auto' && settings.auto.mode === 'rotate');
    if (photos.length) tile('photos', null, words[language].scene_photos, settings.scene === 'photos');
    availableScenes.forEach((name) => tile(name, '/assets/thumb-' + name + '.webp', sceneNames[name][language === 'es' ? 1 : 0], settings.scene === name));
    if (availableScenes.length || photos.length) sceneDialog.showModal();
  }
  async function loadScenes() {
    try {
      const response = await fetch('/api/scenes',{cache:'no-store'});
      if (!response.ok) return;
      const result = await response.json();
      // Keep the retired artwork on disk, but do not offer this duplicate city on the tablet.
      availableScenes = Array.isArray(result.scenes) ? result.scenes.filter(name => name !== 'neon-city' && Object.hasOwn(sceneNames,name)) : [];
      sceneInfo = result.info && typeof result.info === 'object' ? result.info : {};
      if (availableScenes.length) {
        resolveScene();
        if (!document.body.classList.contains('stage-on') && !photoMode) setScene(selectedScene, false);
      }
      sceneOpen.disabled = !availableScenes.length;
    } catch (_) { sceneOpen.disabled = true; }
  }
  function meter(node, value) {
    if (node) node.style.width = (percent(value) ?? 0) + '%';
  }
  // Credits are an absolute balance, only meaningful after the current week
  // is exactly exhausted, and only a confirmed positive balance enables the switch.
  function creditBalance(data, remaining) {
    if (remaining !== 0 || !data || typeof data.credits !== 'string') return null;
    if (data.credits === '<0.01') return data.credits;
    return /^\d{1,10}(?:\.\d{1,2})?$/.test(data.credits) && Number(data.credits) > 0 ? data.credits : null;
  }
  function creditSize(value) {
    return value.length > 10 ? 'tiny' : value.length > 7 ? 'small' : 'normal';
  }
  function provider(name, data) {
    const card = $('[data-provider="' + name + '"]');
    data = data || {};
    const week = data.weekly && timeLeft(data.weekly.resets_at) !== '—' ? data.weekly : null;
    const raw = week && valid(week.remaining) && week.remaining >= 0 && week.remaining <= 100 ? week.remaining : null;
    const left = raw === null ? null : raw > 0 && raw < 1 ? '<1' : String(Math.floor(raw));
    const credit = creditBalance(data, raw), value = credit;
    card.dataset.level = raw === null ? 'unknown' : quotaLevel(raw);
    card.dataset.mode = credit === null ? 'quota' : 'credits';
    card.dataset.creditSize = credit === null ? 'normal' : creditSize(value);
    $('.amount-number',card).textContent = credit === null ? (left === null ? '—' : left) : value;
    $('.amount-unit',card).textContent = credit === null && raw !== null ? '%' : '';
    $('.card-bottom .caption',card).textContent = words[language][credit === null ? 'weekly_left' : 'credits'];
    $('.reset-time',card).textContent = week ? timeLeft(week.resets_at) : '—';
    meter($('.meter span',card),raw);
    $('.meter',card).setAttribute('aria-label',left === null ? words[language].unavailable : left + '% ' + words[language].remaining);
    const hearts = $('.hearts',card), resets = data.resets || {};
    const count = Number.isInteger(resets.count) && resets.count >= 0 ? resets.count : null;
    hearts.replaceChildren();
    if (count === null || resets.old) {
      const dot = document.createElement('span'); dot.className = 'unknown-dot'; dot.textContent = '•'; hearts.append(dot);
    }
    for (let n = 0; n < 3; n++) {
      const heart = document.createElement(count !== null && n < count ? 'b' : 'i'); heart.textContent = '♥'; hearts.append(heart);
    }
    if (count !== null && count > 3) { const plus = document.createElement('b'); plus.textContent = '+'; hearts.append(plus); }
    hearts.setAttribute('aria-label',count === null ? words[language].unavailable : count + ' ' + words[language].resets + (resets.old ? ' · ' + words[language].old : ''));
    if (name === 'claude') {
      const session = data.session && timeLeft(data.session.resets_at) !== '—' ? data.session : null;
      const known = session && percent(session.remaining) !== null;
      const band = $('.session-band');
      band.dataset.level = known ? quotaLevel(session.remaining) : 'unknown';
      $('.session-value',band).textContent = known ? showPercent(session.remaining) : '—';
      $('.session-time',band).textContent = known ? timeLeft(session.resets_at) : '';
      meter($('.meter span',band),known ? session.remaining : null);
      $('.meter',band).setAttribute('aria-label',known ? showPercent(session.remaining) + ' ' + words[language].remaining : words[language].unavailable);
    }
  }
  function size(bytes) {
    if (!valid(bytes) || bytes < 0) return '—';
    const n = bytes / (1024 ** 3);
    return n >= 1024 ? (n / 1024).toFixed(1).replace(/\.0$/, '') + ' TB' : (n < 10 ? n.toFixed(1) : Math.round(n)) + ' GB';
  }
  function cloudSize(bytes) {
    const gb = bytes / 1000000000;
    const value = gb >= 1000 ? gb / 1000 : gb;
    return value.toFixed(2).replace(/\.?0+$/, '') + (gb >= 1000 ? ' TB' : ' GB');
  }
  function temp(selector, value) {
    const node = $(selector); node.replaceChildren(document.createTextNode(valid(value) ? String(Math.round(value)) : '—'));
    const unit = document.createElement('span'); unit.textContent = '°C'; node.append(unit);
  }
  // One disk: its free space as a size, coloured by how much is left; the bar is how much is USED. No percentage is written.
  function diskItem(disk) {
    const google = disk.kind === 'google_drive';
    const label = google ? disk.name + ' · Drive' : disk.name;
    const storageValid = valid(disk.total) && disk.total > 0 && valid(disk.free) && disk.free >= 0 && disk.free <= disk.total;
    const item = el('div', 'disk'); item.setAttribute('role', 'group');
    if (google && (!storageValid || disk.quota_source !== 'manual' || !valid(disk.quota_at) || !Number.isFinite(new Date(disk.quota_at * 1000).getTime()))) {
      item.append(el('div', 'disk-line', ''), el('div', 'disk-note', words[language].cloud_unavailable));
      item.firstChild.append(el('b', '', label));
      item.setAttribute('aria-label', label + ': ' + words[language].cloud_unavailable);
      return item;
    }
    if (!storageValid) return null;
    item.dataset.level = freeLevel(100 * disk.free / disk.total);
    const freeText = google ? cloudSize(disk.free) : size(disk.free), totalText = google ? cloudSize(disk.total) : size(disk.total);
    const line = el('div', 'disk-line'); line.append(el('b', '', label), el('span', 'disk-of', words[language].of + ' ' + totalText));
    const value = el('div', 'disk-free', freeText); value.append(el('small', '', words[language].free));
    const track = el('div', 'system-meter'); const fill = el('span'); track.append(fill); meter(fill, 100 * (disk.total - disk.free) / disk.total);
    track.setAttribute('aria-hidden', 'true');
    item.append(line, value, track);
    if (google) {
      const when = new Intl.DateTimeFormat(language === 'es' ? 'es-ES' : 'en-GB', {day:'numeric', month:'short', year:'numeric'}).format(new Date(disk.quota_at * 1000));
      item.append(el('div', 'disk-note', words[language].manual + ' · ' + when));
    }
    item.setAttribute('aria-label', label + ': ' + freeText + ' ' + words[language].free + ' ' + words[language].of + ' ' + totalText);
    return item;
  }
  function hardware(data) {
    data = data || {};
    const gpu = Array.isArray(data.gpus) ? data.gpus[0] || {} : {};
    temp('#cpu-temp',data.cpu_temp_c); temp('#gpu-temp',gpu.temp_c);
    $('#cpu-load').textContent = showPercent(data.cpu_percent); meter($('#cpu-meter'),data.cpu_percent);
    $('#gpu-load').textContent = showPercent(gpu.percent); meter($('#gpu-meter'),gpu.percent);
    const mem = data.memory, value = $('#memory-value');
    if (mem && valid(mem.total) && mem.total > 0 && valid(mem.free) && mem.free >= 0 && mem.free <= mem.total) {
      const used = mem.total - mem.free;
      value.replaceChildren(document.createTextNode(size(used).replace(/ (GB|TB)$/, '')), el('span', '', size(used).slice(-2)), el('span', 'of', '/ ' + size(mem.total)));
      $('#memory-load').textContent = showPercent(100 * used / mem.total); meter($('#memory-meter'),100 * used / mem.total);
    } else { value.textContent = '—'; $('#memory-load').textContent = ''; meter($('#memory-meter'),null); }
    const disks = $('#disks'); disks.replaceChildren();
    const list = Array.isArray(data.disks) ? data.disks : [];
    list.forEach((disk) => {
      if (!disk || typeof disk.name !== 'string') return;
      const item = diskItem(disk);
      if (item) disks.append(item);
    });
    if (!disks.childElementCount) disks.append(el('span', 'disk-empty', '—'));
    // the basic view says what uses the most; the Computer page has the rest
    const top = data.processes && Array.isArray(data.processes.cpu) ? data.processes.cpu.filter((p) => valid(p.percent)).slice(0, 2) : [];
    const busy = $('#busy'); busy.replaceChildren();
    if (top.length) { busy.append(document.createTextNode(words[language].most_active + '  ')); top.forEach((p, i) => { if (i) busy.append(document.createTextNode(' · ')); busy.append(el('b', '', p.name + ' ' + Math.round(p.percent) + '%')); }); }
  }

  /* Alerts: what just happened (a quota under its limit, a window renewed, a disk full) is shown at once and, when allowed, heard. */
  const alerts = window.TabletAlerts ? TabletAlerts.create() : null;
  const sound = window.TabletAlerts ? TabletAlerts.createSound(window.AudioContext || window.webkitAudioContext) : null;
  const alertLog = [];
  let toastTimer = 0;
  /* The app's own update (Tony, 2026-11-10): the PC offers the newest APK and says which version and SHA-256 it is (`latest.app`); when it is newer than the installed
     app the page shows an APP UPDATE chip and a button in Settings. The app downloads it from the PC alone, checks the hash and hands it to Android's installer, which
     asks the user and only accepts the same signing key. In a browser, or in an older app without the door, none of this appears (the install link stays). */
  const appBuild = () => { const m = /^1\.(\d{1,6})$/.exec(bridge ? String(native('version') || '') : ''); return m ? Number(m[1]) : null; };
  function appUpdate() {
    const app = latest && latest.app && typeof latest.app === 'object' ? latest.app : null, build = appBuild();
    if (!app || build === null || !bridge || typeof bridge.installUpdate !== 'function') return null;
    const code = app.version_code;
    if (!Number.isInteger(code) || code <= build || typeof app.sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(app.sha256)) return null;
    return { from: build, to: code, sha: app.sha256 };
  }
  function renderAppUpdate() { appUpdateChip.hidden = !appUpdate(); }
  function startAppUpdate() {
    const update = appUpdate(); if (!update) return;
    const answer = native('installUpdate', update.sha);
    if (answer === 'busy') showToast(words[language].app_state_busy, 'info'); else if (answer !== 'started') showToast(words[language].app_state_failed, 'warning');
  }
  window.aiDeskAppUpdate = (state) => {                      // called by the app with a fixed word
    const key = 'app_state_' + String(state);
    if (words[language][key]) showToast(words[language][key], state === 'failed' ? 'warning' : 'info');
  };
  function alertText(a) {
    const w = words[language], who = a.provider ? a.provider.toUpperCase() + ' · ' + (a.window === 'five' ? w.alert_five : w.alert_week) : a.name;
    if (a.kind === 'reset') return who + ' · ' + w.alert_renewed;
    if (a.kind === 'disk-low') return a.name + ' · ' + w.alert_full + ' · ' + size(a.free) + ' ' + w.free;
    return who + ' · ' + a.value + '% ' + w.left;
  }
  function showToast(text, level) {
    const toast = $('#toast'); toast.textContent = text; toast.dataset.level = level; toast.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { toast.hidden = true; }, 9000);
  }
  function flash(level) {
    const node = $('#flash'); node.style.setProperty('--flash', level === 'critical' ? '#ff7278' : level === 'warning' ? '#ffab62' : '#7fe0b2');
    node.classList.remove('on'); void node.offsetWidth; node.classList.add('on');
  }
  function raise(list) {
    if (!list.length) return;
    const top = TabletAlerts.worst(list), extra = list.length > 1 ? '  (+' + (list.length - 1) + ')' : '';
    const audible = settings.sound.enabled && (nightNow === 0 || settings.sound.at_night);
    let text = alertText(top) + extra;
    const heard = audible && sound && sound.play(top.level, settings.sound.volume);
    if (audible && sound && sound.state() === 'locked' && !bridge) text += '\n' + words[language].alert_sound_hint;
    showToast(text, top.level); flash(top.level);
    alertLog.unshift(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' · ' + alertText(top)); alertLog.length = Math.min(alertLog.length, 6);
    if (top.level === 'critical') native('vibrate', 200);
    return heard;
  }

  /* Night: its own schedule, a gentle fade at the edges, a dimmed picture (or, in the app, the real backlight), the clock alone if asked, and a slow
     shift of everything against image retention. A touch wakes it for a minute, like the small screen does. */
  let nightNow = 0, nightWakeUntil = 0, lastBrightness = null;
  function tickNight() {
    const night = settings.night;
    let amount = window.TabletSchedule ? TabletSchedule.nightAmount(new Date(), night) : 0;
    if (Date.now() < nightWakeUntil) amount = 0;
    nightNow = amount;
    const dim = 1 - night.level / 100, body = document.body;
    $('#night-shade').style.opacity = bridge ? '0' : String(Math.round(amount * dim * 1000) / 1000);
    const brightness = amount > 0 ? Math.max(.02, 1 - amount * dim) : -1;
    if (bridge && brightness !== lastBrightness) { native('setBrightness', brightness); lastBrightness = brightness; }
    const clockOnly = amount > .5 && night.clock_only;
    body.classList.toggle('night', amount > 0); body.classList.toggle('night-clock', clockOnly);
    if (stage) { if (typeof stage.setQuality === 'function') stage.setQuality(clockOnly ? 'low' : 'auto'); if (typeof stage.setLive === 'function') stage.setLive(!(amount > .5)); }
    const shift = amount > .5 && window.TabletSchedule ? TabletSchedule.pixelShift(Date.now(), 5) : { x: 0, y: 0 };
    root.style.setProperty('--shift-x', shift.x + 'px'); root.style.setProperty('--shift-y', shift.y + 'px');
    updateArea();
  }

  /* The picture mode: one tap on the clock hides everything but the scene and the clock; another brings the numbers back. */
  let pictureMode = false;
  function pictureLabel() { intro.setAttribute('aria-label', words[language][pictureMode ? 'picture_off' : 'picture_on']); intro.setAttribute('aria-pressed', String(pictureMode)); }
  function setPicture(on) {
    pictureMode = on; resetPictureTouches(); document.body.classList.toggle('picture', on); pictureLabel();
    setStored('tablet-picture-mode', on ? '1' : '0');
    if (on) goPage('home'); fit();
  }

  // In picture mode horizontal swipes select scenes. The normal pager keeps its own gestures outside this mode.
  let pictureGesture = null, pictureSwipeAt = 0;
  const picturePage = $('#page-home'), pictureSurface = $('#display');
  const onPictureBrand = (event) => Boolean(event.target.closest?.('.brand'));

  // Two nearby taps open the same scene picker as the top-bar button. A tap
  // on the clock waits briefly so a double tap there does not exit picture mode.
  const pictureTouches = new Map();
  const pictureDoubleDelay = 650, pictureDoubleDistance = 48;
  let pictureTouch = null, picturePendingTap = null, pictureTapTimer = null, pictureIgnoreClickUntil = 0;
  function clearPictureTap() {
    if (pictureTapTimer !== null) clearTimeout(pictureTapTimer);
    pictureTapTimer = null; picturePendingTap = null;
  }
  function resetPictureTouches() { pictureTouches.clear(); pictureTouch = null; clearPictureTap(); }
  pictureSurface.addEventListener('pointerdown', (event) => {
    if (!pictureMode || sceneDialog.open || event.pointerType !== 'touch' || onPictureBrand(event)) return;
    const now = performance.now();
    if (!pictureTouches.size) pictureTouch = {maximum: 0, invalid: false};
    pictureTouches.set(event.pointerId, {x: event.clientX, y: event.clientY});
    pictureTouch.maximum = Math.max(pictureTouch.maximum, pictureTouches.size);
    if (pictureTouch.maximum > 1) { pictureGesture = null; pictureTouch.invalid = true; pictureIgnoreClickUntil = now + 900; clearPictureTap(); }
  }, true);
  pictureSurface.addEventListener('pointermove', (event) => {
    const start = pictureTouches.get(event.pointerId);
    if (start && pictureTouch && Math.hypot(event.clientX - start.x, event.clientY - start.y) > 28) { pictureTouch.invalid = true; clearPictureTap(); }
  }, true);
  function finishPictureTouch(event, cancelled) {
    const start = pictureTouches.get(event.pointerId);
    if (!start || !pictureTouch) return;
    const now = performance.now();
    if (cancelled || Math.hypot(event.clientX - start.x, event.clientY - start.y) > 28) pictureTouch.invalid = true;
    pictureTouches.delete(event.pointerId);
    if (pictureTouch.invalid) { pictureIgnoreClickUntil = now + (pictureTouch.maximum > 1 ? 900 : 500); clearPictureTap(); }
    if (pictureTouches.size) return;
    pictureTouch = null;
  }
  pictureSurface.addEventListener('pointerup', (event) => finishPictureTouch(event, false), true);
  pictureSurface.addEventListener('pointercancel', (event) => finishPictureTouch(event, true), true);
  picturePage.addEventListener('pointerdown', (event) => {
    if (!pictureMode || !event.isPrimary || event.button !== 0) return;
    pictureGesture = { id: event.pointerId, x: event.clientX, y: event.clientY };
  });
  picturePage.addEventListener('pointercancel', () => { pictureGesture = null; });
  picturePage.addEventListener('pointerup', (event) => {
    if (!pictureMode || !pictureGesture || event.pointerId !== pictureGesture.id) return;
    const dx = event.clientX - pictureGesture.x, dy = event.clientY - pictureGesture.y;
    pictureGesture = null;
    if (Math.abs(dx) < Math.max(48, picturePage.clientWidth * .08) || Math.abs(dx) <= Math.abs(dy) * 1.25) return;
    const choices = photos.length ? [...availableScenes, 'photos'] : availableScenes;
    if (choices.length < 2) return;
    clearPictureTap();
    const current = photoMode ? 'photos' : selectedScene, index = choices.indexOf(current);
    chooseScene(choices[(Math.max(0, index) + (dx < 0 ? 1 : -1) + choices.length) % choices.length]);
    pictureSwipeAt = performance.now();
  });
  pictureSurface.addEventListener('click', (event) => {
    if (onPictureBrand(event)) return;
    const now = performance.now();
    if (now < pictureIgnoreClickUntil || (pictureSwipeAt && now - pictureSwipeAt < 500)) { event.preventDefault(); event.stopPropagation(); return; }
    if (!pictureMode || sceneDialog.open || event.detail === 0) return;
    if (picturePendingTap && now - picturePendingTap.at <= pictureDoubleDelay &&
        Math.hypot(event.clientX - picturePendingTap.x, event.clientY - picturePendingTap.y) <= pictureDoubleDistance) {
      clearPictureTap(); event.preventDefault(); event.stopPropagation(); showScenes(); return;
    }
    if (pictureTapTimer !== null) { clearPictureTap(); event.preventDefault(); event.stopPropagation(); setPicture(false); return; }
    picturePendingTap = {at: now, x: event.clientX, y: event.clientY};
    if (intro.contains(event.target)) {
      event.preventDefault(); event.stopPropagation();
      pictureTapTimer = setTimeout(() => { clearPictureTap(); if (pictureMode && !sceneDialog.open) setPicture(false); }, pictureDoubleDelay);
    }
  }, true);

  /* The pages: Home, Computer, Small screen. A swipe or a dot moves between them; the picture behind stays where it is. */
  const PAGES = ['home', 'computer', 'remote'];
  let currentPage = 'home', remoteTimer = 0;
  function goPage(name, smooth = true) {
    const index = PAGES.indexOf(name); if (index < 0) return;
    pager.scrollTo({ left: index * pager.clientWidth, behavior: smooth ? 'smooth' : 'auto' });
  }
  function alignPage() { const index = PAGES.indexOf(currentPage); if (index > 0 && Math.abs(pager.scrollLeft - index * pager.clientWidth) > 2) pager.scrollTo({ left: index * pager.clientWidth, behavior: 'auto' }); }
  function pageChanged(name) {
    currentPage = name;
    $('#dots').querySelectorAll('button').forEach((b) => { if (b.dataset.page === name) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current'); });
    clearInterval(remoteTimer);
    if (name === 'remote' && window.TabletPanels) { TabletPanels.loadRemote(); remoteTimer = setInterval(() => { if (!document.hidden) TabletPanels.loadRemote(); }, 15000); }
    if (name === 'computer' && window.TabletPanels) TabletPanels.renderComputer();
  }

  /* Picture mode keeps the same remaining quotas as the cards. Unknown stays a dash, never zero. */
  function pictureQuota() {
    const lines = [['codex', 'weekly'], ['claude', 'weekly'], ['session', 'session']];
    for (const [name, which] of lines) {
      const box = $('[data-pq="' + name + '"]'); if (!box) continue;
      const data = latest?.providers?.[name === 'session' ? 'claude' : name] || {}, part = data[which];
      const live = part && timeLeft(part.resets_at) !== '—' ? part : null;
      const raw = live && valid(live.remaining) && live.remaining >= 0 && live.remaining <= 100 ? live.remaining : null;
      const credit = name === 'session' ? null : creditBalance(data, raw), value = credit;
      box.dataset.level = raw === null ? 'unknown' : quotaLevel(raw);
      box.dataset.mode = credit === null ? 'quota' : 'credits';
      box.dataset.creditSize = credit === null ? 'normal' : creditSize(value);
      $('strong', box).textContent = credit !== null ? value : raw === null ? '—' : name === 'session' ? showPercent(raw) : raw > 0 && raw < 1 ? '<1%' : Math.floor(raw) + '%';
      const label = $('.pq-credit-label', box); if (label) label.textContent = credit === null ? '' : words[language].credits;
      $('em', box).style.width = (raw === null ? 0 : percent(raw)) + '%';
      $('small', box).textContent = raw === null ? (name === 'session' ? '' : '—') : timeLeft(live.resets_at);
    }
  }
  function render() {
    const chip = $('#connection'); chip.dataset.state = connection === 'online' ? 'ok' : 'error';
    $('.chip-text', chip).textContent = words[language][connection];
    provider('codex',latest?.providers?.codex); provider('claude',latest?.providers?.claude); pictureQuota();
    hardware(latest?.metrics);
    if (window.TabletPanels) TabletPanels.renderComputer();
    fit();
  }
  let pageBuild = null, updateReady = false, refreshAfter = 0, refreshFailures = 0;
  async function refresh() {
    if (inflight || Date.now() < refreshAfter) return; inflight = true;
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(),4000);
    try {
      const response = await fetch('/api/status',{cache:'no-store',signal:controller.signal});
      if (response.status === 401) { latest = null; if (stage && stage.setReadings) stage.setReadings(null); window.location.replace('/login'); return; }
      if (!response.ok) throw new Error('unavailable');
      latest = await response.json(); connection = latest.quota_connected ? 'online' : 'partial';
      refreshFailures = 0; refreshAfter = 0;
      if (Object.keys(pendingPatch).length) sendSettings();
      if (stage && stage.setReadings) stage.setReadings(latest);
      renderAppUpdate();
      if (typeof latest.build === 'string') {
        if (pageBuild === null) pageBuild = latest.build;
        else if (latest.build !== pageBuild && !updateReady) {
          if (localApp) { pageBuild = latest.build; native('syncOffline'); }
          else { updateReady = true; updateChip.hidden = false; fit(); if (bridge) setTimeout(() => native('reload'), 6000); }
        }
      }
      if (alerts && latest.quota_connected) raise(alerts.feed(latest, settings.alerts, Date.now()));
    } catch (_) {
      latest = null; connection = 'offline'; refreshFailures++; refreshAfter = Date.now() + Math.min(30000, 5000 * 2 ** Math.min(3, refreshFailures - 1));
      if (stage && stage.setReadings) stage.setReadings(null);
    }      // a scene must not keep showing a reading that stopped arriving
    finally { clearTimeout(timeout); inflight = false; render(); }
  }

  /* Three quick taps on the logo: what this browser can do, to check the real tablet (nothing is sent anywhere). */
  const diag = $('#diag');
  function diagnostics() {
    const gl = (() => { try { return document.createElement('canvas').getContext('webgl'); } catch (_) { return null; } })();
    const info = gl && gl.getExtension('WEBGL_debug_renderer_info');
    const ua = (navigator.userAgent.match(/Android [\d.]+|Chrome\/[\d.]+|Firefox\/[\d.]+/g) || []).join(' · ');
    const media = document.createElement('video');
    const lines = [
      'viewport ' + innerWidth + 'x' + innerHeight + ' @' + devicePixelRatio + 'x · screen ' + screen.width + 'x' + screen.height,
      'secure ' + window.isSecureContext + ' · fullscreen ' + Boolean(document.fullscreenElement) + ' · wake lock ' + ('wakeLock' in navigator ? awakeState : 'not offered') + ' · app ' + (bridge ? native('version') : 'no'),
      'webgl ' + (gl ? (info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : 'yes') : 'no') + ' · vp8 ' + (media.canPlayType('video/webm; codecs="vp8"') || 'no'),
      'reduced motion ' + reducedMotion.matches + ' · scene ' + selectedScene + (sceneInfo[selectedScene] ? ' (' + sceneInfo[selectedScene].look + ')' : ' (plain)') + ' · night ' + nightNow.toFixed(2) + ' ' + JSON.stringify(settings.night) + ' ' + String(new Date()).slice(16, 24),
      'fit ' + fitScale.toFixed(3) + ' (needed ' + fitFirst + ' px more at 1) · overflow ' + overflowOf().join('x') + ' · u ' + ((ruler.getBoundingClientRect().height / 100) || 0).toFixed(3) + ' px · app-h ' + root.style.getPropertyValue('--app-h'),
      'stage ' + (stage && stage.status ? JSON.stringify(stage.status()) : 'none'),
      'build ' + (pageBuild || '?') + ' · settings ' + (settingsLoaded ? 'loaded' : 'defaults'),
      ua
    ];
    diag.textContent = lines.join('\n');
  }
  let taps = [];
  $('.brand').addEventListener('click', () => {
    const now = Date.now(); taps = taps.filter(t => now - t < 900); taps.push(now);
    if (taps.length < 3) return;
    taps = []; diagnostics(); diag.hidden = !diag.hidden;
    clearTimeout(diag.timer); if (!diag.hidden) diag.timer = setTimeout(() => { diag.hidden = true; }, 30000);
  });
  diag.addEventListener('click', () => { diag.hidden = true; });
  fullButton.hidden = Boolean(bridge) || !document.fullscreenEnabled || typeof document.documentElement.requestFullscreen !== 'function';    // the app is already full screen
  fullButton.addEventListener('click',async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen(); else await document.documentElement.requestFullscreen();
      fullStatus.hidden = true;
    } catch (_) { fullStatus.textContent = words[language].full_screen_failed; fullStatus.hidden = false; }
  });
  document.addEventListener('fullscreenchange',() => { updateFull(); if (document.fullscreenElement) keepAwake(); else letSleep(); fit(); report('fullscreen', 1500); });
  sceneOpen.addEventListener('click',showScenes);
  sceneClose.addEventListener('click',() => sceneDialog.close());
  settingsOpen.addEventListener('click', () => { if (window.TabletPanels) TabletPanels.renderSettings(); settingsDialog.showModal(); });
  settingsClose.addEventListener('click', () => settingsDialog.close());
  $('#pool-close').addEventListener('click', () => $('#pool-dialog').close());
  updateChip.addEventListener('click', () => { if (bridge) native('reload'); else window.location.reload(); });
  appUpdateChip.addEventListener('click', startAppUpdate);
  $('#dots').addEventListener('click', (event) => { const button = event.target.closest('button[data-page]'); if (button) goPage(button.dataset.page); });
  pager.addEventListener('scroll', () => { const index = Math.round(pager.scrollLeft / Math.max(1, pager.clientWidth)); if (PAGES[index] && PAGES[index] !== currentPage) pageChanged(PAGES[index]); }, { passive: true });
  machine.addEventListener('click', () => goPage('computer'));
  machine.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); goPage('computer'); } });
  intro.addEventListener('click', () => setPicture(!pictureMode));
  intro.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setPicture(!pictureMode); } });
  // a touch on the picture reaches the scene (ripples, sparks), and a first touch anywhere lets the browser play sounds
  slot.addEventListener('pointerdown', (event) => { if (stage && typeof stage.poke === 'function') stage.poke(event.clientX, event.clientY); });
  document.addEventListener('pointerdown', () => { if (sound && sound.state() === 'locked') sound.unlock(); if (nightNow > 0) { nightWakeUntil = Date.now() + 60000; tickNight(); } }, { capture: true });
  document.addEventListener('visibilitychange',() => {
    if (document.hidden) { resetPictureTouches(); if (stage) stage.pause(); return; }
    if (stage) stage.resume();
    updateTime(); refreshAfter = 0; refresh(); loadWeather(); keepAwake(); tickNight();
  });
  if (reducedMotion.addEventListener) reducedMotion.addEventListener('change', applyMotion);
  window.addEventListener('resize', () => { fit(); report('resize', 2500); });
  window.addEventListener('orientationchange', () => { fit(); report('resize', 2500); });
  if (window.visualViewport) window.visualViewport.addEventListener('resize', () => { fit(); report('resize', 2500); });
  if (window.ResizeObserver) { const watcher = new ResizeObserver(updateArea); watcher.observe(slot); watcher.observe(dock); }

  if (window.TabletPanels) {
    TabletPanels.init({
      words: wordsNow, language: () => language, setLanguage, settings: () => settings, setSetting, latest: () => latest, size, diskItem,
      appInfo: () => ({ installed: Boolean(bridge), version: bridge ? String(native('version') || '') : '', apk: Boolean(latest && latest.app), update: appUpdate(), offline: offlineInfo() }),
      startAppUpdate, choosePool, poolSummary,
      saveOffline: () => native('syncOffline'),
      action: (name, button) => { if (name === 'sound_test' && sound) { sound.unlock(); const ok = sound.play('warning', settings.sound.volume); button.textContent = words[language].sound_test + (ok ? ' ✓' : ' …'); } },
      aboutText: () => 'build ' + (pageBuild || '?') + ' · ' + innerWidth + '×' + innerHeight + ' · fit ' + fitScale.toFixed(2) + (alertLog.length ? '\n' + alertLog.join('\n') : ''),
    });
  }
  createStage();
  settingsChanged('*');
  fit();
  if (bridge) keepAwake();
  setLanguage(getStored('tablet-preview-language')); loadSettings(); loadScenes(); loadPhotos(); refresh(); loadWeather();
  if (getStored('tablet-picture-mode') === '1') setPicture(true);
  let offlineRevision = offlineInfo()?.revision || '';
  let offlinePhase = '';
  function checkOffline() {
    const value = offlineInfo();
    if (value && value.state !== offlinePhase) { offlinePhase = value.state; report('tick', 750); }
    if (value && value.ready && value.revision && value.revision !== offlineRevision) {
      offlineRevision = value.revision;
      const previous = selectedScene;
      // A game atlas can have new bytes at the same URL. Once the complete
      // pack is installed, reload the still-selected game without changing its
      // settings or the picture mode; never switch during a partial transfer.
      loadScenes().then(() => {
        const info = displayInfo(previous);
        if (!photoMode && selectedScene === previous && info && info.look === 'game') setScene(previous, false);
      });
      loadPhotos();
    }
    if (window.TabletPanels && TabletPanels.updateOffline) TabletPanels.updateOffline();
  }
  window.aiDeskOfflineChanged = checkOffline;
  if (localApp) setInterval(checkOffline, 2000);
  window.addEventListener('online', () => { refreshAfter = 0; refresh(); if (localApp) native('syncOffline'); });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(fit);
  setInterval(() => { updateTime(); render(); tickNight(); renderWeather(); },10000);
  setInterval(() => { if (settings.scene === 'auto' || ['infinite-express', 'midnight-video-club', 'neon-district'].includes(selectedScene)) resolveScene(); }, 30000);
  setInterval(refresh,5000);
  setInterval(loadWeather,300000);
  report('load', 6000);
  setInterval(() => { if (!document.hidden) report('tick'); }, 180000);
})();
