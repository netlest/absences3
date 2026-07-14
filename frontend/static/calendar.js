// Calendar page behaviour: nav-bar navigation + the absence add/edit modal.
// Loaded with `defer`, so the DOM is ready when this runs.

function navGo() {
  const m = String(document.getElementById('nav-month').value).padStart(2, '0');
  const y = document.getElementById('nav-year').value;
  const n = document.getElementById('nav-count').value;
  const g = document.getElementById('nav-group').value;
  window.location = `/${m}/${y}?months=${n}&group=${g}`;
}

(function () {
  const modal = document.getElementById('add-modal');
  const title = document.getElementById('modal-title');
  const form = modal.querySelector('form');
  const del = document.getElementById('modal-delete');
  const start = form.elements.abs_date_start;
  const end = form.elements.abs_date_end;

  function syncMin() {
    end.min = start.value;
    if (end.value && end.value < start.value) end.value = start.value;
  }
  start.addEventListener('change', syncMin);

  function openAddModal(params) {
    const today = new Date().toISOString().slice(0, 10);
    const day = params.get('date') || today;
    const objectId = params.get('object_id');
    title.textContent = 'Add absence';
    form.action = '/absences/new';
    if (objectId) form.elements.object_id.value = objectId;
    start.value = day;
    end.value = day;
    form.elements.description.value = '';
    del.classList.add('hidden');
    syncMin();
    modal.showModal();
  }

  async function openEditModal(id, fallbackHref) {
    let a;
    try {
      const r = await fetch(`/absences/${id}/data`);
      if (!r.ok) throw new Error(r.status);
      a = await r.json();
    } catch {
      window.location = fallbackHref;  // standalone edit page
      return;
    }
    title.textContent = 'Edit absence';
    form.action = `/absences/${id}/edit`;
    form.elements.object_id.value = a.object_id;
    form.elements.type_id.value = a.type_id;
    start.value = a.abs_date_start;
    end.value = a.abs_date_end;
    form.elements.description.value = a.description || '';
    del.action = `/absences/${id}/delete`;
    del.elements.abs_date_start.value = a.abs_date_start;
    del.classList.remove('hidden');
    syncMin();
    modal.showModal();
  }

  document.addEventListener('click', function (e) {
    const a = e.target.closest('a[href^="/absences/"]');
    if (!a) return;
    const url = new URL(a.href, location.origin);
    if (url.pathname === '/absences/new') {
      e.preventDefault();
      openAddModal(url.searchParams);
      return;
    }
    const m = url.pathname.match(/^\/absences\/(\d+)\/edit$/);
    if (m) {
      e.preventDefault();
      openEditModal(m[1], a.href);
    }
  });
})();
