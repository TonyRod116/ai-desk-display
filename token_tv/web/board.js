'use strict';

const defaultNames = ['Game Boy', 'Paradise', 'Neon City', 'Tidal Rush', 'Token Run', 'Versus', 'Platform', 'City'];
const grid = document.getElementById('screen-grid');
const note = document.getElementById('setting-note');
const currentImage = document.getElementById('current-preview');
const touchNote = document.getElementById('touch-note');
const modeHold = document.getElementById('mode-hold');
const connectHold = document.getElementById('connect-hold');
let latest = null;
let sending = false;
let polling = false;
let previewVersion = 0;
let commandVersion = 0;
let previewRetry = null;
let touchDirty = false;
let sceneSlot = null;
let lastSceneState = '';
let libraryObserver = null;
const sceneDialog = document.getElementById('scene-dialog');
const sceneSelect = document.getElementById('scene-select');
const sceneLibrary = document.getElementById('scene-library');
const sceneNote = document.getElementById('scene-note');
const orderDialog = document.getElementById('order-dialog');
const orderGrid = document.getElementById('order-grid');
const orderNote = document.getElementById('order-note');
const orderSave = orderDialog.querySelector('.dialog-save');
const orderOpen = document.getElementById('reorder-open');
let orderOriginal = null;
let orderDraft = [];
let orderDrag = null;
let orderSelected = null;

function sceneName(id, fallback) {
  return latest?.scene_catalog?.find(scene => scene.id === id)?.name || fallback;
}

const previewExtension = matchMedia('(prefers-reduced-motion: reduce)').matches ? 'png' : 'webp';
function previewUrl(index) { return `/board/preview/${index}.${previewExtension}?v=${previewVersion}`; }

function retryPreviews() {
  if (previewRetry || !latest || !['connected', 'busy'].includes(latest.state)) return;
  previewRetry = setTimeout(() => { previewRetry = null; refreshPreviews(); }, 5000);
}

defaultNames.forEach((name, index) => {
  const slot = document.createElement('div');
  slot.className = 'screen-slot';
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'screen-card';
  button.dataset.page = String(index);
  button.setAttribute('aria-pressed', 'false');
  button.disabled = true;
  const thumb = document.createElement('span');
  thumb.className = 'thumb';
  const img = document.createElement('img');
  img.alt = '';
  img.loading = 'lazy';
  img.addEventListener('error', () => { img.hidden = true; retryPreviews(); });
  img.addEventListener('load', () => { img.hidden = false; });
  thumb.append(img);
  const details = document.createElement('span');
  details.className = 'card-details';
  const title = document.createElement('strong');
  title.textContent = name;
  const number = document.createElement('small');
  number.textContent = String(index + 1).padStart(2, '0');
  details.append(title, number);
  button.append(thumb, details);
  button.addEventListener('click', () => command('page', index));
  const change = document.createElement('button');
  change.type = 'button';
  change.className = 'screen-change';
  change.textContent = 'Change screen';
  change.disabled = true;
  change.addEventListener('click', () => openSceneDialog(index));
  slot.append(button, change);
  grid.append(slot);
});

