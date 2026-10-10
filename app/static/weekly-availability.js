(() => {
  const form = document.querySelector("#availability-form");
  const rows = document.querySelector("#window-rows");
  const source = document.querySelector("#schedule-source");
  const error = document.querySelector("#window-error");
  if (!form || !rows || !source) return;

  const days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  const times = [];
  for (let minute = 0; minute < 24 * 60; minute += 30) {
    times.push(minute);
  }

  function timeValue(minute) {
    return `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
  }

  function timeLabel(minute) {
    const hour = Math.floor(minute / 60);
    const suffix = hour < 12 ? "AM" : "PM";
    return `${hour % 12 || 12}:${String(minute % 60).padStart(2, "0")} ${suffix}`;
  }

  function parseTime(value) {
    const [hour, minute] = value.split(":").map(Number);
    return hour * 60 + minute;
  }

  function makeSelect(label, className) {
    const wrapper = document.createElement("label");
    wrapper.className = "window-field";
    const caption = document.createElement("span");
    caption.textContent = label;
    const select = document.createElement("select");
    select.className = className;
    select.setAttribute("aria-label", label);
    wrapper.append(caption, select);
    return { wrapper, select };
  }

  function addOption(select, value, label, selectedValue) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    option.selected = value === selectedValue;
    select.append(option);
  }

  function fillStartOptions(select, selectedValue) {
    select.replaceChildren();
    const minutes = [...new Set([...times, parseTime(selectedValue)])].sort((a, b) => a - b);
    minutes.forEach((minute) => addOption(select, timeValue(minute), timeLabel(minute), selectedValue));
  }

  function fillEndOptions(select, startMinute, selectedValue) {
    select.replaceChildren();
    // Each window must have a positive duration within the selected day.
    const minutes = [...new Set([...times, 1439, parseTime(selectedValue)])].filter((minute) => Number.isFinite(minute) && minute > startMinute && minute < 1440).sort((a, b) => a - b);
    minutes.forEach((minute) => {
      addOption(select, timeValue(minute), timeLabel(minute), selectedValue);
    });
    if (![...select.options].some((option) => option.selected)) {
      select.selectedIndex = 0;
    }
  }

  function findOverlap() {
    const windowsByDay = new Map();
    for (const row of rows.querySelectorAll(".window-row")) {
      const [day, start, end] = row.querySelectorAll("select");
      const startMinute = parseTime(start.value);
      const endMinute = parseTime(end.value);
      if (startMinute === endMinute) continue;
      const dayWindows = windowsByDay.get(day.value) ?? [];
      dayWindows.push([startMinute, endMinute]);
      windowsByDay.set(day.value, dayWindows);
    }

    for (const [day, dayWindows] of windowsByDay) {
      dayWindows.sort((left, right) => left[0] - right[0]);
      for (let index = 1; index < dayWindows.length; index += 1) {
        if (dayWindows[index][0] < dayWindows[index - 1][1]) return days[Number(day)];
      }
    }
    return null;
  }

  function updateStoredSchedule() {
    const invalidRange = [...rows.querySelectorAll(".window-row")].some((row) => {
      const [, start, end] = row.querySelectorAll("select");
      return !start.value || !end.value || parseTime(start.value) >= parseTime(end.value);
    });
    const values = [...rows.querySelectorAll(".window-row")].map((row) => {
      const [day, start, end] = row.querySelectorAll("select");
      return `${day.value},${start.value},${end.value}`;
    });
    source.value = values.join("\n");
    const overlapDay = findOverlap();
    if (error) {
      error.textContent = invalidRange ? "Each end time must be later than its start time." : (overlapDay ? `Availability windows overlap on ${overlapDay}. Adjust the times before saving.` : "");
      error.hidden = !invalidRange && !overlapDay;
    }
    return invalidRange || Boolean(overlapDay);
  }

  function addRow(existing = null) {
    const row = document.createElement("div");
    row.className = "window-row";

    const dayField = makeSelect("Day", "day-select");
    dayField.wrapper.classList.add("day-field");
    days.forEach((day, index) => addOption(dayField.select, String(index), day, String(existing?.day ?? (rows.children.length % 7))));

    const startField = makeSelect("Start", "start-select");
    startField.wrapper.classList.add("start-field");
    const defaultStart = existing?.start ?? "18:00";
    fillStartOptions(startField.select, defaultStart);

    const endField = makeSelect("End", "end-select");
    endField.wrapper.classList.add("end-field");
    const defaultEnd = existing?.end ?? "20:00";
    fillEndOptions(endField.select, parseTime(startField.select.value), defaultEnd);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "remove-window";
    remove.textContent = "Remove";
    remove.setAttribute("aria-label", "Remove this time window");
    remove.addEventListener("click", () => {
      row.remove();
      updateStoredSchedule();
    });

    startField.select.addEventListener("change", () => {
      const previousEnd = endField.select.value;
      fillEndOptions(endField.select, parseTime(startField.select.value), previousEnd);
      updateStoredSchedule();
    });
    dayField.select.addEventListener("change", updateStoredSchedule);
    endField.select.addEventListener("change", updateStoredSchedule);

    row.append(dayField.wrapper, startField.wrapper, endField.wrapper, remove);
    rows.append(row);
  }

  function loadExistingWindows() {
    source.value.split(/\r?\n/).forEach((line) => {
      const [day, start, end] = line.trim().split(",").map((part) => part.trim());
      if (day === undefined || !start || !end) return;
      addRow({ day: Number(day), start, end });
    });
  }

  document.querySelector("#add-window")?.addEventListener("click", () => {
    addRow();
    updateStoredSchedule();
  });
  form.addEventListener("submit", (event) => {
    if (updateStoredSchedule()) event.preventDefault();
  });

  loadExistingWindows();
  form.classList.add("availability-ready");
  updateStoredSchedule();
})();
