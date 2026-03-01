(function () {
  const menuBtn = document.getElementById("menu-toggle");
  const nav = document.getElementById("main-nav");

  if (menuBtn && nav) {
    menuBtn.addEventListener("click", () => {
      const isOpen = nav.classList.toggle("open");
      menuBtn.setAttribute("aria-expanded", isOpen ? "true" : "false");
    });
  }

  const visibilitySelect = document.getElementById("visibility-select");
  const sharedWrap = document.getElementById("shared-with-wrap");
  if (visibilitySelect && sharedWrap) {
    const updateShared = () => {
      const isPrivate = visibilitySelect.value === "private";
      sharedWrap.classList.toggle("hidden", !isPrivate);
    };
    visibilitySelect.addEventListener("change", updateShared);
    updateShared();
  }

  const modal = document.getElementById("confirm-modal");
  const modalConfirm = document.getElementById("modal-confirm");
  const modalCancel = document.getElementById("modal-cancel");
  let pendingForm = null;

  function closeModal() {
    if (!modal) return;
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
    pendingForm = null;
  }

  function openModal(form) {
    if (!modal) return;
    pendingForm = form;
    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");
  }

  document.addEventListener("submit", (event) => {
    const form = event.target.closest(".delete-song-form");
    if (!form || !modal) return;
    event.preventDefault();
    openModal(form);
  });

  if (modalConfirm) {
    modalConfirm.addEventListener("click", () => {
      if (pendingForm) {
        const form = pendingForm;
        closeModal();
        form.submit();
      }
    });
  }

  if (modalCancel) {
    modalCancel.addEventListener("click", closeModal);
  }

  if (modal) {
    modal.addEventListener("click", (event) => {
      if (event.target === modal) {
        closeModal();
      }
    });
  }

  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeModal();
    }
  });
})();
