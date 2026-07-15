// Manage page: the add/edit form arrives inside <dialog id="manage-modal" open>
// (visible even without JS). Here we upgrade it to a real modal — backdrop,
// focus trap, ESC — and close it when the backdrop is clicked.

function upgradeManageModal(root) {
  const dlg = (root || document).querySelector('#manage-modal');
  if (!dlg || dlg.dataset.modal) return;
  dlg.dataset.modal = '1';
  dlg.removeAttribute('open');   // showModal() requires a closed dialog
  dlg.showModal();
  const field = dlg.querySelector('input:not([type=hidden]), select, textarea');
  if (field) field.focus();
  dlg.addEventListener('click', function (e) {
    if (e.target === dlg) dlg.close();  // click on ::backdrop
  });
}

document.addEventListener('DOMContentLoaded', function () {
  upgradeManageModal(document);
});
document.body.addEventListener('htmx:afterSwap', function (e) {
  upgradeManageModal(e.target);
});
