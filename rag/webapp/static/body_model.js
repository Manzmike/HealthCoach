/*
 * Local WebGL anthropometric body model.
 *
 * The mesh asset is a compact browser reduction of the MIT-licensed
 * 3D-Human-Body-Shape research model. It is intentionally an illustrative
 * anthropometric visualization, not a medical scan or a DEXA reconstruction.
 * See THIRD_PARTY_NOTICES.md for attribution.
 */
(function () {
  "use strict";

  const canvas = document.getElementById("bodyModel");
  if (!canvas) return;
  const overlayTitle = document.getElementById("modelOverlayTitle");
  const overlayText = document.getElementById("modelOverlayText");
  const personalized = canvas.dataset.personalized === "true";
  const reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const MATRIX_DIMENSIONS = {
    sex: [
      { label: "woman", value: "female", hip: 1.08, chest: 1.02 },
      { label: "man", value: "male", hip: 0.98, chest: 1.06 }
    ],
    height: [{ label: "smallest height", cm: 150 }, { label: "middle height", cm: 175 }, { label: "tallest height", cm: 200 }],
    waist: [{ label: "smallest waist", cm: 60 }, { label: "middle waist", cm: 80 }, { label: "largest waist", cm: 110 }],
    weight: [{ label: "lightest example", kg: 55 }, { label: "middle example", kg: 80 }, { label: "heaviest example", kg: 110 }],
    armScale: [{ label: "smallest arms", value: 0.82 }, { label: "middle arms", value: 1.0 }, { label: "largest arms", value: 1.18 }],
    legScale: [{ label: "smallest legs", value: 0.84 }, { label: "middle legs", value: 1.0 }, { label: "largest legs", value: 1.16 }]
  };
  const PRESETS = buildMatrix();
  const assetURL = new URL("body_model_mesh.bin", document.currentScript && document.currentScript.src || "body_model_mesh.bin").toString();

  const gl = canvas.getContext("webgl", { antialias: true, alpha: true });
  if (!gl) return;
  const program = makeProgram(gl, `
    attribute vec3 aPosition; attribute vec3 aNormal;
    uniform mat4 uModel; uniform mat4 uView; uniform mat4 uProjection;
    varying vec3 vNormal; varying vec3 vPosition;
    void main() { vec4 world = uModel * vec4(aPosition, 1.0); vPosition = world.xyz; vNormal = mat3(uModel) * aNormal; gl_Position = uProjection * uView * world; }
  `, `
    precision mediump float; varying vec3 vNormal; varying vec3 vPosition;
    uniform vec3 uColor; uniform vec3 uLight;
    void main() { vec3 normal = normalize(vNormal); float diffuse = 0.40 + 0.60 * max(dot(normal, normalize(uLight - vPosition)), 0.0); float rim = 1.0 - smoothstep(0.15, 1.0, length(vPosition.xz) * 0.32); gl_FragColor = vec4(uColor * diffuse * (0.94 + rim * 0.06), 1.0); }
  `);
  if (!program) return;
  gl.useProgram(program); gl.enable(gl.DEPTH_TEST); gl.enable(gl.CULL_FACE); gl.clearColor(0, 0, 0, 0);
  const locations = {
    position: gl.getAttribLocation(program, "aPosition"), normal: gl.getAttribLocation(program, "aNormal"),
    model: gl.getUniformLocation(program, "uModel"), view: gl.getUniformLocation(program, "uView"),
    projection: gl.getUniformLocation(program, "uProjection"), color: gl.getUniformLocation(program, "uColor"),
    light: gl.getUniformLocation(program, "uLight")
  };

  let modelAsset = null, mesh = null, currentProfile = null, currentVertices = null;
  let matrixOrder = personalized ? [] : shuffledOrder(PRESETS.length), orderCursor = 0;
  let targetProfile = null, targetVertices = null, transitionStart = 0, nextSwitch = 0;
  let rotation = 0, dragging = false, previousX = 0, previousTime = 0, uploadedVertices = null;

  fetch(assetURL, { cache: "force-cache" })
    .then(function (response) { if (!response.ok) throw new Error("Body model asset returned " + response.status); return response.arrayBuffer(); })
    .then(function (buffer) {
      modelAsset = decodeAsset(buffer); mesh = createMesh(modelAsset.faces);
      currentProfile = personalized ? personalizedProfile() : PRESETS[matrixOrder[orderCursor]];
      currentVertices = verticesFor(currentProfile);
      if (personalized) setPersonalOverlay(); else setExampleOverlay(currentProfile);
      nextSwitch = performance.now() + 1800; render(performance.now());
      if (!reducedMotion) window.requestAnimationFrame(animationFrame);
    })
    .catch(function (error) {
      canvas.setAttribute("aria-label", "3D body model unavailable; complete setup to view your visual guide.");
      if (overlayTitle) overlayTitle.textContent = "Body model preview unavailable";
      if (overlayText) overlayText.textContent = "The rest of HealthCoach is still available. Reload to try the local model again.";
      if (window.console && console.warn) console.warn("HealthCoach body model:", error);
    });

  function decodeAsset(buffer) {
    const header = new Uint32Array(buffer, 0, 6);
    if (header[1] !== 1 || header[2] !== 12500 || header[3] !== 25000 || header[4] !== 19 || header[5] !== 2) throw new Error("Unsupported body model asset");
    let offset = 24; const models = [];
    for (let sex = 0; sex < 2; sex += 1) {
      const means = new Float32Array(buffer, offset, 19); offset += 19 * 4;
      const stds = new Float32Array(buffer, offset, 19); offset += 19 * 4;
      const base = new Float32Array(buffer, offset, 12500 * 3); offset += 12500 * 3 * 4;
      const measurementBases = new Float32Array(buffer, offset, 19 * 12500 * 3); offset += 19 * 12500 * 3 * 4;
      models.push({ means: means, stds: stds, base: base, measurementBases: measurementBases });
    }
    const rawFaces = new Uint32Array(buffer, offset, 25000 * 3);
    return { models: models, faces: new Uint16Array(rawFaces) };
  }

  function createMesh(faces) {
    const result = { positionBuffer: gl.createBuffer(), normalBuffer: gl.createBuffer(), indexBuffer: gl.createBuffer(), faces: faces, count: faces.length };
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, result.indexBuffer); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, faces, gl.STATIC_DRAW); return result;
  }

  function render(now) {
    if (!mesh || !currentVertices) return;
    resizeCanvas(); gl.viewport(0, 0, canvas.width, canvas.height); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    const projection = perspective(Math.PI / 4.3, canvas.width / canvas.height, 0.1, 100), view = lookAt([0, 0.02, 4.5], [0, 0, 0], [0, 1, 0]);
    gl.uniformMatrix4fv(locations.view, false, view); gl.uniformMatrix4fv(locations.projection, false, projection); gl.uniform3f(locations.light, -2.5, 4.0, 5.5);
    const vertices = transitionVertices(now); if (vertices !== uploadedVertices) uploadVertices(vertices);
    // The reference mesh stores body height on its source z axis. Rotate it
    // upright before applying the user's horizontal viewing rotation so the
    // person faces the viewer instead of presenting a sideways/top-down view.
    const upright = multiply(rotateX(-Math.PI / 2), scale(5.65, 5.65, 5.65));
    gl.uniformMatrix4fv(locations.model, false, multiply(rotateY(rotation), upright)); gl.uniform3f(locations.color, 0.34, 0.49, 0.42);
    gl.bindBuffer(gl.ARRAY_BUFFER, mesh.positionBuffer); gl.enableVertexAttribArray(locations.position); gl.vertexAttribPointer(locations.position, 3, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, mesh.normalBuffer); gl.enableVertexAttribArray(locations.normal); gl.vertexAttribPointer(locations.normal, 3, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, mesh.indexBuffer); gl.drawElements(gl.TRIANGLES, mesh.count, gl.UNSIGNED_SHORT, 0);
  }

  function uploadVertices(vertices) {
    const normals = new Float32Array(vertices.length);
    for (let face = 0; face < mesh.faces.length; face += 3) {
      const a = mesh.faces[face] * 3, b = mesh.faces[face + 1] * 3, c = mesh.faces[face + 2] * 3;
      const abx = vertices[b] - vertices[a], aby = vertices[b + 1] - vertices[a + 1], abz = vertices[b + 2] - vertices[a + 2];
      const acx = vertices[c] - vertices[a], acy = vertices[c + 1] - vertices[a + 1], acz = vertices[c + 2] - vertices[a + 2];
      const nx = aby * acz - abz * acy, ny = abz * acx - abx * acz, nz = abx * acy - aby * acx;
      normals[a] += nx; normals[a + 1] += ny; normals[a + 2] += nz; normals[b] += nx; normals[b + 1] += ny; normals[b + 2] += nz; normals[c] += nx; normals[c + 1] += ny; normals[c + 2] += nz;
    }
    for (let index = 0; index < normals.length; index += 3) { const length = Math.hypot(normals[index], normals[index + 1], normals[index + 2]) || 1; normals[index] /= length; normals[index + 1] /= length; normals[index + 2] /= length; }
    gl.bindBuffer(gl.ARRAY_BUFFER, mesh.positionBuffer); gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.DYNAMIC_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER, mesh.normalBuffer); gl.bufferData(gl.ARRAY_BUFFER, normals, gl.DYNAMIC_DRAW); uploadedVertices = vertices;
  }

  function verticesFor(profile) {
    const model = modelAsset.models[profile.sex === "male" ? 1 : 0], z = measurementsFor(profile, model), vertices = new Float32Array(model.base), measurementBases = model.measurementBases;
    for (let measure = 0; measure < 19; measure += 1) { const amount = z[measure], basisOffset = measure * 12500 * 3; for (let vertex = 0; vertex < vertices.length; vertex += 1) vertices[vertex] += measurementBases[basisOffset + vertex] * amount; }
    return vertices;
  }

  function measurementsFor(profile, model) {
    const raw = new Float32Array(model.means), heightRatio = clamp(profile.heightCm / 175, 0.82, 1.18), waistRatio = clamp(profile.waistCm / 80, 0.72, 1.42), armRatio = clamp(profile.armScale || 1, 0.78, 1.24), legRatio = clamp((profile.legScale || 1) * heightRatio, 0.75, 1.35);
    raw[0] = Math.pow(Math.max(profile.weightKg, 25), 1 / 3) * 1000; raw[1] = profile.heightCm * 10; raw[2] *= 0.88 + waistRatio * 0.12; raw[3] *= 0.82 + waistRatio * 0.18 * (profile.chest || 1);
    [4, 10, 11].forEach(function (index) { raw[index] *= waistRatio * (index === 11 ? (profile.hip || 1) : 1); });
    [6, 13, 14, 15].forEach(function (index) { raw[index] *= armRatio; }); [7, 16, 17, 18].forEach(function (index) { raw[index] *= legRatio; });
    raw[8] *= profile.sex === "male" ? 1.04 : 0.98; raw[9] *= heightRatio; raw[12] *= heightRatio;
    const normalized = new Float32Array(19); for (let index = 0; index < 19; index += 1) normalized[index] = clamp((raw[index] - model.means[index]) / (model.stds[index] || 1), -2.75, 2.75); return normalized;
  }

  function transitionVertices(now) {
    if (!transitionStart || !targetVertices) return currentVertices;
    const progress = clamp((now - transitionStart) / 1100, 0, 1), eased = progress * progress * (3 - 2 * progress);
    if (progress >= 1) { currentProfile = targetProfile; currentVertices = targetVertices; targetProfile = null; targetVertices = null; transitionStart = 0; nextSwitch = now + 700; return currentVertices; }
    const blended = new Float32Array(currentVertices.length); for (let index = 0; index < blended.length; index += 1) blended[index] = currentVertices[index] + (targetVertices[index] - currentVertices[index]) * eased; return blended;
  }

  function animationFrame(now) {
    const delta = previousTime ? Math.min(now - previousTime, 50) : 16; previousTime = now;
    if (!reducedMotion) { rotation += delta * 0.00028; if (!personalized && !transitionStart && now >= nextSwitch) beginTransition(now); }
    render(now); if (!reducedMotion || transitionStart) window.requestAnimationFrame(animationFrame);
  }
  function beginTransition(now) { orderCursor += 1; if (orderCursor >= matrixOrder.length) { matrixOrder = shuffledOrder(PRESETS.length); orderCursor = 0; } targetProfile = PRESETS[matrixOrder[orderCursor]]; targetVertices = verticesFor(targetProfile); transitionStart = now; setExampleOverlay(targetProfile); }
  function setExampleOverlay(profile) { if (overlayTitle) overlayTitle.textContent = "Add your data to see your metrics"; if (overlayText) overlayText.textContent = profile.label + " · " + profile.detail + " · randomized pass item " + (orderCursor + 1) + "/" + PRESETS.length + " · example only."; canvas.setAttribute("aria-label", "Rotating randomized reference-derived 3D body model: " + profile.label + ". Use arrow keys or drag to rotate."); }
  function setPersonalOverlay() { if (overlayTitle) overlayTitle.textContent = "Your confirmed approximation"; if (overlayText) overlayText.textContent = "Uses confirmed height, weight, and sex with the reference mesh as a visual guide — not a scan."; canvas.setAttribute("aria-label", "Rotating reference-derived 3D approximation based on confirmed measurements. Use arrow keys or drag to rotate."); }
  function personalizedProfile() {
    const heightCm = number(canvas.dataset.height, 175), weightKg = number(canvas.dataset.weight, 75), bodyFat = number(canvas.dataset.bodyFat, 18), bmi = weightKg / Math.pow(heightCm / 100, 2), sex = canvas.dataset.sex === "male" ? "male" : "female";
    return { label: "Your confirmed approximation", detail: "confirmed height, weight, and optional body-fat data", sex: sex, heightCm: heightCm, weightKg: weightKg, waistCm: clamp(72 + (bmi - 21) * 3.1 + bodyFat * 0.25, 60, 125), armScale: clamp(0.92 + (bmi - 21) * 0.012, 0.78, 1.2), legScale: clamp(heightCm / 175, 0.84, 1.18), hip: sex === "male" ? 0.98 : 1.08, chest: sex === "male" ? 1.06 : 1.02 };
  }
  function buildMatrix() {
    const profiles = [];
    MATRIX_DIMENSIONS.sex.forEach(function (sex) { MATRIX_DIMENSIONS.height.forEach(function (height) { MATRIX_DIMENSIONS.waist.forEach(function (waist) { MATRIX_DIMENSIONS.weight.forEach(function (weight) { MATRIX_DIMENSIONS.armScale.forEach(function (armScale) { MATRIX_DIMENSIONS.legScale.forEach(function (legScale) {
      const position = profiles.length + 1;
      profiles.push({ label: "Example · " + sex.label, detail: height.label + " (" + height.cm + " cm) · " + waist.label + " (" + waist.cm + " cm) · " + weight.label + " (" + weight.kg + " kg) · " + armScale.label + " · " + legScale.label + " · matrix " + position + "/486", sex: sex.value, heightCm: height.cm, waistCm: waist.cm, weightKg: weight.kg, armScale: armScale.value, legScale: legScale.value, hip: sex.hip, chest: sex.chest });
    }); }); }); }); }); });
    return profiles;
  }

  canvas.addEventListener("keydown", function (event) { if (event.key === "ArrowLeft" || event.key === "ArrowRight") { event.preventDefault(); rotation += event.key === "ArrowLeft" ? -0.12 : 0.12; render(performance.now()); } });
  canvas.addEventListener("pointerdown", function (event) { dragging = true; previousX = event.clientX; canvas.setPointerCapture(event.pointerId); });
  canvas.addEventListener("pointermove", function (event) { if (!dragging) return; rotation += (event.clientX - previousX) * 0.01; previousX = event.clientX; render(performance.now()); });
  canvas.addEventListener("pointerup", function () { dragging = false; }); canvas.addEventListener("pointercancel", function () { dragging = false; });
  window.addEventListener("resize", function () { render(performance.now()); }, { passive: true });

  function resizeCanvas() { const ratio = Math.min(window.devicePixelRatio || 1, 2), width = Math.max(1, Math.floor(canvas.clientWidth * ratio)), height = Math.max(1, Math.floor(canvas.clientHeight * ratio)); if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; } }
  function makeProgram(context, vertexSource, fragmentSource) { const vertex = compile(context, context.VERTEX_SHADER, vertexSource), fragment = compile(context, context.FRAGMENT_SHADER, fragmentSource); if (!vertex || !fragment) return null; const result = context.createProgram(); context.attachShader(result, vertex); context.attachShader(result, fragment); context.linkProgram(result); return context.getProgramParameter(result, context.LINK_STATUS) ? result : null; }
  function compile(context, type, source) { const shader = context.createShader(type); context.shaderSource(shader, source); context.compileShader(shader); return context.getShaderParameter(shader, context.COMPILE_STATUS) ? shader : null; }
  function identity() { return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]; }
  function multiply(a, b) { const out = Array(16).fill(0); for (let row = 0; row < 4; row += 1) for (let col = 0; col < 4; col += 1) for (let k = 0; k < 4; k += 1) out[col * 4 + row] += a[k * 4 + row] * b[col * 4 + k]; return out; }
  function scale(x, y, z) { const matrix = identity(); matrix[0] = x; matrix[5] = y; matrix[10] = z; return matrix; }
  function rotateX(angle) { const matrix = identity(); matrix[5] = Math.cos(angle); matrix[6] = Math.sin(angle); matrix[9] = -Math.sin(angle); matrix[10] = Math.cos(angle); return matrix; }
  function rotateY(angle) { const matrix = identity(); matrix[0] = Math.cos(angle); matrix[2] = -Math.sin(angle); matrix[8] = Math.sin(angle); matrix[10] = Math.cos(angle); return matrix; }
  function perspective(fov, aspect, near, far) { const f = 1 / Math.tan(fov / 2), nf = 1 / (near - far); return [f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * nf, -1, 0, 0, 2 * far * near * nf, 0]; }
  function lookAt(eye, center, up) { const z = normalize([eye[0] - center[0], eye[1] - center[1], eye[2] - center[2]]), x = normalize(cross(up, z)), y = cross(z, x); return [x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0, -dot(x, eye), -dot(y, eye), -dot(z, eye), 1]; }
  function normalize(value) { const length = Math.hypot.apply(Math, value) || 1; return value.map(function (item) { return item / length; }); }
  function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
  function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
  function clamp(value, low, high) { return Math.max(low, Math.min(high, value)); }
  function number(value, fallback) { const parsed = Number.parseFloat(value); return Number.isFinite(parsed) ? parsed : fallback; }
  function shuffledOrder(length) { const order = Array.from({ length: length }, function (_, index) { return index; }); for (let index = order.length - 1; index > 0; index -= 1) { const swap = randomInt(index + 1), value = order[index]; order[index] = order[swap]; order[swap] = value; } return order; }
  function randomInt(max) { if (window.crypto && window.crypto.getRandomValues) { const values = new Uint32Array(1); window.crypto.getRandomValues(values); return values[0] % max; } return Math.floor(Math.random() * max); }
}());
