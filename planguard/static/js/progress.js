document.querySelectorAll('.progress-form').forEach((form) => {
  const input = form.querySelector('[data-progress-input]');
  const output = form.querySelector('[data-progress-output]');
  input.addEventListener('input', () => {
    output.textContent = `${input.value}%`;
  });
});