function openSceneDialog(index) {
  if (!latest?.scene_catalog || latest.scene_settings_error) return;
  sceneSlot = index;
  document.getElementById('scene-dialog-title').textContent = `Change screen ${String(index + 1).padStart(2, '0')}`;
  sceneSelect.value = latest.scene_ids[index];
  document.getElementById('scene-selected-name').textContent = sceneName(sceneSelect.value, defaultNames[index]);
  sceneLibrary.replaceChildren();
  if (libraryObserver) libraryObserver.disconnect();
  libraryObserver = 'IntersectionObserver' in window ? new IntersectionObserver((entries, observer) => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      const image = entry.target.querySelector('img');
      image.src = image.dataset.src;
      observer.unobserve(entry.target);
    });
  }, {root: sceneDialog, rootMargin: '160px'}) : null;
  latest.scene_catalog.forEach(scene => {
    const slot = latest.scene_ids.indexOf(scene.id);
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'library-card'; button.dataset.scene = scene.id;
    button.setAttribute('aria-pressed', String(scene.id === sceneSelect.value));
    const picture = document.createElement('span'); picture.className = 'library-picture';
    const img = document.createElement('img'); img.alt = ''; img.width = 320; img.height = 240;
    const placeholder = document.createElement('span'); placeholder.className = 'library-placeholder';
    placeholder.textContent = 'Loading preview…';
    const libraryUrl = `/board/library/${encodeURIComponent(scene.id)}.${previewExtension}?v=${previewVersion}`;
    const confirmed = slot >= 0 && !latest.scene_pending?.[slot] && latest.scene_delivered_ids?.[slot] === scene.id;
    let usingLibrary = !confirmed;
    img.addEventListener('load', () => { img.hidden = false; placeholder.hidden = true; });
    img.addEventListener('error', () => {
      if (!usingLibrary) { usingLibrary = true; img.src = libraryUrl; }
      else { img.hidden = true; placeholder.textContent = 'Preview unavailable'; }
    });
    img.hidden = true;
    img.dataset.src = confirmed ? previewUrl(slot) : libraryUrl;
    picture.append(placeholder, img);
    if (libraryObserver) libraryObserver.observe(picture);
    else img.src = img.dataset.src;
    const details = document.createElement('span'); details.className = 'library-details';
    const name = document.createElement('strong'); name.textContent = scene.name;
    const tag = document.createElement('small'); tag.textContent = scene.id === latest.scene_ids[index] ? 'CURRENT' : scene.archived ? 'EARLIER VERSION' : 'SCREEN';
    details.append(name, tag); button.append(picture, details);
    button.addEventListener('click', () => {
      sceneSelect.value = scene.id;
      document.getElementById('scene-selected-name').textContent = scene.name;
      sceneLibrary.querySelectorAll('.library-card').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
    });
    sceneLibrary.append(button);
  });
  sceneNote.textContent = '';
  sceneDialog.showModal();
  sceneDialog.scrollTop = 0;
  sceneDialog.querySelector('.dialog-close').focus({preventScroll:true});
}
sceneDialog.addEventListener('close', () => { if (libraryObserver) libraryObserver.disconnect(); });
sceneDialog.querySelectorAll('.dialog-close, .dialog-cancel').forEach(button => button.addEventListener('click', () => sceneDialog.close()));
document.getElementById('scene-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (sending || sceneSlot === null) return;
  commandVersion++;
  sending = true;
  sceneNote.textContent = 'Saving your choice…';
  sceneDialog.querySelector('.dialog-save').disabled = true;
  try {
    const response = await fetch('/board/scene', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({value: {slot: sceneSlot, scene: sceneSelect.value}})});
    if (!response.ok) throw new Error('Could not save');
    const status = await response.json();
    sending = false;
    sceneDialog.close();
    render(status, status.scene_pending?.[sceneSlot] ? 'Screen saved · waiting for the display to receive it.' : 'Screen already in this slot.');
  } catch (_) {
    sending = false;
    sceneNote.textContent = 'Could not save. Please try again.';
  } finally {
    sceneDialog.querySelector('.dialog-save').disabled = false;
  }
});

function orderIsStale() {
  return !Array.isArray(latest?.scene_ids) || JSON.stringify(latest.scene_ids) !== JSON.stringify(orderOriginal);
}

