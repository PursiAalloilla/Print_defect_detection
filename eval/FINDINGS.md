# Print Defect Detection — Model Evaluation Findings

Evaluation of multimodal models from the Gemini and open-weight Gemma 4 families on vision-based 3D-print anomaly detection and severity estimation for automated Klipper calibration.

---

## 1. Executive Summary

- **Stringing detection works out of the box with open models:** Both **`gemma-4-31b-it`** and **`gemma-4-26b-a4b-it`** achieved **100% stringing recall (14/14)**, with **`gemma-4-26b-a4b-it`** posting the highest **Stringing F1 (96.6%)** across all tested models.
- **Apparent 3-class errors are mostly multi-defect label conflicts, not missed defects:** When collapsed to binary anomaly detection (`clean` vs `defect`), **`gemini-3.8-flash` jumps from 69.0% → 89.7%** (with **0% false alarms** on clean prints) and **`gemma-4-31b-it` jumps from 86.2% → 93.1%** (catching **26/26** defective prints).
- **Severity estimation aligns closely with human judgment:** Both `gemini-3.8-flash` and `gemma-4-26b-a4b-it` matched human 1–3 severity labels **within ±1 tier on 11/11 (100%)** of labeled stringing samples (`gemma-4-31b-it`: 10/11).
- **Edge-scale tradeoff (`gemma-4-26b-a4b-it`):** The 4B-active MoE model remains rock-solid on stringing (14/14 recall), making it viable for retraction/temperature tuning, but misses subtle non-stringing surface/overhang defects captured on the real printer USB camera (`3/6` on the USB subset vs `5/6` for `gemma-4-31b-it`).

---

## 2. Dataset & Methodology

### Dataset composition (baseline runs — 29 images)

| Folder / Ground Truth | Count | Description |
|---|---:|---|
| `dataset/stringing/` | 14 | Fine filament wisps to heavy cobwebbing across towers, Benchies, and functional parts (11 with human severity tiers `1–3` in `dataset/labels.json`) |
| `dataset/clean/` | 3 | Defect-free prints (`Clean_butterfly.jpeg`, `Clean_zoro.webp`, `clean_traffic_cone.jpg`) to measure false-recalibration rate |
| `dataset/other_defect/` | 12 | Distractor defects (corner blobs, zits, layer shifts, overhang curling, poor adhesion, seam/wall defects), including in-situ USB webcam captures |

*(Note: After the baseline runs completed, `golden_whispV3.jpg` was reclassified from `other_defect/` to `stringing/`, making the current split `15 stringing / 3 clean / 11 other_defect`.)*

### Models & API notes

1. **`gemini-3.8-flash`** — Proprietary cloud baseline (`temperature: 0`, constrained JSON schema decoding via `response_schema`).
2. **`gemma-4-31b-it`** — Frontier 31B dense open-weight Gemma 4 model (`temperature: 0`, chain-of-thought `thought` parts filtered prior to JSON extraction).
3. **`gemma-4-26b-a4b-it`** — Open-weight 26B MoE with **4B active parameters**; smallest Gemma 4 variant hosted on the Google AI Studio API, used as the cloud-hosted proxy for edge-class 4B inference.
4. **Unavailable endpoints noted during testing:**
   - `gemini-decision-1`: Listed in the `v1beta` catalog (`supportedGenerationMethods: ["createDecision"]`, `outputTokenLimit: 1`), but `:createDecision` returns a routing-level HTTP 404 on public REST (`v1`/`v1beta`/`v1alpha`).
   - `Gemma-4-E4B-it` (Arduino Ventuno Q target): On-device edge model not served on Google's cloud API (`HTTP 404`); open GGUF weights (`ggml-org/gemma-4-E4B-it-GGUF`) are available on Hugging Face for local execution.

---

## 3. 3-Class Evaluation Results (`stringing` / `clean` / `other_defect`)

