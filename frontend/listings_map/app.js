import { evaluateProperty } from "./eligibility_engine.js";

const NOTES_STORAGE_KEY = "jp_property_notes";
const SHORTLIST_STORAGE_KEY = "jp_property_shortlist";

const DEFAULT_JSON_PATHS = [
  "/output/consolidated/listings_map_payload.json",
  "./data/listings_map_payload.json",
  "/api/listings-map-payload",
];
const API_KEY_STORAGE_KEY = "jp_property_google_maps_api_key";

const ELIGIBILITY_COLORS = {
  "SIMPLE LODGING": "#157f1f",
  "MINPAKU": "#f4a261",
  "SPECIAL ZONE": "#4a90d9",
  "UNCERTAIN / MISSING": "#94a3b8",
};

const state = {
  map: null,
  infoWindow: null,
  records: [],
  markerEntries: [],
  localConfigKey: "",
  remoteConfigKey: "",
  activeDataPath: "",
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
  state.remoteConfigKey = await loadRemoteConfigKey();
  if (params.get("resetMapsKey") === "1") {
    window.localStorage.removeItem(API_KEY_STORAGE_KEY);
  }
  const dataFromQuery = toText(params.get("data"));
  const dataCandidates = dataFromQuery ? [dataFromQuery] : DEFAULT_JSON_PATHS;
  const { apiKey, source } = resolveMapsApiKey(
    params,
    state.localConfigKey,
    state.remoteConfigKey,
  );
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
  await loadRecords(dataCandidates);
  await createMarkersFromRecords();
  applyFilters();
}

function resolveMapsApiKey(params, localConfigKey = "", remoteConfigKey = "") {
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

  const fromRemoteConfig = toText(remoteConfigKey);
  if (fromRemoteConfig) {
    const classified = classifyApiKeyInput(fromRemoteConfig);
    if (classified === "ok") {
      window.localStorage.setItem(API_KEY_STORAGE_KEY, fromRemoteConfig);
      return { apiKey: fromRemoteConfig, source: "remote-config" };
    }
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
      "Google Maps API key missing. Use frontend/listings_map/config.local.json, " +
      "Vercel env (GOOGLE_MAPS_BROWSER_API_KEY), or ?mapsApiKey=YOUR_KEY. " +
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

async function loadRecords(paths) {
  setStatus("Loading listings...");

  const candidates = Array.isArray(paths) ? paths : [paths];
  const attempts = [];

  for (const path of candidates) {
    const candidate = toText(path);
    if (!candidate) {
      continue;
    }

    try {
      const response = await fetch(candidate, { cache: "no-store" });
      if (!response.ok) {
        attempts.push(`${candidate} (HTTP ${response.status})`);
        continue;
      }

      const payload = await response.json();
      if (!Array.isArray(payload)) {
        attempts.push(`${candidate} (payload is not JSON array)`);
        continue;
      }

      state.records = payload;
      state.activeDataPath = candidate;
      setStatus(`Loaded ${payload.length} listings.`);
      return;
    } catch (error) {
      attempts.push(`${candidate} (${error.message})`);
    }
  }

  const detail = attempts.length ? attempts.join("; ") : "No data paths provided.";
  throw new Error(`Failed to load listings JSON. Tried: ${detail}`);
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
  const eligibility = eligibilityBucket(record);
  const color = ELIGIBILITY_COLORS[eligibility] || ELIGIBILITY_COLORS["UNCERTAIN / MISSING"];

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
    google.maps.event.addListenerOnce(state.infoWindow, "domready", () => {
      wirePopupNote(toText(record.property_number));
    });
  });

  return marker;
}

const SEVERITY_COLOR = {
  pass: "#157f1f",
  warn: "#c07000",
  fail: "#c0392b",
  info: "#64748b",
};
const SEVERITY_BG = {
  pass: "#edf7ee",
  warn: "#fff8ed",
  fail: "#fdf2f2",
  info: "#f4f6f8",
};

function buildEligibilityHtml(assessment) {
  if (!assessment) return "";
  const { results, recommendation, recommendation_severity } = assessment;

  const dashIdx = recommendation.indexOf(" — ");
  const recHeadline = dashIdx >= 0 ? recommendation.slice(0, dashIdx) : recommendation;
  const recDetail = dashIdx >= 0 ? escapeHtml(recommendation.slice(dashIdx + 3)) : "";
  const recColor = SEVERITY_COLOR[recommendation_severity] || SEVERITY_COLOR.info;
  const recBg = SEVERITY_BG[recommendation_severity] || SEVERITY_BG.info;

  const checksHtml = results.map((r) => {
    const color = SEVERITY_COLOR[r.severity] || SEVERITY_COLOR.info;
    const bg = SEVERITY_BG[r.severity] || SEVERITY_BG.info;
    return (
      `<div class="elig-check">` +
      `<span class="elig-status" style="color:${color};background:${bg}">${escapeHtml(r.status)}</span>` +
      `<span class="elig-detail"><strong>${escapeHtml(r.check)}:</strong> ${escapeHtml(r.detail)}</span>` +
      `</div>`
    );
  }).join("");

  return (
    `<details class="popup-elig">` +
    `<summary>` +
    `<span class="elig-badge" style="color:${recColor};background:${recBg}">${escapeHtml(recHeadline)}</span>` +
    `<span class="elig-summary-label">Lodging Assessment</span>` +
    `<span class="elig-toggle">▼</span>` +
    `</summary>` +
    `<div class="elig-body">` +
    (recDetail ? `<p class="elig-rec-detail">${recDetail}</p>` : "") +
    checksHtml +
    `</div>` +
    `</details>`
  );
}

