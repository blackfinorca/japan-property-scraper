/**
 * Kyoto Lodging License Eligibility Engine
 * Pure deterministic rule engine — no API calls, no side effects.
 * All thresholds are in CFG so regulations can be updated in one place.
 */

// ─── CONFIG ───────────────────────────────────────────────────────────────────

const CFG = {
  FLOOR_AREA_MIN_TOTAL_SQM: 33,
  FLOOR_AREA_MIN_PER_PERSON_SQM: 3.3,
  STREET_WIDTH_MIN_M: 2.0,
  BUILDING_USE_CHANGE_THRESHOLD_SQM: 100,
  LICENSE_APPROVAL_BUSINESS_DAYS: 30,
};

// ─── REFERENCE DATA ───────────────────────────────────────────────────────────

export const LICENSE_TYPES = [
  {
    id: "simple_lodging",
    name: "Simple Lodging (簡易宿所)",
    name_jp: "簡易宿所",
    law: "Hotel Business Act (旅館業法)",
    max_days_per_year: 365,
    min_stay_nights: 1,
    approval_authority: "Prefectural Governor",
    requires_zoning_check: true,
    allowed_zones: [
      "Category I Residential",
      "Category II Residential",
      "Quasi-Residential",
      "Neighborhood Commercial",
      "Commercial",
      "Quasi-Industrial",
    ],
    front_desk_required: false,
    kyoto_emergency_response_10min: true,
    min_floor_area_sqm: 33,
    min_floor_area_per_person_sqm: 3.3,
    min_street_width_m: 2.0,
    building_use_change_threshold_sqm: 100,
    fire_safety_required: true,
    neighbor_notification_required: true,
    school_consultation_radius_m: 110,
    license_auto_transferable: false,
    approval_time_business_days: 30,
    housing_loan_available: false,
    kyoto_available: true,
  },
  {
    id: "minpaku",
    name: "Private Lodging / Minpaku (民泊)",
    name_jp: "民泊",
    law: "Private Lodging Business Act (住宅宿泊事業法, 2018)",
    max_days_per_year: 180,
    max_days_per_year_kyoto_residential: 60,
    kyoto_operating_window: "Jan 15 – Mar 16 (residential zones)",
    min_stay_nights: 1,
    approval_authority: "Local government notification",
    requires_zoning_check: false,
    front_desk_required: false,
    min_floor_area_per_person_sqm: 3.3,
    owner_absent_requires_management_company: true,
    fire_safety_accommodation_under_50sqm: "general_housing_rules",
    fire_safety_accommodation_over_50sqm: "commercial_lodging_rules",
    kyoto_available: true,
    kyoto_viable_for_investment: false,
    hachise_recommendation: "NOT recommended for Kyoto investment",
  },
  {
    id: "special_zone",
    name: "Special Zone Minpaku (特区民泊)",
    name_jp: "特区民泊",
    law: "National Strategic Special Zones Act",
    max_days_per_year: 365,
    min_stay_nights: 2,
    min_floor_area_sqm: 25,
    designated_cities: ["Tokyo (select wards)", "Osaka", "Fukuoka", "Sendai", "select others"],
    kyoto_available: false,
    kyoto_designation_status: "NOT designated as of 2025",
  },
];

export const TAX_REFERENCE = [
  {
    tax: "Income Tax",
    rate: "5–45% progressive + 2.1% Reconstruction Surtax",
    notes: "On rental income",
  },
  {
    tax: "Accommodation Tax (Kyoto)",
    rate: "¥200–¥1,000 per guest/night",
    notes: "Host collects & remits. Varies by room rate.",
  },
  {
    tax: "Consumption Tax",
    rate: "10%",
    notes: "Exempt if annual sales < ¥10M",
  },
  {
    tax: "Property Tax",
    rate: "Fixed asset tax + city planning tax",
    notes: "Annual, on ownership",
  },
];

