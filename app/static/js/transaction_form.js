// Show only categories that match the chosen transaction type.
// (The server re-validates this; the script is a convenience only.)
const typeSelect = document.getElementById("type");
const categorySelect = document.getElementById("category_id");

function syncCategories() {
  const wanted = typeSelect.value;
  let selectedStillValid = false;
  let firstMatch = null;
  for (const option of categorySelect.options) {
    const match = option.dataset.type === wanted;
    option.hidden = !match;
    option.disabled = !match;
    if (match && firstMatch === null) firstMatch = option;
    if (match && option.selected) selectedStillValid = true;
  }
  if (!selectedStillValid && firstMatch) firstMatch.selected = true;
}

if (typeSelect && categorySelect) {
  typeSelect.addEventListener("change", syncCategories);
  syncCategories();
}