function drawOrder(focusIndex = null) {
  const existing = new Map([...orderGrid.children].map(card => [Number(card.dataset.original), card]));
  orderGrid.replaceChildren();
  orderDraft.forEach((originalIndex, index) => {
    const scene = orderOriginal[originalIndex];
    const name = sceneName(scene, defaultNames[originalIndex]);
    const previous = existing.get(originalIndex);
    if (previous) {
      previous.disabled = sending;
      previous.setAttribute('aria-label', `${name}, position ${index + 1} of 8`);
      previous.setAttribute('aria-pressed', String(orderSelected === originalIndex));
      previous.querySelector('.order-position').textContent = String(index + 1).padStart(2, '0');
      delete previous.dataset.dragging;
      orderGrid.append(previous);
      if (originalIndex === focusIndex) requestAnimationFrame(() => previous.focus({preventScroll:true}));
      return;
    }
    const card = document.createElement('button');
    card.type = 'button'; card.className = 'order-card'; card.dataset.original = String(originalIndex);
    card.disabled = sending;
    card.setAttribute('aria-label', `${name}, position ${index + 1} of 8`);
    card.setAttribute('aria-pressed', String(orderSelected === originalIndex));
    const picture = document.createElement('span'); picture.className = 'library-picture';
    const placeholder = document.createElement('span'); placeholder.className = 'library-placeholder'; placeholder.textContent = 'Loading preview…';
    const img = document.createElement('img'); img.alt = ''; img.width = 320; img.height = 240; img.hidden = true; img.draggable = false;
    const libraryUrl = `/board/library/${encodeURIComponent(scene)}.${previewExtension}?v=${previewVersion}`;
    const confirmed = !latest?.scene_pending?.[originalIndex] && latest?.scene_delivered_ids?.[originalIndex] === scene;
    let usingLibrary = !confirmed;
    img.addEventListener('load', () => { img.hidden = false; placeholder.hidden = true; });
    img.addEventListener('error', () => {
      if (!usingLibrary) { usingLibrary = true; img.src = libraryUrl; }
      else { img.hidden = true; placeholder.textContent = 'Preview unavailable'; }
    });
    img.src = confirmed ? previewUrl(originalIndex) : libraryUrl;
    const position = document.createElement('span'); position.className = 'order-position'; position.textContent = String(index + 1).padStart(2, '0');
    picture.append(placeholder, img, position);
    const details = document.createElement('span'); details.className = 'order-details';
    const title = document.createElement('strong'); title.textContent = name;
    const grip = document.createElement('span'); grip.className = 'order-grip'; grip.setAttribute('aria-hidden', 'true');
    details.append(title, grip); card.append(picture, details);
    card.addEventListener('click', event => { if (event.detail === 0) selectOrderTile(originalIndex); });
    card.addEventListener('keydown', event => {
      const columns = getComputedStyle(orderGrid).gridTemplateColumns.split(' ').length;
      const delta = {ArrowLeft:-1, ArrowRight:1, ArrowUp:-columns, ArrowDown:columns}[event.key];
      if (delta === undefined) return;
      event.preventDefault(); orderSelected = null;
      moveOrder(orderDraft.indexOf(originalIndex), orderDraft.indexOf(originalIndex) + delta);
    });
    orderGrid.append(card);
    if (originalIndex === focusIndex) requestAnimationFrame(() => card.focus({preventScroll:true}));
  });
  orderSave.disabled = sending || orderIsStale() || orderDraft.every((original, index) => original === index);
}

function moveOrder(from, to) {
  if (sending || from === to || to < 0 || to >= orderDraft.length) return;
  const [original] = orderDraft.splice(from, 1); orderDraft.splice(to, 0, original);
  orderNote.dataset.error = 'false';
  orderNote.textContent = `Moved ${sceneName(orderOriginal[original], defaultNames[original])} to position ${to + 1} of 8.`;
  drawOrder(original);
}

function selectOrderTile(original) {
  if (sending || orderIsStale()) return;
  if (orderSelected === null) {
    orderSelected = original;
    orderNote.textContent = `Selected ${sceneName(orderOriginal[original], defaultNames[original])}. Choose its new position.`;
    drawOrder(original);
  } else if (orderSelected === original) {
    orderSelected = null; orderNote.textContent = ''; drawOrder(original);
  } else {
    const from = orderDraft.indexOf(orderSelected), to = orderDraft.indexOf(original);
    orderSelected = null; moveOrder(from, to);
  }
}

function placeDraggedCard(x, y) {
  const target = document.elementFromPoint(x, y)?.closest('.order-card');
  if (!target || target.parentElement !== orderGrid || target === orderDrag.card) return;
  const cards = [...orderGrid.children];
  const from = cards.indexOf(orderDrag.card), to = cards.indexOf(target);
  orderGrid.insertBefore(orderDrag.card, from < to ? target.nextSibling : target);
}

function scrollWhileDragging() {
  if (!orderDrag?.ghost) return;
  const top = orderDialog.getBoundingClientRect().top + 50;
  const bottom = orderDialog.querySelector('.order-footer').getBoundingClientRect().top - 22;
  const y = orderDrag.y;
  const amount = y < top ? -Math.min(14, (top - y) / 2) : y > bottom ? Math.min(14, (y - bottom) / 2) : 0;
  if (amount) { orderDialog.scrollTop += amount; placeDraggedCard(orderDrag.x, y); }
  orderDrag.scrollFrame = requestAnimationFrame(scrollWhileDragging);
}

