/**
 * Generate PRNG test vectors from the authoritative JavaScript SplitMix32
 * implementation (copied verbatim from sender.html).
 *
 * Output: tests/data/prng_vectors.json
 */

const fs = require("fs");
const path = require("path");

// ---- Copied verbatim from sender.html lines 175-186 ----
function createPRNG(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x9e3779b9) >>> 0;
    let t = a ^ (a >>> 16);
    t = Math.imul(t, 0x21f0aaad) >>> 0;
    t ^= t >>> 15;
    t = Math.imul(t, 0x735a2d97) >>> 0;
    t ^= t >>> 15;
    return t >>> 0;
  };
}

// ---- Based on sender.html lines 188-201, with degree capped to K ----
// NOTE: The original sender.html chooseIndices has an infinite-loop bug when
// degree > K (e.g., K=1 with degree=2: the set can never reach size 2 since
// next() % 1 is always 0). We cap degree to K here to avoid hanging.
// This bug also exists in receiver_fountain.py -- will be fixed in a later phase.
function chooseIndices(seed, K) {
  const next = createPRNG(seed);
  const degreeRand = next() / 0x100000000;
  let degree = 1;
  if (degreeRand < 0.1) degree = 1;
  else if (degreeRand < 0.6) degree = 2;
  else degree = Math.floor((next() / 0x100000000) * Math.min(K, 20)) + 1;

  // Cap degree to K to prevent infinite loop when degree > K
  degree = Math.min(degree, K);

  const indices = new Set();
  while (indices.size < degree) {
    indices.add(next() % K);
  }
  return Array.from(indices);
}

// ---- Vector generation ----

// 1. PRNG output vectors: seeds 0..1023 plus edge cases
const prngOutputs = [];
const seeds = [];
for (let i = 0; i < 1024; i++) {
  seeds.push(i);
}
// Edge case seeds
seeds.push(0xffffffff, 0xdeadbeef, 0x80000000, 0x7fffffff);

for (const seed of seeds) {
  const next = createPRNG(seed);
  const outputs = [];
  for (let j = 0; j < 10; j++) {
    outputs.push(next());
  }
  prngOutputs.push({ seed, outputs });
}

// 2. chooseIndices vectors: seeds 1..100 x K values [1, 2, 5, 10, 20, 50]
const chooseIndicesVectors = [];
const kValues = [1, 2, 5, 10, 20, 50];

for (let seed = 1; seed <= 100; seed++) {
  for (const K of kValues) {
    const indices = chooseIndices(seed, K);
    chooseIndicesVectors.push({
      seed,
      K,
      degree: indices.length,
      indices: indices.sort((a, b) => a - b),
    });
  }
}

// 3. Write JSON
const outputDir = path.join(__dirname, "..", "tests", "data");
fs.mkdirSync(outputDir, { recursive: true });

const data = {
  prng_outputs: prngOutputs,
  choose_indices: chooseIndicesVectors,
};

const outPath = path.join(outputDir, "prng_vectors.json");
fs.writeFileSync(outPath, JSON.stringify(data, null, 2));

console.log(`Written ${prngOutputs.length} PRNG output entries`);
console.log(`Written ${chooseIndicesVectors.length} chooseIndices entries`);
console.log(`Output: ${outPath}`);