// ─── ZONE CLASSIFICATION ──────────────────────────────────────────────────────
// 13 Japanese land use zones. Only 6 allow Simple Lodging.
// Matching is fuzzy/normalized — handles English/Japanese variants.

function classifyZone(rawZone) {
  if (!rawZone) return null;
  const z = String(rawZone)
    .toLowerCase()
    .replace(/\b(district|zone|地区|地域)\b/g, "")
    .replace(/\s+/g, " ")
    .trim();

  // ── BLOCKED — check most specific patterns first ──────────────────────────

  // Exclusively Low-Rise Residential (Cat I & II)
  if (
    z.includes("exclusively low-rise") ||
    z.includes("low-rise exclusive") ||
    z.includes("第1種低層") ||
    z.includes("第2種低層") ||
    /category\s+[i1]\s+exclusively/.test(z) ||
    /category\s+[ii2]+\s+exclusively/.test(z) ||
    z.includes("first-class low-rise") ||
    z.includes("1st class low-rise") ||
    z.includes("2nd class low-rise")
  ) {
    return { allowed: false, name: "Exclusively Low-Rise Residential" };
  }

  // Exclusively Mid/High-Rise Residential (Cat I & II)
  if (
    z.includes("exclusively mid") ||
    z.includes("exclusively high") ||
    z.includes("mid-high exclusive") ||
    z.includes("第1種中高層") ||
    z.includes("第2種中高層")
  ) {
    return { allowed: false, name: "Exclusively Mid/High-Rise Residential" };
  }

  // Agricultural Residential
  if (z.includes("agricultural")) {
    return { allowed: false, name: "Agricultural Residential" };
  }

  // Exclusively Industrial
  if (
    z.includes("exclusively industrial") ||
    z.includes("工業専用") ||
    z.includes("専用工業")
  ) {
    return { allowed: false, name: "Exclusively Industrial" };
  }

  // ── ALLOWED — check quasi- before simple keywords to avoid false matches ──

  if (z.includes("quasi-industrial") || z.includes("quasi industrial") || z.includes("準工業")) {
    return { allowed: true, name: "Quasi-Industrial" };
  }

  if (z.includes("quasi-residential") || z.includes("quasi residential") || z.includes("準住居")) {
    return { allowed: true, name: "Quasi-Residential" };
  }

  if (z.includes("neighborhood commercial") || z.includes("近隣商業")) {
    return { allowed: true, name: "Neighborhood Commercial" };
  }

  if (z.includes("commercial") || z.includes("商業")) {
    return { allowed: true, name: "Commercial" };
  }

  // Category I/II Residential (allowed, distinct from exclusively residential above)
  if (
    /category\s+[i1]\s+residential/.test(z) ||
    /category\s+[ii2]+\s+residential/.test(z) ||
    z.includes("第1種住居") ||
    z.includes("第2種住居")
  ) {
    return { allowed: true, name: "Category I/II Residential" };
  }

  // Generic "residential" without "exclusively" or "agricultural" — treat as allowed
  if (z.includes("residential") && !z.includes("exclusive") && !z.includes("agricultural")) {
    return { allowed: true, name: "Residential" };
  }

  // Industrial (after quasi-industrial already handled above)
  if (z.includes("industrial") || z.includes("工業")) {
    return { allowed: false, name: "Industrial" };
  }

  return null; // UNKNOWN
}

// ─── REMARKS INFERENCE ────────────────────────────────────────────────────────

function inferFromRemarks(prop) {
  const remarksList = Array.isArray(prop.remarks)
    ? prop.remarks
    : typeof prop.remarks === "string"
    ? [prop.remarks]
    : [];
  const combined = remarksList.join(" ").toLowerCase();

  return {
    hasSimpleLodging:
      prop.has_simple_lodging_license === true ||
      combined.includes("simple lodging") ||
      combined.includes("簡易宿所"),
    hasMachiyaKarte:
      prop.has_kyo_machiya_karte === true ||
      combined.includes("kyo-machiya karte") ||
      combined.includes("kyo machiya karte") ||
      combined.includes("京町家カルテ"),
    hasBusinessSuccession:
      combined.includes("business succession") ||
      combined.includes("succession") ||
      combined.includes("reapply") ||
      combined.includes("re-apply"),
  };
}