orderGrid.addEventListener('pointerdown', event => {
  const card = event.target.closest('.order-card');
  if (!card || sending || orderIsStale() || !event.isPrimary || event.button !== 0) return;
  const rect = card.getBoundingClientRect();
  orderDrag = {card, pointer: event.pointerId, x: event.clientX, y: event.clientY,
    startX: event.clientX, startY: event.clientY, offsetX: event.clientX - rect.left,
    offsetY: event.clientY - rect.top, width: rect.width, height: rect.height, ghost: null};
  orderGrid.setPointerCapture(event.pointerId);
});
orderGrid.addEventListener('pointermove', event => {
  if (!orderDrag || event.pointerId !== orderDrag.pointer) return;
  orderDrag.x = event.clientX; orderDrag.y = event.clientY;
  if (!orderDrag.ghost && Math.hypot(event.clientX - orderDrag.startX, event.clientY - orderDrag.startY) >= 7) {
    orderSelected = null;
    const ghost = orderDrag.card.cloneNode(true);
    ghost.classList.add('order-float'); ghost.setAttribute('aria-hidden', 'true'); ghost.tabIndex = -1;
    ghost.style.width = `${orderDrag.width}px`; ghost.style.height = `${orderDrag.height}px`;
    orderDialog.append(ghost); orderDrag.ghost = ghost;
    orderDrag.card.dataset.dragging = 'true'; orderGrid.classList.add('is-dragging');
    orderDrag.scrollFrame = requestAnimationFrame(scrollWhileDragging);
  }
  if (orderDrag.ghost) {
    event.preventDefault();
    orderDrag.ghost.style.left = `${event.clientX - orderDrag.offsetX}px`;
    orderDrag.ghost.style.top = `${event.clientY - orderDrag.offsetY}px`;
    placeDraggedCard(event.clientX, event.clientY);
  }
});
function finishOrderDrag(event, cancel = false) {
  if (!orderDrag || event.pointerId !== orderDrag.pointer) return;
  const {card, ghost, scrollFrame} = orderDrag;
  const original = Number(card.dataset.original);
  if (scrollFrame) cancelAnimationFrame(scrollFrame);
  ghost?.remove(); orderGrid.classList.remove('is-dragging'); orderDrag = null;
  if (!ghost && !cancel) { selectOrderTile(original); return; }
  if (ghost && !cancel) {
    const next = [...orderGrid.children].map(item => Number(item.dataset.original));
    const from = orderDraft.indexOf(original), to = next.indexOf(original);
    if (from !== to) { moveOrder(from, to); return; }
  }
  drawOrder(original);
}
orderGrid.addEventListener('pointerup', event => finishOrderDrag(event));
orderGrid.addEventListener('pointercancel', event => finishOrderDrag(event, true));
orderGrid.addEventListener('lostpointercapture', event => finishOrderDrag(event, true));

orderOpen.addEventListener('click', () => {
  if (!Array.isArray(latest?.scene_ids) || latest.scene_ids.length !== defaultNames.length || latest.scene_settings_error) return;
  orderOriginal = [...latest.scene_ids]; orderDraft = orderOriginal.map((_, index) => index); orderSelected = null;
  orderGrid.replaceChildren();  // Reload previews when the saved screens may have changed.
  orderNote.textContent = ''; orderNote.dataset.error = 'false';
  drawOrder(); orderDialog.showModal(); orderDialog.scrollTop = 0;
  orderDialog.querySelector('.dialog-close').focus({preventScroll:true});
});
orderDialog.querySelectorAll('.dialog-close, .dialog-cancel').forEach(button => button.addEventListener('click', () => { if (!sending) orderDialog.close(); }));
orderDialog.addEventListener('cancel', event => { if (sending) event.preventDefault(); });
orderDialog.addEventListener('close', () => { if (orderDrag) finishOrderDrag({pointerId:orderDrag.pointer}, true); });
document.getElementById('order-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (sending || orderIsStale() || orderSave.disabled) return;
  commandVersion++; sending = true; drawOrder();
  orderNote.textContent = 'Saving order…'; orderNote.dataset.error = 'false';
  try {
    const response = await fetch('/board/order', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({value:{expected:orderOriginal, order:orderDraft}})});
    if (!response.ok) {
      if (response.status === 400) throw new Error('stale');
      throw new Error('save');
    }
    const status = await response.json();
    sending = false; orderDialog.close();
    render(status, status.scene_pending?.some(Boolean) ? 'Order saved · waiting for the display to receive the screens.' : 'Order saved.');
  } catch (error) {
    sending = false;
    orderNote.dataset.error = 'true';
    orderNote.textContent = error.message === 'stale' ? 'The screens changed elsewhere. Close and reopen to try again.' : 'Could not save. Please try again.';
    drawOrder();
    if (error.message === 'stale') orderSave.disabled = true;
  }
});