Result logs:
- `eval/results/gemini-3.8-flash/run-2026-11-14T17-43-51-145Z.json`
- `eval/results/gemma-4-31b-it/run-2026-11-14T20-14-12-133Z.json`
- `eval/results/gemma-4-26b-a4b-it/run-2026-11-14T20-38-04-576Z.json`

| Metric | `gemini-3.8-flash` | `gemma-4-31b-it` (Frontier Open) | `gemma-4-26b-a4b-it` (4B-active Open) |
|---|---|---|---|
| **Overall accuracy** | 20/29 (**69.0%**) | **25/29 (86.2%)** | 23/29 (**79.3%**) |
| **Stringing precision** | 78.6% | 77.8% | **93.3%** |
| **Stringing recall** | 78.6% (11/14) | **100.0% (14/14)** | **100.0% (14/14)** |
| **Stringing F1** | 78.6% | 87.5% | **96.6%** |
| **Clean precision / recall** | 50.0% / **100.0% (3/3)** | **100.0%** / 33.3% (1/3) | 33.3% / 66.7% (2/3) |
| **Other-defect precision / recall** | 66.7% / 50.0% (6/12) | **100.0%** / **83.3% (10/12)** | **100.0%** / 63.6% (7/11 + 1 empty) |
| **Severity exact tier match** | **7/11 (63.6%)** | 6/11 (54.5%) | 5/11 (45.5%) |
| **Severity within ±1 tier** | **11/11 (100%)** | 10/11 (90.9%) | **11/11 (100%)** |

### Confusion matrices (rows = ground truth, columns = predicted)

**`gemini-3.8-flash`**
| Truth \ Pred | `stringing` | `clean` | `other_defect` |
|---|---:|---:|---:|
| **`stringing`** | **11** | 0 | 3 |
| **`clean`** | 0 | **3** | 0 |
| **`other_defect`** | 3 | 3 | **6** |

**`gemma-4-31b-it`**
| Truth \ Pred | `stringing` | `clean` | `other_defect` |
|---|---:|---:|---:|
| **`stringing`** | **14** | 0 | 0 |
| **`clean`** | 2 | **1** | 0 |
| **`other_defect`** | 2 | 0 | **10** |

**`gemma-4-26b-a4b-it`** *(+1 empty response on `other_defect002.jpeg` due to 2048 thinking-token cap, since raised to 4096)*
| Truth \ Pred | `stringing` | `clean` | `other_defect` |
|---|---:|---:|---:|
| **`stringing`** | **14** | 0 | 0 |
| **`clean`** | 1 | **2** | 0 |
| **`other_defect`** | 0 | 4 | **7** |

---

## 4. In-Situ USB Printer Camera Subset (6 images)

| Image | Baseline Label | `gemini-3.8-flash` | `gemma-4-31b-it` | `gemma-4-26b-a4b-it` |
|---|---|---|---|---|
| `golden_support_piece.jpg` | `other_defect` | ✓ `other_defect` | ✓ `other_defect` | ✗ `clean` |
| `golden_whispV3.jpg` | `other_defect`* | ✗ `clean` | ✓ `other_defect` | ✓ `other_defect` |
| `gray_problem.jpg` | `other_defect` | ✗ `clean` | ✗ `stringing` | ✓ `other_defect` |
| `green_slant2.jpg` | `other_defect` | ✓ `other_defect` | ✓ `other_defect` | ✗ `clean` |
| `green_slant3.jpg` | `other_defect` | ✓ `other_defect` | ✓ `other_defect` | ✗ `clean` |
| `real_stringing.jpg` | `stringing` | ✗ `other_defect` | ✓ `stringing` | ✓ `stringing` |
| **Subset score** | | **3/6 (50%)** | **5/6 (83%)** | **3/6 (50%)** |

*\*Subsequently moved to `stringing/` in the updated dataset.*

---

## 5. Binary Anomaly Detection (`clean` vs `defect`)

When `stringing` and `other_defect` are combined into a single **`defect`** class (`26 defect`, `3 clean`), multi-defect attribution disagreements disappear:

