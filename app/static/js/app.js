// Month/year pickers: submit as soon as a <select> changes. Without JavaScript
// the visible "Go" button does the same thing.
document.querySelectorAll("select[data-autosubmit]").forEach((select) => {
  select.addEventListener("change", () => select.form.requestSubmit());
});

// Fill the shared confirmation modal from the button that opened it.
const confirmModal = document.getElementById("confirmModal");
if (confirmModal) {
  confirmModal.addEventListener("show.bs.modal", (event) => {
    const trigger = event.relatedTarget;
    if (!trigger) return;
    document.getElementById("confirmForm").action = trigger.dataset.confirmAction;
    document.getElementById("confirmModalTitle").textContent = trigger.dataset.confirmTitle || "Are you sure?";
    document.getElementById("confirmBody").textContent = trigger.dataset.confirmBody || "";
    document.getElementById("confirmNext").value = trigger.dataset.confirmNext || "";
  });
}
