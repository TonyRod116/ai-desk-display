'use strict';
/* UI language is local to this browser; usage and display settings are untouched. */
(() => {
  const es = {
    'YOUR SCREEN':'TU PANTALLA', 'YOUR COLLECTION':'TU COLECCIÓN', 'Screen':'Pantalla',
    'Screen library':'Galería de pantallas', 'Change screen':'Cambiar pantalla',
    'Choose a screen':'Elige una pantalla', 'Close screen library':'Cerrar galería de pantallas',
    'See any screen here, with your local usage. Your device stays as it is.':'Mira aquí cualquier pantalla con tus datos de uso locales. Tu dispositivo no cambiará.',
    'Selected screen with current usage':'Pantalla elegida con el uso actual',
    'Live local readings · This page only':'Datos locales actualizados · Solo esta página',
    'On your display':'En tu dispositivo', 'More screens':'Más pantallas',
    'Loading screens…':'Cargando pantallas…', 'Loading preview…':'Cargando vista previa…',
    'Preview unavailable.':'Vista previa no disponible.', 'Screen unavailable. Choose another screen.':'Pantalla no disponible. Elige otra pantalla.',
    'Local connection lost. Waiting for current readings.':'Conexión local perdida. Esperando datos actuales.',
    'Previews paused. Reload them for current readings.':'Vistas previas pausadas. Vuelve a cargarlas para ver los datos actuales.',
    'Waiting for an updated preview…':'Esperando una vista previa actualizada…',
    'Could not load the screen library.':'No se ha podido cargar la galería de pantallas.',
    'Try again':'Volver a intentar',
    'Display controls · AI Desk Display':'Controles de pantalla · AI Desk Display',
    'AI Desk Display · Usage dashboard':'AI Desk Display · Panel de uso',
    'AI Desk Display · Live demo':'AI Desk Display · Demostración',
    'Live demo with sample data':'Demostración con datos de ejemplo', 'AI Desk Display on GitHub':'AI Desk Display en GitHub',
    'Language':'Idioma', 'Skip to screens':'Ir a las pantallas', 'Skip to usage':'Ir al uso',
    'AI Desk Display home':'Inicio de AI Desk Display', 'Usage dashboard':'Panel de uso',
    'Desk display':'Pantalla', 'Display controls':'Controles de pantalla',
    'YOUR DESK DISPLAY':'TU PANTALLA', 'Choose a screen and set how it plays.':'Elige una pantalla y configura su reproducción.',
    'Touch settings':'Controles táctiles', 'Current screen and playback settings':'Pantalla actual y ajustes de reproducción',
    'NOW SHOWING':'EN PANTALLA', 'Your display':'Tu pantalla',
    'Preview of the selected display screen':'Vista previa de la pantalla seleccionada',
    'Waiting for a preview':'Esperando la vista previa', 'Local preview':'Vista previa local',
    'Animated screens move here too':'Las pantallas animadas también se mueven aquí', 'SETTINGS':'AJUSTES',
    'Playback':'Reproducción', 'Saved on your display.':'Guardado en la pantalla.',
    'Auto-rotate':'Rotación automática', 'Change screens on the hour or half-hour.':'Cambia de pantalla a la hora en punto o a y media.',
    'Automatic screen rotation':'Rotación automática de pantallas', 'Never':'Nunca', '1 hour':'1 hora',
    'Animation speed':'Velocidad de animación', 'For the selected screen.':'Para la pantalla seleccionada.',
    'Slower':'Más lento', 'Normal':'Normal', 'Faster':'Más rápido',
    'Changes motion speed, not frame rate.':'Cambia la velocidad del movimiento, no los fotogramas por segundo.',
    'Connecting to your display…':'Conectando con tu pantalla…', 'Screens':'Pantallas',
    'Tap a screen to show it. Change a slot to bring back an earlier version.':'Toca una pantalla para mostrarla. Cambia una posición para recuperar otra versión.',
    '8 SLOTS':'8 POSICIONES', 'Display screens':'Pantallas disponibles', 'SCREEN LIBRARY':'GALERÍA DE PANTALLAS',
    'Change screen':'Cambiar pantalla', 'Close':'Cerrar',
    'Choose what to put in this slot. You can bring the current screen back later.':'Elige qué poner en esta posición. Puedes recuperar la pantalla actual cuando quieras.',
    'Screens move in the preview and use your latest available local readings.':'Las pantallas se mueven en la vista previa y utilizan los últimos datos locales disponibles.',
    'Loading preview…':'Cargando vista previa…', 'Preview unavailable':'Vista previa no disponible',
    'Choose a screen':'Elige una pantalla',
    'YOUR SCREENS':'TUS PANTALLAS', 'Reorder screens':'Ordenar pantallas',
    'Drag a screen into place, or tap it and then its new position.':'Arrastra una pantalla hasta su sitio o tócala y después toca la nueva posición.',
    'Keyboard: use the arrow keys to move a focused screen.':'Teclado: usa las flechas para mover la pantalla seleccionada.',
    'Screen order':'Orden de las pantallas', 'Animation speed stays with the position.':'La velocidad de animación se conserva en cada posición.',
    'Save order':'Guardar orden', 'Saving order…':'Guardando el orden…',
    'Order saved · waiting for the display to receive the screens.':'Orden guardado · esperando a que las pantallas lleguen al dispositivo.',
    'Order saved.':'Orden guardado.',
    'The screens changed elsewhere. Close and reopen to try again.':'Las pantallas han cambiado en otro lugar. Cierra y vuelve a abrir para intentarlo de nuevo.',
    'Animation speed belongs to the slot and stays the same when you change its screen.':'La velocidad pertenece a la posición y se conserva al cambiar de pantalla.',
    'Cancel':'Cancelar', 'Replace screen':'Cambiar pantalla', 'Selected:':'Seleccionada:', 'ON THE DISPLAY':'EN LA PANTALLA',
    'Touch controls':'Controles táctiles', 'A short tap changes the screen. Hold and release for the shortcuts below.':'Un toque cambia la pantalla. Mantén pulsado y suelta para usar los siguientes accesos.',
    'Change auto-rotate mode':'Cambiar la rotación automática', 'Open connection screen':'Abrir la pantalla de conexión',
    'Connection always requires a physical hold of at least 5 seconds.':'La conexión siempre requiere mantener pulsada la pantalla al menos 5 segundos.',
    'Save touch settings':'Guardar controles táctiles', 'Running locally on this computer':'Funciona localmente en este ordenador',
    'CURRENT':'ACTUAL', 'EARLIER VERSION':'VERSIÓN ANTERIOR', 'SCREEN':'PANTALLA',
    'CHECKING':'COMPROBANDO', 'QUEUED':'EN COLA', 'ON DISPLAY':'EN PANTALLA',
    'Saving your choice…':'Guardando tu elección…', 'Screen saved · waiting for the display to receive it.':'Pantalla guardada · esperando a que llegue al dispositivo.',
    'Screen already in this slot.':'Esta pantalla ya está en esa posición.', 'Could not save. Please try again.':'No se ha podido guardar. Vuelve a intentarlo.',
    'Connected':'Conectado', 'Connecting':'Conectando', 'Sending data':'Enviando datos', 'Not connected':'Sin conexión', 'Not configured':'Sin configurar',
    'Waiting for screen':'Esperando la pantalla', 'Connection screen':'Pantalla de conexión',
    'Waiting for the screen to reach the display':'Esperando a que la pantalla llegue al dispositivo',
    'Applies to all screens on this display version.':'Se aplica a todas las pantallas de esta versión.',
    'Screen settings could not be read. Existing screens have been kept.':'No se han podido leer los ajustes. Se han conservado las pantallas existentes.',
    'Connect a display to get started.':'Conecta una pantalla para empezar.', 'Waiting for your display to reconnect.':'Esperando a que la pantalla vuelva a conectarse.',
    'Some screens are waiting to reach the display.':'Algunas pantallas están esperando a llegar al dispositivo.',
    'Screen selection is available. Update the display to enable rotation and speed controls.':'Puedes elegir pantallas. Actualiza el dispositivo para activar la rotación y la velocidad.',
    'Waiting for the computer to sync the clock.':'Esperando a que el ordenador sincronice la hora.',
    'Saved on your display · works when this page is closed.':'Guardado en la pantalla · funciona aunque cierres esta página.',
    'Update the display to enable touch settings.':'Actualiza el dispositivo para activar los controles táctiles.',
    'Save to apply your changes.':'Guarda para aplicar los cambios.',
    'Sending to your display… This may wait for a current transfer.':'Enviando a la pantalla… Puede esperar a que termine una transferencia.',
    'Sending to your display…':'Enviando a la pantalla…', 'Could not confirm the change. Please try again.':'No se ha podido confirmar el cambio. Vuelve a intentarlo.',
    'Could not confirm the change. Check the connection and try again.':'No se ha podido confirmar el cambio. Comprueba la conexión y vuelve a intentarlo.',
    'AI USAGE DASHBOARD':'PANEL DE USO DE IA', 'USAGE DASHBOARD':'PANEL DE USO', 'LOCAL DASHBOARD':'PANEL LOCAL',
    'POCKET · LOCAL DASHBOARD':'POCKET · PANEL LOCAL', 'Hearts: saved resets · Bar: remaining quota':'Corazones: resets guardados · Barra: cuota restante',
    'AI PROVIDERS':'PROVEEDORES DE IA', 'REMAINING QUOTA':'CUOTA RESTANTE', 'QUOTA / TERMINAL':'CUOTA / TERMINAL',
    'Remaining quota and saved resets':'Cuota restante y resets guardados',
    'Saved resets':'Resets guardados', 'Accounts':'Cuentas', 'Reporting':'Con datos', 'Providers':'Proveedores', 'Today':'Hoy', 'Local':'Local',
    'Provider usage':'Uso de los proveedores', 'Loading your accounts…':'Cargando tus cuentas…',
    '— reporting':'— con datos', 'Waiting for data':'Esperando datos',
    'Automatic updates · local background service':'Actualización automática · servicio local en segundo plano',
    'Used quota levels':'Niveles de cuota utilizada', 'Used quota':'Cuota utilizada', 'Remaining quota levels':'Niveles de cuota restante', 'Remaining quota':'Cuota restante',
    'USAGE SETTINGS':'AJUSTES DE USO', 'Close saved resets panel':'Cerrar el panel de resets guardados',
    'Each heart is an available saved reset. The bar shows quota.':'Cada corazón es un reset guardado disponible. La barra muestra la cuota.',
    'Save confirmed balance':'Guardar saldo confirmado', 'Confirm manual balances in the official Usage settings.':'Confirma los saldos manuales en los ajustes oficiales de uso.',
    'Dashboard appearance':'Aspecto del panel', 'Changes this page only':'Solo cambia esta página', 'Dashboard theme':'Tema del panel',
    'To change the screens on your device, open':'Para cambiar las pantallas de tu dispositivo, abre',
    'How to read the dashboard':'Cómo leer el panel', 'Each appearance shows':'Cada aspecto muestra', 'weekly quota remaining':'la cuota semanal restante',
    "and the time until the weekly reset. Expand a card to see other limits, such as the current session. When Codex's weekly allowance is exhausted, its card shows extra credits if the official reading provides them; the empty bar still represents weekly quota. Official readings disappear when a refresh fails, they become more than three minutes old, or their reset time passes. Unknown readings appear as — or ?.":'y el tiempo hasta el reinicio semanal. Despliega una tarjeta para ver otros límites, como la sesión actual. Cuando se agota la cuota semanal de Codex, su tarjeta muestra los créditos extra si la lectura oficial los proporciona; la barra vacía sigue representando la cuota semanal. Las lecturas oficiales desaparecen si falla una actualización, tienen más de tres minutos o pasa su hora de reinicio. Los datos desconocidos aparecen como — o ?.',
    'Hearts count saved resets, which are separate from extra credits and are never calculated from the quota bar. When automatic checks are enabled, balances come from the official account readers. Otherwise, confirm them manually in the official Usage settings. An unknown balance appears as ?.':'Los corazones cuentan los resets guardados, que son distintos de los créditos extra y nunca se calculan a partir de la barra. Si las consultas automáticas están activadas, los saldos vienen de los lectores oficiales de las cuentas. De lo contrario, confírmalos manualmente en los ajustes oficiales de uso. Un saldo desconocido aparece como ?.',
    'Awaiting reset':'Esperando el reinicio', 'QUOTA':'CUOTA', 'CLI BUDGET':'PRESUPUESTO CLI', 'WEEKLY':'SEMANAL', '5-HOUR':'5 HORAS',
    'QUOTA LEFT':'CUOTA RESTANTE', 'QUOTA USED':'CUOTA USADA', 'WEEKLY LEFT':'RESTANTE SEMANAL', 'WEEKLY USED':'USO SEMANAL',
    '5-HOUR LEFT':'RESTANTE 5 HORAS', '5-HOUR USED':'USO 5 HORAS', 'CLI BUDGET LEFT':'PRESUPUESTO CLI RESTANTE', 'CLI BUDGET USED':'PRESUPUESTO CLI USADO',
    'EXTRA CREDITS':'CRÉDITOS EXTRA', 'Balance unavailable':'Saldo no disponible', 'Weekly limit reached':'Límite semanal alcanzado',
    'Limit reached':'Límite alcanzado', 'Near limit':'Cerca del límite', 'High usage':'Uso alto', 'Moderate':'Moderado', 'Low usage':'Uso bajo',
    'OLD · Last known usage':'ANTERIOR · Último uso conocido', 'No recent weekly reading. Retrying automatically.':'Sin lectura semanal reciente. Reintentando automáticamente.',
    'No current local Claude reading. This page does not refresh the Claude Code reader.':'Sin lectura local actual de Claude. Esta página no actualiza el lector de Claude Code.',
    'No quota reported.':'No hay cuota disponible.', 'No reading available.':'Sin lectura disponible.', 'RESETS IN':'REINICIO EN',
    'Saved-reset balance unknown':'Saldo de resets guardados desconocido', 'Account':'Cuenta', 'Window':'Periodo', 'Source':'Origen',
    'Official client · local cache':'Cliente oficial · caché local', 'Local files':'Archivos locales', 'This computer':'Este ordenador',
    'Linked snapshot':'Lectura vinculada', 'Last good':'Última válida', 'Checked':'Consultado', 'Status':'Estado',
    'OFFLINE · Previous value':'SIN CONEXIÓN · Valor anterior', 'Unknown':'Desconocido', 'Loading':'Cargando',
    'Login needed':'Necesita iniciar sesión', 'Check identity':'Comprueba la identidad', 'Quota unavailable':'Cuota no disponible',
    'Blocked by Codex':'Bloqueado por Codex', 'OLD · Previous value':'ANTERIOR · Valor previo', 'Retry later':'Reintentar más tarde', 'Fetch failed':'Error al consultar',
    'Demo · sample data':'Demostración · datos de ejemplo', 'Live':'En directo', 'Server offline':'Servidor desconectado',
    'Waiting for first reading':'Esperando la primera lectura', 'Local connection lost. Official quotas remain unknown until readings recover.':'Se ha perdido la conexión local. Las cuotas oficiales permanecerán desconocidas hasta recuperar las lecturas.',
    'Cannot reach the local monitor. Is it running?':'No se puede conectar con el monitor local. ¿Está en marcha?', 'No usage data received.':'No se han recibido datos de uso.',
    'Official check pending or unavailable.':'Comprobación oficial pendiente o no disponible.', 'Balance awaiting confirmation.':'Saldo pendiente de confirmación.',
    'Balance saved locally. No reset was used.':'Saldo guardado localmente. No se ha usado ningún reset.',
    'Could not save. Check the values and try again.':'No se ha podido guardar. Comprueba los valores y vuelve a intentarlo.',
    '5-hour window':'Periodo de 5 horas', 'Weekly window':'Periodo semanal', 'CLI budget window':'Periodo del presupuesto CLI'
  };
  const rules = [
    [/^(.+), position (\d+) of 8$/, (_, name, n) => `${name}, posición ${n} de 8`],
    [/^Selected (.+)\. Choose its new position\.$/, (_, name) => `${name} seleccionada. Elige su nueva posición.`],
    [/^Moved (.+) to position (\d+) of 8\.$/, (_, name, n) => `${name} se ha movido a la posición ${n} de 8.`],
    [/^Change screen (\d+): (.+)$/, (_, n, name) => `Cambiar pantalla ${n}: ${name}`],
    [/^Change screen (\d+)$/, (_, n) => `Cambiar pantalla ${n}`],
    [/^(\d+) seconds?$/, (_, n) => `${n} ${n === '1' ? 'segundo' : 'segundos'}`],
    [/^(\d+) saved resets( · confirmed by you)?$/, (_, n, confirmed) => `${n} resets guardados${confirmed ? ' · confirmados por ti' : ''}`],
    [/^Saved-reset balance unknown · confirmed by you$/, () => 'Saldo de resets guardados desconocido · confirmado por ti'],
    [/^(.+) accounts$/, (_, name) => `Cuentas de ${name}`],
    [/^(.+) (WEEKLY|5-HOUR|CLI BUDGET|QUOTA) (remaining|used) quota( unavailable)?$/, (_, name, period, kind, unavailable) => `${name} · ${es[period] || period} · cuota ${kind === 'remaining' ? 'restante' : 'usada'}${unavailable ? ' no disponible' : ''}`],
    [/^(\d+) more windows$/, (_, n) => `${n} periodos más`],
    [/^(\d+) \/ (\d+) reporting$/, (_, n, total) => `${n} / ${total} con datos`],
    [/^(\d+) stale · Live server$/, (_, n) => `${n} anteriores · Servidor activo`],
    [/^(\d+) accounts? (?:has|have) an older reading\. Check the selected account’s source and last successful update\.$/, (_, n) => `${n} ${n === '1' ? 'cuenta tiene una lectura anterior' : 'cuentas tienen lecturas anteriores'}. Comprueba el origen y la última actualización correcta.`],
    [/^Server checked (.+)$/, (_, value) => `Servidor consultado ${value}`],
    [/^Official check: (.+)$/, (_, value) => `Comprobación oficial: ${value}`],
    [/^Confirmed by you: (.+)$/, (_, value) => `Confirmado por ti: ${value}`]
  ];
  let language = 'en';
  try { if (localStorage.getItem('ai-desk-display.language') === 'es') language = 'es'; } catch (_) {}
  const nodes = new WeakMap(), attributes = new WeakMap();
  const originalTitle = document.title;
  function translate(value) {
    if (language !== 'es') return value;
    if (Object.hasOwn(es, value)) return es[value];
    for (const [pattern, replace] of rules) { const match = value.match(pattern); if (match) return replace(...match); }
    return value;
  }
  function textNode(node) {
    if (!node.parentElement || node.parentElement.closest('script,style')) return;
    const current = node.nodeValue;
    let record = nodes.get(node);
    if (!record || current !== record.last) record = {source: current, last: current};
    const match = record.source.match(/^(\s*)(.*?)(\s*)$/s);
    const next = match ? match[1] + translate(match[2]) + match[3] : record.source;
    record.last = next; nodes.set(node, record);
    if (current !== next) node.nodeValue = next;
  }
  function attribute(element, name) {
    if (!element.hasAttribute(name)) return;
    let entry = attributes.get(element); if (!entry) { entry = {}; attributes.set(element, entry); }
    const current = element.getAttribute(name);
    let record = entry[name];
    if (!record || current !== record.last) record = {source: current, last: current};
    const next = translate(record.source); record.last = next; entry[name] = record;
    if (current !== next) element.setAttribute(name, next);
  }
  function visit(root) {
    if (root.nodeType === Node.TEXT_NODE) { textNode(root); return; }
    if (root.nodeType !== Node.ELEMENT_NODE || root.matches('script,style')) return;
    for (const name of ['aria-label', 'title', 'alt', 'placeholder']) attribute(root, name);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (node.nodeType === Node.TEXT_NODE) textNode(node);
      else for (const name of ['aria-label', 'title', 'alt', 'placeholder']) attribute(node, name);
    }
  }
  function apply() {
    document.documentElement.lang = language;
    document.title = translate(originalTitle);
    document.querySelectorAll('.language-switch').forEach(select => { select.value = language; });
    visit(document.body);
    window.dispatchEvent(new Event('desk-language-change'));
  }
  document.querySelectorAll('.language-switch').forEach(select => select.addEventListener('change', () => {
    language = select.value === 'es' ? 'es' : 'en';
    try { localStorage.setItem('ai-desk-display.language', language); } catch (_) {}
    apply();
  }));
  apply();
  new MutationObserver(records => {
    for (const record of records) {
      if (record.type === 'characterData') textNode(record.target);
      else if (record.type === 'attributes') attribute(record.target, record.attributeName);
      else for (const node of record.addedNodes) visit(node);
    }
  }).observe(document.body, {subtree:true, childList:true, characterData:true, attributes:true, attributeFilter:['aria-label','title','alt','placeholder']});
})();