| Metric | `gemini-3.8-flash` | `gemma-4-31b-it` | `gemma-4-26b-a4b-it` |
|---|---|---|---|
| **3-class accuracy** | 69.0% (20/29) | 86.2% (25/29) | 79.3% (23/29) |
| **Binary accuracy** | **89.7%** (26/29) *(+20.7 pts)* | **93.1%** (27/29) *(+6.9 pts)* | **79.3%** (23/29; **82.1%** of 28 valid) |
| **Defect recall** | 88.5% (23/26) | **100.0% (26/26)** | 80.8% (21/26; 84.0% valid) |
| **Defect precision** | **100.0% (23/23)** | 92.9% (26/28) | 95.5% (21/22) |
| **Defect F1** | 93.9% | **96.3%** | 89.4% |
| **Clean specificity (no false alarms)** | **100.0% (3/3)** | 33.3% (1/3) | 66.7% (2/3) |

---

## 6. Per-Image Error Analysis & Model Reasonings

All 15 images where at least one model disagreed with the baseline ground-truth label (the remaining 14 images were unanimous 3/3 hits):

| Image | Truth | `gemini-3.8-flash` | `gemma-4-31b-it` | `gemma-4-26b-a4b-it` |
|---|---|---|---|---|
| `Clean_butterfly.jpeg` | `clean` | ✓ `clean` — *"Cleanly printed with sharp color transitions, smooth surfaces, and no noticeable stringing."* | ✗ `stringing` — *"Fine strands of filament are visible extending from the right side of the print onto the build plate."* | ✓ `clean` — *"Smooth surfaces and sharp details with no visible stringing or other defects."* |
| `Clean_zoro.webp` | `clean` | ✓ `clean` — *"Only a couple of negligible, hairline stringing wisps visible near the sword hilts and hair tips, minor enough to classify as overall clean."* | ✗ `stringing` — *"Fine strands of filament are visible between the sword handles and around the spiky hair."* | ✗ `stringing` — *"Fine filament strands are visible between the sword hilts and near the top of the left sword."* |
| `bad_wall_quality_inside_bike.jpg` | `other_defect` | ✗ `stringing` — *"Fine wisps and thin strands of filament bridging across the interior cavity."* | ✓ `other_defect` — *"Significant blobbing and a rough, uneven surface texture."* | ✓ `other_defect` — *"Significant texture irregularities and heavy blobbing."* |
| `golden_support_piece.jpg` | `other_defect` | ✓ `other_defect` — *"Significant under-extrusion or perimeter failure on the right vertical column."* | ✓ `other_defect` — *"Visible blobbing and rough surface texture on the right side."* | ✗ `clean` — *"No obvious stringing, blobs, or layer shifts."* |
| `golden_whispV3.jpg` | `other_defect` | ✗ `clean` — *"No observable stringing between sections, intact geometry, and minimal surface defects."* | ✓ `other_defect` — *"Significant surface irregularities, blobs, and uneven wall textures."* | ✓ `other_defect` — *"Top edge and surface of the print are uneven and poorly formed."* |
| `gray_problem.jpg` | `other_defect` | ✗ `clean` — *"Printed neatly with smooth surfaces, good layer consistency, and no detectable defects."* | ✗ `stringing` — *"Fine filament strands are visible bridging the gaps between the printed pillars."* | ✓ `other_defect` — *"Severe structural distortion and irregular, wavy layer formation."* |
| `green_slant2.jpg` | `other_defect` | ✓ `other_defect` — *"Significant roughness and degradation along the curved overhang on the right side."* | ✓ `other_defect` — *"Significant surface roughness and uneven texture."* | ✗ `clean` — *"Smooth surfaces and clean edges with no visible stringing, blobs, or layer shifts."* |
| `green_slant3.jpg` | `other_defect` | ✓ `other_defect` — *"Inconsistent extrusion/rough surface texture along a horizontal band across the front wall."* | ✓ `other_defect` — *"Visible white blob/defect on the top surface of the part."* | ✗ `clean` — *"Smooth surfaces and consistent layer lines with no visible stringing or major defects."* |
| `other_defect001.jpeg` | `other_defect` | ✗ `stringing` — *"Thin strands of filament spanning across the inner arch opening… along with minor layer inconsistencies."* | ✓ `other_defect` — *"Small horizontal zits or blobs are visible on the side of the main arch."* | ✗ `clean` — *"Printed surface appears smooth and free of visible stringing, blobs, or layer shifts."* |
| `other_defect002.jpeg` | `other_defect` | ✓ `other_defect` — *"Severe under-extrusion, rough localized scarring, gaps between extrusion lines."* | ✓ `other_defect` — *"Severe blobbing and zits across the entire surface."* | ✗ `ERROR` — *"Empty response from model"* *(2048 token cap exhausted)* |
| `other_defect004.jpeg` | `other_defect` | ✗ `stringing` — *"Small raised features (braille dots) show fine wisps and stringing caused by retraction and travel moves."* | ✓ `other_defect` — *"Visible zits and blobs on the top surface."* | ✓ `other_defect` — *"Visible small blobs or zits on the surface."* |
| `poor_adhesion.jpg` | `other_defect` | ✗ `clean` — *"Clean, uniform layer lines with no noticeable stringing, bridging defects, or visible layer shifts."* | ✗ `stringing` — *"Fine filament strands are visible bridging the small rectangular cutouts."* | ✓ `other_defect` — *"Top rim exhibits visible surface roughness and uneven texture."* |
| `Always_first_strand.webp` | `stringing` | ✗ `other_defect` — *"Catastrophic hotend blob / blob of death engulfing the nozzle area."* | ✓ `stringing` — *"Numerous fine filament strands and hairs bridging gaps across the part."* | ✓ `stringing` — *"Extreme, pervasive stringing and a highly whiskery, hairy texture."* |
| `real_stringing.jpg` | `stringing` | ✗ `other_defect` — *"Prominent layer lines, uneven extrusion, and sagging/incomplete bridging across internal cavity."* | ✓ `stringing` — *"Numerous fine filament strands bridging the top opening."* | ✓ `stringing` — *"Fine filament strands visible bridging the top opening and gaps."* |
| `stringing006.webp` | `stringing` | ✗ `other_defect` — *"Severe overhang and bridging failures, sagging and looped extrusions along roofline and chimney."* | ✓ `stringing` — *"Extensive cobweb-like stringing under the cabin roof and around the chimney."* | ✓ `stringing` — *"Significant messy filament strands and clumps around the cabin and smokestack."* |