// ─── FLOOR AREA PARSING ───────────────────────────────────────────────────────

function parseFloorArea(prop) {
  if (typeof prop.floor_area_sqm === "number" && isFinite(prop.floor_area_sqm)) {
    return prop.floor_area_sqm;
  }
  const raw = String(prop.floor_area || prop.floor_area_sqm || "");
  if (!raw) return null;

  const totalMatch = raw.match(/total[^0-9]*([0-9]+(?:\.[0-9]+)?)/i);
  if (totalMatch) return parseFloat(totalMatch[1]);

  const sqmMatches = [...raw.matchAll(/([0-9]+(?:\.[0-9]+)?)\s*sqm/gi)].map(m => parseFloat(m[1]));
  if (sqmMatches.length === 1) return sqmMatches[0];
  if (sqmMatches.length > 1) return sqmMatches.reduce((a, b) => a + b, 0);

  const bare = parseFloat(raw.replace(/[^0-9.]/g, ""));
  return isFinite(bare) && bare > 0 ? bare : null;
}

// ─── THE 10 CHECKS ────────────────────────────────────────────────────────────

function checkZoning(prop) {
  const raw = String(prop.land_use_district || "").trim();
  if (!raw) {
    return {
      check: "Zoning (Simple Lodging)",
      status: "UNKNOWN",
      severity: "warn",
      detail: "Land use district is missing — zoning eligibility cannot be determined.",
    };
  }
  const cls = classifyZone(raw);
  if (!cls) {
    return {
      check: "Zoning (Simple Lodging)",
      status: "UNKNOWN",
      severity: "warn",
      detail: `Zone "${raw}" could not be classified. Manual verification required.`,
    };
  }
  if (cls.allowed) {
    return {
      check: "Zoning (Simple Lodging)",
      status: "PASS",
      severity: "pass",
      detail: `${cls.name} zone — Simple Lodging (簡易宿所) is permitted here.`,
    };
  }
  return {
    check: "Zoning (Simple Lodging)",
    status: "FAIL",
    severity: "fail",
    detail: `${cls.name} zone — Simple Lodging is NOT permitted. This is the primary blocker.`,
  };
}

function checkFloorArea(floorArea) {
  if (floorArea === null) {
    return {
      check: "Floor Area",
      status: "UNKNOWN",
      severity: "warn",
      detail: "Floor area could not be determined. Verify ≥33 sqm for standard Simple Lodging.",
    };
  }
  if (floorArea >= CFG.FLOOR_AREA_MIN_TOTAL_SQM) {
    return {
      check: "Floor Area",
      status: "PASS",
      severity: "pass",
      detail: `${floorArea.toFixed(2)} sqm meets the 33 sqm standard minimum.`,
    };
  }
  if (floorArea >= CFG.FLOOR_AREA_MIN_PER_PERSON_SQM) {
    const maxGuests = Math.floor(floorArea / CFG.FLOOR_AREA_MIN_PER_PERSON_SQM);
    return {
      check: "Floor Area",
      status: "WARN",
      severity: "warn",
      detail: `${floorArea.toFixed(2)} sqm is below 33 sqm standard. Under the 3.3 sqm/guest rule, maximum capacity is ${maxGuests} guests.`,
    };
  }
  return {
    check: "Floor Area",
    status: "FAIL",
    severity: "fail",
    detail: `${floorArea.toFixed(2)} sqm is below the 3.3 sqm/person absolute minimum. Does not meet any Simple Lodging floor area threshold.`,
  };
}

