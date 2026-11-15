/**
 * degrade_dataset.js — Emulate low-cost printer USB webcam quality
 *
 * Calibrated against `dataset/other_defect/gray_problem.jpg`: although the UVC
 * driver saves a 1920x1080 MJPEG container, its fixed-focus plastic optics and
 * small CMOS sensor resolve only ~480p of real spatial detail (3x3 Laplacian
 * std ≈ 4.9 vs. 10–38 on smartphone/web images) with visible shadow grain and
 * 4:2:0 MJPEG compression artifacts.
 *
 * Pipeline applied deterministically to every image in `dataset/`:
 *   1. Resize longest edge to <= 640px (preserving aspect ratio, no upscaling)
 *   2. Mild optical blur (sigma = 0.75) to emulate cheap fixed-focus lens MTF
 *   3. Seeded CMOS read/shot noise (correlated luma σ=7.5 + per-channel chroma σ=4.5)
 *   4. Re-encode as 4:2:0 MJPEG (quality = 65) into `dataset_usb_degraded/`
 *   5. Rewrite `labels.json` keys to `.jpg` so human severity scoring still works
 */

const fs = require("fs");
const path = require("path");
const sharp = require("sharp");

const SRC_DIR = path.join(__dirname, "..", "dataset");
const DST_DIR = path.join(__dirname, "..", "dataset_usb_degraded");
const CLASSES = ["stringing", "clean", "other_defect"];
const IMG_EXTS = new Set([".jpg", ".jpeg", ".png", ".webp"]);

// Deterministic Mulberry32 PRNG seeded from relative file key so runs are 100% reproducible.
function makeRng(seedStr) {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < seedStr.length; i++) {
    h = Math.imul(h ^ seedStr.charCodeAt(i), 16777619) >>> 0;
  }
  return function () {
    h |= 0;
    h = (h + 0x6d2b79f5) | 0;
    let t = Math.imul(h ^ (h >>> 15), 1 | h);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function gaussian(rng) {
  const u = Math.max(1e-9, rng());
  const v = rng();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

async function degradeImage(inPath, outPath, seedKey) {
  const rng = makeRng(seedKey);

  const { data, info } = await sharp(inPath)
    .resize({ width: 640, height: 640, fit: "inside", withoutEnlargement: true })
    .blur(0.75)
    .removeAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true });

  const noisy = Buffer.alloc(data.length);
  for (let i = 0; i < data.length; i += 3) {
    const lumaNoise = gaussian(rng) * 7.5;
    for (let c = 0; c < 3; c++) {
      const val = data[i + c] + lumaNoise + gaussian(rng) * 4.5;
      noisy[i + c] = val < 0 ? 0 : val > 255 ? 255 : Math.round(val);
    }
  }

  await sharp(noisy, {
    raw: { width: info.width, height: info.height, channels: 3 },
  })
    .jpeg({ quality: 65, chromaSubsampling: "4:2:0" })
    .toFile(outPath);

  return { width: info.width, height: info.height };
}

async function main() {
  fs.rmSync(DST_DIR, { recursive: true, force: true });

  let count = 0;
  for (const cls of CLASSES) {
    const srcCls = path.join(SRC_DIR, cls);
    const dstCls = path.join(DST_DIR, cls);
    if (!fs.existsSync(srcCls)) continue;
    fs.mkdirSync(dstCls, { recursive: true });

    for (const file of fs.readdirSync(srcCls).sort()) {
      const parsed = path.parse(file);
      if (!IMG_EXTS.has(parsed.ext.toLowerCase())) continue;

      const inPath = path.join(srcCls, file);
      const outFile = `${parsed.name}.jpg`;
      const outPath = path.join(dstCls, outFile);
      const dims = await degradeImage(inPath, outPath, `${cls}/${parsed.name}`);
      count++;
      console.log(
        `  [${count}] ${cls}/${file} -> ${cls}/${outFile} (${dims.width}x${dims.height})`
      );
    }
  }

  // Copy and remap labels.json extensions (.webp/.png/.jpeg -> .jpg)
  const srcLabels = path.join(SRC_DIR, "labels.json");
  if (fs.existsSync(srcLabels)) {
    const raw = JSON.parse(fs.readFileSync(srcLabels, "utf8"));
    const remapped = {};
    for (const [k, v] of Object.entries(raw)) {
      if (k.startsWith("_")) {
        remapped[k] = v;
      } else {
        const dir = path.dirname(k);
        const stem = path.parse(k).name;
        remapped[`${dir}/${stem}.jpg`] = v;
      }
    }
    fs.writeFileSync(
      path.join(DST_DIR, "labels.json"),
      JSON.stringify(remapped, null, 2)
    );
  }

  console.log(`\nCreated ${count} USB-degraded images in ${DST_DIR}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