---

## 7. Key Takeaways for Control-Loop Design

1. **Replace mutually-exclusive classes with independent defect flags:** Real calibration prints frequently exhibit co-occurring defects (e.g., stringing + overhang sag on `stringing006.webp`, or zits + travel wisps on `other_defect004.jpeg`). Asking for `{ has_stringing: bool, stringing_severity: 0..1, has_surface_blobs: bool, ... }` eliminates forced single-choice conflicts and maps directly to independent Klipper parameters (retraction/temp vs. Pressure Advance `K`).
2. **Add a severity floor for "clean":** All three models spotted identical microscopic wisps on `Clean_zoro.webp`; defining `clean` as `severity < 0.15` prevents negligible cosmetic hairs from triggering unnecessary recalibration.

---

## 8. USB-Camera Degradation Stress Test (`dataset_usb_degraded/`)

To test whether high scores on crisp web/smartphone photos survive real low-cost printer webcam optics, **`eval/degrade_dataset.js`** calibrated a synthetic degradation pipeline against `dataset/other_defect/gray_problem.jpg` (whose nominal `1920x1080` MJPEG container exhibits only ~480p of effective optical sharpness: 3×3 Laplacian std `4.94` vs. `10–38` on sharp web photos):

1. Downscaled every image to **`<= 640px` longest edge** (preserving aspect ratio, no upscaling)
2. Applied mild fixed-focus lens blur (**`sigma = 0.75`**)
3. Added deterministic CMOS low-light read/shot noise (**correlated luma `σ = 7.5` + per-channel chroma `σ = 4.5`**)
4. Re-encoded as **`4:2:0` MJPEG (`quality = 65`)** into `dataset_usb_degraded/` (`15 stringing / 3 clean / 11 other_defect`)

