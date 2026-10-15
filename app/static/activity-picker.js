(() => {
  const picker = document.querySelector(".activity-picker");
  if (!picker) return;
  const choices = [...picker.querySelectorAll('input[name="hobbies"]')];
  const count = picker.querySelector("#activity-count");

  function update() {
    const selected = choices.filter((choice) => choice.checked).length;
    count.textContent =
      `${selected} of 4 selected${selected >= 4 ? ". Deselect an activity to choose another." : "."}`;
    choices.forEach((choice) => {
      choice.disabled = selected >= 4 && !choice.checked;
      choice.setCustomValidity(choice.checked && selected > 4 ? "Choose up to 4 activities." :
        "");
    });
  }
  choices.forEach((choice) => choice.addEventListener("change", update));
  update();
})();