function refreshPreviews() {
  previewVersion = Date.now();
  document.querySelectorAll('.screen-card').forEach((card, index) => {
    card.querySelector('img').src = previewUrl(index);
  });
  if (latest && latest.page !== null) currentImage.src = previewUrl(latest.page);
  // Refresh only thumbnails that have actually entered the open gallery.
  // The images contain local readings and must not remain stuck on old values.
  if (sceneDialog.open) sceneLibrary.querySelectorAll('img[src]').forEach(img => {
    const url = new URL(img.src, location.href);
    url.searchParams.set('v', String(previewVersion));
    img.src = url.pathname + url.search;
  });
}

function showNote(message, error = false) {
  note.textContent = message;
  note.dataset.error = String(error);
}

function render(status, message) {
  latest = status;
  orderOpen.disabled = sending || !Array.isArray(status.scene_ids) || !status.scene_catalog || status.scene_settings_error;
  if (orderDialog.open && orderIsStale() && !sending) {
    orderSave.disabled = true; orderNote.dataset.error = 'true';
    orderNote.textContent = 'The screens changed elsewhere. Close and reopen to try again.';
  }
  const connection = document.getElementById('connection');
  const descriptions = {connected: 'Connected', busy: 'Sending data', offline: 'Not connected', not_configured: 'Not configured'};
  connection.dataset.state = status.state;
  connection.querySelector('span').textContent = descriptions[status.state] || 'Connecting';
  const usable = status.state === 'connected' || (status.state === 'busy' && status.page !== null);
  const showingConnection = status.showing_connection === true;
  const sceneState = JSON.stringify([status.scene_ids, status.scene_pending]);
  if (lastSceneState && lastSceneState !== sceneState) refreshPreviews();
  lastSceneState = sceneState;
  document.querySelectorAll('.screen-card').forEach((card, index) => {
    const selected = !showingConnection && status.page === index;
    card.disabled = sending || !usable;
    card.setAttribute('aria-pressed', String(selected));
    const name = sceneName(status.scene_ids?.[index], defaultNames[index]);
    card.querySelector('strong').textContent = name;
    card.querySelector('small').textContent = status.scene_pending?.[index] ? (status.scene_delivered_ids?.[index] === null ? 'CHECKING' : 'QUEUED') : selected ? 'ON DISPLAY' : String(index + 1).padStart(2, '0');
    const change = card.parentElement.querySelector('.screen-change');
    change.disabled = sending || !status.scene_catalog || status.scene_settings_error;
    change.setAttribute('aria-label', `Change screen ${index + 1}: ${name}`);
  });
  const knownPage = !showingConnection && Number.isInteger(status.page) && status.page >= 0 && status.page < defaultNames.length;
  const pagePending = knownPage && status.scene_pending?.[status.page];
  const delivered = knownPage ? status.scene_delivered_ids?.[status.page] : null;
  const currentName = delivered ? sceneName(delivered, defaultNames[status.page]) : status.scene_pending?.[status.page] ? 'Waiting for screen' : sceneName(status.scene_ids?.[status.page], defaultNames[status.page]);
  document.getElementById('current-name').textContent = showingConnection ? 'Connection screen' : knownPage ? currentName : 'Your display';
  document.getElementById('current-number').textContent = knownPage ? `${String(status.page + 1).padStart(2, '0')} / 08` : '— / 08';
  document.querySelector('#preview-empty p').textContent = pagePending ? 'Waiting for the screen to reach the display' : 'Waiting for a preview';
  if (pagePending) {
    currentImage.hidden = true;
    document.getElementById('preview-empty').hidden = false;
  } else if (knownPage && currentImage.dataset.page !== String(status.page)) {
    currentImage.dataset.page = String(status.page);
    currentImage.src = previewUrl(status.page);
  } else if (!knownPage) {
    currentImage.dataset.page = '';
    currentImage.hidden = true;
    document.getElementById('preview-empty').hidden = false;
  }
  document.getElementById('rotation-controls').disabled = sending || !usable || !status.controls;
  document.getElementById('speed-controls').disabled = sending || !usable || !status.controls;
  document.getElementById('speed-description').textContent = status.per_screen_speed ?
    'For the selected screen.' : 'Applies to all screens on this display version.';
  document.getElementById('touch-controls').disabled = sending || !usable || !status.touch_controls;
  if (!touchDirty && status.touch_controls) {
    modeHold.value = String(status.mode_hold_seconds);
    connectHold.value = String(status.connect_hold_seconds);
  }
  document.querySelectorAll('[data-rotation]').forEach(button => button.setAttribute('aria-pressed', String(Number(button.dataset.rotation) === status.rotation_minutes)));
  document.querySelectorAll('[data-speed]').forEach(button => button.setAttribute('aria-pressed', String(Number(button.dataset.speed) === status.speed_percent)));
  if (!sending) {
    if (message) showNote(message);
    else if (status.scene_settings_error) showNote('Screen settings could not be read. Existing screens have been kept.', true);
    else if (!usable) showNote(status.state === 'not_configured' ? 'Connect a display to get started.' : 'Waiting for your display to reconnect.', true);
    else if (status.scene_pending?.some(Boolean)) showNote('Some screens are waiting to reach the display.');
    else if (!status.controls) showNote('Screen selection is available. Update the display to enable rotation and speed controls.');
    else if (!status.clock_synced && status.rotation_minutes) showNote('Waiting for the computer to sync the clock.');
    else showNote('Saved on your display · works when this page is closed.');
    if (!usable) touchNote.textContent = 'Waiting for your display to reconnect.';
    else if (!status.touch_controls) touchNote.textContent = 'Update the display to enable touch settings.';
    else if (!touchDirty) touchNote.textContent = 'Saved on your display.';
  }
}

