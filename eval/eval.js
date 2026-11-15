/**
 * eval.js — Anomaly-detection evaluation harness for Gemini
 *
 * What this script does, end to end:
 *   1. Walks the dataset/ folder and builds a list of test examples.
 *      The FOLDER NAME is the ground-truth label (dataset/stringing/x.webp
 *      is expected to be "stringing"). No separate labels file needed.
 *   2. For each image, sends it to the Gemini API with a carefully
 *      designed prompt and asks for a STRUCTURED (JSON) response.
 *   3. Compares predictions against ground truth and computes metrics:
 *      confusion matrix, accuracy, and per-class precision/recall/F1.
 *   4. Saves every raw prediction to eval/results/ so you can inspect
 *      exactly what the model said on each image (crucial for debugging).
 *
 * Usage:
 *   GEMINI_API_KEY=your_key  node eval.js [model-id]
 *
 * The model id defaults to gemini-2.5-flash but can be anything the API
 * supports — pass the model you're actually testing as the first argument.
 */

const fs = require("fs");
const path = require("path");

// ---------------------------------------------------------------------------
// 1. CONFIGURATION
// ---------------------------------------------------------------------------

// Model comes from CLI arg > GEMINI_MODEL env var > default.
// We deliberately don't hardcode a model in the middle of the script:
// an eval harness should make the "thing being tested" easy to swap.
const MODEL = process.argv[2] || process.env.GEMINI_MODEL || "gemini-2.5-flash";
const USE_OPENROUTER =
  process.env.API_PROVIDER === "openrouter" ||
  (MODEL.includes("/") && !MODEL.startsWith("models/"));
const API_URL = USE_OPENROUTER
  ? "https://openrouter.ai/api/v1/chat/completions"
  : `https://generativelanguage.googleapis.com/v1beta/models/${MODEL}:generateContent`;

// Gemma models on this API don't support two Gemini features we rely on:
//   - system_instruction (persistent role/rules message)
//   - response_schema (constrained JSON decoding)
// So for gemma-* we fold the instructions into the user turn and parse the
// JSON defensively out of whatever prose comes back.
const IS_GEMMA = /^gemma/i.test(MODEL);

const DATASET_DIR = process.env.DATASET_DIR
  ? path.resolve(process.env.DATASET_DIR)
  : path.join(__dirname, "..", "dataset");
// One subdirectory per model: results/gemini-3.8-flash/, results/gemma-4-31b-it/...
// RESULTS_ROOT can be overridden (e.g. eval/results_usb_degraded) to separate experiments.
const RESULTS_ROOT = process.env.RESULTS_ROOT
  ? path.resolve(process.env.RESULTS_ROOT)
  : path.join(__dirname, "results");
