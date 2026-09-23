/* Shared accessible native dialog for the home and selection pages. */
const dialog = document.querySelector("#about-dialog");
document.querySelector("#about-open").addEventListener("click", () => dialog.showModal());
document.querySelector("#about-close").addEventListener("click", () => dialog.close());
dialog.addEventListener("click", event => {
  if (event.target !== dialog) return;
  const bounds = dialog.getBoundingClientRect();
  if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
});
