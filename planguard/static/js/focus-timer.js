const focusRoot = document.querySelector('[data-focus-root]');

if (focusRoot) {
  const display = focusRoot.querySelector('[data-focus-display]');
  const message = focusRoot.querySelector('[data-focus-message]');
  const stateBadge = focusRoot.querySelector('[data-focus-state]');
  const pauseButton = focusRoot.querySelector('[data-focus-pause]');
  const resumeButton = focusRoot.querySelector('[data-focus-resume]');
  const endButton = focusRoot.querySelector('[data-focus-end]');
  const startButton = focusRoot.querySelector('[data-focus-start]');
  const focusTitle = focusRoot.querySelector('[data-focus-title]');
  const progressDialog = document.querySelector('[data-focus-progress-dialog]');
  const progressForm = document.querySelector('[data-focus-progress-form]');
  const progressClose = document.querySelector('[data-focus-progress-close]');
  const progressRange = document.querySelector('[data-progress-range]');
  const progressNumber = document.querySelector('[data-progress-number]');
  const progressError = document.querySelector('[data-progress-error]');
  const assignmentRows = document.querySelectorAll('[data-assignment-row]');
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

  const setProgressError = (text) => {
    if (!progressError) return;
    progressError.textContent = text;
    progressError.hidden = !text;
  };

  const clampProgress = (value) => {
    const parsed = Number.parseInt(value, 10);
    if (Number.isNaN(parsed)) return null;
    return Math.min(Math.max(parsed, 0), 100);
  };

  const syncProgressInputs = (value) => {
    const progress = clampProgress(value);
    if (progress === null) return;
    if (progressRange) progressRange.value = progress;
    if (progressNumber) progressNumber.value = progress;
    setProgressError('');
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

  const applyEndedState = (session) => {
    applySession(session);
    if (pauseButton) pauseButton.hidden = true;
    if (resumeButton) resumeButton.hidden = true;
    if (endButton) endButton.hidden = true;
  };

  const updateAssignmentRow = (row, assignment, rank) => {
    row.dataset.assignmentId = assignment.id;
    const rankLabel = row.querySelector('.rank');
    const course = row.querySelector('.task-info small');
    const title = row.querySelector('.task-info h3 a') || row.querySelector('.task-info h3');
    const editLink = row.querySelector('.edit-link');
    const deleteButton = row.querySelector('[data-delete-open]');
    const meter = row.querySelector('.meter i');
    const score = row.querySelector('.task-score b');
    if (rankLabel) rankLabel.childNodes[rankLabel.childNodes.length - 1].textContent = String(rank).padStart(2, '0');
    if (course) course.textContent = assignment.course;
    if (title) title.textContent = assignment.title;
    if (title?.tagName === 'A' && assignment.detail_url) title.href = assignment.detail_url;
    if (editLink && assignment.edit_url) {
      editLink.href = assignment.edit_url;
      editLink.setAttribute('aria-label', `Edit ${assignment.title}`);
    }
    if (deleteButton && assignment.delete_url) {
      deleteButton.dataset.deleteName = assignment.title;
      deleteButton.dataset.deleteUrl = assignment.delete_url;
      deleteButton.setAttribute('aria-label', `Delete ${assignment.title}`);
    }
    if (meter) meter.style.width = `${assignment.progress}%`;
    if (score) score.textContent = Math.trunc(assignment.priority_score);
  };

  const refreshDashboard = (assignments = []) => {
    assignments.forEach((assignment, index) => {
      const row = assignmentRows[index];
      if (row) updateAssignmentRow(row, assignment, index + 1);
    });

    if (!focusTitle) return;
    const activeAssignment = assignments.find((assignment) => String(assignment.id) === String(focusTitle.dataset.assignmentId));
    if (activeAssignment) focusTitle.dataset.assignmentProgress = activeAssignment.progress;
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
      setMessage(`${action[0].toUpperCase()}${action.slice(1)}...`);
      const data = await request(`/api/focus-sessions/${sessionId}/${action}`, {method: 'POST', body});
      if (action === 'end') {
        applyEndedState(data.session);
        refreshDashboard(data.assignments);
        setMessage('Focus session ended.');
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
      setMessage('Starting focus session...');
      await request('/api/focus-sessions', {method: 'POST', body: {assignment_id: Number(startButton.dataset.assignmentId), planned_minutes: Number(startButton.dataset.plannedMinutes)}});
      window.location.reload();
    } catch (error) {
      startButton.disabled = false;
      setMessage(error.message, true);
    }
  });

  pauseButton?.addEventListener('click', () => sendAction('pause'));
  resumeButton?.addEventListener('click', () => sendAction('resume'));
  endButton?.addEventListener('click', () => {
    syncProgressInputs(focusTitle?.dataset.assignmentProgress || 0);
    setProgressError('');
    progressDialog?.showModal();
  });

  progressClose?.addEventListener('click', () => progressDialog?.close());
  progressRange?.addEventListener('input', () => syncProgressInputs(progressRange.value));
  progressNumber?.addEventListener('input', () => syncProgressInputs(progressNumber.value));

  progressForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const isSave = event.submitter?.matches('[data-save-progress]');
    const assignmentId = Number(focusTitle?.dataset.assignmentId);

    if (!isSave) {
      if (!window.confirm('End this focus session without updating assignment progress?')) return;
      progressDialog.close();
      sendAction('end', {reason: 'manual'});
      return;
    }

    if (!progressNumber.value.trim()) {
      setProgressError('Enter progress from 0 to 100.');
      return;
    }

    const progress = clampProgress(progressNumber.value);
    if (progress === null) {
      setProgressError('Enter progress from 0 to 100.');
      return;
    }

    try {
      const data = await request(`/api/assignments/${assignmentId}`, {method: 'PATCH', body: {progress}});
      syncProgressInputs(data.progress);
      refreshDashboard(data.assignments);
      const finished = window.confirm('Are you finished with this focus session?');
      progressDialog.close();
      if (finished) {
        sendAction('end', {reason: 'manual'});
      } else {
        if (focusTitle) focusTitle.dataset.assignmentProgress = data.progress;
        setMessage('Progress saved. Focus session is still running.');
      }
    } catch (error) {
      setProgressError(error.message);
    }
  });

  const tick = () => {
    if (!display || status !== 'running') return;
    const remaining = currentRemaining();
    display.textContent = formatTime(remaining);
    if (remaining <= 0 && !completionSent) {
      completionSent = true;
      setMessage('Focus block complete! Saving your session...');
      sendAction('end', {reason: 'timer_complete'});
    }
  };

  const resync = async () => {
    if (!sessionId || status === 'ended' || status === 'completed') return;
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
