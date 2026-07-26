const deleteDialog = document.querySelector('#delete-assignment-dialog');

document.querySelectorAll('[data-delete-open]').forEach((button) => {
  button.addEventListener('click', () => {
    deleteDialog.querySelector('[data-delete-name]').textContent = `“${button.dataset.deleteName}”`;
    deleteDialog.querySelector('[data-delete-form]').action = button.dataset.deleteUrl;
    deleteDialog.showModal();
  });
});

document.querySelectorAll('[data-delete-close]').forEach((button) => {
  button.addEventListener('click', () => deleteDialog.close());
});

deleteDialog?.addEventListener('click', (event) => {
  if (event.target === deleteDialog) deleteDialog.close();
});
