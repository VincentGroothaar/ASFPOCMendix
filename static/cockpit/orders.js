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

  // A link with ?filters=open (the dashboard's "Choose another plant") opens the filter bar.
  if (new URLSearchParams(window.location.search).get("filters") === "open") {
    setOpen(true);
    document.getElementById("filter-plant").focus();
  }

  // After a filter change the URL has a new plant and range: the sidebar links to Orders and
  // the Dashboard carry them, so the dashboard shows what Orders shows (#30).
  document.addEventListener("htmx:pushedIntoHistory", function () {
    const current = new URLSearchParams(window.location.search);
    const shared = new URLSearchParams();
    ["plant", "from", "to"].forEach(function (key) {
      if (current.get(key)) {
        shared.set(key, current.get(key));
      }
    });
    document.querySelectorAll('.sidebar-link[href^="/orders/"], .sidebar-link[href^="/dashboard/"]').forEach(function (link) {
      link.setAttribute("href", link.getAttribute("href").split("?")[0] + "?" + shared.toString());
    });
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
