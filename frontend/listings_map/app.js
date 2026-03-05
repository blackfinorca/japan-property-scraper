const DEFAULT_JSON_PATH = "/output/consolidated/listings_map_payload.json";
const API_KEY_STORAGE_KEY = "jp_property_google_maps_api_key";

const ELIGIBILITY_COLORS = {
  "ALREADY A RYOKAN": "#157f1f",
  "LIKELY ELIGIBLE": "#2a9d8f",
  "LIKELY NOT ELIGIBLE": "#c0392b",
  UNCERTAIN: "#f4a261",
  OTHER: "#64748b",
};

const state = {
  map: null,
  infoWindow: null,
  records: [],
  markerEntries: [],
  localConfigKey: "",
  selectedMarker: null,
  ignoreMapClicksUntilMs: 0,
};

bootstrap().catch((error) => {
  setStatus(`Initialization failed: ${error.message}`);
  // eslint-disable-next-line no-console
  console.error(error);
});

async function bootstrap() {
  const params = new URLSearchParams(window.location.search);
  state.localConfigKey = await loadLocalConfigKey();
  if (params.get("resetMapsKey") === "1") {
    window.localStorage.removeItem(API_KEY_STORAGE_KEY);
  }
  const dataPath = params.get("data") || DEFAULT_JSON_PATH;
  const { apiKey, source } = resolveMapsApiKey(params, state.localConfigKey);
  document.getElementById("data-path-label").textContent = dataPath;

  try {
    await loadGoogleMaps(apiKey);
  } catch (error) {
    if (source === "storage") {
      window.localStorage.removeItem(API_KEY_STORAGE_KEY);
    }
    throw error;
  }
  initMap();
  wireFilters();
  await loadRecords(dataPath);
  await createMarkersFromRecords();
  applyFilters();
}

function resolveMapsApiKey(params, localConfigKey = "") {
  const fromLocalConfig = toText(localConfigKey);
  if (fromLocalConfig) {
    const classified = classifyApiKeyInput(fromLocalConfig);
    if (classified === "placeholder") {
      throw new Error(
        "Local config key is a placeholder. Update frontend/listings_map/config.local.json.",
      );
    }
    if (classified === "openai") {
      throw new Error(
        "Local config key looks like an OpenAI key. Use a Google Maps API key instead.",
      );
    }
    window.localStorage.setItem(API_KEY_STORAGE_KEY, fromLocalConfig);
    return { apiKey: fromLocalConfig, source: "local-config" };
  }

  const fromQuery = toText(params.get("mapsApiKey"));
  if (fromQuery) {
    const classified = classifyApiKeyInput(fromQuery);
    if (classified === "placeholder") {
      throw new Error(
        "mapsApiKey looks like a placeholder. Replace with your real Google Maps key.",
      );
    }
    if (classified === "openai") {
      throw new Error(
        "mapsApiKey looks like an OpenAI key. Use a Google Maps API key instead.",
      );
    }
    window.localStorage.setItem(API_KEY_STORAGE_KEY, fromQuery);
    return { apiKey: fromQuery, source: "query" };
  }

  const fromStorage = toText(window.localStorage.getItem(API_KEY_STORAGE_KEY));
  const classifiedStorage = classifyApiKeyInput(fromStorage);
  if (fromStorage && classifiedStorage === "ok") {
    return { apiKey: fromStorage, source: "storage" };
  }
  if (fromStorage) {
    window.localStorage.removeItem(API_KEY_STORAGE_KEY);
  }

  throw new Error(
    (
      "Google Maps API key missing. Add frontend/listings_map/config.local.json or ?mapsApiKey=YOUR_KEY. " +
      "If you had a bad cached key, use ?resetMapsKey=1 once."
    ),
  );
}

function loadGoogleMaps(apiKey) {
  if (window.google && window.google.maps) {
    return Promise.resolve();
  }

  return new Promise((resolve, reject) => {
    const timeoutId = window.setTimeout(() => {
      cleanup();
      reject(new Error("Google Maps script load timeout."));
    }, 15000);

    function cleanup() {
      window.clearTimeout(timeoutId);
      delete window.__initMapOnce;
      delete window.gm_authFailure;
    }

    window.__initMapOnce = () => {
      cleanup();
      resolve();
    };
    window.gm_authFailure = () => {
      cleanup();
      reject(
        new Error(
          (
            "Google Maps authentication failed. Verify API key, billing, " +
            "and HTTP referrer restrictions for this origin."
          ),
        ),
      );
    };

    const script = document.createElement("script");
    script.src =
      "https://maps.googleapis.com/maps/api/js?" +
      (
        `key=${encodeURIComponent(apiKey)}&callback=__initMapOnce` +
        "&v=weekly&loading=async"
      );
    script.async = true;
    script.defer = true;
    script.onerror = () => {
      cleanup();
      reject(new Error("Failed to load Google Maps script."));
    };
    document.head.appendChild(script);
  });
}