function checkBuildingUseChange(floorArea) {
  if (floorArea === null) {
    return {
      check: "Building Use Change",
      status: "UNKNOWN",
      severity: "warn",
      detail: "Cannot determine requirement — floor area unknown.",
    };
  }
  if (floorArea > CFG.BUILDING_USE_CHANGE_THRESHOLD_SQM) {
    return {
      check: "Building Use Change",
      status: "REQUIRED",
      severity: "warn",
      detail: `${floorArea.toFixed(2)} sqm exceeds 100 sqm. A Purpose of Usage change application to the registry is required before licensing.`,
    };
  }
  return {
    check: "Building Use Change",
    status: "NOT REQUIRED",
    severity: "pass",
    detail: `${floorArea.toFixed(2)} sqm is ≤100 sqm. No use-change registration required. Consulting city hall is still recommended.`,
  };
}

function checkStreetWidth(prop) {
  const widths = Array.isArray(prop.adjoining_street_widths)
    ? prop.adjoining_street_widths.filter(w => typeof w === "number" && isFinite(w))
    : [];
  if (widths.length === 0) {
    return {
      check: "Street Width (Access)",
      status: "UNKNOWN",
      severity: "warn",
      detail: "Adjoining street widths not available. Verify ≥2m access width with the local Fire Department before purchase.",
    };
  }
  const minWidth = Math.min(...widths);
  if (minWidth >= CFG.STREET_WIDTH_MIN_M) {
    return {
      check: "Street Width (Access)",
      status: "PASS",
      severity: "pass",
      detail: `Minimum adjoining street width is ${minWidth}m (≥2m required). Evacuation access compliant.`,
    };
  }
  return {
    check: "Street Width (Access)",
    status: "RISK",
    severity: "fail",
    detail: `Narrowest adjoining street is ${minWidth}m — below the 2m minimum. This may BLOCK lodging operation entirely. Verify with Fire Department before purchase.`,
  };
}

function checkExistingLicense(inferred) {
  if (inferred.hasSimpleLodging) {
    return {
      check: "Existing Simple Lodging License",
      status: "EXISTS",
      severity: "pass",
      detail: `License detected. Note: it is NOT auto-transferable on sale. New owner must apply for business succession (~${CFG.LICENSE_APPROVAL_BUSINESS_DAYS} business days) before operating.`,
    };
  }
  return {
    check: "Existing Simple Lodging License",
    status: "NONE",
    severity: "warn",
    detail: `No existing license. New application required (~${CFG.LICENSE_APPROVAL_BUSINESS_DAYS} business days). Engage an administrative scrivener (行政書士) early.`,
  };
}

function checkMachiyaKarte(inferred) {
  if (inferred.hasMachiyaKarte) {
    return {
      check: "Kyo-machiya Karte",
      status: "OBTAINED",
      severity: "pass",
      detail: "Kyo-machiya Karte confirmed. Cultural heritage designation supports lenient requirements and adds significant marketability.",
    };
  }
  return {
    check: "Kyo-machiya Karte",
    status: "NOT OBTAINED",
    severity: "info",
    detail: "No Kyo-machiya Karte. Standard rules apply. Applying for it is recommended — it increases appeal for lodging use.",
  };
}

function checkFireSafety(prop) {
  if (prop.fire_safety_installed === true) {
    return {
      check: "Fire Safety Equipment",
      status: "PASS",
      severity: "pass",
      detail: "Fire safety equipment reported as installed. Verify emergency lighting, fire alarms, and extinguishers meet Simple Lodging standards.",
    };
  }
  return {
    check: "Fire Safety Equipment",
    status: "UNKNOWN",
    severity: "warn",
    detail: "Fire safety status unknown. Simple Lodging requires emergency lighting, fire alarms, and extinguishers at minimum. Consult Fire Department.",
  };
}