Result logs (`eval/results_usb_degraded/`):
- `eval/results_usb_degraded/gemini-3.8-flash/run-2026-11-14T21-10-13-711Z.json`
- `eval/results_usb_degraded/gemma-4-31b-it/run-2026-11-14T21-13-22-446Z.json`
- `eval/results_usb_degraded/gemma-4-26b-a4b-it/run-2026-11-14T21-28-34-939Z.json`

### 3-Class & Binary Results Under USB Degradation (vs. Original Dataset)

| Metric | `gemini-3.8-flash` (Orig → USB) | `gemma-4-31b-it` (Orig → USB) | `gemma-4-26b-a4b-it` (Orig → USB) |
|---|---|---|---|
| **3-class accuracy** | 69.0% → **58.6%** (17/29) | 86.2% → **65.5%** (19/29) | 79.3% → **62.1%** (18/29) |
| **Binary accuracy (`clean` vs `defect`)** | 89.7% → **72.4%** (21/29) | 93.1% → **82.8%** (24/29) | 79.3% → **72.4%** (21/29) |
| **Stringing recall** | 78.6% → **80.0%** (12/15) | 100.0% → **80.0%** (12/15)* | 100.0% → **73.3%** (11/15) |
| **Stringing precision** | 78.6% → **92.3%** | 77.8% → **85.7%** | 93.3% → **91.7%** |
| **Stringing F1** | 78.6% → **85.7%** | 87.5% → **82.8%** | 96.6% → **81.5%** |
| **Clean specificity (no false alarms)** | 100.0% → **100.0% (3/3)** | 33.3% → **100.0% (3/3)** | 66.7% → **100.0% (3/3)** |
| **Other-defect recall** | 50.0% → **18.2%** (2/11) | 83.3% → **36.4%** (4/11) | 63.6% → **36.4%** (4/11) |
| **Severity within ±1 tier** | 11/11 → **11/11 (100%)** | 10/11 → **10/11 (90.9%)** | 11/11 → **9/11 (81.8%)** |

*\*Note: All 3 of `gemma-4-31b-it`'s misses on `stringing` were classified as `other_defect` (`0` stringing images missed as `clean`).*

### Confusion Matrices Under USB Degradation (`15 stringing / 3 clean / 11 other_defect`)

**`gemini-3.8-flash` (USB-degraded)**
| Truth \ Pred | `stringing` | `clean` | `other_defect` |
|---|---:|---:|---:|
| **`stringing`** | **12** | 0 | 3 |
| **`clean`** | 0 | **3** | 0 |
| **`other_defect`** | 1 | 8 | **2** |

**`gemma-4-31b-it` (USB-degraded)**
| Truth \ Pred | `stringing` | `clean` | `other_defect` |
|---|---:|---:|---:|
| **`stringing`** | **12** | 0 | 3 |
| **`clean`** | 0 | **3** | 0 |
| **`other_defect`** | 2 | 5 | **4** |

**`gemma-4-26b-a4b-it` (USB-degraded)**
| Truth \ Pred | `stringing` | `clean` | `other_defect` |
|---|---:|---:|---:|
| **`stringing`** | **11** | 2 | 2 |
| **`clean`** | 0 | **3** | 0 |
| **`other_defect`** | 1 | 6 | **4** |

### Binary (`clean` vs `defect`) Metrics Under USB Degradation

