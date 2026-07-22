const dialog = document.querySelector('#task-dialog');
document.querySelector('[data-add-task]')?.addEventListener('click', () => dialog.showModal());
document.querySelectorAll('.dialog-close').forEach((button) => button.addEventListener('click', () => dialog.close()));
document.querySelector('[data-focus]')?.addEventListener('click', (event) => {
  event.currentTarget.textContent = 'Focus block started ✓';
});

