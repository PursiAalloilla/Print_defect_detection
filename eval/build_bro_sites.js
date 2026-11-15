/**
 * build_bro_sites.js — Generates /bro-style plain-language showcase sites in /workspace/wSite/bro/:
 *   1. wSite/bro/index.html            — Public Edition (ONLY own Prusa USB camera photos)
 *   2. wSite/bro/local_uncensored.html — Local Demo Edition (includes curated scraped & benchmark edge cases)
 *
 * Follows https://github.com/luchasarie/bro-skill:
 *   - Explain it like a smart friend over a beer ("impossible to misunderstand")
 *   - Simpler, not shorter — zero dense academic/consultant jargon
 *   - Every fact, model name, filename, command, and number survives 100% verbatim
 *   - Flatten stiff ceremony: drop numbered academic headers & turn tables into plain sentences
 */

const fs = require("fs");
const path = require("path");
const sharp = require("sharp");

const ROOT = path.join(__dirname, "..");
const OUT_DIR = path.join(ROOT, "wSite", "bro");

async function toDataUri(relPath, maxDim = 840, quality = 78) {
  const fullPath = path.join(ROOT, relPath);
  const buf = await sharp(fullPath)
    .resize({ width: maxDim, height: maxDim, fit: "inside", withoutEnlargement: true })
    .webp({ quality })
    .toBuffer();
  return `data:image/webp;base64,${buf.toString("base64")}`;
}