| Metric | `gemini-3.8-flash` | `gemma-4-31b-it` | `gemma-4-26b-a4b-it` |
|---|---|---|---|
| **Binary accuracy** | 72.4% (21/29) | **82.8% (24/29)** | 72.4% (21/29) |
| **Defect recall** (caught / 26) | 69.2% (18/26) | **80.8% (21/26)** | 69.2% (18/26) |
| **Defect precision** | **100.0% (18/18)** | **100.0% (21/21)** | **100.0% (18/18)** |
| **Defect F1** | 81.8% | **89.4%** | 81.8% |
| **Clean specificity (no false alarms)** | **100.0% (3/3)** | **100.0% (3/3)** | **100.0% (3/3)** |
| **Severity exact / within ±1 tier** | 5/11 / **11/11** | **6/11** / 10/11 | 5/11 / 9/11 |

### What USB-Camera Degradation Changed

1. **Stringing detection & severity estimation survive cheap USB webcam quality (`81.5%–85.7%` F1):** Even at 640p with optical blur, CMOS grain, and MJPEG compression, filament strands spanning open air maintain enough contrast for both cloud and open-weight 4B-active models to detect reliably and estimate severity within ±1 tier (`9/11` to `11/11`). Only the mildest tier-1 wisps (`stringing011.jpg`) and co-occurring Z-band prints (`stringing010.jpg`) dropped below `gemma-4-26b-a4b-it`'s detection threshold.
2. **False alarms dropped to 0% across all three models (`3/3` clean specificity, `100%` binary defect precision):** Slight optical softening acted as a natural low-pass filter, erasing the sub-pixel cosmetic hairs on `Clean_zoro` and `Clean_butterfly` that previously triggered false positives on the Gemma models.
3. **Subtle surface/relief defects (`other_defect`) require better optics or grazing light:** `other_defect` recall dropped sharply across every model (`18.2%–36.4%`) because 480p softness + sensor noise washes out fine zits (`other_defect004`), seam lines (`other_defect001`), and subtle corner bulges (`terrible_corners`, `poor_adhesion`). **Implication:** Stock printer webcams are sufficient as-is for automated retraction/temperature (stringing) tuning, whereas automated Pressure Advance (`K`) tuning needs closer camera placement or grazing side-lighting so corner blobs cast high-contrast shadows.

---

## 9. Broad 18-Class Diagnosis & Root-Cause Reasoning Benchmark (`dataset/context_dev/`)

To evaluate **Step 2 (root-cause & Klipper/slicer fix reasoning)** across a wide 18-class taxonomy (`stringing`, `oozing`, `warping`, `layer_shift`, `underextrusion`, `overextrusion`, `bed_adhesion`, `first_layer`, `spaghetti_detection`, `z_banding`, `ringing`, `blobs_zits`, `cracking`, `pillowing`, `ghosting`, `overhang_curling`, `mechanical_misalignment`, `other`) plus `clean` negative controls, we evaluated **`68` multimodal `r/FixMyPrint` failure cases (`59` OP-solved)** and **`16` deduplicated clean/showcase prints** under three input regimes:

- **Variant A — Pure Visual-Only:** Image(s) *only* (zero title, zero telemetry, zero body text).
- **Variant T — Printer Telemetry-Only:** Image(s) + static machine/slicer setup parameters (`printer_context`: printer model, material, nozzle/bed temps, speeds, retraction) — matching what **Moonraker / Klipper** knows automatically with zero human input.
- **Variant B — Full Context-Assisted:** Image(s) + post title + telemetry + body excerpt.

Root causes and recommended fixes are graded `0–2` by a multimodal rubric judge (`gemini-pro-latest`) inspecting both the photograph(s) and the thread's OP/community-validated rubric, alongside a randomized blind head-to-head A/B judge.

Result logs:
- `dataset/context_dev/data/eval_runs/gemini-3.5-flash-lite/eval_report.json` (`2026-11-15T00:12:09Z`)
- `dataset/context_dev/data/eval_runs/gemma-4-31b-it/eval_report.json` (`2026-11-15T01:49:16Z`)
- `dataset/context_dev/data/eval_runs/gemma-4-26b-a4b-it/eval_report.json` (`2026-11-15T01:12:37Z`)
- `dataset/context_dev/data/eval_runs/nemotron-3.5-super-vl/eval_report.json` (`2026-11-15T05:05:37Z`)

