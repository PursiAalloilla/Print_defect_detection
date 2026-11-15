# 20-Record Manual / Visual Quality Audit (`eval.jsonl` — Post-Remediation)

- **Dataset audited**: `data/dataset/eval.jsonl` (`68` positive defect test records + `6` held-out `val.jsonl` records = `74` total defect records; `35` multi-image gallery records)
- **Automated Multimodal VLM Gate**: Prior to dataset assembly, `src/synthesize.py` (`gemini-3.5-flash`) visually inspected all `179` downloaded images and populated per-image `image_roles` (`failed_print`, `clean_print`, `hardware_closeup`, `slicer_or_ui`, `other`) and `shows_failed_print`:
  - **10 non-defect posts** (`fixmyprint_104yh02`, `fixmyprint_10okdfa`, `fixmyprint_15462pi`, `fixmyprint_16m4iq2`, `fixmyprint_1i2mo2x`, `fixmyprint_1ty1iz3`, `fixmyprint_m1ct0o`, `fixmyprint_p3ig0u`, `fixmyprint_rrglqe`, `fixmyprint_u298h1`) were automatically excluded into `data/dataset/excluded_non_defect.jsonl`.
  - **10 clean/post-fix print images** were routed into `data/dataset/negative_controls.jsonl` (`defect_class: "clean"`) to measure model False-Alarm Rate / Specificity.
- **Post-remediation audit sample**: Deterministic uniform sample of `20` records (`random.Random(2026)`) from the cleaned `68`-record `eval.jsonl`.
- **Result**: **20 / 20 ACCEPT (`100.0%`)** (up from `17 / 20` before the multimodal image-role gate).

---

## Per-Record Audit Table (`eval.jsonl` Cleaned Sample)

| # | Record ID | Imgs | Defect Class | Solved | Decision | Visual & Diagnostic Notes |
| ---: | --- | ---: | --- | --- | --- | --- |
| 01 | `fixmyprint_1mtko0a` | 3 | `underextrusion` | `true` | **ACCEPT** | Photos clearly show localized underextrusion holes after corners on a black part; OP confirmed lowering print acceleration fixed it. |
| 02 | `fixmyprint_m5j16b` | 4 | `blobs_zits` | `true` | **ACCEPT** | Grey Benchy covered in large blobs along hull and cabin pillars from retraction speed/buffer stalls. |
| 03 | `fixmyprint_wtkwlr` | 3 | `first_layer` | `true` | **ACCEPT** | Gallery shows uneven first-layer corner lifting/gaps caused by unlevel bed corner. |
| 04 | `fixmyprint_1l7wdk2` | 2 | `first_layer` | `true` | **ACCEPT** | Unbonded first-layer extrusion lines from overly high Z-offset compounded by slicer offset. |
| 05 | `fixmyprint_1ssocki` | 3 | `other` | `true` | **ACCEPT** | Wood PLA print showing pronounced diagonal surface banding/sheen artifacts; OP confirmed slicer infill angle / flow fix. |
| 06 | `fixmyprint_tc74ho` | 1 | `bed_adhesion` | `true` | **ACCEPT** | White first-layer print peeling at the lower-left corner on textured glass bed due to excessive initial nozzle gap. |
| 07 | `fixmyprint_1xozvqf` | 3 | `spaghetti_detection` | `true` | **ACCEPT** | Tall yellow figures erupting into mid-print spaghetti tangles due to model sway at high print speed. |
| 08 | `fixmyprint_ljb4b8` | 1 | `underextrusion` | `true` | **ACCEPT** | Intermittent underextruded gaps across walls resolved by raising printing temperature. |
| 09 | `fixmyprint_1wdjg8y` | 2 | `overextrusion` | `true` | **ACCEPT** | Bottom/first-layer wave ripples caused by uncalibrated flow rate and pressure advance. |
| 10 | `fixmyprint_1ry56nm` | 1 | `pillowing` | `false` | **ACCEPT** | Bumpy/broken top solid surface over infill grid (`pillowing`), with consensus advising more top solid layers + cooling. |
| 11 | `fixmyprint_qjjhp2` | 1 | `layer_shift` | `true` | **ACCEPT** | Severe staircase layer shifting on Ender 3 V2 resolved by replacing overheating 4.2.2 mainboard with 4.2.7. |
| 12 | `fixmyprint_1wr2qz6` | 1 | `layer_shift` | `true` | **ACCEPT** | Dramatic multi-centimeter X/Y gear print shifts across the build plate caused by loose belt/bed hardware. |
| 13 | `fixmyprint_uc4cht` | 1 | `underextrusion` | `true` | **ACCEPT** | `220` temperature tower turning spongy/underextruded mid-height due to heat creep from inverted heatsink fan grill. |
| 14 | `fixmyprint_sjnlnd` | 1 | `underextrusion` | `true` | **ACCEPT** | Delaminated, spaghetti-like seam extrusions on a black box wall resolved by switching from corrupted Cura defaults to CHEP profile. |
| 15 | `fixmyprint_p1lgz3` | 1 | `blobs_zits` | `true` | **ACCEPT** | Large solidified plastic blob pooled atop the left post of a retraction test due to missing Z-lift/park in end G-code. |
| 16 | `fixmyprint_q2kdqj` | 3 | `stringing` | `true` | **ACCEPT** | Multi-angle photos of fine hair/stringing webs across features, resolved by lowering nozzle temperature. |
| 17 | `fixmyprint_rz9zul` | 3 | `underextrusion` | `true` | **ACCEPT** | Striped missing-extrusion bands across print walls caused by a cracked stock plastic extruder arm. |
| 18 | `fixmyprint_1uwjj8r` | 4 | `other` | `false` | **ACCEPT** | Overhang/boss curling deformation on calibration temp tower attributed to delayed part cooling fan ramp. |
| 19 | `fixmyprint_pmtbf8` | 1 | `stringing` | `true` | **ACCEPT** | Articulated PETG octopus covered in thick branching strings/ooze from excessive `8mm` retraction distance at `245°C`. |
| 20 | `fixmyprint_1xoye3y` | 4 | `first_layer` | `true` | **ACCEPT** | Torn, ridged first-layer extrusion sheet from nozzle printing too close to the bed. |
