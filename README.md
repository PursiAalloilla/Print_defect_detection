# Print Defect Detection — Live Forum Ground Truth & Local Open Vision for Self-Calibrating 3D Printers

An exploration of how local open-weight models (**Google Gemma 4**) and cloud multimodal models (**Google Gemini**), grounded by a live-web forum distillation pipeline (**Context.dev**), can remove the human from vision-based 3D-printer calibration on open-source **Klipper / Moonraker** machines.

### Interactive Results Showcases (GitHub Pages)
- **Technical Showcase:** [`docs/index.html`](https://pursiaalloilla.github.io/Print_defect_detection/)
- **Plain-English (`/bro`) Showcase:** [`docs/bro/index.html`](https://pursiaalloilla.github.io/Print_defect_detection/bro/)

---

## 1. The Problem: Two Bottlenecks Blocking Open Autonomous Calibration

1. **Human-in-the-loop calibration waste:** Fine-tuning retraction, nozzle temperature, and Pressure Advance (`K`) to fix visual print defects (**stringing**, **corner blobs**, **overhang curling**, **layer lines**) still forces makers, schools, and workshops to print trial-and-error towers by hand—wasting filament and hours of `250W+` heated-bed/nozzle power, unless they buy into closed-cloud proprietary printer ecosystems.
2. **Stale/missing ground truth for Physical AI:** Manually printing and breaking 500 parts in a lab takes months, and static datasets go out of date whenever new high-speed slicers or engineering filaments launch—even though thousands of solved real-world cases sit scattered across unstructured forum threads (`r/FixMyPrint`).

---

## 2. Our Solution & Architecture

```
Live Troubleshooting Forums (r/FixMyPrint, r/3Dprinting)
  │
  ├─► Context.dev API (reddit-search + reddit-post + formats.bytes + Batches)
  ├─► Gemini S5 Multimodal Synthesizer (OP "Solved" gate + score-weighted consensus + comment_id citations)
  ├─► Automated Ground-Truth Testbench (68 wild failures across 18 classes + 16 clean controls)
  │
  ▼
External USB Webcam Sim (Raw + Synthetic <=640p Blur & CMOS Noise Stress Test)
  │
  ├─► Local Open-Weight Vision: Gemma 4 (gemma-4-26b-a4b-it 4B-active & gemma-4-31b-it)
  ├─► Hybrid Escalation + Moonraker Telemetry (Variant T: temps, speeds, retraction -> Gemini)
  └─► Klipper / Moonraker API Target (SET_RETRACTION, SET_PRESSURE_ADVANCE, M104 / M106)
```

---

## 3. Headline Findings (`113` Evaluated Cases)

| Evaluation Dimension | Cloud (`gemini-3.8-flash` / `3.5-flash-lite`) | Open `gemma-4-31b-it` | Open `gemma-4-26b-a4b-it` (4B active) | Open `nemotron-3.5-super-vl` (12B active) |
|---|---|---|---|---|
| **Stringing F1 (Original / 480p USB + Noise)** | 78.6% / **85.7%** | 87.5% / 82.8% | **96.6%** / 81.5% | — |
| **Binary Anomaly Gate (`clean` vs. `defect`)** | **89.7%** (0% false alarms) | **93.1%** (26/26 caught) | 82.1% valid | — |
| **Severity Match (`±1` Human Tier, `N=11`)** | **11/11 (100%)** | 10/11 (90.9%) | **11/11 (100%)** | — |
| **Wild 18-Class Pure Visual (`Var A`)** | **58.5%** (`0.78/2` fix) | 36.9% (`0.79/2` fix) | 36.9% (`0.66/2` fix; **100%** str) | 20.0% (`0.44/2` fix; **100%** str) |
| **Wild 18-Class + Klipper Telemetry (`Var T`)** | **67.7%** (`1.03/2` fix) | 40.0% (`0.93/2` fix) | 40.0% (`0.69/2` fix; **100%** str) | 21.5% (`0.51/2` fix; **100%** str) |
| **Wild 18-Class + Post Context (`Var B`)** | **75.4%** (`1.24/2` fix) | 58.5% (**`1.35/2` fix**) | 58.5% (`1.03/2` fix; **100%** str) | 56.9% (**`1.25/2` fix**; **100%** str) |
| **Clean Negative Controls (`N=16` Pure Visual)** | **93.8% (15/16)** | **87.5% (14/16)** | 75.0% (12/16) | **87.5% (14/16)** |

- **Open 4B-active Gemma 4 is ready for local stringing/retraction loops:** Even under synthetic `<=640p` webcam blur + CMOS grain calibrated to our external USB test camera (`3×3` Laplacian `σ=4.94`), open models preserve `81.5%–85.7%` Stringing F1 and `0%` false alarms on clean prints, while revealing that subtle Pressure Advance corner blobs need closer optics or GPIO-triggered grazing side-LEDs.
- **Moonraker telemetry boosts 18-class diagnosis with zero human text:** Injecting static printer/slicer specs (`Variant T`) lifts closed-taxonomy accuracy from **`58.5%` → `67.7%` (`+9.2 pts`)** and boosts actionable fix quality by **`+32%`** (`0.78` → `1.03 / 2.0`).

---

## 4. Context.dev Endpoints Used & Why

1. **`POST /v1/scrape` (`formats.parse`, prebuilt `reddit-search`):** Discovers high-engagement troubleshooting threads across `r/FixMyPrint` and `r/3Dprinting` filtered by post type, comment count, and flair.
2. **`POST /v1/scrape` & `POST /v1/batches` (`formats.parse`, prebuilt `reddit-post` with deterministic `Idempotency-Key`):** Extracts full post metadata and nested 200-comment trees (`sort=top`) as clean JSON so Stage 5 can verify explicit OP `Solved` confirmations and weight advice by community score without maintaining fragile scrapers.
3. **`POST /v1/scrape` (`formats.bytes`, `maxAgeMs=0`):** Downloads original failure photographs with MIME verification, per-output `.success` checks, SHA-256 crosspost deduplication, and local `request_id` / credit logging (`credit_usage.jsonl`) to prevent duplicate spend.
4. **Optional `formats.images` (`enrich: ["dimensions", "classification", "file"]`, `dedupe: "visual"`):** Filters out non-photographic UI chrome on mixed web forum pages.

---

## 5. Google Gemma & Gemini Integration

- **Google DeepMind Gemma 4 (`gemma-4-31b-it` & `gemma-4-26b-a4b-it`):** Evaluated as the local open-weight vision backbone (down to 4B active parameters), handling chain-of-thought reasoning extraction, continuous `0.0–1.0` severity estimation, and zero-cloud privacy.
- **Google Gemini API (`gemini-3.8-flash`, `gemini-3.5-flash`, `gemini-3.5-flash-lite`):**
  1. **Multimodal Ground-Truth Synthesizer (`S5`):** Audits every thread's gallery images (`failed_print` vs. `hardware_closeup` / `slicer_or_ui` / `clean_print`) while synthesizing comment trees into Draft 2020-12 JSON Schema rubrics with verified `evidence_comment_ids`.
  2. **Multimodal Rubric & Blind Pairwise A/B Judge (`S7`):** Scores candidate root causes and fixes (`0–2`) against both the photograph and confirmed community fix.
  3. **Hybrid Telemetry Escalation (`Variant T`):** Provides deep multi-parameter root-cause synthesis when subtle non-stringing defects exceed 4B edge capacity.

---

### Made for Junction 2026