async function loadAssets(includeScraped) {
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
    str006_deg: await toDataUri("dataset_usb_degraded/other_defect/other_defect006.jpg").catch(() =>
      toDataUri("dataset_usb_degraded/stringing/stringing006.jpg")
    ),
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
      badge: "External USB Cam Sim · golden_whispV3.jpg",
      title: "Yellow Stringing Tower Shot on Our External USB Webcam",
      truth: "stringing",
      modeType: "degrade",
      imgA: ownUsb.golden_whisp_orig,
      imgB: ownUsb.golden_whisp_deg,
      labelA: "Original USB Shot",
      labelB: "Crushed to 640p + Noise",
      takeaway:
        "We pointed a separate USB webcam at the print bed to simulate a low-cost printer camera. Both open Gemma 4 models immediately spotted that the print was rough and defective, while gemini-3.8-flash initially passed the raw frame as clean—until shrinking it to 640p with extra noise made the stringy web between the towers stand out enough for Flash and Gemma A4B to catch it.",
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
      badge: "External USB Cam Sim · golden_support_piece.jpg",
      title: "Chewed-Up Right Wall: Big Model vs. Small 4B Model",
      truth: "other_defect (broken right wall)",
      modeType: "degrade",
      imgA: ownUsb.golden_support_orig,
      imgB: ownUsb.golden_support_deg,
      labelA: "Original USB Shot",
      labelB: "Crushed to 640p + Noise",
      takeaway:
        "Look at the right column—the wall tore apart like a ladder. On the raw photo, the two bigger models (gemini-3.8-flash and gemma-4-31b-it) caught it, while the smaller 4B-active model (gemma-4-26b-a4b-it) missed it and said clean. Once we added extra 640p blur and grain, nobody got it right anymore.",
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
      badge: "External USB Cam Sim · green_slant2.jpg",
      title: "Rough Overhang That Disappears Into Camera Grain",
      truth: "other_defect (rough overhang on the right curve)",
      modeType: "degrade",
      imgA: ownUsb.green_slant2_orig,
      imgB: ownUsb.green_slant2_deg,
      labelA: "Original USB Shot",
      labelB: "Crushed to 640p + Noise",
      takeaway:
        "Green bumps on a green wall have very little contrast. On the original shot, Flash and Gemma 31B spotted the rough curve on the right. Click the 640p + Noise button: that rough texture blends into the camera grain, and all three models call the print smooth.",
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
      badge: "External USB Cam Sim · green_slant3.jpg",
      title: "Same Green Part, Except a Bright White Scar Survives Blur",
      truth: "other_defect (wall band + white scar on top right)",
      modeType: "degrade",
      imgA: ownUsb.green_slant3_orig,
      imgB: ownUsb.green_slant3_deg,
      labelA: "Original USB Shot",
      labelB: "Crushed to 640p + Noise",
      takeaway:
        "Compare this to green_slant2. Both Gemma models still caught this defect even after we degraded the image to 640p because a bright white blemish on matte green plastic keeps strong contrast even on a low-end webcam.",
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
      badge: "External USB Cam Sim · gray_problem.jpg",
      title: "The Reference Webcam Shot (Glare + Tree-Support Fakeout)",
      truth: "other_defect (wavy wall; sharpness σ = 4.94)",
      modeType: "degrade",
      imgA: ownUsb.gray_problem_orig,
      imgB: ownUsb.gray_problem_deg,
      labelA: "Original USB Shot",
      labelB: "Crushed to 640p + Noise",
      takeaway:
        "This is the exact photo we measured to copy our USB webcam's blurriness (the file says 1920x1080, but the cheap lens only resolves ~480p of real detail, σ=4.94). Bright glare hid the wavy wall from Flash, and the skinny tree support in the back fooled Gemma 31B into yelling 'stringing'—only Gemma A4B got the original shot right.",
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
      badge: "4/4 Models Baited · 3dprinting_1ihsom2_0.jpg",
      title: "The Millennium Falcon 'String-Art' Fakeout",
      truth: "clean (the strings are literally the design!)",
      modeType: "single",
      imgA: extra.falcon,
      labelA: "Clean Showcase Print (N=16)",
      takeaway:
        "It is easy to see why every model missed this one. Out of 16 clean prints in context_dev, gemini-3.5-flash-lite got 15/16 right (93.8%), while gemma-4-31b-it and nemotron-3.5-super-vl both got 14/16 (87.5%)—and ALL FOUR models flagged this print. Those hundreds of threads are intentional single-strand 'hyperspace streaks' suspending the Falcon in mid-air. Without knowing the 3D file, any camera sees severe stringing.",
      verdictsA: [
        { model: "gemini-3.5-flash-lite", ok: false, pred: "stringing", quote: "Only false alarm out of 16 clean prints (93.8% clean pass rate)." },
        { model: "gemma-4-31b-it", ok: false, pred: "stringing", quote: "Also called stringing (14/16 = 87.5% clean pass rate overall)." },
        { model: "nemotron-3.5-super-vl", ok: false, pred: "stringing", quote: "Also called stringing (14/16 = 87.5% clean pass rate overall)." },
        { model: "gemma-4-26b-a4b-it", ok: false, pred: "stringing", quote: "Called stringing too (12/16 = 75.0%)—which is why your printer should calibrate on a known test tower, not random string-art." },
      ],
    },
    {
      id: "clean_zoro_pair",
      group: "degrade",
      badge: "Funny Plot Twist · Clean_zoro.webp",
      title: "When Making the Camera Worse Actually Fixed False Alarms",
      truth: "clean (2 tiny hairs near the sword hilts)",
      modeType: "degrade",
      imgA: extra.zoro_orig,
      imgB: extra.zoro_deg,
      labelA: "Sharp Phone Photo",
      labelB: "480p USB + Grain",
      takeaway:
        "On the sharp phone photo, all three models spotted two microscopic hairs between Zoro's sword handles. Flash let it slide ('minor enough to call clean'), while both Gemma models followed our rule 'light wisps count as stringing' literally. Once blurred to 480p webcam quality, those tiny hairs vanished—and false alarms dropped to 0% on every model.",
      verdictsA: [
        { model: "gemini-3.8-flash", ok: true, pred: "clean", quote: "Only a couple of negligible, hairline stringing wisps visible near the sword hilts and hair tips, minor enough to classify as overall clean." },
        { model: "gemma-4-31b-it", ok: false, pred: "stringing", quote: "Fine strands of filament are visible between the sword handles and around the spiky hair." },
        { model: "gemma-4-26b-a4b-it", ok: false, pred: "stringing", quote: "Fine filament strands are visible between the sword hilts and near the top of the left sword." },
      ],
      verdictsB: [
        { model: "gemini-3.8-flash", ok: true, pred: "clean", quote: "Passed as clean." },
        { model: "gemma-4-31b-it", ok: true, pred: "clean", quote: "Passed as clean — webcam blur acted like a free filter against microscopic dust/hairs." },
        { model: "gemma-4-26b-a4b-it", ok: true, pred: "clean", quote: "Passed as clean — 3/3 clean prints passed under USB quality." },
      ],
    },
    {
      id: "str001_pair",
      group: "degrade",
      badge: "Why Stringing Works on Cheap Cams · stringing001",
      title: "Spiderwebs Across Open Air Still Show Up at 480p",
      truth: "stringing (Human Tier 2 — slight wisps)",
      modeType: "degrade",
      imgA: extra.str001_orig,
      imgB: extra.str001_deg,
      labelA: "Sharp Photo",
      labelB: "480p USB + Grain",
      takeaway:
        "Toggle between the sharp photo and the grainy 480p USB version: you can still totally see the pale threads stretching between the four black cones, and so can all three models (scoring 0.60–0.75 severity, right in line with Human Tier 2). Strands hanging in mid-air have way more contrast than bumps on a flat wall.",
      verdictsA: [
        { model: "gemini-3.8-flash", ok: true, pred: "stringing", quote: "Caught stringing across the four-cone test print." },
        { model: "gemma-4-31b-it", ok: true, pred: "stringing (0.80)", quote: "Fine filament strands bridging the gaps between the four vertical cones." },
        { model: "gemma-4-26b-a4b-it", ok: true, pred: "stringing (0.70)", quote: "Visible cobwebbing and thin wisps spanning between the test pillars." },
      ],
      verdictsB: [
        { model: "gemini-3.8-flash", ok: true, pred: "stringing (0.65)", quote: "Exact Tier-2 severity match (0.65) even on noisy 640x480 JPEG." },
        { model: "gemma-4-31b-it", ok: true, pred: "stringing (0.75)", quote: "Still catches the strands through heavy sensor grain." },
        { model: "gemma-4-26b-a4b-it", ok: true, pred: "stringing (0.60)", quote: "Exact Tier-2 severity match (0.60) on the 4B-active open model." },
      ],
    },
    {
      id: "od004_pair",
      group: "degrade",
      badge: "Where Cheap Webcams Fail · other_defect004",
      title: "24.5 Megapixel Zits Completely Vanish at 480p",
      truth: "other_defect (tiny surface zits & wisps on raised dots)",
      modeType: "degrade",
      imgA: extra.od004_orig,
      imgB: extra.od004_deg,
      labelA: "24.5 MP Close-Up",
      labelB: "480x640 USB + Grain",
      takeaway:
        "On the 4284x5712 original, every model sees the tiny zits and wisps. Shrink it down to 480x640 with webcam noise and all three models call the surface completely smooth. Cheap USB webcams work well for stringing, while tiny surface zits or Pressure Advance corner bulges need a closer camera or angled side-lighting to cast shadows.",
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
      badge: "Two Problems at Once · stringing006.webp",
      title: "Why Forcing One Label Made Gemini Flash Look Dumb",
      truth: "stringing (plus drooping overhang loops under the roof)",
      modeType: "degrade",
      imgA: extra.str006_orig,
      imgB: extra.str006_deg,
      labelA: "Sharp Photo",
      labelB: "480p USB + Grain",
      takeaway:
        "Look under the Benchy's roof: it has wispy hairs AND fat drooping loops from bad overhang cooling. Because our test forced the AI to pick ONE bucket, Flash picked other_defect (overhangs) and got marked wrong! When we changed the rule to 'just tell me if the print is clean or messed up,' Flash jumped +20.7 points (69.0% → 89.7%).",
      verdictsA: [
        { model: "gemini-3.8-flash", ok: false, pred: "other_defect", quote: "Severe overhang and bridging failures, characterized by sagging and looped extrusions along the roofline, chimney, and hull." },
        { model: "gemma-4-31b-it", ok: true, pred: "stringing", quote: "Extensive cobweb-like stringing is visible under the cabin roof and around the chimney." },
        { model: "gemma-4-26b-a4b-it", ok: true, pred: "stringing", quote: "Significant messy filament strands and clumps are visible around the cabin, smokestack, and hull edges." },
      ],
      verdictsB: [
        { model: "gemini-3.8-flash", ok: true, pred: "stringing (0.48)", quote: "At 640p, classified as stringing around cabin and chimney." },
        { model: "gemma-4-31b-it", ok: true, pred: "stringing (0.50)", quote: "Detected filament strands bridging cabin openings." },
        { model: "gemma-4-26b-a4b-it", ok: true, pred: "stringing (0.30)", quote: "Detected messy filament artifacts around cabin roofline." },
      ],
    },
    {
      id: "telemetry_benchies",
      group: "telemetry",
      badge: "Klipper Settings Unlock · fixmyprint_1mveel1",
      title: "7 Benchies: Giving the AI Printer Settings Turns 1/2 Into 2/2",
      truth: "overhang_curling (printing way too fast with weak fan)",
      modeType: "telemetry",
      imgA: extra.benchies7,
      labelA: "Photo Only (Var A)",
      labelB: "+ Printer Settings (Var T)",
      telemetrySnippet: "Filament: Sunlu PLA · Speed: 200mm/s Outer / 300mm/s Inner · Temp: 215°C · Layer: 0.16mm · Fan: 20%–60%",
      takeaway:
        "With just the photo (Var A), Flash-Lite focused on tiny chimney hairs and suggested retraction tweaks (1/2). Handing it only the settings Klipper/Moonraker already knows—printing PLA at 200–300mm/s with the fan capped at 20%–60%—switched the diagnosis to overhang_curling and recommended 100% fan speed (2/2 score).",
      verdictsA: [
        { model: "Variant A (Photo Only)", ok: false, pred: "stringing · Score 1/2", quote: "Blamed retraction distance/speed because of minor chimney wisps, totally missing the curled-up hulls." },
      ],
      verdictsB: [
        { model: "Variant T (+ Printer Settings)", ok: true, pred: "overhang_curling · Score 2/2", quote: "Nailed it: crank cooling fan to 100% and drop nozzle temp 5–10°C—the exact fix that solved OP's print." },
      ],
    },
    {
      id: "telemetry_octopus",
      group: "telemetry",
      badge: "Sneaky Slicer Trap · fixmyprint_pmtbf8",
      title: "PETG Octopus: When 'More Retraction' Actually Causes Stringing",
      truth: "stringing (245°C PETG + crazy 8mm retraction sucking air)",
      modeType: "telemetry",
      imgA: extra.octopus,
      labelA: "Photo Only (Var A)",
      labelB: "+ Printer Settings (Var T)",
      telemetrySnippet: "Material: Gray PETG · Nozzle Temp: 245°C · Retraction Distance: 8mm · Retraction Speed: 40mm/s",
      takeaway:
        "From the photo alone (Var A), the pitted tentacles tricked the AI into calling underextrusion and suggesting a cold pull + hotter nozzle (0/2—that would make it worse!). Adding the printer settings (PETG @ 245°C, 8mm retraction) immediately fixed the diagnosis to stringing and caught the overheating (1/2), though only a seasoned human/rubric caught that 8mm retraction was WAY too long and needed to come down, not go up.",
      verdictsA: [
        { model: "Variant A (Photo Only)", ok: false, pred: "underextrusion · Score 0/2", quote: "Thought the nozzle was clogged—bad advice that would make molten PETG ooze even harder." },
      ],
      verdictsB: [
        { model: "Variant T (+ Printer Settings)", ok: true, pred: "stringing · Score 1/2", quote: "Caught 245°C PETG overheating + wet filament right away, but missed that 8mm retraction was too high instead of too low." },
      ],
    },
  ];

  return [...scrapedCards, ...usbCards];
}

