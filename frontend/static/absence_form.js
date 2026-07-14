// Standalone add/edit absence form: default the dates to today and keep
// "To" from going before "From". Loaded with `defer`.

(function () {
  const start = document.getElementById('abs_date_start');
  const end = document.getElementById('abs_date_end');

  function syncMin() {
    end.min = start.value;
    if (end.value && end.value < start.value) end.value = start.value;
  }
  start.addEventListener('change', syncMin);

  if (!start.value) {
    start.value = new Date().toISOString().slice(0, 10);
    if (!end.value) end.value = start.value;
  }
  syncMin();
})();