function buildPopupHtml(record) {
  const propertyNumber = escapeHtml(toText(record.property_number));
  const propertyName = escapeHtml(toText(record.property_name));
  const existingNote = escapeHtml(loadNote(toText(record.property_number)));
  const isShortlisted = loadShortlist().has(toText(record.property_number));
  const checkedAttr = isShortlisted ? " checked" : "";
  const assessment = evaluateProperty(record);
  const eligibilityHtml = buildEligibilityHtml(assessment);
  const priceJpy = formatPriceJpy(record.price_jpy);
  const pricePerM2 = parsePrice(record.price_per_m2);
  const benchmarkPerM2 = parsePrice(record.price_per_m2_benchmark);
  const pricePerM2Text = formatPricePerM2(record.price_per_m2);
  const benchmarkPerM2Text = formatPricePerM2(record.price_per_m2_benchmark);
  const deltaPct = computeDeltaPercent(pricePerM2, benchmarkPerM2);
  const deltaText = deltaPct === null ? "" : `${deltaPct > 0 ? "+" : ""}${deltaPct.toFixed(1)}%`;
  const deltaColor = deltaPct === null ? "#64748b" : (deltaPct >= 0 ? "#157f1f" : "#c0392b");
  const url = toText(record.url);
  const safeUrl = escapeHtml(url);
  const eligibility = assessment ? assessment.license_type : "UNCERTAIN / MISSING";
  const eligibilityColor = ELIGIBILITY_COLORS[eligibility] || ELIGIBILITY_COLORS["UNCERTAIN / MISSING"];
  const safeEligibility = escapeHtml(eligibility);
  const safeAddress = escapeHtml(toText(record.address));

  return `
    <div class="popup">
      <h3>${propertyName || "(No Name)"}</h3>
      <p><strong>property_number:</strong> ${propertyNumber || "-"}</p>
      <p><strong>eligibility:</strong> <span style="color:${eligibilityColor};font-weight:bold">${safeEligibility}</span></p>
      <p><strong>price_jpy:</strong> ${priceJpy}</p>
      <p><strong>price_per_m2:</strong> ${pricePerM2Text}${
        deltaText ? ` <small style="color:${deltaColor};font-weight:600">(${deltaText})</small>` : ""
      }</p>
      <p><strong>price_per_m2_benchmark:</strong> ${benchmarkPerM2Text}</p>
      ${safeAddress ? `<p><strong>address:</strong> ${safeAddress}</p>` : ""}
      <p><strong>url:</strong> ${
        url ? `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer">${safeUrl}</a>` : "-"
      }</p>
      ${eligibilityHtml}
      <label class="popup-shortlist">
        <input type="checkbox" id="popup-shortlist-cb"${checkedAttr} />
        <span>Shortlisted</span>
      </label>
      <div class="popup-note">
        <label for="popup-note-textarea"><strong>Notes</strong></label>
        <textarea
          id="popup-note-textarea"
          maxlength="200"
          placeholder="Add a note..."
        >${existingNote}</textarea>
        <button id="popup-note-save" type="button">Save note</button>
      </div>
    </div>
  `;
}


function loadShortlist() {
  try {
    return new Set(JSON.parse(localStorage.getItem(SHORTLIST_STORAGE_KEY) || "[]"));
  } catch {
    return new Set();
  }
}

function setShortlisted(propertyNumber, checked) {
  const list = loadShortlist();
  if (checked) {
    list.add(propertyNumber);
  } else {
    list.delete(propertyNumber);
  }
  try {
    localStorage.setItem(SHORTLIST_STORAGE_KEY, JSON.stringify([...list]));
  } catch {
    // localStorage unavailable — silently ignore
  }
}

function loadNote(propertyNumber) {
  try {
    const notes = JSON.parse(localStorage.getItem(NOTES_STORAGE_KEY) || "{}");
    return toText(notes[propertyNumber]);
  } catch {
    return "";
  }
}

function saveNote(propertyNumber, text) {
  try {
    const notes = JSON.parse(localStorage.getItem(NOTES_STORAGE_KEY) || "{}");
    if (text) {
      notes[propertyNumber] = text;
    } else {
      delete notes[propertyNumber];
    }
    localStorage.setItem(NOTES_STORAGE_KEY, JSON.stringify(notes));
  } catch {
    // localStorage unavailable — silently ignore
  }
}

function wirePopupNote(propertyNumber) {
  const btn = document.getElementById("popup-note-save");
  const textarea = document.getElementById("popup-note-textarea");
  const shortlistCb = document.getElementById("popup-shortlist-cb");

  if (shortlistCb) {
    shortlistCb.addEventListener("change", () => {
      setShortlisted(propertyNumber, shortlistCb.checked);
      applyFilters();
    });
  }

  if (!btn || !textarea) {
    return;
  }
  btn.addEventListener("click", () => {
    const note = textarea.value.slice(0, 200);
    saveNote(propertyNumber, note);
    btn.textContent = "Saved!";
    btn.disabled = true;
    setTimeout(() => {
      btn.textContent = "Save note";
      btn.disabled = false;
    }, 1500);
  });
}

function debounce(fn, delayMs) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delayMs);
  };
}

function wireFilters() {
  const ids = [
    "filter-property-number",
    "filter-property-name",
    "filter-price-min",
    "filter-price-max",
    "filter-url",
    "filter-reno-status",
  ];

  const debouncedApply = debounce(applyFilters, 200);
  for (const id of ids) {
    const element = document.getElementById(id);
    element.addEventListener("input", debouncedApply);
  }

  const eligibilityCheckboxes = document.querySelectorAll(".filter-eligibility");
  for (const checkbox of eligibilityCheckboxes) {
    checkbox.addEventListener("change", applyFilters);
  }

  document.getElementById("filter-shortlist").addEventListener("change", applyFilters);

  document.getElementById("clear-filters").addEventListener("click", () => {
    for (const id of ids) {
      document.getElementById(id).value = "";
    }
    for (const checkbox of eligibilityCheckboxes) {
      checkbox.checked = true;
    }
    document.getElementById("filter-shortlist").checked = false;
    applyFilters();
  });
}

function applyFilters() {
  const propertyNumberNeedle = toLower(document.getElementById("filter-property-number").value);
  const propertyNameNeedle = toLower(document.getElementById("filter-property-name").value);
  const urlNeedle = toLower(document.getElementById("filter-url").value);
  const renoStatusNeedle = toLower(document.getElementById("filter-reno-status").value);
  const minPriceRaw = document.getElementById("filter-price-min").value.trim();
  const maxPriceRaw = document.getElementById("filter-price-max").value.trim();
  const shortlistOnly = document.getElementById("filter-shortlist").checked;

  const minPrice = minPriceRaw ? Number(minPriceRaw) : null;
  const maxPrice = maxPriceRaw ? Number(maxPriceRaw) : null;
  const selectedEligibility = getSelectedEligibility();
  const shortlist = shortlistOnly ? loadShortlist() : null;

  let visible = 0;
  let selectedStillVisible = false;
  const bounds = new google.maps.LatLngBounds();

  for (const entry of state.markerEntries) {
    const { record, marker } = entry;
    const matches = matchesFilters({
      record,
      propertyNumberNeedle,
      propertyNameNeedle,
      urlNeedle,
      renoStatusNeedle,
      minPrice,
      maxPrice,
      selectedEligibility,
      shortlist,
    });

    marker.setMap(matches ? state.map : null);
    if (matches) {
      visible += 1;
      bounds.extend(marker.getPosition());
      if (state.selectedMarker && marker === state.selectedMarker) {
        selectedStillVisible = true;
      }
    }
  }

  if (state.selectedMarker && !selectedStillVisible) {
    state.infoWindow.close();
    state.selectedMarker = null;
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
  renoStatusNeedle,
  minPrice,
  maxPrice,
  selectedEligibility,
  shortlist,
}) {
  const propertyNumber = toLower(toText(record.property_number));
  const propertyName = toLower(toText(record.property_name));
  const url = toLower(toText(record.url));
  const renoStatus = toLower(toText(record.reno_status));
  const price = parsePrice(record.price_jpy);
  const eligibility = eligibilityBucket(record);

  if (propertyNumberNeedle && !propertyNumber.includes(propertyNumberNeedle)) {
    return false;
  }
  if (propertyNameNeedle && !propertyName.includes(propertyNameNeedle)) {
    return false;
  }
  if (urlNeedle && !url.includes(urlNeedle)) {
    return false;
  }
  if (renoStatusNeedle && !renoStatus.includes(renoStatusNeedle)) {
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
  if (shortlist !== null && !shortlist.has(toText(record.property_number))) {
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

function formatPricePerM2(value) {
  const parsed = parsePrice(value);
  if (parsed === null) {
    return "-";
  }
  return `${parsed.toLocaleString("en-US")} JPY/m²`;
}

function computeDeltaPercent(value, benchmark) {
  if (value === null || benchmark === null || benchmark <= 0) {
    return null;
  }
  return ((value - benchmark) / benchmark) * 100;
}

function eligibilityBucket(record) {
  const assessment = evaluateProperty(record);
  if (!assessment) return "UNCERTAIN / MISSING";
  return assessment.license_type;
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

async function loadRemoteConfigKey() {
  try {
    const response = await fetch("/api/maps-config", { cache: "no-store" });
    if (!response.ok) {
      return "";
    }
    const payload = await response.json();
    return toText(payload.mapsApiKey || payload.googleMapsApiKey);
  } catch {
    return "";
  }
}
