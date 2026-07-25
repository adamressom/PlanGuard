const focusRoot = document.querySelector('[data-focus-root]');

if (focusRoot) {
  const display = focusRoot.querySelector('[data-focus-display]');
  const message = focusRoot.querySelector('[data-focus-message]');
  const stateBadge = focusRoot.querySelector('[data-focus-state]');
  const pauseButton = focusRoot.querySelector('[data-focus-pause]');
  const resumeButton = focusRoot.querySelector('[data-focus-resume]');
  const endButton = focusRoot.querySelector('[data-focus-end]');
  const startButton = focusRoot.querySelector('[data-focus-start]');
  let sessionId = display?.dataset.sessionId || null;
  let status = display?.dataset.status || null;
  let syncedRemaining = Number(display?.dataset.remainingSeconds || 0);
  let syncedAt = Date.now();
  let completionSent = false;

  const formatTime = (seconds) => {
    const safeSeconds = Math.max(Math.ceil(seconds), 0);
    const minutes = Math.floor(safeSeconds / 60);
    const remainder = safeSeconds % 60;
    return `${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`;
  };

  const currentRemaining = () => {
    if (status !== 'running') return syncedRemaining;
    return Math.max(syncedRemaining - (Date.now() - syncedAt) / 1000, 0);
  };

  const setMessage = (text, isError = false) => {
    if (!message) return;
    message.textContent = text;
    message.classList.toggle('error', isError);
  };

  const applySession = (session) => {
    sessionId = session.id;
    status = session.status;
    syncedRemaining = session.remaining_seconds;
    syncedAt = Date.now();
    if (display) {
      display.dataset.sessionId = session.id;
      display.dataset.status = session.status;
      display.dataset.remainingSeconds = session.remaining_seconds;
      display.textContent = formatTime(session.remaining_seconds);
    }
    if (stateBadge) {
      stateBadge.textContent = session.status;
      stateBadge.className = `focus-state ${session.status}`;
    }
    if (pauseButton) pauseButton.hidden = session.status !== 'running';
    if (resumeButton) resumeButton.hidden = session.status !== 'paused';
  };

  const request = async (url, options = {}) => {
    const response = await fetch(url, {
      method: options.method || 'GET',
      headers: options.body ? {'Content-Type': 'application/json'} : {},
      body: options.body ? JSON.stringify(options.body) : undefined,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Focus session could not be updated.');
    return data;
  };

  const sendAction = async (action, body) => {
    try {
      setMessage(`${action[0].toUpperCase()}${action.slice(1)}…`);
      const data = await request(`/api/focus-sessions/${sessionId}/${action}`, {method: 'POST', body});
      if (action === 'end') {
        window.location.reload();
      } else {
        applySession(data.session);
        setMessage(action === 'pause' ? 'Session paused. It is safe to navigate away.' : 'Focus session resumed.');
      }
    } catch (error) {
      setMessage(error.message, true);
    }
  };

  startButton?.addEventListener('click', async () => {
    try {
      startButton.disabled = true;
      setMessage('Starting focus session…');
      await request('/api/focus-sessions', {method: 'POST', body: {assignment_id: Number(startButton.dataset.assignmentId), planned_minutes: Number(startButton.dataset.plannedMinutes)}});
      window.location.reload();
    } catch (error) {
      startButton.disabled = false;
      setMessage(error.message, true);
    }
  });

  pauseButton?.addEventListener('click', () => sendAction('pause'));
  resumeButton?.addEventListener('click', () => sendAction('resume'));
  endButton?.addEventListener('click', () => sendAction('end', {reason: 'manual'}));

  const tick = () => {
    if (!display || status !== 'running') return;
    const remaining = currentRemaining();
    display.textContent = formatTime(remaining);
    if (remaining <= 0 && !completionSent) {
      completionSent = true;
      setMessage('Focus block complete! Saving your session…');
      sendAction('end', {reason: 'timer_complete'});
    }
  };

  const resync = async () => {
    if (!sessionId) return;
    try {
      const data = await request(focusRoot.dataset.activeUrl);
      if (data.session) applySession(data.session);
    } catch (error) {
      setMessage('Timer is continuing locally; server sync will retry.', true);
    }
  };

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') resync();
  });
  setInterval(tick, 250);
  setInterval(resync, 30000);
  tick();
}
