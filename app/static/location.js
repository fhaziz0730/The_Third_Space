(() => {
  const picker = document.querySelector(".location-picker");
  if (!picker) return;
  const query = document.getElementById("location-query");
  const label = document.getElementById("location-label");
  const latitude = document.getElementById("location-latitude");
  const longitude = document.getElementById("location-longitude");
  const status = document.getElementById("location-status");
  const results = document.getElementById("location-results");
  const searchButton = document.getElementById("search-location");
  const currentButton = document.getElementById("approximate-location");
  let revision = 0;
  let controller;

  function resetResults() {
    results.replaceChildren();
    results.hidden = true;
  }

  function invalidate() {
    revision += 1;
    controller?.abort();
    controller = null;
    searchButton.disabled = false;
    latitude.value = longitude.value = label.value = "";
    resetResults();
  }

  function selectLocation(location) {
    revision += 1;
    query.value = label.value = location.label;
    latitude.value = location.latitude;
    longitude.value = location.longitude;
    resetResults();
    status.textContent = `${location.label} selected. Save your profile to keep it.`;
  }

  query.addEventListener("input", () => {
    invalidate();
    status.textContent = query.value.trim() ? "Search and choose a match to update your starting area." : "No starting area chosen. Save to remove the previous location.";
  });

  document.getElementById("clear-location").addEventListener("click", () => {
    invalidate();
    query.value = "";
    status.textContent = "Location cleared. Save your profile to remove it.";
    query.focus();
  });

  async function search() {
    const searchText = query.value.trim();
    if (searchText.length < 2 || searchText.length > 100) {
      status.textContent = "Enter a town or postal code between 2 and 100 characters.";
      return;
    }
    controller?.abort();
    const request = new AbortController();
    controller = request;
    const version = ++revision;
    searchButton.disabled = true;
    resetResults();
    status.textContent = "Searching locations…";
    try {
      const response = await fetch(picker.dataset.searchUrl, {
        method: "POST",
        headers: { "X-CSRF-Token": document.querySelector('meta[name="csrf-token"]')?.content || "" },
        body: new URLSearchParams({ q: searchText }),
        signal: request.signal,
        credentials: "same-origin",
      });
      const data = await response.json();
      if (version !== revision) return;
      if (!response.ok) throw new Error(data.error || "Location search is unavailable. Please try again.");
      if (!data.results.length) {
        status.textContent = data.sample ? "No sample location matched. Try Brooklyn, New York, Boston, or use your current location." : "No locations found. Try a nearby town or add the state or country.";
        return;
      }
      for (const location of data.results) {
        const item = document.createElement("li");
        const button = document.createElement("button");
        button.type = "button";
        button.className = "secondary location-match";
        button.textContent = location.label;
        button.addEventListener("click", () => selectLocation(location));
        item.append(button);
        results.append(item);
      }
      results.hidden = false;
      status.textContent = data.sample ? "Choose a sample location below." : "Choose the matching town or area below.";
    } catch (error) {
      if (version !== revision || error.name === "AbortError") return;
      status.textContent = error.message || "Search failed. Try again or use your current location.";
    } finally {
      if (controller === request) {
        controller = null;
        searchButton.disabled = false;
      }
    }
  }

  searchButton.addEventListener("click", search);
  query.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      search();
    }
  });

  currentButton.addEventListener("click", () => {
    if (!navigator.geolocation) {
      status.textContent = "Your browser cannot share a location. Search for your town instead.";
      return;
    }
    controller?.abort();
    controller = null;
    searchButton.disabled = false;
    const version = ++revision;
    currentButton.disabled = true;
    resetResults();
    status.textContent = "Waiting for your browser's location permission…";
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        currentButton.disabled = false;
        if (version !== revision) return;
        selectLocation({ label: "Near my current location", latitude: coords.latitude.toFixed(2), longitude: coords.longitude.toFixed(2) });
      },
      () => {
        currentButton.disabled = false;
        if (version === revision) status.textContent = "Location was unavailable or permission was declined. Search for your town instead.";
      },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 },
    );
  });
})();
