// Orders page (#25): the Edit/Hide filters toggle, "Choose another plant", and row clicks.
// Small on purpose: everything else is HTMX attributes in the templates.
(function () {
  const toggle = document.querySelector(".filter-toggle");
  const fields = document.getElementById("filter-fields");
  if (!toggle || !fields) {
    return;
  }

  function setOpen(open) {
    fields.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    toggle.querySelector(".filter-toggle-label").textContent = open ? "Hide filters" : "Edit filters";
  }

  toggle.addEventListener("click", function () {
    setOpen(fields.hidden);
  });

  // Buttons and rows inside #orders-results are replaced by HTMX, so listen on the document.
  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-choose-plant]")) {
      setOpen(true);
      document.getElementById("filter-plant").focus();
      return;
    }
    const row = event.target.closest("tr[data-href]");
    if (row && !event.target.closest("a, button")) {
      window.location.href = row.dataset.href;
    }
  });
})();