currentImage.addEventListener('load', () => {
  if (!latest || latest.scene_pending?.[latest.page] || currentImage.dataset.page !== String(latest.page)) return;
  currentImage.hidden = false;
  document.getElementById('preview-empty').hidden = true;
});
currentImage.addEventListener('error', () => {
  currentImage.hidden = true;
  document.getElementById('preview-empty').hidden = false;
  retryPreviews();
});
document.querySelectorAll('[data-rotation]').forEach(button => button.addEventListener('click', () => command('rotation', Number(button.dataset.rotation))));
document.querySelectorAll('[data-speed]').forEach(button => button.addEventListener('click', () => {
  const percent = Number(button.dataset.speed);
  command('speed', latest && latest.per_screen_speed ? {percent, page: latest.page} : percent);
}));
[modeHold, connectHold].forEach(select => select.addEventListener('change', () => {
  touchDirty = true;
  touchNote.dataset.error = 'false';
  touchNote.textContent = 'Save to apply your changes.';
}));
document.getElementById('touch-form').addEventListener('submit', event => {
  event.preventDefault();
  command('touch', {mode: Number(modeHold.value), connect: Number(connectHold.value)});
});

async function command(kind, value) {
  if (sending) return;
  commandVersion++;
  sending = true;
  if (latest) render(latest);
  showNote('Sending to your display… This may wait for a current transfer.');
  if (kind === 'touch') touchNote.textContent = 'Sending to your display…';
  try {
    const response = await fetch(`/board/${kind}`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({value})});
    if (!response.ok) throw new Error('Display did not confirm the change');
    const status = await response.json();
    sending = false;
    if (kind === 'touch') {
      touchDirty = false;
      touchNote.dataset.error = 'false';
    }
    render(status, 'Saved on your display.');
  } catch (_) {
    sending = false;
    if (latest) render(latest);
    showNote('Could not confirm the change. Check the connection and try again.', true);
    if (kind === 'touch') {
      touchNote.dataset.error = 'true';
      touchNote.textContent = 'Could not confirm the change. Please try again.';
    }
  }
}

async function poll() {
  if (polling || sending) return;
  polling = true;
  const version = commandVersion;
  try {
    const response = await fetch('/board/status', {cache: 'no-store'});
    if (!response.ok) throw new Error('Status unavailable');
    const status = await response.json();
    if (!sending && version === commandVersion) render(status);
  } catch (_) {
    if (!sending && version === commandVersion) render({state: 'offline', page: null, controls: false});
  } finally { polling = false; }
}

refreshPreviews();
poll();
setInterval(poll, 15000);
setInterval(refreshPreviews, 60000);
