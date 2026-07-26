const dialog = document.querySelector('#task-dialog');
document.querySelector('[data-add-task]')?.addEventListener('click', () => dialog.showModal());
document.querySelectorAll('#task-dialog .dialog-close').forEach((button) => {
  button.addEventListener('click', () => dialog.close());
});

const focusButton = document.querySelector('[data-focus]');
const focusCard = document.querySelector('[data-focus-card]');
const progressDialog = document.querySelector('#progress-dialog');
const progressCopy = document.querySelector('[data-progress-copy]');
const progressRange = document.querySelector('[data-progress-range]');
const progressNumber = document.querySelector('[data-progress-number]');
let focusInProgress = false;

document.querySelector('[data-progress-close]')?.addEventListener('click', () => {
  progressDialog.close();
});

focusButton?.addEventListener('click', () => {
  if (!focusInProgress) {
    focusInProgress = true;
    focusButton.textContent = 'Finish focus';
    return;
  }

  const currentProgress = focusCard.dataset.assignmentProgress || 0;
  progressCopy.textContent = `How complete is ${focusCard.dataset.assignmentTitle} now?`;
  progressRange.value = currentProgress;
  progressNumber.value = currentProgress;
  progressDialog.showModal();
});