function renderBroHtml({ cards, ownUsb, isUncensored }) {
  const editionBadge = isUncensored
    ? `<span class="pill pill-warn">LOCAL DEMO · FULL GALLERY (SCRAPED + OUR USB)</span>`
    : `<span class="pill pill-ok">PUBLIC VERSION · ONLY OUR OWN USB PHOTOS</span>`;

  const gallerySubtitle = isUncensored
    ? `Here are the wildest examples from our external USB webcam setup and our Context.dev Reddit benchmark—the stuff that worked, and the stuff that tripped the models up. Click the buttons on any photo to flip between versions live.`
    : `Every photo down here was shot with our own external USB webcam aimed at printed test parts to simulate a mounted printer camera (no scraped internet pics, safe to host anywhere). Hit the button on any photo to see what happens when we crush it to 640p + webcam noise.`;

  const filterButtons = isUncensored
    ? `
      <div class="seg-group" id="galleryFilters">
        <button class="seg active" data-filter="all">All (${cards.length})</button>
        <button class="seg" data-filter="degrade">Sharp vs. Blurry Webcam (3)</button>
        <button class="seg" data-filter="telemetry">Context.dev Forum &amp; Specs (4)</button>
        <button class="seg" data-filter="usb">External USB Webcam Sim (5)</button>
      </div>`
    : "";

  const cardsJson = JSON.stringify(cards);
  const simCasesJson = JSON.stringify([
    {
      id: "whisp",
      name: "golden_whispV3.jpg (Hairy Tower)",
      img: ownUsb.golden_whisp_orig,
      defect: "stringing",
      severity: 0.72,
      tier: "Tier 3 — pretty bad",
      modelUsed: "gemma-4-26b-a4b-it (4B-active open model)",
      telemetry: "PLA · Nozzle 215°C · Retraction 0.6mm @ 35mm/s",
      reasoning: "Dense fine filament strands and oozing visibly span across the open gap between the two vertical test columns.",
      plainTalk: "Translation: it sees heavy stringing (0.72 out of 1.0), so instead of doing a tiny tweak, it bumps retraction up noticeably and cools the nozzle down 7°C.",
      klipperCmds: [
        "# Sent to Klipper via Moonraker API (scaled by severity = 0.72)",
        "SET_RETRACTION RETRACT_LENGTH=1.0 RETRACT_SPEED=45",
        "M104 S208 ; drop nozzle temp -7C for the next test block",
      ],
    },
    {
      id: "slant2",
      name: "green_slant2.jpg (Crusty Overhang)",
      img: ownUsb.green_slant2_orig,
      defect: "overhang_curling",
      severity: 0.58,
      tier: "Tier 2 — medium",
      modelUsed: "gemma-4-31b-it / gemini-3.8-flash",
      telemetry: "Matte PLA · Outer Wall 180mm/s · Part Fan 60%",
      reasoning: "Significant surface roughness and upward curling along the steep right-hand overhang while vertical vents remain sharp.",
      plainTalk: "Translation: the plastic on that steep right curve isn't cooling fast enough before the next layer hits it—so crank the part fan to 100% and slow down outer walls.",
      klipperCmds: [
        "# Max out part cooling & slow down steep overhangs",
        "M106 S255 ; fan to 100%",
        "SET_VELOCITY_LIMIT VELOCITY=120",
      ],
    },
    {
      id: "support",
      name: "golden_support_piece.jpg (Torn Wall)",
      img: ownUsb.golden_support_orig,
      defect: "underextrusion",
      severity: 0.78,
      tier: "Tier 3 — severe",
      modelUsed: "gemini-3.8-flash",
      telemetry: "Silk PLA · 0.4mm Nozzle @ 210°C · Pressure Advance K=0.065",
      reasoning: "Under-extrusion and perimeter separation on the right vertical column creating ladder-like wall gaps along corner transitions.",
      plainTalk: "Translation: Pressure Advance K is cranked too high, starving the nozzle of plastic coming out of corners—so dial K down from 0.065 to 0.040.",
      klipperCmds: [
        "# Back off Pressure Advance K so corners stop starving",
        "SET_PRESSURE_ADVANCE ADVANCE=0.040",
        "M221 S104 ; +4% flow safety bump",
      ],
    },
  ]);

  const severityPointsJson = JSON.stringify([
    { id: "stringing011", human: 1, flash: 0.40, g31: 0.70, ga4: 0.40 },
    { id: "stringing001", human: 2, flash: 1.00, g31: 0.80, ga4: 0.70 },
    { id: "stringing002", human: 2, flash: 0.55, g31: 0.70, ga4: 0.70 },
    { id: "stringing003", human: 2, flash: 0.85, g31: 0.90, ga4: 0.80 },
    { id: "stringing004", human: 3, flash: 0.85, g31: 0.80, ga4: 0.70 },
    { id: "stringing005", human: 3, flash: 0.85, g31: 0.90, ga4: 0.80 },
    { id: "stringing006", human: 3, flash: 0.85, g31: 0.80, ga4: 0.70 },
    { id: "stringing007", human: 3, flash: 1.00, g31: 0.70, ga4: 0.60 },
    { id: "stringing008", human: 3, flash: 0.70, g31: 0.80, ga4: 0.70 },
    { id: "stringing009", human: 3, flash: 0.68, g31: 0.70, ga4: 0.70 },
    { id: "stringing010", human: 3, flash: 0.45, g31: 0.40, ga4: 0.40 },
  ]);

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Can AI Tune Your 3D Printer From Its Webcam? · Plain-English Showcase (/bro)</title>
<style>
  :root {
    --bg: #0c0f14;
    --bg-card: #151a22;
    --bg-muted: #0f1319;
    --border: #262f3d;
    --border-hi: #3b4759;
    --text: #eef2f6;
    --muted: #9aa5b4;
    --accent: #ff6b2b;
    --accent-soft: rgba(255, 107, 43, 0.14);
    --cyan: #2dd4bf;
    --cyan-soft: rgba(45, 212, 191, 0.13);
    --blue: #60a5fa;
    --ok: #22c55e;
    --bad: #ef4444;
    --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
    --sans: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: radial-gradient(circle at 12% 0%, rgba(255,107,43,0.08), transparent 40%),
                var(--bg);
    color: var(--text);
    font-family: var(--sans);
    line-height: 1.62;
    -webkit-font-smoothing: antialiased;
  }
  .wrap { max-width: 1120px; margin: 0 auto; padding: 30px 22px 80px; }
  .hero {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 30px 28px;
    margin-bottom: 26px;
  }
  .top-badges { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
  .pill {
    font-family: var(--mono);
    font-size: 11px;
    padding: 4px 10px;
    border-radius: 999px;
    border: 1px solid var(--border-hi);
    background: var(--bg-muted);
    color: var(--muted);
  }
  .pill-ok { border-color: rgba(34,197,94,0.45); color: #4ade80; background: rgba(34,197,94,0.09); }
  .pill-warn { border-color: rgba(255,107,43,0.5); color: #ff8a57; background: var(--accent-soft); }
  .hero-top {
    display: grid;
    grid-template-columns: 1.25fr 0.85fr;
    gap: 24px;
    align-items: center;
  }
  @media (max-width: 900px) { .hero-top { grid-template-columns: 1fr; } }
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
    background: rgba(12, 15, 20, 0.88);
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
  h1 { font-size: clamp(26px, 3.6vw, 38px); line-height: 1.18; margin: 0 0 14px; letter-spacing: -0.02em; }
  h1 span { color: var(--accent); }
  .lead { font-size: 16.5px; color: #d5dde7; max-width: 860px; margin: 0; }
  .tldr-strip {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 12px;
    margin-top: 18px;
  }
  .stat {
    background: var(--bg-muted);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 14px 16px;
  }
  .stat .big { font-family: var(--mono); font-size: 25px; font-weight: 700; }
  .stat .big.accent { color: var(--accent); }
  .stat .big.cyan { color: var(--cyan); }
  .stat .big.ok { color: var(--ok); }
  .stat p { margin: 4px 0 0; font-size: 13px; color: var(--muted); line-height: 1.42; }

  .block { margin-bottom: 28px; }
  .panel {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 22px 24px;
  }
  .panel h2 { font-size: 20px; margin: 0 0 6px; letter-spacing: -0.01em; }
  .panel .intro { color: var(--muted); font-size: 14.5px; margin: 0 0 18px; max-width: 840px; }
  .grid-2 { display: grid; grid-template-columns: 1.12fr 0.88fr; gap: 18px; }
  @media (max-width: 900px) { .grid-2 { grid-template-columns: 1fr; } }

  .controls-row { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 16px; }
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
  }
  .seg:hover { color: var(--text); }
  .seg.active { background: var(--accent); color: #fff; font-weight: 600; }
  .seg-cyan.active { background: var(--cyan); color: #06201d; }

  .chart-legend { display: flex; flex-wrap: wrap; gap: 15px; font-size: 12.5px; color: var(--muted); margin-bottom: 14px; }
  .dot { width: 10px; height: 10px; border-radius: 3px; display: inline-block; margin-right: 6px; vertical-align: middle; }
  .metric-group { margin-bottom: 16px; }
  .metric-head { display: flex; justify-content: space-between; font-size: 13.5px; font-weight: 600; margin-bottom: 6px; }
  .metric-note { font-weight: 400; color: var(--muted); font-size: 12px; }
  .bar-row { display: grid; grid-template-columns: 168px 1fr 58px; align-items: center; gap: 10px; margin: 5px 0; font-size: 12px; }
  .bar-row .mname { font-family: var(--mono); color: var(--muted); font-size: 11.5px; }
  .bar-track { background: var(--bg-muted); border: 1px solid var(--border); height: 18px; border-radius: 5px; overflow: hidden; }
  .bar-fill { height: 100%; border-radius: 4px; transition: width 0.35s cubic-bezier(.2,.8,.2,1); }
  .bar-val { font-family: var(--mono); text-align: right; font-weight: 600; }

  .talk-box {
    margin-top: 14px;
    padding: 13px 16px;
    border-left: 3px solid var(--accent);
    background: rgba(255,107,43,0.07);
    border-radius: 0 8px 8px 0;
    font-size: 13.8px;
    color: #e2e8f0;
  }
  .talk-box.cyan { border-left-color: var(--cyan); background: var(--cyan-soft); }
  .prose-stack p { margin: 0 0 13px; font-size: 14.5px; color: #cfd8e3; }
  .prose-stack p:last-child { margin-bottom: 0; }
  .prose-stack strong { color: #fff; }
  code { font-family: var(--mono); font-size: 0.9em; background: rgba(255,255,255,0.06); padding: 1px 5px; border-radius: 4px; }

  .sim-grid { display: grid; grid-template-columns: 310px 1fr; gap: 20px; align-items: start; }
  @media (max-width: 820px) { .sim-grid { grid-template-columns: 1fr; } }
  .sim-img-wrap { border: 1px solid var(--border); border-radius: 10px; overflow: hidden; background: #000; }
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

  .gallery-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(345px, 1fr)); gap: 18px; }
  .case-card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px; overflow: hidden; display: flex; flex-direction: column; }
  .case-img-box { position: relative; background: #07090c; aspect-ratio: 16/11; overflow: hidden; border-bottom: 1px solid var(--border); }
  .case-img-box img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .img-toggle {
    position: absolute;
    bottom: 10px;
    right: 10px;
    display: inline-flex;
    background: rgba(12, 15, 20, 0.9);
    border: 1px solid var(--border-hi);
    border-radius: 8px;
    padding: 2px;
    gap: 2px;
  }
  .img-toggle button { border: 0; background: transparent; color: var(--muted); font-size: 11px; font-family: var(--mono); padding: 5px 8px; border-radius: 6px; cursor: pointer; }
  .img-toggle button.active { background: var(--accent); color: #fff; font-weight: 600; }
  .case-body { padding: 16px 18px 18px; display: flex; flex-direction: column; gap: 10px; flex: 1; }
  .case-badge { font-family: var(--mono); font-size: 11px; color: var(--cyan); }
  .case-body h3 { margin: 0; font-size: 16px; line-height: 1.3; }
  .truth-line { font-family: var(--mono); font-size: 11.5px; color: var(--muted); }
  .truth-line strong { color: var(--text); }
  .telem-pill { font-family: var(--mono); font-size: 11px; background: #0b0f14; border: 1px solid var(--border); padding: 6px 9px; border-radius: 6px; color: #93c5fd; }
  .case-takeaway { font-size: 13.5px; color: #d0d8e2; margin: 0; }
  .verdicts { display: flex; flex-direction: column; gap: 7px; margin-top: auto; padding-top: 6px; }
  .v-item { background: var(--bg-muted); border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; font-size: 12px; }
  .v-top { display: flex; justify-content: space-between; font-family: var(--mono); font-size: 11.5px; margin-bottom: 3px; }
  .v-ok { color: var(--ok); font-weight: 600; }
  .v-bad { color: var(--bad); font-weight: 600; }
  .v-quote { color: var(--muted); font-size: 11.8px; line-height: 1.42; }
  footer { margin-top: 44px; text-align: center; font-size: 12.5px; color: var(--muted); font-family: var(--mono); }
</style>
</head>
<body>
<div class="wrap">
  <header class="hero">
    <div class="hero-top">
      <div>
        <div class="top-badges">
          <span class="pill">Junction Finland 2026</span>
          <span class="pill">Context.dev Live Forum Ground Truth</span>
          <span class="pill">Gemma 4 · Local Open Models</span>
          <span class="pill">Plain-English Edition</span>
          ${editionBadge}
        </div>
        <h1>Turning messy forum wisdom into <span>local, open AI calibration for any 3D printer</span></h1>
        <p class="lead">
          When a 3D print comes out hairy (stringing) or blobby at the corners, tuning it by hand wastes plastic filament and hours of <code>250W+</code> heater electricity printing test towers—unless you buy a closed-ecosystem printer that streams your workshop camera to a vendor cloud. We tested whether <strong>local open-weight Gemma 4 vision models</strong> + a cheap €10 external USB webcam + open-source Klipper/Moonraker can tune <em>any</em> old or new printer on your own hardware. To evaluate it without spending months breaking 500 prints in a lab, we built a <strong>Context.dev pipeline</strong> that mines real troubleshooting forums, summarizes threads where the owner confirmed the fix worked, and turns collective forum knowledge into automated ground truth—testing Google's cloud models (<code>gemini-3.8-flash</code>, <code>gemini-3.5-flash-lite</code>) against open Gemma 4 models (<code>gemma-4-31b-it</code> and 4B-active <code>gemma-4-26b-a4b-it</code>) across <strong>113 cases</strong>.
        </p>
      </div>
      <div class="hero-hook">
        <div class="hero-hook-img">
          <img id="heroUsbImg" src="${ownUsb.golden_whisp_orig}" alt="Hairy yellow 3D print test shot on our external USB webcam" />
          <span class="hero-hook-tag">● Our USB Webcam · Caught Stringing (0.72)</span>
          <div class="img-toggle">
            <button class="active" onclick="document.getElementById('heroUsbImg').src='${ownUsb.golden_whisp_orig}';this.parentElement.querySelectorAll('button').forEach(b=>b.classList.remove('active'));this.classList.add('active');">Sharp USB</button>
            <button onclick="document.getElementById('heroUsbImg').src='${ownUsb.golden_whisp_deg}';this.parentElement.querySelectorAll('button').forEach(b=>b.classList.remove('active'));this.classList.add('active');">640p + Noise</button>
          </div>
        </div>
        <div class="hero-hook-cap">
          <span><strong>Local Gemma 4B</strong> → <code>SET_RETRACTION</code></span>
          <span>96.6% F1</span>
        </div>
      </div>
    </div>

    <div class="tldr-strip">
      <div class="stat">
        <div class="big cyan">84 Threads</div>
        <p>Pulled via <strong>Context.dev</strong> &amp; distilled from messy forum comments into verified ground-truth tests (<code>68</code> failures + <code>16</code> clean).</p>
      </div>
      <div class="stat">
        <div class="big accent">96.6%</div>
        <p>Stringing F1 score on the small 4B-active open model (<code>gemma-4-26b-a4b-it</code> caught 14/14 stringing prints; <code>81.5%</code> on 480p USB).</p>
      </div>
      <div class="stat">
        <div class="big ok">93.1%</div>
        <p>Accuracy when simply asking "is this print clean or messed up?" (<code>gemma-4-31b-it</code> caught 26/26 bad prints; Flash hit <code>89.7%</code> with zero false alarms).</p>
      </div>
      <div class="stat">
        <div class="big">+9.2 pts</div>
        <p>Accuracy jump across 18 defect types just by handing the AI the printer's own temp/speed settings (<code>58.5% → 67.7%</code>).</p>
      </div>
      <div class="stat">
        <div class="big ok">15 / 16</div>
        <p>Clean prints passed without crying wolf (<code>93.8%</code>)—the lone mistake was a Star Wars print literally hanging on strings.</p>
      </div>
    </div>
  </header>

  <div class="block grid-2">
    <div class="panel prose-stack" style="border-color:rgba(45,212,191,0.38);">
      <div class="controls-row" style="justify-content:space-between;margin-bottom:6px;">
        <h2 style="margin:0;">Turning messy forum threads into automated ground truth with Context.dev</h2>
      </div>
      <p>
        Building AI for physical hardware hits an immediate bottleneck: <strong>where do you get the answer key?</strong> New filaments, slicers, and fast printers launch constantly, so static datasets go stale quickly—and printing 500 broken parts yourself takes months. Meanwhile, thousands of makers on <code>r/FixMyPrint</code> have already run into every print failure imaginable, debated the cause, tested the top-voted fix, and confirmed what worked.
      </p>
      <p>
        Our 7-stage <strong>Context.dev</strong> pipeline pulls those threads, photos, and 200-comment trees into structured JSON (<code>POST /v1/scrape</code> with <code>reddit-search</code>, <code>reddit-post</code>, <code>formats.bytes</code> with <code>maxAgeMs=0</code> &amp; <code>.success</code> checks, and <code>POST /v1/batches</code> with <code>Idempotency-Key</code>), filters for OP-confirmed fixes, verifies exact <code>evidence_comment_ids</code>, and turns forum discussions into ready-to-run test cases. Click any solved thread below to see the extracted ground-truth rubric and model grades:
      </p>
      <div class="controls-row" style="margin:8px 0 10px;">
        <div class="seg-group" id="ctxSelector"></div>
      </div>
      <div id="ctxView"></div>
    </div>

    <div class="panel prose-stack" style="border-color:rgba(255,107,43,0.38);">
      <h2>Local open-weight models + how Gemma 4 &amp; Gemini fit together</h2>
      <p>
        Today, automatic camera calibration usually means replacing working printers with closed, cloud-tethered machines. Running <strong>open-weight local vision models</strong> alongside a €10 external USB webcam and open-source Klipper + Moonraker lets workshops, schools, and makers <strong>upgrade the printers they already own</strong>—local, private, and $0 per print, cutting both failed plastic scrap and hours of wasted <code>250W+</code> bed/nozzle heating.
      </p>
      <p>
        <strong>Google DeepMind Gemma 4 (local open-weight vision):</strong> We tested both <code>gemma-4-31b-it</code> and lightweight 4B-active <code>gemma-4-26b-a4b-it</code>. Even with just 4B active parameters, open Gemma beat cloud Flash on Stringing F1 (<strong>96.6%</strong> sharp / <strong>81.5%</strong> degraded 480p USB), caught <strong>100% (7/7)</strong> of wild Reddit stringing threads, and matched human severity within one tier <strong>11/11</strong> times. And for tiny corner blobs that wash out on 480p webcams, adding angled side-LEDs right before snapping a frame lets surface bumps cast clear shadows.
      </p>
      <p>
        <strong>Google Gemini API (synthesizer, judge, and cloud fallback):</strong> Gemini handles three jobs: (1) auditing gallery photos + summarizing forum comments into strict JSON answer keys in Stage 5, (2) acting as the multimodal rubric and blind A/B judge in Stage 7, and (3) serving as an optional cloud escalation when subtle multi-variable failures need deeper telemetry reasoning (<strong>67.7%</strong> across 18 defect types).
      </p>
    </div>
  </div>

  <div class="block grid-2">
    <div class="panel">
      <h2>Does it spot bad prints—and does a cheap USB webcam ruin it?</h2>
      <p class="intro">We tested 29 prints (14–15 stringing, 3 clean, 11–12 other defects) two ways: first on the original photos, then crushed down to <code>&lt;=640px</code> with blur and grain to match the separate external USB webcam we pointed at the bed. Click the buttons to see what changed.</p>

      <div class="controls-row">
        <div class="seg-group" id="modeToggle">
          <button class="seg active" data-mode="three">Pick Exact Bucket (3-Way)</button>
          <button class="seg" data-mode="binary">Just "Clean vs. Bad Print"</button>
        </div>
        <div class="seg-group" id="usbToggle">
          <button class="seg seg-cyan active" data-usb="orig">Sharp Photos</button>
          <button class="seg seg-cyan" data-usb="usb">480p Blurry USB Cam</button>
        </div>
      </div>

      <div class="chart-legend">
        <span><i class="dot" style="background:#60a5fa"></i>gemini-3.8-flash</span>
        <span><i class="dot" style="background:#ff6b2b"></i>gemma-4-31b-it</span>
        <span><i class="dot" style="background:#2dd4bf"></i>gemma-4-26b-a4b-it (4B active)</span>
        <span><i class="dot" style="background:#a78bfa"></i>nemotron-3.5-super-vl</span>
      </div>

      <div id="mainBarChart"></div>
      <div class="talk-box" id="chartInsight"></div>
    </div>

    <div class="panel">
      <h2>Can it tell "barely hairy" from "total spiderweb"?</h2>
      <p class="intro">
        Knowing there's stringing isn't enough—Klipper needs to know <em>how much</em> to change retraction or temp. We graded 11 stringing prints by hand from Tier 1 (tiny specs) to Tier 3 (bad) and compared the models' <code>0.0–1.0</code> scores.
      </p>
      <svg id="severitySvg" viewBox="0 0 420 235" style="width:100%;height:auto;display:block;"></svg>
      <div class="talk-box cyan" style="font-size:13.3px;">
        <strong>The takeaway:</strong> Both <code>gemini-3.8-flash</code> and <code>gemma-4-26b-a4b-it</code> landed within one step of our human rating <strong>11 out of 11 times (100%)</strong> (<code>gemma-4-31b-it</code> got <code>10/11</code>). Higher human tier = higher AI number, which is all a control loop needs to pick a small tweak vs. a big tweak.
      </div>
    </div>
  </div>

  <div class="block grid-2">
    <div class="panel">
      <div class="controls-row" style="justify-content:space-between;margin-bottom:8px;">
        <h2 style="margin:0;">What about 18 wild defect types + fixing the settings?</h2>
        <div class="seg-group" id="telemVarToggle">
          <button class="seg" data-var="A">Photo Only (Var A)</button>
          <button class="seg active" data-var="T">+ Printer Specs (Var T)</button>
          <button class="seg" data-var="B">+ Reddit Post (Var B)</button>
        </div>
      </div>
      <p class="intro">We also threw 68 messy real-world failures (59 confirmed solved by the printer owner) across 18 defect categories at the models, and had a judge grade their root-cause and fix ideas from <code>0</code> to <code>2</code>.</p>
      <div id="telemetryChart"></div>
      <div class="talk-box cyan" id="telemInsight"></div>
    </div>

    <div class="panel prose-stack">
      <h2>Cloud Gemini vs. open Gemma 4 vs. NVIDIA Nemotron VL</h2>
      <p>
        Here is the practical breakdown without a dense table. For <strong>catching stringing and tuning retraction/temperature</strong>, the lightweight open model <code>gemma-4-26b-a4b-it</code> (only 4B active parameters, easy to host locally) performed remarkably well: <strong>96.6% Stringing F1</strong> on sharp photos, <strong>81.5%</strong> on degraded 480p USB photos, and <strong>100% (7/7)</strong> recall on wild stringing posts across every test mode—at $0 in API fees and without sending workshop video to the cloud.
      </p>
      <p>
        Across all 18 wild defect types with printer telemetry (Variant T), both <code>gemma-4-26b-a4b-it</code> and <code>gemma-4-31b-it</code> named the exact defect <strong>40.0%</strong> of the time, whereas cloud <code>gemini-3.5-flash-lite</code> hit <strong>67.7%</strong>. We also benchmarked <code>nvidia/nemotron-3.5-super-vl</code> (120B total / 12B active MoE), which revealed a sharp split between vision and text reasoning: on raw photos alone, Nemotron struggled with subtle 3D-print layer textures (<strong>20.0%</strong> Variant A, <strong>21.5%</strong> Variant T—calling 30 of 68 prints <code>stringing</code> and 19 <code>clean</code>), yet once given symptom text in Variant B it jumped <strong>+36.9 points to 56.9%</strong> and scored <strong>1.25 / 2.0</strong> on fixes (edging out Flash-Lite's <code>1.24</code>, just behind Gemma 31B's <code>1.35</code>).
      </p>
      <p>
        On the 16 clean negative-control prints, Flash-Lite passed <strong>93.8% (15/16)</strong>, Gemma 31B and Nemotron VL both passed <strong>87.5% (14/16)</strong>, and Gemma A4B passed <strong>75.0% (12/16)</strong>. And on the 29-image hand-picked set, Nemotron VL also caught <strong>100% (15/15)</strong> of stringing prints on sharp photos (<strong>85.7% F1</strong>, <code>10/11</code> severity within one tier) and held <strong>78.6% F1 / 100% clean pass rate</strong> at 480p USB—while missing most <code>other_defect</code> surface flaws (<code>18.2%</code>). Rerunning Nemotron a second time at <code>temperature=0</code> showed ~7–10% jitter on borderline images (<code>26/29</code> raw and <code>27/29</code> USB matched identically).
      </p>
      <p>
        <strong>Practical setup:</strong> Gemma 4's stronger visual encoder makes it the clear open-weight winner for camera-driven inspection, while larger models (<code>Gemini Flash</code> or <code>Gemma 31B</code>) handle multi-variable telemetry troubleshooting best.
      </p>
    </div>
  </div>

  <div class="block">
    <div class="panel">
      <h2>Closed-loop Klipper pipeline: USB frame → JSON → command (&amp; is it fast enough?)</h2>
      <p class="intro">Pick one of the photos we shot with our external USB webcam aimed at test prints on the bed—here's what the model outputs, the exact command our loop sends to Moonraker / Klipper, and how long each model takes per photo.</p>
      <div class="controls-row" style="margin-bottom:14px;">
        <div class="seg-group" id="simSelector"></div>
      </div>
      <div class="sim-grid" id="simView"></div>

      <div style="border-top:1px solid var(--border);margin-top:20px;padding-top:18px;">
        <div class="grid-2" style="align-items:center;">
          <div>
            <div class="metric-head" style="margin-bottom:8px;"><span>Average Processing Time per Photo</span><span class="metric-note">Time · internal thinking tokens</span></div>
            <div class="bar-row" style="grid-template-columns:170px 1fr 122px;">
              <span class="mname">gemini-3.5-flash-lite</span>
              <div class="bar-track"><div class="bar-fill" style="width:10.3%;background:#93c5fd"></div></div>
              <span class="bar-val" style="font-size:11px;">1.5s · 0 think</span>
            </div>
            <div class="bar-row" style="grid-template-columns:170px 1fr 122px;">
              <span class="mname">nemotron-3.5-super-vl</span>
              <div class="bar-track"><div class="bar-fill" style="width:27.2%;background:#a78bfa"></div></div>
              <span class="bar-val" style="font-size:11px;">4.0s · ~721 tok</span>
            </div>
            <div class="bar-row" style="grid-template-columns:170px 1fr 122px;">
              <span class="mname">gemini-3.8-flash</span>
              <div class="bar-track"><div class="bar-fill" style="width:40.1%;background:#60a5fa"></div></div>
              <span class="bar-val" style="font-size:11px;">5.9s · ~242 tok</span>
            </div>
            <div class="bar-row" style="grid-template-columns:170px 1fr 122px;">
              <span class="mname">gemma-4-26b-a4b-it</span>
              <div class="bar-track"><div class="bar-fill" style="width:85.0%;background:#2dd4bf"></div></div>
              <span class="bar-val" style="font-size:11px;">12.5s · ~785 tok</span>
            </div>
            <div class="bar-row" style="grid-template-columns:170px 1fr 122px;">
              <span class="mname">gemma-4-31b-it</span>
              <div class="bar-track"><div class="bar-fill" style="width:100%;background:#ff6b2b"></div></div>
              <span class="bar-val" style="font-size:11px;">14.7s · ~354 tok</span>
            </div>
          </div>
          <div class="talk-box cyan" style="margin-top:0;font-size:13.3px;">
            <strong>Why 13 seconds is plenty fast for a closed Klipper loop:</strong> Unlike a self-driving car that needs 30 frames a second, a 3D printer takes <strong>5 to 15 minutes (300–900s)</strong> to print one calibration section before the camera checks a single snapshot—so <code>12.5–14.7s</code> adds <strong>under 3%</strong> to the cycle. Also notice <em>why</em> Gemma took ~13s: the JSON answer is only ~50 tokens, while ~90% of the wait went into internal thinking tokens (<code>~785</code> on 4B-active A4B vs. <code>~354</code> on 31B). Turning off or capping thinking mode when running locally in <code>llama.cpp</code> or <code>vLLM</code> drops that wait to <strong>~2–3 seconds per frame</strong>.
          </div>
        </div>
      </div>
    </div>
  </div>

  <div class="block">
    <div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-end;gap:14px;margin-bottom:16px;">
      <div>
        <h2 style="margin:0;font-size:21px;">The Fun Part: Photos That Worked &amp; Photos That Tripped the AI</h2>
        <p style="color:var(--muted);font-size:14.5px;margin:4px 0 0;max-width:780px;">${gallerySubtitle}</p>
      </div>
      ${filterButtons}
    </div>
    <div class="gallery-grid" id="galleryGrid"></div>
  </div>

  <div class="block">
    <div class="panel prose-stack">
      <h2>How we kept the test fair (and what it taught us about printer cameras)</h2>
      <p>
        <strong>No cheating or lucky rolls:</strong> Every model ran at <code>temperature=0</code> so answers stay repeatable, duplicate crossposts were stripped by SHA-256 hash, and in pure-photo mode (Variant A) we stripped out every word of post titles and comments so the AI couldn't read the answer. People also asked us: <em>"Wait, didn't Gemini and Gemma already memorize these Reddit photos during training?"</em> We checked! Splitting the Reddit posts by year showed pure-photo accuracy on brand-new <strong>2026 posts was 55.6%</strong> vs. <strong>55.9% overall</strong>—and on brand-new photos we took ourselves with a separate USB camera at the hackathon, <code>gemma-4-31b-it</code> still hit <strong>83% (5/6)</strong>.
      </p>
      <p>
        <strong>How we faked a cheap USB webcam:</strong> When we measured our external USB webcam reference shot (<code>gray_problem.jpg</code>), we noticed a classic cheap-webcam trick: the file is saved as <code>1920x1080</code>, but the plastic lens is so soft (3×3 Laplacian sharpness <code>σ=4.94</code> vs. <code>10–38</code> on phone cameras) that it's really only giving you ~480p of detail. So we shrank all 29 test images to <code>&lt;=640px</code>, added lens blur (<code>σ=0.75</code>), sprinkled in realistic sensor grain, and saved them as compressed <code>4:2:0</code> JPEGs.
      </p>
      <p>
        <strong>Two big lessons if you're building this into a printer:</strong> First, your printer's stock webcam is <em>already</em> good enough to auto-tune stringing, because thin threads across empty air still show up at 480p—but if you want to auto-tune Pressure Advance (<code>K</code>) from tiny corner bulges or surface zits, mount the camera closer or add angled LED lighting so bumps cast shadows. Second, don't force the AI to pick just one defect label when prints often have two problems at once; ask separate yes/no questions per defect, and always run calibration on a known test tower so cool bridged string-art doesn't get mistaken for a failed print.
      </p>
    </div>
  </div>

  <footer>
    Print Defect Detection · Plain-English Showcase · Klipper &amp; Moonraker Vision Calibration
  </footer>
</div>

<script>
const BENCH_DATA = {
  three: {
    orig: {
      metrics: [
        { name: "Overall Score (Exact 3-Way Match)", note: "29 prints", vals: [69.0, 86.2, 79.3, 65.5] },
        { name: "Stringing F1 (Catching Hairs Cleanly)", note: "Precision + recall combined", vals: [78.6, 87.5, 96.6, 85.7] },
        { name: "Catching Other Defects", note: "Blobs, zits, rough walls, curling", vals: [50.0, 83.3, 63.6, 18.2] },
        { name: "Passing Good Prints (No False Alarms)", note: "Didn't cry wolf on clean parts", vals: [100.0, 33.3, 66.7, 66.7] }
      ],
      insight: "<strong>Sharp photos (3-way classification):</strong> Both open Gemma models and <code>nemotron-3.5-super-vl</code> caught <strong>100% (15/15) of the stringing prints</strong>, with 4B-active <code>gemma-4-26b-a4b-it</code> hitting <strong>96.6% Stringing F1</strong>. <code>gemini-3.8-flash</code> looks lower at 69.0% only because when a print had stringing <em>plus</em> another defect, Flash named the other defect—click <strong>Just 'Clean vs. Bad Print'</strong> above.<br/><span style='color:var(--muted);font-size:12.3px;'><strong>Note on Nemotron run-to-run jitter (temperature=0):</strong> Running the exact same test twice on OpenRouter gave <code>26/29 (89.7%)</code> identical answers with 3 borderline flips: overall score stayed <code>65.5% (19/29)</code>, Stringing F1 nudged <code>85.7% ↔ 87.5%</code>, and other-defect recall moved <code>18.2% ↔ 27.3%</code> (severity stayed <code>10/11</code> within one tier).</span>"
    },
    usb: {
      metrics: [
        { name: "Overall Score (Exact 3-Way Match)", note: "29 prints @ <=640px + noise", vals: [58.6, 65.5, 62.1, 55.2] },
        { name: "Stringing F1 (Catching Hairs Cleanly)", note: "Holds up at 480p", vals: [85.7, 82.8, 81.5, 78.6] },
        { name: "Catching Other Defects", note: "Tiny zits lost in webcam grain", vals: [18.2, 36.4, 36.4, 18.2] },
        { name: "Passing Good Prints (No False Alarms)", note: "Zero false alarms on any of the 4 models", vals: [100.0, 100.0, 100.0, 100.0] }
      ],
      insight: "<strong>Blurry 480p USB photos:</strong> Stringing F1 stayed strong across all four models (<strong>78.6%–85.7%</strong>) and false alarms dropped to <strong>0% on every model (3/3 clean)</strong> because webcam blur filtered out microscopic dust and hairs. Meanwhile, tiny surface zits and slight wall bumps blended into sensor grain, dropping other-defect recall to 18.2%–36.4%.<br/><span style='color:var(--muted);font-size:12.3px;'><strong>Note on Nemotron run-to-run jitter (temperature=0):</strong> Repeating the blurry USB test gave <code>27/29 (93.1%)</code> identical answers with 2 borderline flips, bumping overall score <code>55.2% ↔ 62.1%</code>, Stringing F1 <code>78.6% ↔ 85.7%</code>, and other-defect recall <code>18.2% ↔ 27.3%</code> (<code>100%</code> clean pass rate and <code>8/11</code> severity stayed the same).</span>"
    }
  },
  binary: {
    orig: {
      metrics: [
        { name: "Overall Score (Clean vs. Bad Print)", note: "29 prints", vals: [89.7, 93.1, 82.1, 79.3] },
        { name: "Bad Prints Caught", note: "Out of 26 defective prints", vals: [88.5, 100.0, 84.0, 80.8] },
        { name: "When It Flags a Print, Is It Really Bad?", note: "Precision", vals: [100.0, 92.9, 95.5, 95.5] },
        { name: "Passing Good Prints (No False Alarms)", note: "True negative rate", vals: [100.0, 33.3, 66.7, 66.7] }
      ],
      insight: "<strong>Clean vs. Bad Print gate:</strong> When step one of the printer loop simply asks <em>'did this test print come out clean, or does it need tuning?'</em>, <code>gemini-3.8-flash</code> jumps from 69.0% to <strong>89.7% with zero false alarms</strong>, <code>gemma-4-31b-it</code> reaches <strong>93.1% (26/26 bad prints caught)</strong>, and <code>nemotron-3.5-super-vl</code> hits <strong>79.3%</strong> (21/26 caught in Run 1, <code>75.9%</code> / 20/26 in Run 2 due to 1 borderline flip)."
    },
    usb: {
      metrics: [
        { name: "Overall Score (Clean vs. Bad Print)", note: "29 prints @ <=640px + noise", vals: [72.4, 82.8, 72.4, 65.5] },
        { name: "Bad Prints Caught", note: "Stringing caught; tiny zits missed", vals: [69.2, 80.8, 69.2, 61.5] },
        { name: "When It Flags a Print, Is It Really Bad?", note: "100% across all 4 models!", vals: [100.0, 100.0, 100.0, 100.0] },
        { name: "Passing Good Prints (No False Alarms)", note: "3/3 clean passed on every model", vals: [100.0, 100.0, 100.0, 100.0] }
      ],
      insight: "<strong>On 480p USB webcam quality:</strong> Whenever any of the four models flags a print as bad, it's right <strong>100% of the time</strong> (zero wasted recalibrations), with <code>gemma-4-31b-it</code> catching <strong>80.8%</strong> of all bad prints vs. <code>69.2%</code> on Flash/Gemma A4B and <code>61.5%</code> on Nemotron VL (<code>65.5%</code> binary score stayed identical across both Nemotron runs)."
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
  document.getElementById("mainBarChart").innerHTML = block.metrics.map(m => \`
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

const TELEM_DATA = {
  A: {
    cls: [58.5, 36.9, 36.9, 20.0],
    str: [85.7, 85.7, 100.0, 100.0],
    fixPct: [39.0, 39.5, 33.0, 22.0],
    fixRaw: ["0.78 / 2.0", "0.79 / 2.0", "0.66 / 2.0", "0.44 / 2.0"],
    insight: "<strong>Photo Only (Var A):</strong> Zero text, 18 defect types. <code>gemini-3.5-flash-lite</code> hits <strong>58.5%</strong> and both Gemma 4 models hit <strong>36.9%</strong>—nearly double <code>nemotron-3.5-super-vl</code> (<strong>20.0%</strong>, which over-called stringing and missed fine layer issues), though Gemma A4B and Nemotron both caught <strong>100% (7/7)</strong> of wild stringing."
  },
  T: {
    cls: [67.7, 40.0, 40.0, 21.5],
    str: [85.7, 71.4, 100.0, 100.0],
    fixPct: [51.5, 46.5, 34.5, 25.5],
    fixRaw: ["1.03 / 2.0", "0.93 / 2.0", "0.69 / 2.0", "0.51 / 2.0"],
    insight: "<strong>Photo + Printer Specs (Var T):</strong> Adding settings Klipper/Moonraker already knows (material, temps, speeds, retraction—zero user typing) lifts <code>gemini-3.5-flash-lite</code> <strong>+9.2 points (58.5% → 67.7%, +32% fix score)</strong> and lifts <code>gemma-4-31b-it</code> fixes to <code>0.93 / 2.0</code>, while Nemotron stays limited by visual detail at <strong>21.5%</strong>."
  },
  B: {
    cls: [75.4, 58.5, 58.5, 56.9],
    str: [100.0, 100.0, 100.0, 100.0],
    fixPct: [62.0, 67.5, 51.5, 62.5],
    fixRaw: ["1.24 / 2.0", "1.35 / 2.0", "1.03 / 2.0", "1.25 / 2.0"],
    insight: "<strong>Photo + Full Reddit Post (Var B):</strong> Once a human describes the symptom in text, <code>nemotron-3.5-super-vl</code> jumps <strong>+36.9 points (20.0% → 56.9%)</strong> with <strong>1.25 / 2.0</strong> on fixes—showing strong 120B text reasoning despite weak zero-text 3D-print vision, while <code>gemma-4-31b-it</code> leads all models on fixes (<strong>1.35 / 2.0</strong>)."
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
      <div class="metric-head"><span>Naming the Exact Defect (Out of 18 Types)</span><span class="metric-note">65 named failures</span></div>
      \${TELEM_MODELS.map((m, i) => \`
        <div class="bar-row" style="grid-template-columns:175px 1fr 58px;">
          <span class="mname">\${m.label}</span>
          <div class="bar-track"><div class="bar-fill" style="width:\${d.cls[i]}%;background:\${m.color}"></div></div>
          <span class="bar-val">\${d.cls[i].toFixed(1)}%</span>
        </div>
      \`).join("")}
    </div>
    <div class="metric-group">
      <div class="metric-head"><span>Catching Wild Stringing Posts</span><span class="metric-note">7 r/FixMyPrint stringing threads</span></div>
      \${TELEM_MODELS.map((m, i) => \`
        <div class="bar-row" style="grid-template-columns:175px 1fr 58px;">
          <span class="mname">\${m.label}</span>
          <div class="bar-track"><div class="bar-fill" style="width:\${d.str[i]}%;background:\${m.color}"></div></div>
          <span class="bar-val">\${d.str[i].toFixed(1)}%</span>
        </div>
      \`).join("")}
    </div>
    <div class="metric-group" style="margin-bottom:6px;">
      <div class="metric-head"><span>How Good Was Its Fix Advice?</span><span class="metric-note">Graded 0 to 2 by judge</span></div>
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
renderTelemetry();

(function renderSeveritySvg() {
  const pts = ${severityPointsJson};
  const svg = document.getElementById("severitySvg");
  const padL = 96, padR = 22, padT = 22, padB = 34;
  const W = 420, H = 235;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  const x = v => padL + v * plotW;
  const yTier = t => padT + ((3 - t) + 0.5) * (plotH / 3);

  let out = "";
  const bands = [
    { t: 3, label: "Tier 3 (Bad)", sub: "Heavy webs", x0: 0.67, x1: 1.0 },
    { t: 2, label: "Tier 2 (Meh)", sub: "Light wisps", x0: 0.34, x1: 0.66 },
    { t: 1, label: "Tier 1 (Tiny)", sub: "A few specs", x0: 0.0, x1: 0.33 }
  ];
  bands.forEach(b => {
    const cy = yTier(b.t);
    out += \`<line x1="\${padL}" y1="\${cy}" x2="\${W - padR}" y2="\${cy}" stroke="#262f3d" stroke-dasharray="3,3"/>\`;
    out += \`<rect x="\${x(b.x0)}" y="\${cy - 18}" width="\${x(b.x1) - x(b.x0)}" height="36" fill="rgba(45,212,191,0.07)" stroke="rgba(45,212,191,0.22)" rx="4"/>\`;
    out += \`<text x="8" y="\${cy - 2}" fill="#eef2f6" font-size="11" font-family="monospace">\${b.label}</text>\`;
    out += \`<text x="8" y="\${cy + 12}" fill="#9aa5b4" font-size="10">\${b.sub}</text>\`;
  });
  [0, 0.33, 0.67, 1.0].forEach(v => {
    out += \`<line x1="\${x(v)}" y1="\${padT}" x2="\${x(v)}" y2="\${H - padB}" stroke="#1e2530"/>\`;
    out += \`<text x="\${x(v)}" y="\${H - 10}" fill="#9aa5b4" font-size="10.5" text-anchor="middle" font-family="monospace">\${v.toFixed(2)}</text>\`;
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
      <div class="telem-pill">What Klipper already knows: \${c.telemetry}</div>
      <div class="code-box">{
  <span class="k">"model"</span>: <span class="s">"\${c.modelUsed}"</span>,
  <span class="k">"predicted_class"</span>: <span class="s">"\${c.defect}"</span>,
  <span class="k">"severity"</span>: <span class="cmd">\${c.severity.toFixed(2)}</span>, <span class="c">// \${c.tier}</span>
  <span class="k">"reasoning"</span>: <span class="s">"\${c.reasoning}"</span>
}</div>
      <p style="margin:10px 0 6px;font-size:13.5px;color:#d5dde7;">\${c.plainTalk}</p>
      <div class="code-box" style="border-color:rgba(255,107,43,0.35);">
\${c.klipperCmds.map(l => l.startsWith("#") ? \`<span class="c">\${l}</span>\` : \`<span class="cmd">\${l}</span>\`).join("\\n")}
      </div>
    </div>
  \`;
}
renderSimulator();

const CTX_RECORDS = [
  {
    id: "fixmyprint_1u3vzsg",
    short: "TPU Stringing (25 comments)",
    url: "https://www.reddit.com/r/FixMyPrint/comments/1u3vzsg/cant_understand_tpu/",
    comments: 25,
    telemetry: "Bambu P1S, Priline 98a TPU",
    defect: "stringing",
    solved: true,
    evidenceIds: ["or8ei5k", "orbkp5y", "oratz2y", "oruu5pn"],
    causes: ["TPU dryer temp too low (55°C instead of 65–70°C)", "Retraction settings off for TPU"],
    fixes: ["Dry TPU hotter at 65–70°C", "Set 0.6 mm retraction & turn on Avoid crossing walls"],
    consensus: "OP came back and confirmed drying at 70°C + 0.6 mm retraction totally fixed the stringing.",
    grades: "All 4 models nailed it -> Flash-Lite: 2/2 · Gemma 31B: 2/2 · Gemma A4B: 2/2 · Nemotron VL: 2/2"
  },
  {
    id: "fixmyprint_t8kb40",
    short: "Klipper ASA Blobs (25 comments)",
    url: "https://www.reddit.com/r/FixMyPrint/comments/t8kb40/blobs_underextrusion/",
    comments: 25,
    telemetry: "Ender 3 Pro + Klipper, SuperSlicer, DuraPro ASA @ 230°C / 100°C bed",
    defect: "blobs_zits",
    solved: true,
    evidenceIds: ["hzqbv6t", "hzoj0y6", "hzovm3c", "hzpc9k3"],
    causes: ["Nozzle temp too hot (230°C) causing surface zits/pits", "Moisture popping in filament"],
    fixes: ["Drop nozzle temp 10°C (230°C -> 220°C)", "Dry the ASA spool"],
    consensus: "OP confirmed dropping hotend temp 10°C in Klipper completely wiped out the blobs.",
    grades: "Flash-Lite: 2/2 · Nemotron VL: 2/2 · Gemma 31B & A4B: 0/2 (called underextrusion)"
  },
  {
    id: "fixmyprint_1bia375",
    short: "Y-Axis Layer Shift (52 comments)",
    url: "https://www.reddit.com/r/FixMyPrint/comments/1bia375/my_yaxis_is_having_layer_shifts_please_help/",
    comments: 52,
    telemetry: "None listed in original post",
    defect: "layer_shift",
    solved: true,
    evidenceIds: ["kvjiq12", "kvjjnc0", "kvju5ea", "kvm6qpa"],
    causes: ["Missing bolt on Y-stepper motor mount", "Low stepper driver voltage on mainboard"],
    fixes: ["Tighten Y-motor bolts & belt pulleys", "Check stepper driver voltage with a multimeter"],
    consensus: "Boiled down from 52 comments: OP found a missing Y-motor bolt plus a weak mainboard stepper driver.",
    grades: "Flash-Lite: 2/2 · Gemma 31B: 1/2 · Gemma A4B: 0/2 · Nemotron VL: 0/2 on photo -> 2/2 with post text"
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
      Pulled via Context.dev <code>reddit-post</code> · <strong>\${r.comments} comments</strong> · <a href="\${r.url}" target="_blank" rel="noopener" style="color:var(--cyan);">Open Reddit Thread ↗</a>
    </div>
    <div class="code-box" style="margin-top:0;">{
  <span class="k">"id"</span>: <span class="s">"\${r.id}"</span>,
  <span class="k">"printer_context"</span>: <span class="s">"\${r.telemetry}"</span>,
  <span class="k">"defect_class"</span>: <span class="s">"\${r.defect}"</span>,
  <span class="k">"solved"</span>: <span class="cmd">\${r.solved}</span>, <span class="c">// OP confirmed the fix worked</span>
  <span class="k">"evidence_comment_ids"</span>: [\${r.evidenceIds.map(x => \`<span class="s">"\${x}"</span>\`).join(", ")}],
  <span class="k">"likely_causes"</span>: [\${r.causes.map(x => \`<span class="s">"\${x}"</span>\`).join(", ")}],
  <span class="k">"recommended_fixes"</span>: [\${r.fixes.map(x => \`<span class="s">"\${x}"</span>\`).join(", ")}]
}</div>
    <div class="talk-box cyan" style="margin-top:10px;font-size:13px;">
      <strong>What actually fixed it:</strong> \${r.consensus}<br/>
      <span style="color:var(--muted);font-family:var(--mono);font-size:11.5px;">How the models scored (Var T): \${r.grades}</span>
    </div>
  \`;
}
renderCtxExplorer();

const CASES = ${cardsJson};
let activeFilter = "all";

function renderGallery() {
  const grid = document.getElementById("galleryGrid");
  const visible = CASES.filter(c => activeFilter === "all" || c.group === activeFilter);
  grid.innerHTML = visible.map(c => {
    const hasToggle = c.modeType === "degrade" || c.modeType === "telemetry";
    const toggleHtml = hasToggle ? \`
      <div class="img-toggle" data-card="\${c.id}">
        <button class="active" data-side="A">\${c.labelA}</button>
        <button data-side="B">\${c.labelB}</button>
      </div>\` : "";
    return \`
      <article class="case-card">
        <div class="case-img-box">
          <img id="img-\${c.id}" src="\${c.imgA}" alt="\${c.title}" loading="lazy" />
          \${toggleHtml}
        </div>
        <div class="case-body">
          <div class="case-badge">\${c.badge}</div>
          <h3>\${c.title}</h3>
          <div class="truth-line">Actual label: <strong>\${c.truth}</strong></div>
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

        document.getElementById("verdicts-" + id).innerHTML = renderVerdictItems(
          side === "B" && card.verdictsB ? card.verdictsB : card.verdictsA
        );
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
  const publicHtml = renderBroHtml({
    cards: publicCards,
    ownUsb: publicAssets.ownUsb,
    isUncensored: false,
  });
  const publicPath = path.join(OUT_DIR, "index.html");
  fs.writeFileSync(publicPath, publicHtml, "utf8");
  console.log(
    `Wrote PUBLIC /bro showcase: ${publicPath} (${(fs.statSync(publicPath).size / 1024).toFixed(1)} KB)`
  );

  const fullAssets = await loadAssets(true);
  const fullCards = buildCaseCards(fullAssets, true);
  const fullHtml = renderBroHtml({
    cards: fullCards,
    ownUsb: fullAssets.ownUsb,
    isUncensored: true,
  });
  const fullPath = path.join(OUT_DIR, "local_uncensored.html");
  fs.writeFileSync(fullPath, fullHtml, "utf8");
  console.log(
    `Wrote LOCAL /bro showcase: ${fullPath} (${(fs.statSync(fullPath).size / 1024).toFixed(1)} KB)`
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
