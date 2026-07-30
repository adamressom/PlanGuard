const deleteDialog = document.querySelector('#delete-assignment-dialog');
let deleteTrigger = null;

document.querySelectorAll('[data-delete-open]').forEach((button) => {
  button.addEventListener('click', () => {
    deleteTrigger = button;
    deleteDialog.querySelector('[data-delete-name]').textContent = `“${button.dataset.deleteName}”`;
    deleteDialog.querySelector('[data-delete-form]').action = button.dataset.deleteUrl;
    deleteDialog.showModal();
    deleteDialog.querySelector('.cancel-button').focus();
  });
});

document.querySelectorAll('[data-delete-close]').forEach((button) => {
  button.addEventListener('click', () => deleteDialog.close());
});

deleteDialog?.addEventListener('click', (event) => {
  if (event.target === deleteDialog) deleteDialog.close();
});

deleteDialog?.addEventListener('close', () => {
  deleteTrigger?.focus();
  deleteTrigger = null;
});