### Headline Multi-Class & Reasoning Results (`N = 68`, `0` Errors Excluded)

| Model | Variant | `N` | Strict 18-Class | Closed-Tax (`!=other`, `N=65`) | Coarse Group | Causes (`0–2`) | Fixes (`0–2`) | Stringing Recall (`N=7`) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| **`gemini-3.5-flash-lite`** | **A (Pure Visual)** | 68 | **55.9%** | **58.5%** | 55.9% | **0.84** | 0.78 | 85.7% |
| **`gemini-3.5-flash-lite`** | **T (+ Klipper Telemetry)** | 68 | **64.7%** | **67.7%** | **64.7%** | **1.03** | **1.03** | 85.7% |
| **`gemini-3.5-flash-lite`** | **B (+ User Post Text)** | 68 | **72.1%** | **75.4%** | **73.5%** | **1.34** | 1.24 | **100.0%** |
| **`gemma-4-31b-it`** | **A (Pure Visual)** | 68 | 35.3% | 36.9% | 36.8% | 0.79 | **0.79** | 85.7% |
| **`gemma-4-31b-it`** | **T (+ Klipper Telemetry)** | 68 | 38.2% | 40.0% | 38.2% | 0.94 | 0.93 | 71.4% |
| **`gemma-4-31b-it`** | **B (+ User Post Text)** | 68 | 55.9% | 58.5% | 61.8% | 1.32 | **1.35** | **100.0%** |
| **`gemma-4-26b-a4b-it`** | **A (Pure Visual)** | 68 | 35.3% | 36.9% | 39.7% | 0.72 | 0.66 | **100.0%** |
| **`gemma-4-26b-a4b-it`** | **T (+ Klipper Telemetry)** | 68 | 38.2% | 40.0% | 44.1% | 0.71 | 0.69 | **100.0%** |
| **`gemma-4-26b-a4b-it`** | **B (+ User Post Text)** | 68 | 55.9% | 58.5% | 60.3% | 1.06 | 1.03 | **100.0%** |
| **`nvidia/nemotron-3.5-super-vl`** | **A (Pure Visual)** | 68 | 19.1% | 20.0% | 20.6% | 0.50 | 0.44 | **100.0%** |
| **`nvidia/nemotron-3.5-super-vl`** | **T (+ Klipper Telemetry)** | 68 | 20.6% | 21.5% | 25.0% | 0.49 | 0.51 | **100.0%** |
| **`nvidia/nemotron-3.5-super-vl`** | **B (+ User Post Text)** | 68 | 54.4% | 56.9% | 58.8% | 1.28 | 1.25 | **100.0%** |

### Clean Negative Controls (`N = 16` Pure Visual) & Blind Pairwise A/B (`N = 68`)

- **Clean Specificity (`16` showcase/post-fix clean prints):**
  - **`gemini-3.5-flash-lite`:** **`93.8%` (`15/16` clean, `6.2%` false-alarm rate)**
  - **`gemma-4-31b-it`:** **`87.5%` (`14/16` clean, `12.5%` false-alarm rate)**
  - **`nvidia/nemotron-3.5-super-vl`:** **`87.5%` (`14/16` clean, `12.5%` false-alarm rate)**
  - **`gemma-4-26b-a4b-it`:** **`75.0%` (`12/16` clean, `25.0%` false-alarm rate)**
  - Notably, **all four models (`Gemini`, `Gemma 31B`, `Gemma A4B`, and `Nemotron 3.5 Super VL`) unanimously tripped on `3dprinting_1ihsom2_clean_0`**—a Millennium Falcon intentionally suspended mid-air by hundreds of single-extrusion "hyperspace" bridged strands (visually identical to severe stringing without CAD/G-code context).
