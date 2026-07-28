const dialog = document.querySelector('#task-dialog');
document.querySelector('[data-add-task]')?.addEventListener('click', () => dialog?.showModal());
document.querySelectorAll('#task-dialog .dialog-close').forEach((button) => button.addEventListener('click', () => dialog.close()));
