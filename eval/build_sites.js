/**
 * build_sites.js — Generates two self-contained Junction showcase HTML sites in /workspace/wSite/original/:
 *   1. wSite/original/index.html            — Public / License-Clean Edition (ONLY own external USB camera photos)
 *   2. wSite/original/local_uncensored.html — Local Demo Edition (includes curated scraped & benchmark edge cases)
 */

const fs = require("fs");
const path = require("path");
const sharp = require("sharp");

const ROOT = path.join(__dirname, "..");
const OUT_DIR = path.join(ROOT, "wSite", "original");

async function toDataUri(relPath, maxDim = 840, quality = 78) {
  const fullPath = path.join(ROOT, relPath);
  const buf = await sharp(fullPath)
    .resize({ width: maxDim, height: maxDim, fit: "inside", withoutEnlargement: true })
    .webp({ quality })
    .toBuffer();
  return `data:image/webp;base64,${buf.toString("base64")}`;
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function loadAssets(includeScraped) {
  // Own external USB camera photos simulating a printer-mounted webcam (100% license-clean)
  const ownUsb = {
    golden_whisp_orig: await toDataUri("dataset/stringing/golden_whispV3.jpg"),
    golden_whisp_deg: await toDataUri("dataset_usb_degraded/stringing/golden_whispV3.jpg"),
    golden_support_orig: await toDataUri("dataset/other_defect/golden_support_piece.jpg"),
    golden_support_deg: await toDataUri("dataset_usb_degraded/other_defect/golden_support_piece.jpg"),
    gray_problem_orig: await toDataUri("dataset/other_defect/gray_problem.jpg"),
    gray_problem_deg: await toDataUri("dataset_usb_degraded/other_defect/gray_problem.jpg"),
    green_slant2_orig: await toDataUri("dataset/other_defect/green_slant2.jpg"),
    green_slant2_deg: await toDataUri("dataset_usb_degraded/other_defect/green_slant2.jpg"),
    green_slant3_orig: await toDataUri("dataset/other_defect/green_slant3.jpg"),
    green_slant3_deg: await toDataUri("dataset_usb_degraded/other_defect/green_slant3.jpg"),
  };

  if (!includeScraped) return { ownUsb, extra: {} };

  const extra = {
    falcon: await toDataUri("dataset/context_dev/data/images/3dprinting_1ihsom2_0.jpg", 900, 80),
    zoro_orig: await toDataUri("dataset/clean/Clean_zoro.webp"),
    zoro_deg: await toDataUri("dataset_usb_degraded/clean/Clean_zoro.jpg"),
    str001_orig: await toDataUri("dataset/stringing/stringing001.webp"),
    str001_deg: await toDataUri("dataset_usb_degraded/stringing/stringing001.jpg"),
    od004_orig: await toDataUri("dataset/other_defect/other_defect004.jpeg"),
    od004_deg: await toDataUri("dataset_usb_degraded/other_defect/other_defect004.jpg"),
    str006_orig: await toDataUri("dataset/stringing/stringing006.webp"),
    str006_deg: await toDataUri("dataset_usb_degraded/stringing/stringing006.jpg"),
    benchies7: await toDataUri("dataset/context_dev/data/images/fixmyprint_1mveel1_0.jpg", 1100, 82),
    octopus: await toDataUri("dataset/context_dev/data/images/fixmyprint_pmtbf8_0.png", 840, 78),
  };

  return { ownUsb, extra };
}

function buildCaseCards({ ownUsb, extra }, isUncensored) {
  const usbCards = [
    {
      id: "golden_whispV3",
      group: "usb",
      badge: "External USB Cam Sim · Stringing Tower",
      title: "Yellow Retraction Tower — External USB Webcam Capture",
      truth: "stringing (reclassified from subtle wisp test)",
      modeType: "degrade",
      imgA: ownUsb.golden_whisp_orig,
      imgB: ownUsb.golden_whisp_deg,
      labelA: "Raw 1080p UVC Frame",
      labelB: "640p + Extra CMOS Noise",
      takeaway:
        "Captured with our separate USB webcam aimed at the bed to simulate a printer camera: both open Gemma 4 models detected the defect immediately, while Gemini Flash passed the raw frame until 640p recompression increased inter-tower oozing contrast.",
      verdictsA: [
        { model: "gemini-3.8-flash", ok: false, pred: "clean", quote: "No observable stringing between sections, intact geometry, and minimal surface defects." },
        { model: "gemma-4-31b-it", ok: true, pred: "defect", quote: "Significant surface irregularities, blobs, and uneven wall textures." },
        { model: "gemma-4-26b-a4b-it", ok: true, pred: "defect", quote: "The top edge and surface of the print are uneven and poorly formed." },
      ],
      verdictsB: [
        { model: "gemini-3.8-flash", ok: true, pred: "stringing", quote: "Dense filament stringing and oozing visibly span across the gap between the two vertical towers." },
        { model: "gemma-4-31b-it", ok: false, pred: "other_defect", quote: "The vertical walls exhibit significant surface irregularities and ringing." },
        { model: "gemma-4-26b-a4b-it", ok: true, pred: "stringing", quote: "Fine filament strands are visible bridging gaps and sticking out from the edges of the part." },
      ],
    },
    {
      id: "golden_support_piece",
      group: "usb",
      badge: "External USB Cam Sim · Perimeter Failure",
      title: "Broken Right-Column Perimeter vs. 4B Edge Sensitivity",
      truth: "other_defect (under-extruded / broken vertical wall)",
      modeType: "degrade",
      imgA: ownUsb.golden_support_orig,
      imgB: ownUsb.golden_support_deg,
      labelA: "Raw 1080p UVC Frame",
      labelB: "640p + Extra CMOS Noise",
      takeaway:
        "Illustrates the exact boundary between 31B/Cloud and 4B-active edge models: Gemini Flash and Gemma 31B spotted the ladder-like broken right column on the raw frame, whereas Gemma A4B passed it as clean—and once degraded to 640p, Flash mistook the ladder gaps for inter-tower stringing.",
      verdictsA: [
        { model: "gemini-3.8-flash", ok: true, pred: "other_defect", quote: "Significant under-extrusion or perimeter failure on the right vertical column, leading to gaps and a ladder-like broken wall." },
        { model: "gemma-4-31b-it", ok: true, pred: "other_defect", quote: "Visible blobbing and rough surface texture on the right side of the part." },
        { model: "gemma-4-26b-a4b-it", ok: false, pred: "clean", quote: "The part shows no obvious stringing, blobs, or layer shifts, appearing to be a successful print." },
      ],
      verdictsB: [
        { model: "gemini-3.8-flash", ok: false, pred: "stringing", quote: "Severe stringing and oozing between the two vertical test towers, with numerous strands bridging the open gap." },
        { model: "gemma-4-31b-it", ok: false, pred: "clean", quote: "The part shows smooth surfaces and clean edges with no visible stringing or other defects." },
        { model: "gemma-4-26b-a4b-it", ok: false, pred: "clean", quote: "No visible signs of stringing, layer shifts, or other major print defects." },
      ],
    },
    {
      id: "green_slant2",
      group: "usb",
      badge: "External USB Cam Sim · Overhang Curling",
      title: "Curved Overhang Roughness Vanishes at 640p",
      truth: "other_defect (steep overhang cooling degradation)",
      modeType: "degrade",
      imgA: ownUsb.green_slant2_orig,
      imgB: ownUsb.green_slant2_deg,
      labelA: "Raw 1080p UVC Frame",
      labelB: "640p + Extra CMOS Noise",
      takeaway:
        "On the original USB capture, Flash and Gemma 31B cleanly diagnosed the rough right-hand overhang band. Adding 640p downsampling + noise erased the low-contrast green-on-green surface texture across all three models—showing why surface relief defects need grazing side-lighting.",
      verdictsA: [
        { model: "gemini-3.8-flash", ok: true, pred: "other_defect", quote: "Significant roughness and degradation along the curved overhang on the right side, likely caused by insufficient cooling." },
        { model: "gemma-4-31b-it", ok: true, pred: "other_defect", quote: "The right side of the part exhibits significant surface roughness and uneven texture." },
        { model: "gemma-4-26b-a4b-it", ok: false, pred: "clean", quote: "Smooth surfaces and clean edges with no visible stringing, blobs, or layer shifts." },
      ],
      verdictsB: [
        { model: "gemini-3.8-flash", ok: false, pred: "clean", quote: "Smooth exterior walls, sharp details around the ventilation slots, and no visible stringing or defects." },
        { model: "gemma-4-31b-it", ok: false, pred: "clean", quote: "Consistent surface finish with no visible stringing or significant print defects." },
        { model: "gemma-4-26b-a4b-it", ok: false, pred: "clean", quote: "The part's surface and edges appear smooth and free of any visible printing artifacts." },
      ],
    },
    {
      id: "green_slant3",
      group: "usb",
      badge: "External USB Cam Sim · High-Contrast Defect",
      title: "High-Contrast Top Void Survives 640p + Grain",
      truth: "other_defect (horizontal wall band + top-right white void/scarring)",
      modeType: "degrade",
      imgA: ownUsb.green_slant3_orig,
      imgB: ownUsb.green_slant3_deg,
      labelA: "Raw 1080p UVC Frame",
      labelB: "640p + Extra CMOS Noise",
      takeaway:
        "Compare this with green_slant2: because the defect on top of green_slant3 creates a bright white contrast patch against matte green PLA, both open Gemma models caught it even AFTER 640p + CMOS noise degradation.",
      verdictsA: [
        { model: "gemini-3.8-flash", ok: true, pred: "other_defect", quote: "Inconsistent extrusion/rough surface texture along a horizontal band across the front wall, plus a void around the top-right feature." },
        { model: "gemma-4-31b-it", ok: true, pred: "other_defect", quote: "There is a visible white blob/defect on the top surface of the part." },
        { model: "gemma-4-26b-a4b-it", ok: false, pred: "clean", quote: "Smooth surfaces and consistent layer lines with no visible stringing or major defects." },
      ],
      verdictsB: [
        { model: "gemini-3.8-flash", ok: false, pred: "clean", quote: "Smooth, intact surfaces and well-defined contours without any visible stringing or notable defects." },
        { model: "gemma-4-31b-it", ok: true, pred: "other_defect", quote: "Visible surface irregularities and small blobs or voids on the top face of the part." },
        { model: "gemma-4-26b-a4b-it", ok: true, pred: "other_defect", quote: "There are visible white blobs or zits on the top surface of the part." },
      ],
    },
    {
      id: "gray_problem",
      group: "usb",
      badge: "External USB Cam Sim · Baseline Optical Reference",
      title: "Overexposed Grey Column + Tree Support Confounder",
      truth: "other_defect (wavy wall distortion; Laplacian sharpness std = 4.94)",
      modeType: "degrade",
      imgA: ownUsb.gray_problem_orig,
      imgB: ownUsb.gray_problem_deg,
      labelA: "Raw 1080p UVC Frame",
      labelB: "640p + Extra CMOS Noise",
      takeaway:
        "Our optical reference photo (1920x1080 UVC container, ~480p effective sharpness). Blown highlights on glossy grey PLA hid the wall distortion from Gemini Flash, while organic tree-support branches behind the part tricked Gemma 31B into calling stringing—only Gemma A4B nailed the raw frame.",
      verdictsA: [
        { model: "gemini-3.8-flash", ok: false, pred: "clean", quote: "Printed object and adjacent tree support structure are printed neatly with smooth surfaces and good layer consistency." },
        { model: "gemma-4-31b-it", ok: false, pred: "stringing", quote: "Fine filament strands are visible bridging the gaps between the printed pillars." },
        { model: "gemma-4-26b-a4b-it", ok: true, pred: "other_defect", quote: "The part exhibits severe structural distortion and irregular, wavy layer formation." },
      ],
      verdictsB: [
        { model: "gemini-3.8-flash", ok: false, pred: "clean", quote: "The 3D printed object and its adjacent tree support structure appear smooth and clean." },
        { model: "gemma-4-31b-it", ok: false, pred: "stringing", quote: "Fine filament strands are visible bridging gaps in the printed part." },
        { model: "gemma-4-26b-a4b-it", ok: false, pred: "stringing", quote: "Fine, hair-like wisps of filament are visible between the different sections of the white printed part." },
      ],
    },
  ];

  if (!isUncensored) return usbCards;

  const scrapedCards = [
    {
      id: "falcon_string_art",
      group: "edge",
      badge: "Negative Control Edge Case · Unanimous 4/4 Trap",
      title: "The Millennium Falcon 'Hyperspace' String-Art Trap",
      truth: "clean (intentional single-extrusion suspension bridges)",
      modeType: "single",
      imgA: extra.falcon,
      labelA: "Showcase Clean Print (N=16 Control Set)",
      takeaway:
        "Out of 16 clean prints in context_dev, Gemini Flash-Lite achieved 93.8% specificity (15/16) while Gemma 31B and Nemotron 3.5 Super VL both achieved 87.5% (14/16)—and ALL FOUR models unanimously tripped on THIS print. Hundreds of intentional bridged single-filament 'hyperspace streaks' suspend the Falcon in mid-air: without CAD/G-code awareness, no pure-vision inspector can distinguish intentional string-art from severe stringing.",
      verdictsA: [
        { model: "gemini-3.5-flash-lite", ok: false, pred: "stringing", quote: "Only false positive out of 16 clean showcase prints (93.8% specificity)." },
        { model: "gemma-4-31b-it", ok: false, pred: "stringing", quote: "Flagged as stringing (87.5% overall clean specificity across N=16)." },
        { model: "nemotron-3.5-super-vl", ok: false, pred: "stringing", quote: "Also flagged as stringing (87.5% overall clean specificity across N=16)." },
        { model: "gemma-4-26b-a4b-it", ok: false, pred: "stringing", quote: "Flagged as stringing—proving calibration loops should inspect known test geometries or cross-check travel moves in G-code." },
      ],
    },
    {
      id: "clean_zoro_pair",
      group: "degrade",
      badge: "Optical Low-Pass Effect · Clean Specificity",
      title: "Why Cheap USB Blur Cured Gemma's False Alarms",
      truth: "clean (spiky bust with 2 microscopic sword-hilt hairs)",
      modeType: "degrade",
      imgA: extra.zoro_orig,
      imgB: extra.zoro_deg,
      labelA: "Original Crisp 1080x1440",
      labelB: "Simulated 480p USB + Grain",
      takeaway:
        "At full smartphone sharpness, ALL three models saw the exact same two sub-millimeter hairs near the sword hilts: Flash forgave them as negligible, while both Gemma models obeyed 'light wisps count as stringing' literally. Under 480p USB webcam blur, those cosmetic hairs vanished below the sensor floor—pushing clean specificity to 100% (3/3) across every model.",
      verdictsA: [
        { model: "gemini-3.8-flash", ok: true, pred: "clean", quote: "Only a couple of negligible, hairline stringing wisps visible near the sword hilts and hair tips, minor enough to classify as overall clean." },
        { model: "gemma-4-31b-it", ok: false, pred: "stringing", quote: "Fine strands of filament are visible between the sword handles and around the spiky hair." },
        { model: "gemma-4-26b-a4b-it", ok: false, pred: "stringing", quote: "Fine filament strands are visible between the sword hilts and near the top of the left sword." },
      ],
      verdictsB: [
        { model: "gemini-3.8-flash", ok: true, pred: "clean", quote: "Classified clean — microscopic wisps filtered out by 480p optical MTF." },
        { model: "gemma-4-31b-it", ok: true, pred: "clean", quote: "Classified clean — zero false alarms across all clean prints under USB degradation." },
        { model: "gemma-4-26b-a4b-it", ok: true, pred: "clean", quote: "Classified clean — natural optical low-pass threshold eliminated cosmetic-hair false triggers." },
      ],
    },
    {
      id: "str001_pair",
      group: "degrade",
      badge: "Optical Resilience · Stringing + Severity",
      title: "Open-Air Stringing Survives 480p + Sensor Noise",
      truth: "stringing (Human Severity Tier 2 — slight wisps)",
      modeType: "degrade",
      imgA: extra.str001_orig,
      imgB: extra.str001_deg,
      labelA: "Original Crisp 1080x810",
      labelB: "Simulated 480p USB + Grain",
      takeaway:
        "Even small filament strands spanning open air against a darker background retain strong edge contrast after 640p downsampling, blur (σ=0.75), CMOS grain, and 4:2:0 MJPEG compression—all three models caught it in both regimes with calibrated severity (0.60–0.75).",
      verdictsA: [
        { model: "gemini-3.8-flash", ok: true, pred: "stringing", quote: "Detected stringing across the four-post retraction pyramid (tier within ±1)." },
        { model: "gemma-4-31b-it", ok: true, pred: "stringing (0.80)", quote: "Fine filament strands bridging the gaps between the four vertical cones." },
        { model: "gemma-4-26b-a4b-it", ok: true, pred: "stringing (0.70)", quote: "Visible cobwebbing and thin wisps spanning between the test pillars." },
      ],
      verdictsB: [
        { model: "gemini-3.8-flash", ok: true, pred: "stringing (0.65)", quote: "Exact human tier-2 match (score 0.65) even on noisy 640x480 MJPEG." },
        { model: "gemma-4-31b-it", ok: true, pred: "stringing (0.75)", quote: "Strands spanning the towers remain clearly distinguishable from background sensor grain." },
        { model: "gemma-4-26b-a4b-it", ok: true, pred: "stringing (0.60)", quote: "Exact human tier-2 match (score 0.60) on 4B-active open model." },
      ],
    },
    {
      id: "od004_pair",
      group: "degrade",
      badge: "Optical Bottleneck · Surface Zits Lost at 480p",
      title: "24MP Macro Surface Zits Wash Out Into Webcam Grain",
      truth: "other_defect (surface zits + tiny travel wisps on raised dots)",
      modeType: "degrade",
      imgA: extra.od004_orig,
      imgB: extra.od004_deg,
      labelA: "Original 4284x5712 (24.5 MP)",
      labelB: "Simulated 480x640 USB + Grain",
      takeaway:
        "At 24.5 MP, all 3 models detected defects (Gemma 31B/A4B called zits; Flash noted wisps between raised dots). Crushed to 480x640 + sensor grain, ALL THREE models called it completely clean—demonstrating why Pressure Advance / surface-zit calibration requires closer macro optics or grazing light.",
      verdictsA: [
        { model: "gemini-3.8-flash", ok: false, pred: "stringing", quote: "Small raised features (braille dots) show fine wisps and stringing caused by retraction and travel moves between tiny points." },
        { model: "gemma-4-31b-it", ok: true, pred: "other_defect", quote: "There are visible zits and blobs on the top surface of the rectangular printed part." },
        { model: "gemma-4-26b-a4b-it", ok: true, pred: "other_defect", quote: "Visible small blobs or zits are present on the surface of the rectangular part." },
      ],
      verdictsB: [
        { model: "gemini-3.8-flash", ok: false, pred: "clean", quote: "Smooth surface layers, well-defined perimeters, and no evidence of stringing, warping, or layer defects." },
        { model: "gemma-4-31b-it", ok: false, pred: "clean", quote: "The printed parts appear to have smooth surfaces with no visible defects or stringing." },
        { model: "gemma-4-26b-a4b-it", ok: false, pred: "clean", quote: "No visible printing defects such as stringing, blobs, or layer shifts are apparent on the surface." },
      ],
    },
    {
      id: "str006_benchy",
      group: "edge",
      badge: "Label Taxonomy Insight · Co-Occurring Defects",
      title: "Blue Benchy: Stringing Hairs vs. Overhang Loops",
      truth: "stringing (co-occurring with severe roofline overhang sag)",
      modeType: "degrade",
      imgA: extra.str006_orig,
      imgB: extra.str006_deg,
      labelA: "Original Crisp 1080x607",
      labelB: "Simulated 480p USB + Grain",
      takeaway:
        "Why forced single-choice classification lied about Gemini Flash: on the crisp photo, Flash accurately diagnosed the drooping cabin loops as overhang/cooling failure (scored 'wrong' against the stringing folder!). Switching to binary anomaly gating (+20.7 pts for Flash) or independent boolean flags eliminates this false penalty.",
      verdictsA: [
        { model: "gemini-3.8-flash", ok: false, pred: "other_defect", quote: "Severe overhang and bridging failures, characterized by sagging and looped extrusions along the roofline, chimney, and hull." },
        { model: "gemma-4-31b-it", ok: true, pred: "stringing", quote: "Extensive cobweb-like stringing is visible under the cabin roof and around the chimney." },
        { model: "gemma-4-26b-a4b-it", ok: true, pred: "stringing", quote: "Significant messy filament strands and clumps are visible around the cabin, smokestack, and hull edges." },
      ],
      verdictsB: [
        { model: "gemini-3.8-flash", ok: true, pred: "stringing (0.48)", quote: "Under 640p softening, classified as stringing around cabin and chimney." },
        { model: "gemma-4-31b-it", ok: true, pred: "stringing (0.50)", quote: "Detected filament strands bridging cabin openings." },
        { model: "gemma-4-26b-a4b-it", ok: true, pred: "stringing (0.30)", quote: "Detected messy filament artifacts around cabin roofline." },
      ],
    },
    {
      id: "telemetry_benchies",
      group: "telemetry",
      badge: "Moonraker Telemetry Unlock · Variant A → T",
      title: "7 Benchies: Machine Telemetry Flips 1/2 → Perfect 2/2",
      truth: "overhang_curling (200–300 mm/s outer/inner, 20–60% fan, no enclosure)",
      modeType: "telemetry",
      imgA: extra.benchies7,
      labelA: "Variant A: Pure Pixels Only",
      labelB: "Variant T: + Klipper Telemetry",
      telemetrySnippet: "Filament: Sunlu PLA · Speed: 200mm/s Outer / 300mm/s Inner · Temp: 215°C · Layer: 0.16mm · Fan: 20%–60%",
      takeaway:
        "From pixels alone (Variant A), Flash-Lite fixated on tiny chimney wisps and prescribed retraction tweaks (1/2). Adding ONLY static machine telemetry that Moonraker already knows—200–300 mm/s speed + 20–60% fan cap—flipped the diagnosis to overhang_curling with a perfect 2/2 on both causes and fixes!",
      verdictsA: [
        { model: "Variant A (Pixels Only)", ok: false, pred: "stringing · Judge 1/2", quote: "Causes: Retraction distance too low; Retraction speed too slow. Judge: 'Focuses on minor stringing rather than the severe bow overhang curling, missing the cooling root cause.'" },
      ],
      verdictsB: [
        { model: "Variant T (+ Telemetry)", ok: true, pred: "overhang_curling · Judge 2/2", quote: "Fixes: Increase minimum cooling fan speed to 100%; lower print temp 5–10°C. Judge: 'Accurately identifies primary cooling root cause and specific fixes aligned with confirmed solution.'" },
      ],
    },
    {
      id: "telemetry_octopus",
      group: "telemetry",
      badge: "Step-2 Reasoning Nuance · Retraction Paradox",
      title: "PETG Octopus: When 'More Retraction' Makes Stringing Worse",
      truth: "stringing (OP solved: 8mm retraction + 245°C PETG sucked air & oozed)",
      modeType: "telemetry",
      imgA: extra.octopus,
      labelA: "Variant A: Pure Pixels Only",
      labelB: "Variant T: + Klipper Telemetry",
      telemetrySnippet: "Material: Gray PETG · Nozzle Temp: 245°C · Retraction Distance: 8mm · Retraction Speed: 40mm/s",
      takeaway:
        "Pixels alone misread pitted tentacles as underextrusion (cold pull — 0/2, actively harmful!). Telemetry (PETG @ 245°C, 8mm retraction) fixed the class to stringing and caught overheating/moisture (1/2), while our rubric judge caught the subtle expert nuance: 8mm retraction was EXCESSIVE (trapping air bubbles), so retraction needed to go DOWN, not up.",
      verdictsA: [
        { model: "Variant A (Pixels Only)", ok: false, pred: "underextrusion · Judge 0/2", quote: "Predicted partial nozzle clog / cold pull. Judge: 'Incorrectly diagnoses severe branching stringing as underextrusion; raising temp would worsen the issue.'" },
      ],
      verdictsB: [
        { model: "Variant T (+ Telemetry)", ok: true, pred: "stringing · Judge 1/2", quote: "Correctly flags 245°C PETG overheating + filament moisture (lower 5–10°C, dry spool), but misses that 8mm retraction was too long rather than too short." },
      ],
    },
  ];

  return [...scrapedCards, ...usbCards];
}

function renderHtml({ cards, ownUsb, isUncensored }) {
  const editionBadge = isUncensored
    ? `<span class="pill pill-warn">LOCAL PARTICIPANT DEMO · FULL BENCHMARK GALLERY</span>`
    : `<span class="pill pill-ok">PUBLIC SHOWCASE · 100% OWN PRINTER USB PHOTOS</span>`;

  const gallerySubtitle = isUncensored
    ? `Curated edge cases across our external USB webcam captures, synthetic 480p degradation pairs, and wild Context.dev-mined r/FixMyPrint & r/3Dprinting cases. Use the toggle inside any paired card to switch inputs live.`
    : `Every photograph on this public page was captured with our own external USB webcam aimed at printed test parts to simulate a printer camera (zero third-party scraped images). Toggle between the raw UVC frame and synthetic 640p + noise stress test on any card.`;

  const filterButtons = isUncensored
    ? `
      <div class="seg-group" id="galleryFilters">
        <button class="seg active" data-filter="all">All Curated (${cards.length})</button>
        <button class="seg" data-filter="degrade">Optical Degradation Pairs (3)</button>
        <button class="seg" data-filter="telemetry">Context.dev Forum &amp; Telemetry (4)</button>
        <button class="seg" data-filter="usb">External USB Webcam Sim (5)</button>
      </div>`
    : "";

  const cardsJson = JSON.stringify(cards);
  const simCasesJson = JSON.stringify([
    {
      id: "whisp",
      name: "golden_whispV3.jpg (Stringing Tower)",
      img: ownUsb.golden_whisp_orig,
      defect: "stringing",
      severity: 0.72,
      tier: "Tier 3 (Heavy)",
      modelUsed: "gemma-4-26b-a4b-it (4B-Active Local Open Model)",
      telemetry: "Material: PLA · Nozzle: 215°C · Retract: 0.6mm @ 35mm/s",
      reasoning: "Dense fine filament strands and oozing visibly span across the open gap between the two vertical test columns.",
      klipperCmds: [
        "# Moonraker / Klipper proportional step (severity = 0.72)",
        "SET_RETRACTION RETRACT_LENGTH=1.0 RETRACT_SPEED=45",
        "M104 S208 ; step hotend -7C for next calibration segment",
      ],
    },
    {
      id: "slant2",
      name: "green_slant2.jpg (Curved Overhang)",
      img: ownUsb.green_slant2_orig,
      defect: "overhang_curling",
      severity: 0.58,
      tier: "Tier 2 (Moderate)",
      modelUsed: "gemma-4-31b-it / gemini-3.8-flash",
      telemetry: "Material: Matte PLA · Outer Wall: 180mm/s · Part Fan: 60%",
      reasoning: "Significant surface roughness and upward curling along the steep right-hand overhang while vertical vents remain sharp.",
      klipperCmds: [
        "# Increase part-cooling & slow overhang perimeter speed",
        "M106 S255 ; boost part-cooling fan to 100%",
        "SET_VELOCITY_LIMIT VELOCITY=120 ; reduce outer overhang speed",
      ],
    },
    {
      id: "support",
      name: "golden_support_piece.jpg (Wall Gaps)",
      img: ownUsb.golden_support_orig,
      defect: "underextrusion",
      severity: 0.78,
      tier: "Tier 3 (Severe)",
      modelUsed: "gemini-3.8-flash",
      telemetry: "Material: Silk PLA · Nozzle: 0.4mm @ 210°C · PA K=0.065",
      reasoning: "Under-extrusion and perimeter separation on the right vertical column creating ladder-like wall gaps along corner transitions.",
      klipperCmds: [
        "# Reduce excessive Pressure Advance K starving corner restarts",
        "SET_PRESSURE_ADVANCE ADVANCE=0.040",
        "M221 S104 ; +4% extrusion flow multiplier check",
      ],
    },
  ]);

  const severityPointsJson = JSON.stringify([
    { id: "stringing011", human: 1, flash: 0.40, g31: 0.70, ga4: 0.40, usbGa4: 0.00 },
    { id: "stringing001", human: 2, flash: 1.00, g31: 0.80, ga4: 0.70, usbGa4: 0.60 },
    { id: "stringing002", human: 2, flash: 0.55, g31: 0.70, ga4: 0.70, usbGa4: 0.60 },
    { id: "stringing003", human: 2, flash: 0.85, g31: 0.90, ga4: 0.80, usbGa4: 0.70 },
    { id: "stringing004", human: 3, flash: 0.85, g31: 0.80, ga4: 0.70, usbGa4: 0.60 },
    { id: "stringing005", human: 3, flash: 0.85, g31: 0.90, ga4: 0.80, usbGa4: 0.85 },
    { id: "stringing006", human: 3, flash: 0.85, g31: 0.80, ga4: 0.70, usbGa4: 0.30 },
    { id: "stringing007", human: 3, flash: 1.00, g31: 0.70, ga4: 0.60, usbGa4: 0.60 },
    { id: "stringing008", human: 3, flash: 0.70, g31: 0.80, ga4: 0.70, usbGa4: 0.80 },
    { id: "stringing009", human: 3, flash: 0.68, g31: 0.70, ga4: 0.70, usbGa4: 0.40 },
    { id: "stringing010", human: 3, flash: 0.45, g31: 0.40, ga4: 0.40, usbGa4: 0.00 },
  ]);

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Zero-Human-Loop 3D Print Calibration · Vision &amp; Edge VLM Study (Junction)</title>
<style>
  :root {
    --bg: #0b0d10;
    --bg-elev: #12161c;
    --bg-card: #161b22;
    --bg-muted: #0e1116;
    --border: #252d38;
    --border-hi: #384454;
    --text: #e6edf3;
    --muted: #8b96a5;
    --accent: #ff6b2b;
    --accent-soft: rgba(255, 107, 43, 0.14);
    --cyan: #2dd4bf;
    --cyan-soft: rgba(45, 212, 191, 0.13);
    --blue: #60a5fa;
    --amber: #f59e0b;
    --ok: #22c55e;
    --bad: #ef4444;
    --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
    --sans: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: radial-gradient(circle at 15% 0%, rgba(255,107,43,0.07), transparent 38%),
                radial-gradient(circle at 85% 5%, rgba(45,212,191,0.06), transparent 36%),
                var(--bg);
    color: var(--text);
    font-family: var(--sans);
    line-height: 1.55;
    -webkit-font-smoothing: antialiased;
  }
  .wrap { max-width: 1180px; margin: 0 auto; padding: 32px 22px 80px; }
  header.hero {
    border: 1px solid var(--border);
    background: linear-gradient(180deg, rgba(22,27,34,0.92), rgba(14,17,22,0.96));
    border-radius: 16px;
    padding: 32px 30px 28px;
    margin-bottom: 28px;
  }
  .top-badges { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 14px; }
  .pill {
    font-family: var(--mono);
    font-size: 11px;
    letter-spacing: 0.05em;
    padding: 4px 10px;
    border-radius: 999px;
    border: 1px solid var(--border-hi);
    background: var(--bg-muted);
    color: var(--muted);
    text-transform: uppercase;
  }
  .pill-ok { border-color: rgba(34,197,94,0.45); color: #4ade80; background: rgba(34,197,94,0.09); }
  .pill-warn { border-color: rgba(255,107,43,0.5); color: #ff8a57; background: var(--accent-soft); }
  .hero-top {
    display: grid;
    grid-template-columns: 1.25fr 0.85fr;
    gap: 24px;
    align-items: center;
  }
  @media (max-width: 920px) { .hero-top { grid-template-columns: 1fr; } }
  .hero-hook {
    background: var(--bg-muted);
    border: 1px solid var(--border-hi);
    border-radius: 14px;
    overflow: hidden;
    box-shadow: 0 12px 30px rgba(0, 0, 0, 0.35);
  }
  .hero-hook-img { position: relative; aspect-ratio: 16/10; background: #07090c; overflow: hidden; }
  .hero-hook-img img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .hero-hook-tag {
    position: absolute;
    top: 10px;
    left: 10px;
    background: rgba(11, 13, 16, 0.86);
    backdrop-filter: blur(6px);
    border: 1px solid rgba(255, 107, 43, 0.5);
    color: #ff9f76;
    font-family: var(--mono);
    font-size: 11px;
    padding: 4px 9px;
    border-radius: 999px;
  }
  .hero-hook-cap {
    padding: 10px 14px;
    border-top: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 10px;
    font-family: var(--mono);
    font-size: 11.5px;
    color: var(--muted);
  }
  .hero-hook-cap strong { color: var(--cyan); }
  h1 {
    font-size: clamp(26px, 3.6vw, 40px);
    line-height: 1.15;
    margin: 0 0 12px;
    letter-spacing: -0.02em;
  }
  h1 span { color: var(--accent); }
  .subtitle { color: var(--muted); font-size: 16px; max-width: 860px; margin: 0; }
  .kpi-strip {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(195px, 1fr));
    gap: 12px;
    margin-top: 20px;
  }
  .kpi {
    background: var(--bg-muted);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 14px 16px;
  }
  .kpi .num { font-family: var(--mono); font-size: 26px; font-weight: 700; color: var(--text); }
  .kpi .num.accent { color: var(--accent); }
  .kpi .num.cyan { color: var(--cyan); }
  .kpi .num.ok { color: var(--ok); }
  .kpi .lbl { font-size: 12.5px; color: var(--muted); margin-top: 3px; }

  /* Closed-loop diagram */
  .loop-bar {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 10px;
    margin-top: 22px;
  }
  @media (max-width: 860px) { .loop-bar { grid-template-columns: 1fr; } }
  .loop-step {
    background: rgba(255,255,255,0.02);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 12px 13px;
    position: relative;
  }
  .loop-step.tested { border-color: rgba(45,212,191,0.42); }
  .loop-step.next { border-style: dashed; opacity: 0.88; }
  .loop-step .st-tag {
    font-family: var(--mono);
    font-size: 10px;
    text-transform: uppercase;
    padding: 2px 6px;
    border-radius: 4px;
    display: inline-block;
    margin-bottom: 6px;
  }
  .loop-step.tested .st-tag { background: var(--cyan-soft); color: var(--cyan); }
  .loop-step.next .st-tag { background: rgba(245,158,11,0.14); color: var(--amber); }
  .loop-step h4 { margin: 0 0 4px; font-size: 13.5px; }
  .loop-step p { margin: 0; font-size: 12px; color: var(--muted); line-height: 1.4; }

  section { margin-bottom: 34px; }
  .sec-head {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: flex-end;
    gap: 14px;
    margin-bottom: 16px;
  }
  h2 { font-size: 21px; margin: 0; letter-spacing: -0.01em; }
  .sec-sub { color: var(--muted); font-size: 14px; margin: 4px 0 0; max-width: 780px; }

  .panel {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 22px 24px;
  }
  .grid-2 { display: grid; grid-template-columns: 1.15fr 0.85fr; gap: 18px; }
  @media (max-width: 920px) { .grid-2 { grid-template-columns: 1fr; } }

  /* Segmented controls */
  .controls-row { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 18px; }
  .seg-group {
    display: inline-flex;
    flex-wrap: wrap;
    background: var(--bg-muted);
    border: 1px solid var(--border);
    border-radius: 9px;
    padding: 3px;
    gap: 3px;
  }
  .seg {
    background: transparent;
    color: var(--muted);
    border: 0;
    padding: 6px 12px;
    border-radius: 6px;
    font-size: 12.5px;
    font-family: var(--sans);
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s ease;
  }
  .seg:hover { color: var(--text); }
  .seg.active { background: var(--accent); color: #fff; font-weight: 600; }
  .seg-cyan.active { background: var(--cyan); color: #06201d; }

  /* Bar chart */
  .chart-legend { display: flex; flex-wrap: wrap; gap: 16px; font-size: 12.5px; color: var(--muted); margin-bottom: 14px; }
  .dot { width: 10px; height: 10px; border-radius: 3px; display: inline-block; margin-right: 6px; vertical-align: middle; }
  .metric-group { margin-bottom: 16px; }
  .metric-head { display: flex; justify-content: space-between; font-size: 13px; font-weight: 600; margin-bottom: 6px; }
  .metric-note { font-weight: 400; color: var(--muted); font-size: 12px; }
  .bar-row { display: grid; grid-template-columns: 165px 1fr 56px; align-items: center; gap: 10px; margin: 5px 0; font-size: 12px; }
  .bar-row .mname { font-family: var(--mono); color: var(--muted); font-size: 11.5px; }
  .bar-track { background: var(--bg-muted); border: 1px solid var(--border); height: 18px; border-radius: 5px; overflow: hidden; }
  .bar-fill { height: 100%; border-radius: 4px; transition: width 0.35s cubic-bezier(.2,.8,.2,1); }
  .bar-val { font-family: var(--mono); text-align: right; font-weight: 600; }

  .callout {
    margin-top: 14px;
    padding: 12px 15px;
    border-left: 3px solid var(--accent);
    background: rgba(255,107,43,0.07);
    border-radius: 0 8px 8px 0;
    font-size: 13px;
    color: #d7dfe8;
  }
  .callout.cyan { border-left-color: var(--cyan); background: var(--cyan-soft); }

  /* Simulator */
  .sim-grid { display: grid; grid-template-columns: 320px 1fr; gap: 20px; align-items: start; }
  @media (max-width: 820px) { .sim-grid { grid-template-columns: 1fr; } }
  .sim-img-wrap {
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
    background: #000;
  }
  .sim-img-wrap img { width: 100%; display: block; aspect-ratio: 16/10; object-fit: cover; }
  .code-box {
    background: #090c10;
    border: 1px solid var(--border);
    border-radius: 9px;
    padding: 12px 14px;
    font-family: var(--mono);
    font-size: 12px;
    overflow-x: auto;
    color: #cbd5e1;
    margin-top: 10px;
  }
  .code-box .k { color: #7dd3fc; }
  .code-box .s { color: #86efac; }
  .code-box .c { color: #64748b; }
  .code-box .cmd { color: #fda4af; font-weight: 600; }

  /* Gallery */
  .gallery-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
    gap: 18px;
  }
  .case-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 14px;
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }
  .case-img-box { position: relative; background: #07090c; aspect-ratio: 16/11; overflow: hidden; border-bottom: 1px solid var(--border); }
  .case-img-box img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .img-toggle {
    position: absolute;
    bottom: 10px;
    right: 10px;
    display: inline-flex;
    background: rgba(11, 13, 16, 0.88);
    backdrop-filter: blur(6px);
    border: 1px solid var(--border-hi);
    border-radius: 8px;
    padding: 2px;
    gap: 2px;
  }
  .img-toggle button {
    border: 0;
    background: transparent;
    color: var(--muted);
    font-size: 11px;
    font-family: var(--mono);
    padding: 5px 8px;
    border-radius: 6px;
    cursor: pointer;
  }
  .img-toggle button.active { background: var(--accent); color: #fff; font-weight: 600; }
  .case-body { padding: 16px 18px 18px; display: flex; flex-direction: column; gap: 10px; flex: 1; }
  .case-badge { font-family: var(--mono); font-size: 11px; color: var(--cyan); text-transform: uppercase; letter-spacing: 0.04em; }
  .case-body h3 { margin: 0; font-size: 16px; line-height: 1.3; }
  .truth-line { font-family: var(--mono); font-size: 11.5px; color: var(--muted); }
  .truth-line strong { color: var(--text); }
  .telem-pill {
    font-family: var(--mono);
    font-size: 11px;
    background: #0b0f14;
    border: 1px solid var(--border);
    padding: 6px 9px;
    border-radius: 6px;
    color: #93c5fd;
  }
  .case-takeaway { font-size: 13px; color: #c8d1dc; margin: 0; }
  .verdicts { display: flex; flex-direction: column; gap: 7px; margin-top: auto; padding-top: 6px; }
  .v-item {
    background: var(--bg-muted);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 12px;
  }
  .v-top { display: flex; justify-content: space-between; font-family: var(--mono); font-size: 11.5px; margin-bottom: 3px; }
  .v-ok { color: var(--ok); font-weight: 600; }
  .v-bad { color: var(--bad); font-weight: 600; }
  .v-quote { color: var(--muted); font-size: 11.8px; line-height: 1.4; }

  /* Tables & Methodology */
  table.matrix { width: 100%; border-collapse: collapse; font-size: 13px; }
  table.matrix th, table.matrix td {
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
    text-align: left;
  }
  table.matrix th { color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; font-family: var(--mono); }
  table.matrix td.mono { font-family: var(--mono); }
  .meth-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; }
  .meth-card { background: var(--bg-muted); border: 1px solid var(--border); border-radius: 10px; padding: 15px 16px; }
  .meth-card h4 { margin: 0 0 6px; font-size: 14px; color: var(--text); }
  .meth-card p { margin: 0; font-size: 12.8px; color: var(--muted); }
  footer { margin-top: 46px; text-align: center; font-size: 12.5px; color: var(--muted); font-family: var(--mono); }
</style>
</head>
<body>
<div class="wrap">
  <header class="hero">
    <div class="hero-top">
      <div>
        <div class="top-badges">
          <span class="pill">Junction Finland 2026</span>
          <span class="pill">Context.dev Live-Web Ground Truth</span>
          <span class="pill">Gemma 4 · Local Open Models</span>
          ${editionBadge}
        </div>
        <h1>Live Forum Wisdom Meets Local Open Vision: <span>Self-Calibrating 3D Printers</span></h1>
        <p class="subtitle">
          Closed 3D-printer vendors lock vision calibration behind proprietary clouds, leaving millions of open printers wasting plastic filament and <code>250W+</code> heater energy on failed trial-and-error prints. We built a <strong>Context.dev live-web pipeline</strong> that summarizes scattered forum discussions (<code>r/FixMyPrint</code>) into OP-confirmed ground truth for automated AI testing, and proved that lightweight open-weight <strong>Gemma 4 local models</strong> (<code>gemma-4-26b-a4b-it</code> at 4B active parameters &amp; <code>gemma-4-31b-it</code>) watching a cheap external USB webcam can drive <strong>Klipper / Moonraker</strong> calibration locally with zero cloud lock-in.
        </p>
      </div>
      <div class="hero-hook">
        <div class="hero-hook-img">
          <img id="heroUsbImg" src="${ownUsb.golden_whisp_orig}" alt="External USB webcam capture of stringing retraction tower" />
          <span class="hero-hook-tag">● USB Webcam Sim · Stringing 0.72</span>
          <div class="img-toggle">
            <button class="active" onclick="document.getElementById('heroUsbImg').src='${ownUsb.golden_whisp_orig}';this.parentElement.querySelectorAll('button').forEach(b=>b.classList.remove('active'));this.classList.add('active');">Raw USB</button>
            <button onclick="document.getElementById('heroUsbImg').src='${ownUsb.golden_whisp_deg}';this.parentElement.querySelectorAll('button').forEach(b=>b.classList.remove('active'));this.classList.add('active');">640p + Noise</button>
          </div>
        </div>
        <div class="hero-hook-cap">
          <span><strong>gemma-4-26b-a4b-it</strong> → <code>SET_RETRACTION</code></span>
          <span>96.6% F1</span>
        </div>
      </div>
    </div>

    <div class="kpi-strip">
      <div class="kpi">
        <div class="num cyan">84 Threads</div>
        <div class="lbl">Mined &amp; Synthesized via <strong>Context.dev</strong> into Citation-Backed Ground Truth (179 Photos)</div>
      </div>
      <div class="kpi">
        <div class="num accent">96.6%</div>
        <div class="lbl">Stringing F1 on 4B-Active Local Open Model (<code>gemma-4-26b-a4b-it</code>; <code>81.5%</code> on 480p USB)</div>
      </div>
      <div class="kpi">
        <div class="num ok">93.1%</div>
        <div class="lbl">Binary Anomaly Gate Accuracy (<code>gemma-4-31b-it</code>; <code>89.7%</code> w/ 0% FAR on Flash)</div>
      </div>
      <div class="kpi">
        <div class="num">+9.2 pts</div>
        <div class="lbl">18-Class Lift from Injecting Moonraker Telemetry Alone (<code>58.5% → 67.7%</code>, +32% Fix Score)</div>
      </div>
      <div class="kpi">
        <div class="num ok">93.8%</div>
        <div class="lbl">Clean-Print Specificity on 16 Negative Controls (Only 1 String-Art False Alarm)</div>
      </div>
    </div>

    <div class="loop-bar">
      <div class="loop-step tested">
        <span class="st-tag">Context.dev API</span>
        <h4>1. Live Forum Mining</h4>
        <p><code>reddit-search</code> + <code>reddit-post</code> + <code>formats.bytes</code> harvest real failures &amp; nested comments.</p>
      </div>
      <div class="loop-step tested">
        <span class="st-tag">Auto Ground Truth</span>
        <h4>2. Forum → Eval Rubric</h4>
        <p>Score-weighted consensus + OP <code>Solved</code> confirmation + verified <code>comment_id</code> citations.</p>
      </div>
      <div class="loop-step tested">
        <span class="st-tag">USB Cam Sim</span>
        <h4>3. Optical Stress Test</h4>
        <p>External USB camera captures + synthetic ≤640p blur/noise (σ=4.94) test real webcam limits.</p>
      </div>
      <div class="loop-step tested">
        <span class="st-tag">Local Open Models</span>
        <h4>4. Gemma 4 + Telemetry</h4>
        <p>Open Gemma 4 scores defect + 0–1 severity locally; Moonraker telemetry unlocks +32% better fixes.</p>
      </div>
      <div class="loop-step next">
        <span class="st-tag">Target Hookup</span>
        <h4>5. Moonraker → Klipper</h4>
        <p>Manufacturer-agnostic G-code push (<code>SET_RETRACTION</code>, <code>SET_PRESSURE_ADVANCE</code>).</p>
      </div>
    </div>
  </header>

  <!-- UNIFIED PILLARS + INTERACTIVE CONTEXT.DEV INSPECTOR -->
  <section>
    <div class="grid-2">
      <div class="panel" style="border-color:rgba(45,212,191,0.38);">
        <div class="case-badge" style="margin-bottom:6px;">Context.dev Track · Live Forum Wisdom → Ground Truth</div>
        <h2 style="font-size:18.5px;margin-bottom:8px;">Summarizing Unstructured Forums into Automated Ground Truth</h2>
        <p style="font-size:13.3px;color:var(--muted);margin:0 0 10px;">
          Manually printing and failing 500 parts in a lab takes months, and static datasets go stale whenever new high-speed slicers or filaments launch—while thousands of solved cases already sit scattered across forum comment trees. Our 7-stage <strong>Context.dev</strong> pipeline distills OP-confirmed <code>Solved</code> threads, score-weighted consensus, and verified <code>evidence_comment_ids</code> into an automated ground-truth testbench (<code>68</code> failures + <code>16</code> clean controls). Inspect a live record below:
        </p>
        <div class="controls-row" style="margin-bottom:10px;">
          <div class="seg-group" id="ctxSelector"></div>
        </div>
        <div id="ctxView"></div>
      </div>

      <div class="panel" style="border-color:rgba(255,107,43,0.38);">
        <div class="case-badge" style="color:var(--accent);margin-bottom:6px;">Core Architecture · Context.dev · Gemma 4 · Gemini API</div>
        <h2 style="font-size:18.5px;margin-bottom:10px;">Local Open Edge Calibration, Backed by Live-Web Rubrics</h2>
        <div class="meth-grid" style="grid-template-columns:1fr;">
          <div class="meth-card" style="border-color:rgba(45,212,191,0.35);">
            <h4 style="color:var(--cyan);">Context.dev · Fully Structured Live Web</h4>
            <p>
              <strong>1. <code>POST /v1/scrape</code> (<code>reddit-search</code>):</strong> Discovers troubleshooting threads across <code>r/FixMyPrint</code> &amp; <code>r/3Dprinting</code>.<br/>
              <strong>2. <code>POST /v1/scrape</code> &amp; <code>/v1/batches</code> (<code>reddit-post</code>):</strong> Pulls nested 200-comment trees with deterministic <code>Idempotency-Key</code>.<br/>
              <strong>3. <code>POST /v1/scrape</code> (<code>formats.bytes</code>, <code>maxAgeMs=0</code>):</strong> Downloads raw photos with <code>.success</code> checks, SHA-256 dedupe, and local credit logging (<code>credit_usage.jsonl</code>) + optional <code>formats.images</code> visual dedupe.
            </p>
          </div>
          <div class="meth-card" style="border-color:rgba(255,107,43,0.35);">
            <h4 style="color:var(--accent);">Google DeepMind Gemma 4 · Local Open-Weight Vision</h4>
            <p>
              Running open-weight Gemma 4 locally alongside a €10 USB webcam upgrades any Klipper printer without cloud lock-in, workshop video uploads, or recurring API costs. Even 4B-active <code>gemma-4-26b-a4b-it</code> hits <strong>96.6%</strong> Stringing F1 (<strong>81.5%</strong> at 480p USB), <strong>100% (7/7)</strong> wild stringing recall, and <strong>11/11</strong> severity within ±1 tier, while <code>gemma-4-31b-it</code> reaches <strong>93.1%</strong> binary anomaly accuracy.
            </p>
          </div>
          <div class="meth-card" style="border-color:rgba(96,165,250,0.35);">
            <h4 style="color:var(--blue);">Google Gemini API · Synthesizer, Judge &amp; Escalation</h4>
            <p>
              Powers (1) <strong>Multimodal S5 Synthesis</strong> auditing gallery image roles + citing exact <code>evidence_comment_ids</code>, (2) <strong>S7 Rubric &amp; Blind A/B Judging</strong>, and (3) <strong>Variant T Escalation</strong> (<strong>67.7%</strong> 18-class accuracy with Moonraker telemetry).
            </p>
          </div>
        </div>
      </div>
    </div>
  </section>

  <!-- INTERACTIVE BENCHMARK CHARTS -->
  <section>
    <div class="sec-head">
      <div>
        <h2>1. Cloud vs. Open Gemma 4: Label Mode &amp; USB Webcam Stress Test</h2>
        <p class="sec-sub">Switch between forced single-label (3-class) vs. binary anomaly gating, and toggle between original photos vs. synthetic 480p + CMOS noise USB degradation (N=29 paired prints).</p>
      </div>
    </div>

    <div class="grid-2">
      <div class="panel">
        <div class="controls-row">
          <div class="seg-group" id="modeToggle">
            <button class="seg active" data-mode="three">3-Class Single-Label</button>
            <button class="seg" data-mode="binary">Binary Gate (Clean vs. Defect)</button>
          </div>
          <div class="seg-group" id="usbToggle">
            <button class="seg seg-cyan active" data-usb="orig">Original Photos</button>
            <button class="seg seg-cyan" data-usb="usb">480p USB + Noise Degraded</button>
          </div>
        </div>

        <div class="chart-legend">
          <span><i class="dot" style="background:#60a5fa"></i>gemini-3.8-flash (Cloud)</span>
          <span><i class="dot" style="background:#ff6b2b"></i>gemma-4-31b-it (Frontier Open)</span>
          <span><i class="dot" style="background:#2dd4bf"></i>gemma-4-26b-a4b-it (4B-Active Local Open)</span>
          <span><i class="dot" style="background:#a78bfa"></i>nemotron-3.5-super-vl (120B/12B Open)</span>
        </div>

        <div id="mainBarChart"></div>
        <div class="callout" id="chartInsight"></div>
      </div>

      <!-- Severity calibration SVG strip plot -->
      <div class="panel">
        <h3 style="margin:0 0 6px;font-size:16px;">Severity Approximation vs. Human Tiers (11 Prints)</h3>
        <p style="margin:0 0 12px;font-size:12.8px;color:var(--muted);">
          Proportional control needs calibrated magnitude, not just yes/no. Both <code>gemini-3.8-flash</code> and <code>gemma-4-26b-a4b-it</code> matched human severity <strong>within ±1 tier on 11/11 (100%)</strong> of labeled stringing towers.
        </p>
        <svg id="severitySvg" viewBox="0 0 420 235" style="width:100%;height:auto;display:block;"></svg>
        <div class="callout cyan" style="margin-top:10px;font-size:12.3px;">
          <strong>Control-loop takeaway:</strong> Even when human "slight (2)" vs. "heavy (3)" borderline cases differ by one tier, model scores increase monotonically from Tier 1 (<code>0.40</code>) → Tier 2 (<code>0.55–0.85</code>) → Tier 3 (<code>0.70–1.00</code>).
        </div>
      </div>
    </div>
  </section>

  <!-- WILD 18-CLASS + TELEMETRY BENCHMARK -->
  <section>
    <div class="sec-head">
      <div>
        <h2>2. Wild 18-Class Diagnosis &amp; The Moonraker Telemetry Boost (N=68 + 16 Controls)</h2>
        <p class="sec-sub">Evaluated on 68 deduplicated troubleshooting cases (59 OP-solved) across 18 defect classes + 16 clean showcase prints, graded by a multimodal reference-rubric judge (<code>0–2</code> on root causes &amp; fixes).</p>
      </div>
    </div>

    <div class="grid-2">
      <div class="panel">
        <div class="controls-row" style="justify-content:space-between;margin-bottom:12px;">
          <h3 style="margin:0;font-size:16px;">4-Model Regime Ablation (N=68, 0 Errors)</h3>
          <div class="seg-group" id="telemVarToggle">
            <button class="seg active" data-var="A">Var A · Pure Pixels</button>
            <button class="seg" data-var="T">Var T · +Telemetry</button>
            <button class="seg" data-var="B">Var B · +Post Text</button>
          </div>
        </div>
        <div id="telemetryChart"></div>
        <div class="callout cyan" id="telemInsight"></div>
      </div>

      <div class="panel">
        <h3 style="margin:0 0 10px;font-size:16px;">Cloud vs. Multi-Vendor Open Models Matrix</h3>
        <table class="matrix" style="font-size:12.2px;">
          <thead>
            <tr>
              <th>Dimension</th>
              <th>Gemini Flash</th>
              <th>Gemma 31B</th>
              <th>Gemma A4B</th>
              <th>Nemotron VL</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Stringing F1 (Raw / USB)</td>
              <td class="mono">78.6 / 85.7%</td>
              <td class="mono">87.5 / 82.8%</td>
              <td class="mono" style="color:var(--cyan);font-weight:700;">96.6 / 81.5%</td>
              <td class="mono">85.7 / 78.6%</td>
            </tr>
            <tr>
              <td>29-Img Binary (Raw / USB)</td>
              <td class="mono">89.7 / 72.4%</td>
              <td class="mono" style="color:var(--ok);font-weight:700;">93.1 / 82.8%</td>
              <td class="mono">82.1 / 72.4%</td>
              <td class="mono">79.3 / 65.5%</td>
            </tr>
            <tr>
              <td>18-Class Pure Visual (A)</td>
              <td class="mono" style="color:var(--blue);font-weight:700;">58.5%</td>
              <td class="mono">36.9%</td>
              <td class="mono">36.9%</td>
              <td class="mono">20.0%</td>
            </tr>
            <tr>
              <td>18-Class + Telemetry (T)</td>
              <td class="mono" style="color:var(--blue);font-weight:700;">67.7% (1.03)</td>
              <td class="mono">40.0% (0.93)</td>
              <td class="mono">40.0% (0.69)</td>
              <td class="mono">21.5% (0.51)</td>
            </tr>
            <tr>
              <td>18-Class + Context (B)</td>
              <td class="mono" style="color:var(--blue);font-weight:700;">75.4% (1.24)</td>
              <td class="mono">58.5% (<strong>1.35</strong>)</td>
              <td class="mono">58.5% (1.03)</td>
              <td class="mono">56.9% (<strong>1.25</strong>)</td>
            </tr>
            <tr>
              <td>Blind A/B Tie+Win (B)</td>
              <td class="mono">Baseline</td>
              <td class="mono" style="color:var(--ok);font-weight:700;">52.9% (60% A)</td>
              <td class="mono">42.6% (54% A)</td>
              <td class="mono">51.5% (44% A)</td>
            </tr>
            <tr>
              <td>Clean Specificity (N=16)</td>
              <td class="mono" style="color:var(--ok);font-weight:700;">93.8% (15/16)</td>
              <td class="mono">87.5% (14/16)</td>
              <td class="mono">75.0% (12/16)</td>
              <td class="mono">87.5% (14/16)</td>
            </tr>
            <tr>
              <td>Avg Latency / Frame</td>
              <td class="mono">1.5s–5.9s</td>
              <td class="mono">~14.7s</td>
              <td class="mono">12.5s</td>
              <td class="mono">~4.0s (OpenRouter)</td>
            </tr>
          </tbody>
        </table>
        <p style="font-size:11.6px;color:var(--muted);margin:10px 0 0;">
          <strong>Vision vs. Reasoning split &amp; endpoint variance:</strong> <code>nemotron-3.5-super-vl</code> (120B/12B MoE) struggles on raw 3D-print surface texture alone (<code>20.0%</code> Var A—over-calling <code>stringing</code> on 30/68 items and <code>clean</code> on 19/68), yet surges <strong>+36.9 pts to 56.9%</strong> and <strong>1.25/2 fixes</strong> once given symptom context (Var B), outscoring Flash-Lite (<code>1.24</code>) on fix quality. On repeat <code>temperature=0</code> checks across the 29-image set, OpenRouter's Nemotron endpoint also showed ~7–10% borderline jitter (<code>26/29</code> raw &amp; <code>27/29</code> USB identical across two runs).
        </p>
      </div>
    </div>
  </section>

  <!-- END-TO-END KLIPPER LOOP SIMULATOR -->
  <section>
    <div class="sec-head">
      <div>
        <h2>3. End-to-End Loop: USB Camera Frame → Local VLM JSON → Klipper / Moonraker Action</h2>
        <p class="sec-sub">Select one of our external USB webcam captures (taken on printed test parts to simulate a mounted printer camera) to inspect the structured diagnosis and downstream Klipper adjustment step.</p>
      </div>
    </div>
    <div class="panel">
      <div class="controls-row" style="margin-bottom:14px;">
        <div class="seg-group" id="simSelector"></div>
      </div>
      <div class="sim-grid" id="simView"></div>

      <div style="border-top:1px solid var(--border);margin-top:20px;padding-top:18px;">
        <div class="grid-2" style="align-items:center;">
          <div>
            <h3 style="margin:0 0 8px;font-size:15px;">Per-Frame Processing Latency in the Klipper Loop</h3>
            <div class="bar-row" style="grid-template-columns:175px 1fr 118px;">
              <span class="mname">gemini-3.5-flash-lite</span>
              <div class="bar-track"><div class="bar-fill" style="width:10.3%;background:#93c5fd"></div></div>
              <span class="bar-val" style="font-size:11px;">1.5s · 0 think</span>
            </div>
            <div class="bar-row" style="grid-template-columns:175px 1fr 118px;">
              <span class="mname">nemotron-3.5-super-vl</span>
              <div class="bar-track"><div class="bar-fill" style="width:27.2%;background:#a78bfa"></div></div>
              <span class="bar-val" style="font-size:11px;">4.0s · ~721 tok</span>
            </div>
            <div class="bar-row" style="grid-template-columns:175px 1fr 118px;">
              <span class="mname">gemini-3.8-flash</span>
              <div class="bar-track"><div class="bar-fill" style="width:40.1%;background:#60a5fa"></div></div>
              <span class="bar-val" style="font-size:11px;">5.9s · ~242 tok</span>
            </div>
            <div class="bar-row" style="grid-template-columns:175px 1fr 118px;">
              <span class="mname">gemma-4-26b-a4b-it</span>
              <div class="bar-track"><div class="bar-fill" style="width:85.0%;background:#2dd4bf"></div></div>
              <span class="bar-val" style="font-size:11px;">12.5s · ~785 tok</span>
            </div>
            <div class="bar-row" style="grid-template-columns:175px 1fr 118px;">
              <span class="mname">gemma-4-31b-it</span>
              <div class="bar-track"><div class="bar-fill" style="width:100%;background:#ff6b2b"></div></div>
              <span class="bar-val" style="font-size:11px;">14.7s · ~354 tok</span>
            </div>
          </div>
          <div class="callout cyan" style="margin-top:0;">
            <strong>Closed-loop timing vs. physical print speed:</strong> A Klipper retraction or Pressure Advance tower segment takes <strong>5–15 minutes (300–900s)</strong> to print before inspecting a single snapshot—so even <code>12.5–14.7s</code> adds <strong>&lt;3% cycle overhead</strong>. Moreover, ~90% of Gemma 4's latency goes to internal chain-of-thought (<code>~785</code> thinking tokens on A4B vs. only <code>~50</code> JSON tokens); capping thinking mode when self-hosting locally (<code>llama.cpp</code> / <code>vLLM</code>) cuts local inference to <strong>~2–3s/frame</strong>.
          </div>
        </div>
      </div>
    </div>
  </section>

  <!-- CURATED VISUAL GALLERY -->
  <section>
    <div class="sec-head">
      <div>
        <h2>4. Curated Visual Case Studies: What Worked &amp; What Tripped the Models</h2>
        <p class="sec-sub">${gallerySubtitle}</p>
      </div>
      ${filterButtons}
    </div>
    <div class="gallery-grid" id="galleryGrid"></div>
  </section>

  <!-- METHODOLOGY & HARDWARE RECOMMENDATIONS -->
  <section>
    <div class="sec-head">
      <div>
        <h2>5. Methodology &amp; Printer Hardware Design Takeaways</h2>
        <p class="sec-sub">How the tests were controlled and what our failures imply for physical printer integration.</p>
      </div>
    </div>
    <div class="panel">
      <div class="meth-grid">
        <div class="meth-card">
          <h4>Deterministic &amp; Contamination-Checked</h4>
          <p>All runs used <code>temperature=0</code>, SHA-256 deduplicated images, and strict schemas. Splitting wild posts by year confirmed 2026 pure-visual accuracy (<code>55.6%</code>) matches overall accuracy (<code>55.9%</code>), ruling out pretraining memorization.</p>
        </div>
        <div class="meth-card">
          <h4>Calibrated 480p USB Degradation</h4>
          <p>Measuring our external USB test webcam revealed ~480p effective optical sharpness (3×3 Laplacian σ=4.94 inside a 1080p MJPEG container). We downscaled all 29 test images to ≤640px, applied lens blur (σ=0.75), seeded CMOS luma/chroma grain, and 4:2:0 JPEG compression.</p>
        </div>
        <div class="meth-card">
          <h4>USB Webcam = Ready for Stringing</h4>
          <p>Gap-spanning defects (stringing, oozing) maintain strong figure-ground contrast at 480p, letting even 4B-active open models hit 81.5% F1. Subtle surface relief (corner blobs, fine zits) washes out—requiring grazing side-LEDs or closer nozzle-cam optics for Pressure Advance.</p>
        </div>
        <div class="meth-card">
          <h4>Independent Flags &amp; G-Code Awareness</h4>
          <p>Real failures co-occur (stringing + overhang sag), so production prompts should emit independent booleans per defect family rather than mutually exclusive classes—and run on known calibration towers so intentional bridged geometry isn't misread as stringing.</p>
        </div>
      </div>
    </div>
  </section>

  <footer>
    Print Defect Detection · Automated Vision Calibration Exploration for Klipper &amp; Moonraker · Junction
  </footer>
</div>

<script>
const BENCH_DATA = {
  three: {
    orig: {
      metrics: [
        { name: "Overall 3-Class Accuracy", note: "N=29 prints", vals: [69.0, 86.2, 79.3, 65.5] },
        { name: "Stringing F1 Score", note: "Precision × Recall balance", vals: [78.6, 87.5, 96.6, 85.7] },
        { name: "Other-Defect Recall", note: "Blobs, zits, overhangs, walls", vals: [50.0, 83.3, 63.6, 18.2] },
        { name: "Clean Specificity (No False Alarms)", note: "True negative rate", vals: [100.0, 33.3, 66.7, 66.7] }
      ],
      insight: "<strong>Original Crisp Photos (3-Class):</strong> Both open Gemma 4 models and <code>nemotron-3.5-super-vl</code> hit <strong>100% stringing recall (15/15)</strong>, with 4B-active <code>gemma-4-26b-a4b-it</code> achieving <strong>96.6% Stringing F1</strong>. Gemini Flash looks lower at 69.0% only because it attributed multi-defect prints to their co-occurring defect—click <em>Binary Gate</em> above.<br/><span style='color:var(--muted);font-size:12px;'><strong>Note on Nemotron run-to-run variation (temperature=0):</strong> Across two identical passes on OpenRouter, <code>26/29 (89.7%)</code> predictions stayed identical with 3 borderline flips: overall accuracy remained <code>65.5% (19/29)</code>, Stringing F1 varied <code>85.7% ↔ 87.5%</code> (recall <code>15/15 ↔ 14/15</code>), and <code>other_defect</code> recall varied <code>18.2% ↔ 27.3%</code> (severity stayed <code>10/11</code> within ±1 tier).</span>"
    },
    usb: {
      metrics: [
        { name: "Overall 3-Class Accuracy", note: "N=29 @ ≤640px + CMOS noise", vals: [58.6, 65.5, 62.1, 55.2] },
        { name: "Stringing F1 Score", note: "Survives 480p webcam!", vals: [85.7, 82.8, 81.5, 78.6] },
        { name: "Other-Defect Recall", note: "Surface zits washed out by grain", vals: [18.2, 36.4, 36.4, 18.2] },
        { name: "Clean Specificity (No False Alarms)", note: "0% false alarms on all 4 models!", vals: [100.0, 100.0, 100.0, 100.0] }
      ],
      insight: "<strong>480p USB Webcam Stress Test (3-Class):</strong> Stringing F1 holds steady across all four models at <strong>78.6%–85.7%</strong> and false alarms drop to <strong>0% across every model (3/3 clean)</strong>, while subtle surface zits/bulges wash out into sensor noise (<code>other_defect</code> recall drops to 18.2%–36.4%).<br/><span style='color:var(--muted);font-size:12px;'><strong>Note on Nemotron run-to-run variation (temperature=0):</strong> Across two identical USB passes, <code>27/29 (93.1%)</code> predictions matched with 2 borderline flips, shifting overall accuracy <code>55.2% ↔ 62.1%</code>, Stringing F1 <code>78.6% ↔ 85.7%</code>, and <code>other_defect</code> recall <code>18.2% ↔ 27.3%</code> (clean specificity stayed <code>100%</code> and severity <code>8/11</code> within ±1 tier).</span>"
    }
  },
  binary: {
    orig: {
      metrics: [
        { name: "Binary Accuracy (Clean vs. Defect)", note: "N=29 prints", vals: [89.7, 93.1, 82.1, 79.3] },
        { name: "Defect Recall (All Defects)", note: "26 defective prints", vals: [88.5, 100.0, 84.0, 80.8] },
        { name: "Defect Precision", note: "Flagged prints that truly need tuning", vals: [100.0, 92.9, 95.5, 95.5] },
        { name: "Clean Specificity (No False Alarms)", note: "True negative rate", vals: [100.0, 33.3, 66.7, 66.7] }
      ],
      insight: "<strong>Binary Anomaly Gate (Original Photos):</strong> Collapsing mutually exclusive defect labels jumps <code>gemini-3.8-flash</code> by <strong>+20.7 points (69.0% → 89.7%) with 100% precision</strong>, <code>gemma-4-31b-it</code> reaches <strong>93.1% accuracy (26/26 defects caught)</strong>, and <code>nemotron-3.5-super-vl</code> hits <strong>79.3%</strong> (<code>21/26</code> caught in Run 1, <code>20/26</code> / <code>75.9%</code> in Run 2 due to 1 borderline flip on <code>terrible_corners.jpg</code>)."
    },
    usb: {
      metrics: [
        { name: "Binary Accuracy (Clean vs. Defect)", note: "N=29 @ ≤640px + CMOS noise", vals: [72.4, 82.8, 72.4, 65.5] },
        { name: "Defect Recall (All Defects)", note: "Stringing caught; subtle zits missed", vals: [69.2, 80.8, 69.2, 61.5] },
        { name: "Defect Precision", note: "Zero false recalibrations!", vals: [100.0, 100.0, 100.0, 100.0] },
        { name: "Clean Specificity (No False Alarms)", note: "3/3 clean passed on all 4 models", vals: [100.0, 100.0, 100.0, 100.0] }
      ],
      insight: "<strong>Binary Anomaly Gate (480p USB Degraded):</strong> Every single model achieves <strong>100% defect precision (zero false recalibrations)</strong>, with <code>gemma-4-31b-it</code> still catching <strong>80.8%</strong> of all defects vs. <code>69.2%</code> on Flash/Gemma A4B and <code>61.5%</code> on Nemotron VL (identical <code>65.5%</code> binary accuracy across both Nemotron repeat runs)."
    }
  }
};

const MODELS = [
  { label: "gemini-3.8-flash", color: "#60a5fa" },
  { label: "gemma-4-31b-it", color: "#ff6b2b" },
  { label: "gemma-4-26b-a4b-it", color: "#2dd4bf" },
  { label: "nemotron-3.5-super-vl", color: "#a78bfa" }
];

let curMode = "three";
let curUsb = "orig";

function renderMainChart() {
  const block = BENCH_DATA[curMode][curUsb];
  const container = document.getElementById("mainBarChart");
  container.innerHTML = block.metrics.map(m => \`
    <div class="metric-group">
      <div class="metric-head"><span>\${m.name}</span><span class="metric-note">\${m.note}</span></div>
      \${MODELS.map((mod, idx) => \`
        <div class="bar-row">
          <span class="mname">\${mod.label}</span>
          <div class="bar-track"><div class="bar-fill" style="width:\${m.vals[idx]}%;background:\${mod.color}"></div></div>
          <span class="bar-val">\${m.vals[idx].toFixed(1)}%</span>
        </div>
      \`).join("")}
    </div>
  \`).join("");
  document.getElementById("chartInsight").innerHTML = block.insight;
}

document.querySelectorAll("#modeToggle .seg").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#modeToggle .seg").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    curMode = btn.dataset.mode;
    renderMainChart();
  });
});
document.querySelectorAll("#usbToggle .seg").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#usbToggle .seg").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    curUsb = btn.dataset.usb;
    renderMainChart();
  });
});
renderMainChart();

// Telemetry Ablation Chart (4 Models × Variants A / T / B)
const TELEM_DATA = {
  A: {
    cls: [58.5, 36.9, 36.9, 20.0],
    str: [85.7, 85.7, 100.0, 100.0],
    fixPct: [39.0, 39.5, 33.0, 22.0],
    fixRaw: ["0.78 / 2.0", "0.79 / 2.0", "0.66 / 2.0", "0.44 / 2.0"],
    insight: "<strong>Variant A (Pure Pixels, Zero Text):</strong> Without text across 18 defect classes, <code>gemini-3.5-flash-lite</code> hits <strong>58.5%</strong>, both Gemma 4 models hit <strong>36.9%</strong> ( nearly 2× higher than <code>nemotron-3.5-super-vl</code>'s <strong>20.0%</strong>, which over-triggers stringing/clean on fine layer textures), while Gemma A4B and Nemotron both catch <strong>100% (7/7)</strong> of wild stringing."
  },
  T: {
    cls: [67.7, 40.0, 40.0, 21.5],
    str: [85.7, 71.4, 100.0, 100.0],
    fixPct: [51.5, 46.5, 34.5, 25.5],
    fixRaw: ["1.03 / 2.0", "0.93 / 2.0", "0.69 / 2.0", "0.51 / 2.0"],
    insight: "<strong>Variant T (+Moonraker/Slicer Telemetry Only):</strong> Injecting machine specs (material, temps, speeds, retraction—zero user text) lifts every model: Flash-Lite jumps <strong>+9.2 pts (58.5% → 67.7%, +32% fix score)</strong> and Gemma 31B climbs to <strong>0.93 / 2.0</strong>, while Nemotron stays bottlenecked by fine visual perception (<strong>21.5%</strong>)."
  },
  B: {
    cls: [75.4, 58.5, 58.5, 56.9],
    str: [100.0, 100.0, 100.0, 100.0],
    fixPct: [62.0, 67.5, 51.5, 62.5],
    fixRaw: ["1.24 / 2.0", "1.35 / 2.0", "1.03 / 2.0", "1.25 / 2.0"],
    insight: "<strong>Variant B (+User Post Context):</strong> With symptom descriptions, all four models hit <strong>100% stringing recall</strong>—and <code>nemotron-3.5-super-vl</code> surges <strong>+36.9 pts (20.0% → 56.9%)</strong> with <strong>1.25 / 2.0</strong> on fixes, confirming its 120B/12B MoE reasoning is strong when not bottlenecked by subtle visual texture."
  }
};
const TELEM_MODELS = [
  { label: "gemini-3.5-flash-lite", color: "#60a5fa" },
  { label: "gemma-4-31b-it", color: "#ff6b2b" },
  { label: "gemma-4-26b-a4b-it", color: "#2dd4bf" },
  { label: "nemotron-3.5-super-vl", color: "#a78bfa" }
];
let curTelemVar = "T";

function renderTelemetry() {
  const d = TELEM_DATA[curTelemVar];
  document.getElementById("telemetryChart").innerHTML = \`
    <div class="metric-group">
      <div class="metric-head"><span>18-Class Closed-Taxonomy Accuracy</span><span class="metric-note">N=65 non-'other' failures</span></div>
      \${TELEM_MODELS.map((m, i) => \`
        <div class="bar-row" style="grid-template-columns:175px 1fr 58px;">
          <span class="mname">\${m.label}</span>
          <div class="bar-track"><div class="bar-fill" style="width:\${d.cls[i]}%;background:\${m.color}"></div></div>
          <span class="bar-val">\${d.cls[i].toFixed(1)}%</span>
        </div>
      \`).join("")}
    </div>
    <div class="metric-group">
      <div class="metric-head"><span>Wild Stringing Recall</span><span class="metric-note">N=7 r/FixMyPrint stringing threads</span></div>
      \${TELEM_MODELS.map((m, i) => \`
        <div class="bar-row" style="grid-template-columns:175px 1fr 58px;">
          <span class="mname">\${m.label}</span>
          <div class="bar-track"><div class="bar-fill" style="width:\${d.str[i]}%;background:\${m.color}"></div></div>
          <span class="bar-val">\${d.str[i].toFixed(1)}%</span>
        </div>
      \`).join("")}
    </div>
    <div class="metric-group" style="margin-bottom:6px;">
      <div class="metric-head"><span>Actionable Fix Rubric Score</span><span class="metric-note">Multimodal Judge (0–2 scale)</span></div>
      \${TELEM_MODELS.map((m, i) => \`
        <div class="bar-row" style="grid-template-columns:175px 1fr 74px;">
          <span class="mname">\${m.label}</span>
          <div class="bar-track"><div class="bar-fill" style="width:\${d.fixPct[i]}%;background:\${m.color}"></div></div>
          <span class="bar-val">\${d.fixRaw[i]}</span>
        </div>
      \`).join("")}
    </div>
  \`;
  document.getElementById("telemInsight").innerHTML = d.insight;
}
document.querySelectorAll("#telemVarToggle .seg").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#telemVarToggle .seg").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    curTelemVar = btn.dataset.var;
    renderTelemetry();
  });
});
// Default highlight Variant T button to match curTelemVar="T"
document.querySelectorAll("#telemVarToggle .seg").forEach(b => {
  b.classList.toggle("active", b.dataset.var === curTelemVar);
});
renderTelemetry();

// Severity SVG Strip Plot
(function renderSeveritySvg() {
  const pts = ${severityPointsJson};
  const svg = document.getElementById("severitySvg");
  const padL = 92, padR = 22, padT = 22, padB = 34;
  const W = 420, H = 235;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  const x = v => padL + v * plotW;
  const yTier = t => padT + ((3 - t) + 0.5) * (plotH / 3);

  let out = "";
  // Tier bands
  const bands = [
    { t: 3, label: "Human Tier 3", sub: "Heavy", x0: 0.67, x1: 1.0 },
    { t: 2, label: "Human Tier 2", sub: "Slight", x0: 0.34, x1: 0.66 },
    { t: 1, label: "Human Tier 1", sub: "Specs", x0: 0.0, x1: 0.33 }
  ];
  bands.forEach(b => {
    const cy = yTier(b.t);
    out += \`<line x1="\${padL}" y1="\${cy}" x2="\${W - padR}" y2="\${cy}" stroke="#252d38" stroke-dasharray="3,3"/>\`;
    out += \`<rect x="\${x(b.x0)}" y="\${cy - 18}" width="\${x(b.x1) - x(b.x0)}" height="36" fill="rgba(45,212,191,0.07)" stroke="rgba(45,212,191,0.22)" rx="4"/>\`;
    out += \`<text x="8" y="\${cy - 2}" fill="#e6edf3" font-size="11" font-family="monospace">\${b.label}</text>\`;
    out += \`<text x="8" y="\${cy + 12}" fill="#8b96a5" font-size="10">\${b.sub}</text>\`;
  });
  // X axis ticks
  [0, 0.33, 0.67, 1.0].forEach(v => {
    out += \`<line x1="\${x(v)}" y1="\${padT}" x2="\${x(v)}" y2="\${H - padB}" stroke="#1e2530"/>\`;
    out += \`<text x="\${x(v)}" y="\${H - 10}" fill="#8b96a5" font-size="10.5" text-anchor="middle" font-family="monospace">\${v.toFixed(2)}</text>\`;
  });

  pts.forEach((p, idx) => {
    const baseY = yTier(p.human);
    const jitter = ((idx % 3) - 1) * 4;
    out += \`<circle cx="\${x(p.flash)}" cy="\${baseY - 8 + jitter}" r="4.5" fill="#60a5fa" opacity="0.9"><title>\${p.id} · Flash: \${p.flash}</title></circle>\`;
    out += \`<circle cx="\${x(p.g31)}" cy="\${baseY + jitter}" r="4.5" fill="#ff6b2b" opacity="0.9"><title>\${p.id} · Gemma 31B: \${p.g31}</title></circle>\`;
    out += \`<circle cx="\${x(p.ga4)}" cy="\${baseY + 8 + jitter}" r="4.5" fill="#2dd4bf" opacity="0.9"><title>\${p.id} · Gemma A4B: \${p.ga4}</title></circle>\`;
  });
  svg.innerHTML = out;
})();

// Simulator
const SIM_CASES = ${simCasesJson};
let curSimIdx = 0;
function renderSimulator() {
  const simSel = document.getElementById("simSelector");
  simSel.innerHTML = SIM_CASES.map((c, i) =>
    \`<button class="seg \${i === curSimIdx ? 'active' : ''}" data-idx="\${i}">\${c.name}</button>\`
  ).join("");
  simSel.querySelectorAll("button").forEach(b => {
    b.addEventListener("click", () => { curSimIdx = Number(b.dataset.idx); renderSimulator(); });
  });

  const c = SIM_CASES[curSimIdx];
  document.getElementById("simView").innerHTML = \`
    <div class="sim-img-wrap">
      <img src="\${c.img}" alt="\${c.name}" />
    </div>
    <div>
      <div class="telem-pill">Moonraker Telemetry: \${c.telemetry}</div>
      <div class="code-box">{
  <span class="k">"model"</span>: <span class="s">"\${c.modelUsed}"</span>,
  <span class="k">"predicted_class"</span>: <span class="s">"\${c.defect}"</span>,
  <span class="k">"severity"</span>: <span class="cmd">\${c.severity.toFixed(2)}</span>, <span class="c">// \${c.tier}</span>
  <span class="k">"reasoning"</span>: <span class="s">"\${c.reasoning}"</span>
}</div>
      <div class="code-box" style="border-color:rgba(255,107,43,0.35);">
\${c.klipperCmds.map(l => l.startsWith("#") ? \`<span class="c">\${l}</span>\` : \`<span class="cmd">\${l}</span>\`).join("\\n")}
      </div>
    </div>
  \`;
}
renderSimulator();

// Context.dev Live Forum -> Ground Truth Explorer
const CTX_RECORDS = [
  {
    id: "fixmyprint_1u3vzsg",
    short: "TPU Stringing (25 comments · Solved)",
    url: "https://www.reddit.com/r/FixMyPrint/comments/1u3vzsg/cant_understand_tpu/",
    comments: 25,
    telemetry: "Bambu P1S, Priline 98a TPU",
    defect: "stringing",
    solved: true,
    evidenceIds: ["or8ei5k", "orbkp5y", "oratz2y", "oruu5pn"],
    causes: ["Insufficient TPU drying temp (55°C instead of 65–70°C)", "Suboptimal retraction distance/speed for TPU"],
    fixes: ["Increase TPU drying temperature to 65–70°C", "Set retraction length to 0.6 mm & enable Avoid crossing walls"],
    consensus: "OP confirmed raising dryer temp to 70°C and setting 0.6 mm retraction completely eliminated stringing.",
    grades: "Flash-Lite: 2/2 · Gemma 31B: 2/2 · Gemma A4B: 2/2 · Nemotron VL: 2/2"
  },
  {
    id: "fixmyprint_t8kb40",
    short: "Klipper ASA Blobs (25 comments · Solved)",
    url: "https://www.reddit.com/r/FixMyPrint/comments/t8kb40/blobs_underextrusion/",
    comments: 25,
    telemetry: "Ender 3 Pro + Klipper, SuperSlicer, DuraPro ASA @ 230°C / 100°C bed",
    defect: "blobs_zits",
    solved: true,
    evidenceIds: ["hzqbv6t", "hzoj0y6", "hzovm3c", "hzpc9k3"],
    causes: ["Hotend temperature too high (230°C) causing surface zits/pits", "Filament moisture steam popping"],
    fixes: ["Lower hotend temperature by 10°C (230°C -> 220°C)", "Dry ASA spool before printing"],
    consensus: "OP confirmed dropping hotend temperature 10°C in Klipper completely eliminated the hull blobs.",
    grades: "Flash-Lite: blobs_zits (2/2) · Nemotron VL: blobs_zits (2/2) · Gemma 31B/A4B: underextrusion (0/2)"
  },
  {
    id: "fixmyprint_1bia375",
    short: "Y-Axis Layer Shift (52 comments · Solved)",
    url: "https://www.reddit.com/r/FixMyPrint/comments/1bia375/my_yaxis_is_having_layer_shifts_please_help/",
    comments: 52,
    telemetry: "Not specified in initial post",
    defect: "layer_shift",
    solved: true,
    evidenceIds: ["kvjiq12", "kvjjnc0", "kvju5ea", "kvm6qpa"],
    causes: ["Loose Y-stepper motor mounting bolt", "Undervolted Y-axis stepper driver on mainboard"],
    fixes: ["Tighten Y-stepper bolts & belt pulley grub screws", "Verify stepper driver Vref voltage with multimeter"],
    consensus: "Distilled from 52 comments: OP found a missing Y-motor bolt and low mainboard stepper driver voltage.",
    grades: "Flash-Lite: layer_shift (2/2) · Gemma 31B: z_banding (1/2) · Gemma A4B: 0/2 · Nemotron VL: clean (0/2 A/T -> 2/2 B)"
  }
];
let curCtxIdx = 0;
function renderCtxExplorer() {
  const sel = document.getElementById("ctxSelector");
  sel.innerHTML = CTX_RECORDS.map((r, i) =>
    \`<button class="seg \${i === curCtxIdx ? 'active' : ''}" data-idx="\${i}">\${r.short}</button>\`
  ).join("");
  sel.querySelectorAll("button").forEach(b => {
    b.addEventListener("click", () => { curCtxIdx = Number(b.dataset.idx); renderCtxExplorer(); });
  });
  const r = CTX_RECORDS[curCtxIdx];
  document.getElementById("ctxView").innerHTML = \`
    <div class="telem-pill" style="margin-bottom:8px;">
      Context.dev <code>reddit-post</code> · <strong>\${r.comments} comments parsed</strong> · <a href="\${r.url}" target="_blank" rel="noopener" style="color:var(--cyan);">Source Thread ↗</a>
    </div>
    <div class="code-box" style="margin-top:0;">{
  <span class="k">"id"</span>: <span class="s">"\${r.id}"</span>,
  <span class="k">"printer_context"</span>: <span class="s">"\${r.telemetry}"</span>,
  <span class="k">"defect_class"</span>: <span class="s">"\${r.defect}"</span>,
  <span class="k">"solved"</span>: <span class="cmd">\${r.solved}</span>, <span class="c">// verified OP confirmation</span>
  <span class="k">"evidence_comment_ids"</span>: [\${r.evidenceIds.map(x => \`<span class="s">"\${x}"</span>\`).join(", ")}],
  <span class="k">"likely_causes"</span>: [\${r.causes.map(x => \`<span class="s">"\${x}"</span>\`).join(", ")}],
  <span class="k">"recommended_fixes"</span>: [\${r.fixes.map(x => \`<span class="s">"\${x}"</span>\`).join(", ")}]
}</div>
    <div class="callout cyan" style="margin-top:10px;font-size:12.3px;">
      <strong>Synthesized Consensus:</strong> \${r.consensus}<br/>
      <span style="color:var(--muted);font-family:var(--mono);font-size:11.3px;">Automated S7 Rubric Grades (Var T): \${r.grades}</span>
    </div>
  \`;
}
renderCtxExplorer();

// Curated Case Study Gallery
const CASES = ${cardsJson};
let activeFilter = "all";

function renderGallery() {
  const grid = document.getElementById("galleryGrid");
  const visible = CASES.filter(c => activeFilter === "all" || c.group === activeFilter);
  grid.innerHTML = visible.map((c, cardIdx) => {
    const hasToggle = c.modeType === "degrade" || c.modeType === "telemetry";
    const toggleHtml = hasToggle ? \`
      <div class="img-toggle" data-card="\${c.id}">
        <button class="active" data-side="A">\${c.labelA}</button>
        <button data-side="B">\${c.labelB}</button>
      </div>\` : "";
    return \`
      <article class="case-card" id="card-\${c.id}">
        <div class="case-img-box">
          <img id="img-\${c.id}" src="\${c.imgA}" alt="\${c.title}" loading="lazy" />
          \${toggleHtml}
        </div>
        <div class="case-body">
          <div class="case-badge">\${c.badge}</div>
          <h3>\${c.title}</h3>
          <div class="truth-line">Ground Truth: <strong>\${c.truth}</strong></div>
          \${c.telemetrySnippet ? \`<div class="telem-pill" id="tel-\${c.id}" style="display:none;">\${c.telemetrySnippet}</div>\` : ""}
          <p class="case-takeaway">\${c.takeaway}</p>
          <div class="verdicts" id="verdicts-\${c.id}">
            \${renderVerdictItems(c.verdictsA)}
          </div>
        </div>
      </article>
    \`;
  }).join("");

  grid.querySelectorAll(".img-toggle").forEach(tog => {
    const id = tog.dataset.card;
    const card = CASES.find(x => x.id === id);
    tog.querySelectorAll("button").forEach(btn => {
      btn.addEventListener("click", () => {
        tog.querySelectorAll("button").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        const side = btn.dataset.side;
        const imgEl = document.getElementById("img-" + id);
        if (side === "B" && card.imgB) imgEl.src = card.imgB;
        else imgEl.src = card.imgA;

        const telEl = document.getElementById("tel-" + id);
        if (telEl) telEl.style.display = side === "B" ? "block" : "none";

        const vEl = document.getElementById("verdicts-" + id);
        vEl.innerHTML = renderVerdictItems(side === "B" && card.verdictsB ? card.verdictsB : card.verdictsA);
      });
    });
  });
}

function renderVerdictItems(list) {
  return list.map(v => \`
    <div class="v-item">
      <div class="v-top">
        <span>\${v.model}</span>
        <span class="\${v.ok ? 'v-ok' : 'v-bad'}">\${v.ok ? '✓ ' : '✗ '}\${v.pred}</span>
      </div>
      <div class="v-quote">"\${v.quote}"</div>
    </div>
  \`).join("");
}

const filterWrap = document.getElementById("galleryFilters");
if (filterWrap) {
  filterWrap.querySelectorAll("button").forEach(btn => {
    btn.addEventListener("click", () => {
      filterWrap.querySelectorAll("button").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      activeFilter = btn.dataset.filter;
      renderGallery();
    });
  });
}
renderGallery();
</script>
</body>
</html>`;
}

async function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });

  const publicAssets = await loadAssets(false);
  const publicCards = buildCaseCards(publicAssets, false);
  const publicHtml = renderHtml({
    cards: publicCards,
    ownUsb: publicAssets.ownUsb,
    isUncensored: false,
  });
  const publicPath = path.join(OUT_DIR, "index.html");
  fs.writeFileSync(publicPath, publicHtml, "utf8");
  console.log(
    `Wrote PUBLIC (USB-only) showcase: ${publicPath} (${(fs.statSync(publicPath).size / 1024).toFixed(1)} KB)`
  );

  const fullAssets = await loadAssets(true);
  const fullCards = buildCaseCards(fullAssets, true);
  const fullHtml = renderHtml({
    cards: fullCards,
    ownUsb: fullAssets.ownUsb,
    isUncensored: true,
  });
  const fullPath = path.join(OUT_DIR, "local_uncensored.html");
  fs.writeFileSync(fullPath, fullHtml, "utf8");
  console.log(
    `Wrote LOCAL (uncensored) showcase: ${fullPath} (${(fs.statSync(fullPath).size / 1024).toFixed(1)} KB)`
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