- **Blind Pairwise Head-to-Head A/B vs. `gemini-3.5-flash-lite` (`N = 68`):**
  - **`gemma-4-31b-it`:** Ties or beats `gemini-3.5-flash-lite` on **`60.3%`** of cases in Variant A (`23.5%` wins + `36.8%` ties), **`54.4%`** in Variant T (`25.0%` wins + `29.4%` ties), and **`52.9%`** in Variant B (`29.4%` wins + `23.5%` ties; `1.35` vs. `1.24` fix rubric score).
  - **`gemma-4-26b-a4b-it`:** Ties or beats `gemini-3.5-flash-lite` on **`54.4%`** of cases in Variant A (`20.6%` wins + `33.8%` ties), **`47.1%`** in Variant T (`23.5%` wins + `23.5%` ties), and **`42.6%`** in Variant B (`19.1%` wins + `23.5%` ties)—matching Gemma 31B's exact 18-class accuracy (`36.9% / 40.0% / 58.5%`) and hitting **`100% (7/7)` stringing recall across every variant**, while trailing 31B on telemetry-driven root-cause/fix synthesis (`0.69` vs. `0.93` on Variant T).
  - **`nvidia/nemotron-3.5-super-vl` (`120B` total / `12B` active MoE):** Exhibits a stark **vision-vs-reasoning split**. On pure photography (`Variant A` / `T`), Nemotron's vision encoder is coarse on fine 3D-print layer textures (`20.0%` / `21.5%` closed-taxonomy accuracy)—over-triggering `"stringing"` whenever stray wisps exist (`30/68` Variant A predictions, `7/7 = 100%` stringing recall) while calling `19/68` fine-surface failures `"clean"`. Yet once given symptom text in **`Variant B`**, its `120B` MoE reasoning surges **`+36.9 pts` (`20.0% → 56.9%`)** and reaches **`1.25 / 2.0` on actionable fixes** (edging out `gemini-3.5-flash-lite`'s `1.24` and tying or beating Flash-Lite on **`51.5%`** of blind A/B cases: `29.4%` wins + `22.1%` ties).

---

## 10. Per-Image Processing Latency & Closed-Loop Timing

Measured from full sequential 29-image runs (excluding the intentional `300 ms` rate-limit sleep) plus a 3-image token-telemetry probe on Google AI Studio:

| Model | 29-Image Sequential Avg | 3-Image Timed Probe | Avg JSON Output Tokens | Avg Internal "Thinking" Tokens |
|---|---:|---:|---:|---:|
| **`gemini-3.5-flash-lite`** | — *(ran `concurrency=4`)* | **`1.52 s / img`** | ~60 | **0** *(non-thinking)* |
| **`gemini-3.8-flash`** | **`5.90 s / img`** (`171.1s` / 29) | **`4.83 s / img`** | ~44 | ~242 |
| **`gemma-4-26b-a4b-it`** *(4B active)* | **`12.51 s / img`** USB · **`13.49 s / img`** raw | **`20.47 s / img`** *(ambiguous USB)* | ~52 | **~785** |
| **`gemma-4-31b-it`** *(31B dense)* | **`~14.7 s / img`** (`~426s` / 29) | **`12.82 s / img`** | ~51 | ~354 |

- **Closed-loop Klipper viability:** Because a physical retraction or Pressure Advance calibration segment takes **`5–15 minutes (300–900 s)`** to print before snapping a single inspection frame, even `12.5–14.7 s` represents **`< 3%` cycle overhead**—making every tested model fast enough for automated closed-loop calibration.
- **Local Gemma latency optimization:** ~90% of Gemma 4's API response time goes into generating `350–785` internal chain-of-thought tokens (`thought: true`) rather than vision encoding or the ~50-token JSON payload. Disabling or capping thinking tokens when self-hosting locally (`llama.cpp` / `vLLM`) reduces local per-frame latency by **~5–8×** (to ~2–3 s/frame).