function initMap() {
  state.map = new google.maps.Map(document.getElementById("map"), {
    center: { lat: 35.0116, lng: 135.7681 },
    zoom: 12,
    mapTypeControl: false,
    streetViewControl: false,
    fullscreenControl: true,
  });
  state.infoWindow = new google.maps.InfoWindow();
  state.infoWindow.addListener("closeclick", () => {
    state.selectedMarker = null;
  });
  state.map.addListener("click", () => {
    if (Date.now() < state.ignoreMapClicksUntilMs) {
      return;
    }
    if (!state.selectedMarker) {
      return;
    }
    state.infoWindow.close();
    state.selectedMarker = null;
  });
}

async function loadRecords(path) {
  setStatus("Loading listings...");
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`Failed to load JSON: ${path} (HTTP ${response.status})`);
  }
  const payload = await response.json();
  if (!Array.isArray(payload)) {
    throw new Error("Expected consolidated_changes.json to be a JSON array.");
  }
  state.records = payload;
  setStatus(`Loaded ${payload.length} listings.`);
}

async function createMarkersFromRecords() {
  setStatus("Building markers from precomputed coordinates...");

  for (const record of state.records) {
    const lat = toNumber(record.lat);
    const lng = toNumber(record.lng);
    if (lat === null || lng === null) {
      continue;
    }
    const coords = { lat, lng };
    const marker = buildMarker(record, coords);
    state.markerEntries.push({ record, marker });
  }

  if (state.markerEntries.length === 0) {
    setStatus(
      (
        `No coordinates available in payload (0/${state.records.length}). ` +
        "Run backend geocoding: .venv/bin/python run.py --tags geocode"
      ),
    );
    return;
  }

  setStatus(
    `Map ready. Plotted ${state.markerEntries.length}/${state.records.length} listings.`,
  );
}

function buildMarker(record, coords) {
  const eligibility = eligibilityBucket(record.ryokan_licence_eligibility);
  const color = ELIGIBILITY_COLORS[eligibility] || ELIGIBILITY_COLORS.OTHER;

  const marker = new google.maps.Marker({
    map: state.map,
    position: coords,
    icon: {
      path: google.maps.SymbolPath.CIRCLE,
      scale: 7,
      fillColor: color,
      fillOpacity: 0.95,
      strokeColor: "#ffffff",
      strokeWeight: 1.2,
    },
  });

  marker.addListener("click", () => {
    // Prevent immediate close from a map click fired in the same interaction.
    state.ignoreMapClicksUntilMs = Date.now() + 250;
    state.selectedMarker = marker;
    state.infoWindow.setContent(buildPopupHtml(record));
    state.infoWindow.open({ anchor: marker, map: state.map, shouldFocus: false });
  });

  return marker;
}

