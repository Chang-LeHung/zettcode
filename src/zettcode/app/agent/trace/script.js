document.documentElement.classList.add("js");
var buttons = Array.prototype.slice.call(document.querySelectorAll(".turn"));
var panels = Array.prototype.slice.call(document.querySelectorAll(".panel"));
function show(id) {
  buttons.forEach(function (button) { button.classList.toggle("is-current", button.dataset.panel === id); });
  panels.forEach(function (panel) { panel.classList.toggle("is-current", panel.id === id); });
}
buttons.forEach(function (button) {
  button.addEventListener("click", function () { show(button.dataset.panel); });
});
Array.prototype.slice.call(document.querySelectorAll(".copy")).forEach(function (button) {
  button.addEventListener("click", function () {
    navigator.clipboard.writeText(button.dataset.copy).then(function () {
      button.textContent = "Copied";
      setTimeout(function () { button.textContent = "Copy"; }, 1200);
    });
  });
});