function checkRenoStatus(prop) {
  const status = String(prop.reno_status || "").toLowerCase().trim();
  if (status === "renovated") {
    return {
      check: "Renovation Status",
      status: "RENOVATED",
      severity: "pass",
      detail: "Property is renovated — likely meets or is close to meeting lodging facility standards.",
    };
  }
  if (status === "partial") {
    return {
      check: "Renovation Status",
      status: "PARTIAL",
      severity: "warn",
      detail: "Partial renovation. Additional work may be required to meet Simple Lodging facility standards.",
    };
  }
  if (status === "unrenovated") {
    return {
      check: "Renovation Status",
      status: "NOT RENOVATED",
      severity: "warn",
      detail: "Unrenovated. Renovation will likely be required to meet Simple Lodging facility standards.",
    };
  }
  return {
    check: "Renovation Status",
    status: "UNKNOWN",
    severity: "warn",
    detail: "Renovation status not available. Assess scope of works before committing to lodging use.",
  };
}

function checkMinpakuViability() {
  return {
    check: "Minpaku Viability (Kyoto)",
    status: "NOT RECOMMENDED",
    severity: "fail",
    detail: "Kyoto residential zones limit minpaku to ~60 days/year (Jan 15–Mar 16 only). Not viable as a primary lodging investment strategy.",
  };
}

function checkSpecialZone() {
  return {
    check: "Special Zone Minpaku",
    status: "NOT AVAILABLE",
    severity: "fail",
    detail: "Kyoto is NOT designated as a National Strategic Special Zone for minpaku. This pathway is unavailable.",
  };
}

// ─── RECOMMENDATION ───────────────────────────────────────────────────────────

function computeRecommendation(flags) {
  if (flags.zoning_ok && flags.has_license) {
    return {
      recommendation:
        "STRONG CANDIDATE — Simple Lodging license already exists, zoning is compatible. " +
        "Priority action: apply for business succession to transfer license. " +
        "Verify street width compliance with Fire Department before purchase.",
      recommendation_severity: "pass",
    };
  }
  if (flags.zoning_ok) {
    return {
      recommendation:
        "ELIGIBLE — Zoning allows Simple Lodging. New license application required. " +
        "Budget ~30 business days for approval. Consult administrative scrivener before purchase.",
      recommendation_severity: "warn",
    };
  }
  return {
    recommendation:
      "NOT ELIGIBLE — Zoning does not allow Simple Lodging operation. " +
      "Consider alternative uses (long-term rental, personal residence).",
    recommendation_severity: "fail",
  };
}

// ─── MAIN EXPORT ──────────────────────────────────────────────────────────────

/**
 * Evaluate a property against Kyoto lodging license eligibility rules.
 * @param {object} prop - Property record. Missing fields are handled gracefully.
 * @returns {object|null} EligibilityResult, or null if input is invalid.
 */
export function evaluateProperty(prop) {
  if (!prop || typeof prop !== "object") return null;

  const inferred = inferFromRemarks(prop);
  const floorArea = parseFloorArea(prop);

  const results = [
    checkZoning(prop),
    checkFloorArea(floorArea),
    checkBuildingUseChange(floorArea),
    checkStreetWidth(prop),
    checkExistingLicense(inferred),
    checkMachiyaKarte(inferred),
    checkFireSafety(prop),
    checkRenoStatus(prop),
    checkMinpakuViability(),
    checkSpecialZone(),
  ];

  const flags = {
    zoning_ok: results[0].status === "PASS",
    floor_area_ok: results[1].status === "PASS",
    street_width_ok: results[3].status === "PASS",
    has_license: inferred.hasSimpleLodging,
    has_machiya_karte: inferred.hasMachiyaKarte,
    fire_safety_ok: results[6].status === "PASS",
    is_renovated: String(prop.reno_status || "").toLowerCase() === "renovated",
    license_transferable: false, // licenses never auto-transfer in Japan
  };

  const { recommendation, recommendation_severity } = computeRecommendation(flags);

  // Derive which license type is achievable for this property.
  // Special Zone is never available in Kyoto → no property will land there.
  let license_type;
  if (results[0].status === "PASS") {
    license_type = "SIMPLE LODGING";
  } else if (results[0].status === "FAIL") {
    license_type = "MINPAKU";
  } else {
    license_type = "UNCERTAIN / MISSING";
  }

  return { results, flags, recommendation, recommendation_severity, license_type };
}