function buildPopupHtml(record) {
  const propertyNumber = escapeHtml(toText(record.property_number));
  const propertyName = escapeHtml(toText(record.property_name));
  const priceJpy = formatPriceJpy(record.price_jpy);
  const url = toText(record.url);
  const safeUrl = escapeHtml(url);

  return `
    <div class="popup">
      <h3>${propertyName || "(No Name)"}</h3>
      <p><strong>property_number:</strong> ${propertyNumber || "-"}</p>
      <p><strong>price_jpy:</strong> ${priceJpy}</p>
      <p><strong>url:</strong> ${
        url ? `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer">${safeUrl}</a>` : "-"
      }</p>
    </div>
  `;
}


function wireFilters() {
  const ids = [
    "filter-property-number",
    "filter-property-name",
    "filter-price-min",
    "filter-price-max",
    "filter-url",
  ];

  for (const id of ids) {
    const element = document.getElementById(id);
    element.addEventListener("input", applyFilters);
  }

  const eligibilityCheckboxes = document.querySelectorAll(".filter-eligibility");
  for (const checkbox of eligibilityCheckboxes) {
    checkbox.addEventListener("change", applyFilters);
  }

  document.getElementById("clear-filters").addEventListener("click", () => {
    for (const id of ids) {
      document.getElementById(id).value = "";
    }
    for (const checkbox of eligibilityCheckboxes) {
      checkbox.checked = true;
    }
    applyFilters();
  });
}

function applyFilters() {
  const propertyNumberNeedle = toLower(document.getElementById("filter-property-number").value);
  const propertyNameNeedle = toLower(document.getElementById("filter-property-name").value);
  const urlNeedle = toLower(document.getElementById("filter-url").value);
  const minPriceRaw = document.getElementById("filter-price-min").value.trim();
  const maxPriceRaw = document.getElementById("filter-price-max").value.trim();

  const minPrice = minPriceRaw ? Number(minPriceRaw) : null;
  const maxPrice = maxPriceRaw ? Number(maxPriceRaw) : null;
  const selectedEligibility = getSelectedEligibility();

  let visible = 0;
  const bounds = new google.maps.LatLngBounds();

  for (const entry of state.markerEntries) {
    const { record, marker } = entry;
    const matches = matchesFilters({
      record,
      propertyNumberNeedle,
      propertyNameNeedle,
      urlNeedle,
      minPrice,
      maxPrice,
      selectedEligibility,
    });

    marker.setMap(matches ? state.map : null);
    if (matches) {
      visible += 1;
      bounds.extend(marker.getPosition());
    }
  }

  if (visible > 0) {
    state.map.fitBounds(bounds, 70);
  }
  updateVisibleCount(visible);
}

function matchesFilters({
  record,
  propertyNumberNeedle,
  propertyNameNeedle,
  urlNeedle,
  minPrice,
  maxPrice,
  selectedEligibility,
}) {
  const propertyNumber = toLower(toText(record.property_number));
  const propertyName = toLower(toText(record.property_name));
  const url = toLower(toText(record.url));
  const price = parsePrice(record.price_jpy);
  const eligibility = eligibilityBucket(record.ryokan_licence_eligibility);

  if (propertyNumberNeedle && !propertyNumber.includes(propertyNumberNeedle)) {
    return false;
  }
  if (propertyNameNeedle && !propertyName.includes(propertyNameNeedle)) {
    return false;
  }
  if (urlNeedle && !url.includes(urlNeedle)) {
    return false;
  }
  if (minPrice !== null && (price === null || price < minPrice)) {
    return false;
  }
  if (maxPrice !== null && (price === null || price > maxPrice)) {
    return false;
  }
  if (!selectedEligibility.has(eligibility)) {
    return false;
  }

  return true;
}

function parsePrice(value) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  const raw = toText(value).replace(/[^0-9]/g, "");
  if (!raw) {
    return null;
  }
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatPriceJpy(value) {
  const parsed = parsePrice(value);
  if (parsed === null) {
    return "-";
  }
  return `${parsed.toLocaleString("en-US")} JPY`;
}

function normalizeEligibility(value) {
  const text = toText(value).toUpperCase();
  return text || "OTHER";
}

function eligibilityBucket(value) {
  const normalized = normalizeEligibility(value);
  if (ELIGIBILITY_COLORS[normalized]) {
    return normalized;
  }
  return "OTHER";
}

function toText(value) {
  if (value === null || value === undefined) {
    return "";
  }
  if (Array.isArray(value)) {
    return value.map((item) => String(item).trim()).filter(Boolean).join(" ");
  }
  return String(value).trim();
}

function toLower(value) {
  return String(value || "").trim().toLowerCase();
}

function setStatus(text) {
  document.getElementById("status-text").textContent = text;
}

function updateVisibleCount(visibleCount) {
  document.getElementById("visible-count").textContent =
    `Visible markers: ${visibleCount} / ${state.markerEntries.length}`;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function classifyApiKeyInput(value) {
  const text = toText(value);
  if (!text) {
    return "missing";
  }

  const lower = text.toLowerCase();
  if (
    lower.includes("your_google_maps_api_key") ||
    lower.includes("your_key") ||
    lower === "insert_key_here"
  ) {
    return "placeholder";
  }

  if (lower.startsWith("sk-") || lower.startsWith("sk_proj") || lower.startsWith("sk-proj")) {
    return "openai";
  }

  return "ok";
}

function getSelectedEligibility() {
  const selected = new Set();
  const nodes = document.querySelectorAll(".filter-eligibility");
  for (const node of nodes) {
    if (node.checked) {
      selected.add(node.value);
    }
  }
  return selected;
}

function toNumber(value) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  const text = toText(value);
  if (!text) {
    return null;
  }
  const parsed = Number(text);
  return Number.isFinite(parsed) ? parsed : null;
}

async function loadLocalConfigKey() {
  try {
    const response = await fetch("./config.local.json", { cache: "no-store" });
    if (!response.ok) {
      return "";
    }
    const payload = await response.json();
    return toText(payload.mapsApiKey || payload.googleMapsApiKey);
  } catch {
    return "";
  }
}
