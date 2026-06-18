(function () {
  document.addEventListener("click", function (e) {
    const t = e.target;
    if (t.matches("[data-open-modal]")) {
      const id = t.getAttribute("data-open-modal");
      const m = document.getElementById(id);
      if (m) m.classList.add("open");
    }
    if (t.matches("[data-close-modal]") || t.classList.contains("pdv-modal")) {
      const modal = t.classList.contains("pdv-modal") ? t : t.closest(".pdv-modal");
      if (modal) modal.classList.remove("open");
    }
  });
})();