const SAFE_MODEL_DIR = MODEL.replace(/\//g, "_").replace(/:/g, "_");
const RESULTS_DIR = path.join(RESULTS_ROOT, SAFE_MODEL_DIR);

// Sidecar file with extra per-image metadata (severity, context, notes).
// Design principle: filenames are meaningless IDs; ALL human knowledge
// about an image lives here, where the model can never see it. The file is
// optional — the eval still runs without it, you just don't get the
// severity-agreement report.
const LABELS_FILE = path.join(DATASET_DIR, "labels.json");

// The closed set of classes. The model can ONLY answer with one of these,
// because we enforce it in the JSON schema below. A closed set is what
// turns a fuzzy "look at this image" chat into a measurable classification.
const CLASSES = ["stringing", "clean", "other_defect"];

// The API needs to know how to decode the raw image bytes we send it.
// File extensions map to official MIME types. Note: .jpg -> image/jpeg.
const MIME_TYPES = {
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png",
  ".webp": "image/webp",
};

// ---------------------------------------------------------------------------
// 2. PROMPT DESIGN
// ---------------------------------------------------------------------------

/**
 * The system instruction sets the model's ROLE and defines the classes
 * precisely. Vague class definitions are the #1 cause of bad eval results:
 * if the model and you disagree about what "stringing" means, you'll score
 * it wrong even when it's "right". So each class gets a definition:
 *  - stringing: the defect we care about (positive class)
 *  - other_defect: a defect that ISN'T stringing — this is our distractor
 *    class. It tests SPECIFICITY: can the model tell stringing apart from
 *    similar-looking defects (blobbing, zits...), or does any "bad print"
 *    count as stringing?
 *  - clean: no defect — tests that the model doesn't cry wolf.
 */
const SYSTEM_PROMPT = `You are a 3D-print quality inspection agent.
You are shown a photo of a 3D-printed test part (e.g. a Benchy boat, a stringing test tower, or a calibration part).

Classify the part into exactly one category:
- "stringing": fine strands or hairs of stretched filament bridging surfaces, whiskery/hairy artifacts. Light wisps count as stringing.
- "other_defect": the part has a visible print defect, but NOT stringing. Examples: blobbing/zits, layer shift, under-extrusion, warping, scarring.
- "clean": no visible print defects.

Also estimate:
- severity: 0.0 (flawless) to 1.0 (severely defective)
- confidence: 0.0 to 1.0, how sure you are of the classification
- reasoning: ONE short sentence pointing at the visual evidence.

Respond with only the JSON object matching the provided schema.`;

/**
 * The response schema is the heart of a reliable eval. Two jobs:
 *  1. It CONSTRAINS the model — predicted_class can only be one of the
 *     three enum values, so we can score it automatically without
 *     fragile string parsing ("It looks like stringing!" vs "stringing").
 *  2. It makes the output machine-readable — we get fields we can trend
 *     (severity, confidence) instead of free text.
 * Gemini supports this natively via "constrained decoding": the model
 * literally cannot emit JSON that violates this schema.
 */
const RESPONSE_SCHEMA = {
  type: "OBJECT",
  properties: {
    predicted_class: { type: "STRING", enum: CLASSES },
    severity: { type: "NUMBER" },
    confidence: { type: "NUMBER" },
    reasoning: { type: "STRING" },
  },
  required: ["predicted_class", "severity", "confidence", "reasoning"],
};

// ---------------------------------------------------------------------------
// 3. DATASET COLLECTION
// ---------------------------------------------------------------------------

/**
 * Builds the test list. Convention: an image's folder IS its label.
 *   dataset/stringing/foo.webp  -> expected: "stringing"
 *   dataset/clean/bar.jpg       -> expected: "clean"
 * This is the same convention as PyTorch's ImageFolder — it means zero
 * labeling overhead and zero chance of a label file drifting out of sync
 * with your images. Perfect for a hackathon.
 */
function collectExamples() {
  // Load the sidecar if it exists. Keys are paths relative to dataset/,
  // e.g. "stringing/stringing001.webp".
  const sidecar = fs.existsSync(LABELS_FILE)
    ? JSON.parse(fs.readFileSync(LABELS_FILE, "utf8"))
    : {};

  const examples = [];

  for (const cls of CLASSES) {
    const dir = path.join(DATASET_DIR, cls);
    if (!fs.existsSync(dir)) continue; // a missing class folder is not an error

    for (const file of fs.readdirSync(dir)) {
      const ext = path.extname(file).toLowerCase();
      if (!MIME_TYPES[ext]) continue; // skip .gitkeep, README, etc.
      // Merge sidecar metadata (severity, context...) into the example.
      // The "_scale" key is documentation, not an image — skip it.
      const extra = sidecar[`${cls}/${file}`] || {};
      examples.push({ path: path.join(dir, file), expected: cls, ...extra });
    }
  }

  // Sort so runs are reproducible — same order every time matters when you
  // compare "run with prompt A" against "run with prompt B".
  return examples.sort((a, b) => a.path.localeCompare(b.path));
}

// ---------------------------------------------------------------------------
// 4. CALLING THE MODEL
// ---------------------------------------------------------------------------

/**
 * Sends one image to Gemini and returns its parsed prediction.
 *
 * How images travel over the API: the request body is JSON, so binary
 * image bytes can't be pasted in directly. We base64-encode the file
 * (a text-safe representation of raw bytes) and tell the API the MIME
 * type so it knows how to decode them back into pixels.
 */
async function classifyImage(example) {
  const bytes = fs.readFileSync(example.path);
  const base64Data = bytes.toString("base64");
  const mimeType = MIME_TYPES[path.extname(example.path).toLowerCase()];

  let fetchUrl = API_URL;
  let fetchHeaders;
  let requestBody;

  if (USE_OPENROUTER) {
    fetchHeaders = {
      "Content-Type": "application/json",
      Authorization: `Bearer ${process.env.OPENROUTER_API_KEY}`,
    };
    requestBody = {
      model: MODEL,
      temperature: 0,
      response_format: { type: "json_object" },
      messages: [
        {
          role: "system",
          content: `${SYSTEM_PROMPT}\n\nOutput JSON fields: predicted_class (one of ${JSON.stringify(CLASSES)}), severity (number 0.0-1.0), confidence (number 0.0-1.0), reasoning (one short sentence).`,
        },
        {
          role: "user",
          content: [
            { type: "image_url", image_url: { url: `data:${mimeType};base64,${base64Data}` } },
            { type: "text", text: "Classify this 3D-printed part and respond with ONLY a JSON object." },
          ],
        },
      ],
    };
  } else {
    // For Gemini: instructions live in system_instruction (cleaner separation).
    // For Gemma: no system turn supported, so we prepend the same instructions
    // to the user message. Same effective prompt, different plumbing.
    const userText = IS_GEMMA
      ? `${SYSTEM_PROMPT}\n\nClassify this 3D-printed part. Reply with ONLY the JSON object — no markdown fences, no explanation outside the JSON.`
      : "Classify this 3D-printed part.";

    fetchHeaders = {
      "Content-Type": "application/json",
      "x-goog-api-key": process.env.GEMINI_API_KEY,
    };
    requestBody = {
      contents: [
        {
          role: "user",
          parts: [
            // Image FIRST, question second: the model attends to the image
            // while reading what we want from it.
            { inline_data: { mime_type: mimeType, data: base64Data } },
            { text: userText },
          ],
        },
      ],

      generation_config: {
        // temperature 0 = maximum determinism. For evals you want the
        // model's "best guess", not a creative sample. Same input should
        // (mostly) give the same output, so results are comparable across runs.
        temperature: 0,
        // Structured output is Gemini-only; sending these to a gemma model
        // makes the API reject the request outright.
        ...(IS_GEMMA
          ? {}
          : {
              response_mime_type: "application/json",
              response_schema: RESPONSE_SCHEMA,
            }),
      },
    };

    if (IS_GEMMA) {
      // Gemma emits a chain-of-thought part before the JSON answer; without a
      // generous token budget the answer gets cut off mid-generation.
      requestBody.generation_config.maxOutputTokens = 4096;
    }
  }

  // Retry logic: APIs occasionally hiccup. 429 = rate-limited,
  // 5xx = server error — both are worth retrying after waiting.
  // 4xx (like 400 bad request) will fail again identically, so we bail.
  const MAX_ATTEMPTS = 3;
  let lastError;

  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    try {
      const response = await fetch(fetchUrl, {
        method: "POST",
        headers: fetchHeaders,
        body: JSON.stringify(requestBody),
      });

      if (!response.ok) {
        const body = await response.text();
        const error = new Error(`HTTP ${response.status}: ${body.slice(0, 200)}`);
        if (response.status === 429 || response.status >= 500) throw error;
        throw Object.assign(error, { fatal: true }); // don't retry client errors
      }

      const json = await response.json();

      let text = "";
      if (USE_OPENROUTER) {
        const rawContent = json.choices?.[0]?.message?.content;
        if (typeof rawContent === "string") {
          text = rawContent.replace(/<(?:thought|think)>[\s\S]*?<\/(?:thought|think)>/gi, "").trim();
        } else if (Array.isArray(rawContent)) {
          text = rawContent
            .filter((p) => p && p.type !== "thinking" && typeof p.text === "string")
            .map((p) => p.text)
            .join("\n")
            .trim();
        }
      } else {
        // Digging the text out of the response envelope:
        // response -> candidates[] -> content -> parts[] -> text
        // Thinking models (Gemma 4, Gemini 3.x) may emit several parts: earlier
        // ones flagged `thought: true` are internal reasoning, the LAST part is
        // the answer. Joining all non-thought parts handles both shapes.
        const parts = json.candidates?.[0]?.content?.parts || [];
        text = parts
          .filter((p) => p.text && !p.thought)
          .map((p) => p.text)
          .join("\n")
          .trim();
      }
      if (!text) throw Object.assign(new Error("Empty response from model"), { fatal: true });

      // Gemini's schema guarantees valid JSON. Gemma has no such guarantee,
      // so try direct parsing first, then fall back to grabbing the first
      // {...} block buried in prose (handles ```json fences, chatter, etc.).
      let prediction;
      try {
        prediction = JSON.parse(text);
      } catch {
        const match = text.match(/\{[\s\S]*\}/);
        if (!match) throw Object.assign(new Error(`Unparseable response: ${text.slice(0, 120)}`), { fatal: true });
        prediction = JSON.parse(match[0]);
      }

      // Cross-model normalization. Open models don't follow field names as
      // strictly as Gemini's constrained decoding: Gemma said "category"
      // where we asked for "predicted_class". Accept common aliases, then
      // normalize the VALUE (capitalization, synonyms) — otherwise we'd score
      // correct answers as wrong over naming, which measures nothing.
      const rawClass =
        prediction.predicted_class ??
        prediction.category ??
        prediction.classification ??
        prediction.class ??
        prediction.label;
      const normalized = String(rawClass ?? "").toLowerCase().trim();
      if (CLASSES.includes(normalized)) {
        prediction.predicted_class = normalized;
      } else if (normalized.includes("string")) {
        prediction.predicted_class = "stringing";
      } else if (normalized.includes("clean") || normalized.includes("no defect")) {
        prediction.predicted_class = "clean";
      } else {
        prediction.predicted_class = "other_defect"; // clamp unexpected output
      }

      const numSeverity = Number(prediction.severity);
      prediction.severity = Number.isFinite(numSeverity) ? numSeverity : 0;
      const numConfidence = Number(prediction.confidence);
      prediction.confidence = Number.isFinite(numConfidence) ? numConfidence : 0;
      prediction.reasoning = String(prediction.reasoning ?? "");

      return prediction;
    } catch (err) {
      lastError = err;
      if (err.fatal) break; // retrying a 400 is pointless
      await sleep(1000 * attempt); // linear backoff: 1s, 2s, 3s
    }
  }

  throw lastError;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// ---------------------------------------------------------------------------
// 5. METRICS
// ---------------------------------------------------------------------------

/**
 * Computes all metrics from the list of per-image results.
 *
 * The CONFUSION MATRIX is the foundation: rows = expected (truth),
 * columns = predicted (model). Cell [truth][pred] counts how often
 * that combination happened. The diagonal is correct answers.
 *
 *            | pred: stringing | clean | other_defect
 *   expected:|
 *   stringing|       7         |   1   |     0        <- 1 = MISSED defect
 *   clean    |       0         |   5   |     0        <- here = FALSE ALARM
 *   other    |       2         |   0   |     3        <- 2 = confusion
 *
 * From the matrix we derive per-class metrics. Why not just accuracy?
 * Imagine 95 clean images + 5 stringing images: a lazy model that answers
 * "clean" every time scores 95% accuracy while catching ZERO defects.
 * Precision/recall expose that:
 *   - RECALL (for stringing) = of all real stringing images, what fraction
 *     did we catch? In production, low recall = defective prints ship.
 *   - PRECISION (for stringing) = of everything we flagged as stringing,
 *     what fraction really was? Low precision = the printer recalibrates
 *     for no reason (false alarms destroy trust in the system).
 *   - F1 = harmonic mean of the two. Harmonic (not average) because it
 *     punishes lopsided scores: precision 1.0 + recall 0.1 averages to
 *     0.55 but F1 is 0.18, correctly signaling a problem.
 */
function computeMetrics(results) {
  // Build the empty matrix
  const matrix = {};
  for (const expected of CLASSES) {
    matrix[expected] = {};
    for (const predicted of CLASSES) matrix[expected][predicted] = 0;
  }

  let correct = 0;
  let errors = 0;
  for (const r of results) {
    if (r.predicted === "ERROR") {
      errors++;
      continue;
    }
    if (matrix[r.expected] && r.predicted in matrix[r.expected]) {
      matrix[r.expected][r.predicted]++;
    }
    if (r.expected === r.predicted) correct++;
  }

  const accuracy = results.length > 0 ? correct / results.length : 0;

  const perClass = {};
  for (const cls of CLASSES) {
    const tp = matrix[cls][cls]; // true positives: said cls, was cls
    const fp = CLASSES.reduce((sum, other) => sum + (other === cls ? 0 : matrix[other][cls]), 0);
    const fn = CLASSES.reduce((sum, other) => sum + (other === cls ? 0 : matrix[cls][other]), 0);

    const precision = tp + fp > 0 ? tp / (tp + fp) : null;
    const recall = tp + fn > 0 ? tp / (tp + fn) : null;
    const f1 = precision !== null && recall !== null && precision + recall > 0
      ? (2 * precision * recall) / (precision + recall)
      : null;

    perClass[cls] = { tp, fp, fn, precision, recall, f1 };
  }

  return { accuracy, matrix, perClass, total: results.length, correct, errors };
}

// ---------------------------------------------------------------------------
// 6. REPORTING
// ---------------------------------------------------------------------------

function printReport(results, metrics) {
  const pct = (x) => (x === null ? "  n/a" : (x * 100).toFixed(1).padStart(5) + "%");

  console.log(`\n${"=".repeat(64)}`);
  console.log(`EVALUATION REPORT — ${metrics.total} images, model: ${MODEL}`);
  console.log("=".repeat(64));

  // Confusion matrix
  console.log("\nConfusion matrix (rows = truth, columns = prediction):\n");
  const colWidth = 13;
  console.log("".padStart(colWidth) + CLASSES.map((c) => c.padEnd(colWidth)).join(""));
  for (const expected of CLASSES) {
    let row = expected.padEnd(colWidth);
    for (const predicted of CLASSES) {
      const count = metrics.matrix[expected][predicted];
      row += String(expected === predicted ? `[${count}]` : ` ${count} `).padEnd(colWidth);
    }
    console.log(row);
  }

  // Overall accuracy — with an honest caveat about small samples
  console.log(`\nOverall accuracy: ${metrics.correct}/${metrics.total} = ${pct(metrics.accuracy)}`);
  if (metrics.total < 30) {
    console.log("  (⚠ small sample — treat these numbers as a smoke test, not statistics)");
  }

  // Per-class metrics
  console.log("\nPer-class metrics:");
  console.log("class".padEnd(15) + "precision".padEnd(11) + "recall".padEnd(9) + "F1");
  for (const cls of CLASSES) {
    const m = metrics.perClass[cls];
    console.log(
      cls.padEnd(15) +
        pct(m.precision).padEnd(11) +
        pct(m.recall).padEnd(9) +
        pct(m.f1)
    );
  }

  // The failures are where the learning happens: list every misclassification
  const failures = results.filter((r) => r.expected !== r.predicted);
  if (failures.length > 0) {
    console.log(`\nMisclassifications (${failures.length}):`);
    for (const f of failures) {
      console.log(`  ${path.basename(f.path)}`);
      console.log(`    expected: ${f.expected}  |  predicted: ${f.predicted}`);
      console.log(`    model said: "${f.reasoning}"`);
    }
  } else {
    console.log("\nNo misclassifications.");
  }

  printSeverityReport(results);
}

/**
 * Severity agreement: does the model's 0.0-1.0 severity score line up with
 * the human 1-3 tier from labels.json?
 *
 * We bin the model's continuous score into the same 3 tiers the human used:
 *   0.00-0.33 -> tier 1 (very little), 0.34-0.66 -> tier 2 (slight),
 *   0.67-1.00 -> tier 3 (bad)
 *
 * Then report two numbers:
 *   - exact agreement: same tier
 *   - within-one-tier: off by at most one level (a "2 vs 3" disagreement on a
 *     borderline print is far less concerning than a "1 vs 3")
 */
function printSeverityReport(results) {
  const labeled = results.filter((r) => typeof r.humanSeverity === "number");
  if (labeled.length === 0) {
    console.log("\nSeverity: no human severity labels found (add them to dataset/labels.json)");
    return;
  }

  const toTier = (score) => (score < 1 / 3 ? 1 : score < 2 / 3 ? 2 : 3);

  let exact = 0;
  let withinOne = 0;
  console.log(`\nSeverity agreement (${labeled.length} images with human severity labels):`);
  console.log("file".padEnd(22) + "human tier".padEnd(12) + "model tier".padEnd(12) + "model score");

  for (const r of labeled) {
    const modelTier = toTier(r.severity ?? 0);
    const diff = Math.abs(modelTier - r.humanSeverity);
    if (diff === 0) exact++;
    if (diff <= 1) withinOne++;

    const mark = diff === 0 ? "✓" : diff === 1 ? "~" : "✗";
    console.log(
      `${path.basename(r.path)}`.padEnd(22) +
        `${r.humanSeverity}`.padEnd(12) +
        `${modelTier}`.padEnd(12) +
        `${(r.severity ?? 0).toFixed(2)}  ${mark}`
    );
  }

  console.log(
    `\n  exact tier agreement: ${exact}/${labeled.length} | within one tier: ${withinOne}/${labeled.length}`
  );
}

// ---------------------------------------------------------------------------
// 7. MAIN LOOP
// ---------------------------------------------------------------------------

async function main() {
  if (!USE_OPENROUTER && !process.env.GEMINI_API_KEY) {
    console.error("Error: set GEMINI_API_KEY first, e.g.");
    console.error("  GEMINI_API_KEY=xxx node eval.js");
    process.exit(1);
  }
  if (USE_OPENROUTER && !process.env.OPENROUTER_API_KEY) {
    console.error("Error: set OPENROUTER_API_KEY first for OpenRouter models.");
    process.exit(1);
  }

  const examples = collectExamples();
  if (examples.length === 0) {
    console.error(`No images found under ${DATASET_DIR}.`);
    console.error(`Expected folders: ${CLASSES.map((c) => `${DATASET_DIR}/${c}/`).join(", ")}`);
    process.exit(1);
  }

  // Show the test composition — if a class is missing or tiny, your metrics
  // for it will be meaningless. Catch that BEFORE spending API calls.
  const counts = {};
  for (const cls of CLASSES) counts[cls] = examples.filter((e) => e.expected === cls).length;
  console.log(`Model: ${MODEL}`);
  console.log(`Dataset: ${JSON.stringify(counts)}  (${examples.length} total)`);

  // Prepare output path upfront (or resume an interrupted checkpoint file).
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  const resumePath = process.env.RESUME_FILE
    ? path.resolve(process.env.RESUME_FILE)
    : null;
  const outFile = resumePath || path.join(RESULTS_DIR, `run-${timestamp}.json`);
  fs.mkdirSync(path.dirname(outFile), { recursive: true });

  const results =
    resumePath && fs.existsSync(resumePath)
      ? JSON.parse(fs.readFileSync(resumePath, "utf8")).results.filter(
          (r) => r.predicted !== "ERROR"
        )
      : [];
  const completedPaths = new Set(results.map((r) => r.path));
  if (completedPaths.size > 0) {
    console.log(`Resuming from ${resumePath} (${completedPaths.size} already done)`);
  }

  async function saveCheckpoint(data) {
    for (let attempt = 1; attempt <= 4; attempt++) {
      try {
        fs.writeFileSync(outFile, JSON.stringify(data, null, 2));
        return;
      } catch (err) {
        if (attempt === 4) console.error(`Warning: checkpoint write failed (${err.message})`);
        else await sleep(500 * attempt);
      }
    }
  }

  for (const example of examples) {
    if (completedPaths.has(example.path)) continue;

    // Sequential, not parallel: kinder to rate limits, and the progress
    // output stays readable. With ~20 images, speed isn't a concern.
    process.stdout.write(`  classifying ${path.basename(example.path)}... `);
    try {
      const prediction = await classifyImage(example);
      const result = {
        path: example.path,
        expected: example.expected,
        predicted: prediction.predicted_class,
        severity: prediction.severity,
        confidence: prediction.confidence,
        reasoning: prediction.reasoning,
        // Human ground truth from the sidecar (undefined if not labeled).
        // This lets the saved run files be analyzed offline later.
        humanSeverity: example.severity,
        context: example.context,
      };
      results.push(result);
      console.log(result.expected === result.predicted ? "✓" : `✗ (said ${result.predicted})`);
    } catch (err) {
      // One bad image shouldn't kill the run — record it and keep going,
      // but DO record it, otherwise you'd silently inflate accuracy.
      results.push({
        path: example.path,
        expected: example.expected,
        predicted: "ERROR",
        reasoning: err.message,
      });
      console.log(`ERROR: ${err.message.slice(0, 80)}`);
    }
    // Persist progress incrementally so interrupted runs aren't lost.
    const partialMetrics = computeMetrics(results);
    await saveCheckpoint({ model: MODEL, metrics: partialMetrics, results });
    await sleep(300); // small pause to stay under rate limits
  }

  const metrics = computeMetrics(results);
  await saveCheckpoint({ model: MODEL, metrics: metrics, results });

  printReport(results, metrics);
  console.log(`\nFull results saved to: ${outFile}`);
}

main();
