/* Private, dependency-free 3D body landmark.
 *
 * Without confirmed data this gently rotates and morphs through clearly
 * labeled example proportions. With confirmed data it stops the carousel and
 * makes one restrained, non-medical approximation from height, weight, sex,
 * and optional body-fat percentage. It never claims to be a scan.
 */
(function () {
  "use strict";

  const canvas = document.getElementById("bodyModel");
  if (!canvas) return;
  const overlayTitle = document.getElementById("modelOverlayTitle");
  const overlayText = document.getElementById("modelOverlayText");
  const personalized = canvas.dataset.personalized === "true";
  const reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Presentation presets are examples, not health categories or targets.
  const PRESETS = [
    { label: "Example · woman · shorter frame", detail: "shorter height · slimmer arms · narrower shoulders", height: 0.88, width: 0.83, depth: 0.9, shoulder: 0.88, arm: 0.86, leg: 0.9, hip: 0.98 },
    { label: "Example · woman · taller frame", detail: "taller height · longer arms · moderate frame", height: 1.08, width: 0.92, depth: 0.94, shoulder: 0.94, arm: 1.04, leg: 1.1, hip: 1.02 },
    { label: "Example · man · shorter frame", detail: "shorter height · moderate arms · compact frame", height: 0.91, width: 0.98, depth: 1.02, shoulder: 1.03, arm: 0.9, leg: 0.92, hip: 0.94 },
    { label: "Example · man · average frame", detail: "average height · moderate arms · moderate frame", height: 1.0, width: 1.0, depth: 1.0, shoulder: 1.08, arm: 1.0, leg: 1.0, hip: 0.96 },
    { label: "Example · man · taller frame", detail: "taller height · longer arms · broader shoulders", height: 1.14, width: 1.08, depth: 1.07, shoulder: 1.14, arm: 1.1, leg: 1.16, hip: 0.98 },
    { label: "Example · broader frame", detail: "broader torso · larger arm proportions · example only", height: 1.0, width: 1.16, depth: 1.15, shoulder: 1.18, arm: 1.12, leg: 1.0, hip: 1.08 }
  ];

  const PARTS = [
    { key: "head", x: 0, y: 2.75, z: 0, sx: 0.34, sy: 0.39, sz: 0.34, group: "head" },
    { key: "neck", x: 0, y: 2.32, z: 0, sx: 0.17, sy: 0.2, sz: 0.17, group: "torso" },
    { key: "chest", x: 0, y: 1.65, z: 0, sx: 0.67, sy: 0.78, sz: 0.36, group: "torso" },
    { key: "abdomen", x: 0, y: 0.85, z: 0, sx: 0.49, sy: 0.72, sz: 0.3, group: "torso" },
    { key: "pelvis", x: 0, y: 0.15, z: 0, sx: 0.52, sy: 0.38, sz: 0.31, group: "hip" },
    { key: "left-arm", x: -0.82, y: 1.57, z: 0, sx: 0.18, sy: 0.68, sz: 0.18, group: "arm" },
    { key: "right-arm", x: 0.82, y: 1.57, z: 0, sx: 0.18, sy: 0.68, sz: 0.18, group: "arm" },
    { key: "left-forearm", x: -0.96, y: 0.72, z: 0, sx: 0.15, sy: 0.57, sz: 0.15, group: "arm" },
    { key: "right-forearm", x: 0.96, y: 0.72, z: 0, sx: 0.15, sy: 0.57, sz: 0.15, group: "arm" },
    { key: "left-hand", x: -1.0, y: 0.05, z: 0, sx: 0.17, sy: 0.2, sz: 0.16, group: "arm" },
    { key: "right-hand", x: 1.0, y: 0.05, z: 0, sx: 0.17, sy: 0.2, sz: 0.16, group: "arm" },
    { key: "left-thigh", x: -0.29, y: -0.74, z: 0, sx: 0.27, sy: 0.77, sz: 0.27, group: "leg" },
    { key: "right-thigh", x: 0.29, y: -0.74, z: 0, sx: 0.27, sy: 0.77, sz: 0.27, group: "leg" },
    { key: "left-shin", x: -0.29, y: -1.78, z: 0, sx: 0.2, sy: 0.72, sz: 0.2, group: "leg" },
    { key: "right-shin", x: 0.29, y: -1.78, z: 0, sx: 0.2, sy: 0.72, sz: 0.2, group: "leg" },
    { key: "left-foot", x: -0.29, y: -2.62, z: -0.1, sx: 0.24, sy: 0.38, sz: 0.45, group: "leg" },
    { key: "right-foot", x: 0.29, y: -2.62, z: -0.1, sx: 0.24, sy: 0.38, sz: 0.45, group: "leg" }
  ];

  const gl = canvas.getContext("webgl", { antialias: true, alpha: true });
  if (!gl) { drawFallback(canvas); return; }
  const vertexSource = `
    attribute vec3 aPosition; attribute vec3 aNormal;
    uniform mat4 uModel; uniform mat4 uView; uniform mat4 uProjection;
    varying vec3 vNormal; varying vec3 vPosition;
    void main() { vec4 world = uModel * vec4(aPosition, 1.0); vPosition = world.xyz; vNormal = mat3(uModel) * aNormal; gl_Position = uProjection * uView * world; }
  `;
  const fragmentSource = `
    precision mediump float; varying vec3 vNormal; varying vec3 vPosition;
    uniform vec3 uColor; uniform vec3 uLight;
    void main() { vec3 normal = normalize(vNormal); float light = 0.42 + 0.58 * max(dot(normal, normalize(uLight - vPosition)), 0.0); float edge = 1.0 - smoothstep(0.46, 0.9, length(vPosition.xy) * 0.12); gl_FragColor = vec4(uColor * light * (0.93 + 0.07 * edge), 1.0); }
  `;
  const program = makeProgram(gl, vertexSource, fragmentSource);
  if (!program) { drawFallback(canvas); return; }
  gl.useProgram(program); gl.enable(gl.DEPTH_TEST); gl.enable(gl.CULL_FACE); gl.clearColor(0, 0, 0, 0);
  const locations = {
    position: gl.getAttribLocation(program, "aPosition"), normal: gl.getAttribLocation(program, "aNormal"),
    model: gl.getUniformLocation(program, "uModel"), view: gl.getUniformLocation(program, "uView"),
    projection: gl.getUniformLocation(program, "uProjection"), color: gl.getUniformLocation(program, "uColor"),
    light: gl.getUniformLocation(program, "uLight")
  };
  const mesh = sphereMesh(gl, 16, 10);
  const personal = personalizedPreset();
  let current = personalized ? personal : PRESETS[0];
  let target = current, presetIndex = 0, transitionStart = 0, nextSwitch = 0;
  let rotation = 0, dragging = false, previousX = 0, previousTime = 0;

  function render(now) {
    resizeCanvas(); gl.viewport(0, 0, canvas.width, canvas.height); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    const projection = perspective(Math.PI / 4, canvas.width / canvas.height, 0.1, 100);
    const view = lookAt([0, 0.05, 8.4], [0, 0, 0], [0, 1, 0]);
    gl.uniformMatrix4fv(locations.view, false, view); gl.uniformMatrix4fv(locations.projection, false, projection); gl.uniform3f(locations.light, -3.5, 5.5, 6.5);
    gl.bindBuffer(gl.ARRAY_BUFFER, mesh.buffer); gl.enableVertexAttribArray(locations.position); gl.vertexAttribPointer(locations.position, 3, gl.FLOAT, false, 24, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, mesh.normalBuffer); gl.enableVertexAttribArray(locations.normal); gl.vertexAttribPointer(locations.normal, 3, gl.FLOAT, false, 24, 0);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, mesh.indexBuffer);
    const profile = transitionProfile(now);
    PARTS.forEach(function (part) { const d = partDimensions(part, profile); const model = multiply(rotateY(rotation), translate(d.x, d.y, part.z)); const scaled = multiply(model, scale(d.sx, d.sy, d.sz)); gl.uniformMatrix4fv(locations.model, false, scaled); gl.uniform3f(locations.color, 0.32, 0.50, 0.40); gl.drawElements(gl.TRIANGLES, mesh.count, gl.UNSIGNED_SHORT, 0); });
  }

  function animationFrame(now) {
    const delta = previousTime ? Math.min(now - previousTime, 50) : 16; previousTime = now;
    if (!reducedMotion) { rotation += delta * 0.00028; if (!personalized && !transitionStart && now >= nextSwitch) beginTransition(now); }
    render(now);
    if (!reducedMotion || transitionStart) window.requestAnimationFrame(animationFrame);
  }
  function transitionProfile(now) {
    if (!transitionStart) return current;
    const progress = clamp((now - transitionStart) / 1400, 0, 1), eased = progress * progress * (3 - 2 * progress);
    if (progress >= 1) { current = target; transitionStart = 0; nextSwitch = now + 2200; return current; }
    return blend(current, target, eased);
  }
  function beginTransition(now) { presetIndex = (presetIndex + 1) % PRESETS.length; target = PRESETS[presetIndex]; transitionStart = now; setExampleOverlay(target); }
  function setExampleOverlay(profile) { if (overlayTitle) overlayTitle.textContent = "Add your data to see your metrics"; if (overlayText) overlayText.textContent = profile.label + " · " + profile.detail + " · example only."; canvas.setAttribute("aria-label", "Rotating example 3D body model: " + profile.label + ". Use arrow keys or drag to rotate."); }
  function setPersonalOverlay() { if (overlayTitle) overlayTitle.textContent = "Your confirmed approximation"; if (overlayText) overlayText.textContent = "Uses confirmed measurements as a visual guide — not a scan."; canvas.setAttribute("aria-label", "Rotating 3D approximation based on confirmed measurements. Use arrow keys or drag to rotate."); }
  function personalizedPreset() {
    const height = number(canvas.dataset.height, 175), weight = number(canvas.dataset.weight, 75), bodyFat = number(canvas.dataset.bodyFat, 18), bmi = weight / Math.pow(height / 100, 2), width = clamp(0.86 + (bmi - 21) * 0.018 + (bodyFat - 18) * 0.004, 0.78, 1.24), isWoman = canvas.dataset.sex === "female";
    return { label: "Your confirmed approximation", detail: "confirmed height, weight, and optional body-fat data", height: clamp(height / 175, 0.82, 1.18), width: width, depth: width, shoulder: isWoman ? 0.96 : 1.08, arm: clamp(width, 0.84, 1.16), leg: clamp(height / 175, 0.86, 1.16), hip: isWoman ? 1.04 : 0.96 };
  }
  function partDimensions(part, profile) { const xFrame = part.group === "arm" ? profile.shoulder : profile.width, xSize = part.group === "arm" ? profile.arm : profile.width, ySize = part.group === "arm" ? profile.arm : part.group === "leg" ? profile.leg : profile.height; return { x: part.x * xFrame, y: part.y * profile.height, sx: part.sx * xSize * (part.group === "hip" ? profile.hip : 1), sy: part.sy * ySize, sz: part.sz * profile.depth }; }
  function blend(a, b, amount) { const result = {}; Object.keys(a).forEach(function (key) { result[key] = typeof a[key] === "number" ? a[key] + (b[key] - a[key]) * amount : b[key]; }); return result; }
  function resizeCanvas() { const ratio = Math.min(window.devicePixelRatio || 1, 2), width = Math.max(1, Math.floor(canvas.clientWidth * ratio)), height = Math.max(1, Math.floor(canvas.clientHeight * ratio)); if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; } }
  canvas.addEventListener("keydown", function (event) { if (event.key === "ArrowLeft" || event.key === "ArrowRight") { event.preventDefault(); rotation += event.key === "ArrowLeft" ? -0.12 : 0.12; render(performance.now()); } });
  canvas.addEventListener("pointerdown", function (event) { dragging = true; previousX = event.clientX; canvas.setPointerCapture(event.pointerId); });
  canvas.addEventListener("pointermove", function (event) { if (!dragging) return; rotation += (event.clientX - previousX) * 0.01; previousX = event.clientX; render(performance.now()); });
  canvas.addEventListener("pointerup", function () { dragging = false; }); canvas.addEventListener("pointercancel", function () { dragging = false; });
  window.addEventListener("resize", function () { render(performance.now()); }, { passive: true });
  if (personalized) setPersonalOverlay(); else setExampleOverlay(PRESETS[0]);
  nextSwitch = performance.now() + 3200; render(performance.now()); if (!reducedMotion) window.requestAnimationFrame(animationFrame);

  function makeProgram(context, vertex, fragment) { const vs = compile(context, context.VERTEX_SHADER, vertex), fs = compile(context, context.FRAGMENT_SHADER, fragment); if (!vs || !fs) return null; const result = context.createProgram(); context.attachShader(result, vs); context.attachShader(result, fs); context.linkProgram(result); return context.getProgramParameter(result, context.LINK_STATUS) ? result : null; }
  function compile(context, type, source) { const shader = context.createShader(type); context.shaderSource(shader, source); context.compileShader(shader); return context.getShaderParameter(shader, context.COMPILE_STATUS) ? shader : null; }
  function sphereMesh(context, bands, rings) { const vertices = [], normals = [], indices = []; for (let y = 0; y <= rings; y += 1) { const v = y / rings, phi = v * Math.PI; for (let x = 0; x <= bands; x += 1) { const u = x / bands, theta = u * Math.PI * 2, px = Math.sin(phi) * Math.cos(theta), py = Math.cos(phi), pz = Math.sin(phi) * Math.sin(theta); vertices.push(px, py, pz); normals.push(px, py, pz); } } for (let y = 0; y < rings; y += 1) for (let x = 0; x < bands; x += 1) { const a = y * (bands + 1) + x, b = a + bands + 1; indices.push(a, b, a + 1, b, b + 1, a + 1); } const buffer = context.createBuffer(); context.bindBuffer(context.ARRAY_BUFFER, buffer); context.bufferData(context.ARRAY_BUFFER, new Float32Array(vertices), context.STATIC_DRAW); const normalBuffer = context.createBuffer(); context.bindBuffer(context.ARRAY_BUFFER, normalBuffer); context.bufferData(context.ARRAY_BUFFER, new Float32Array(normals), context.STATIC_DRAW); const indexBuffer = context.createBuffer(); context.bindBuffer(context.ELEMENT_ARRAY_BUFFER, indexBuffer); context.bufferData(context.ELEMENT_ARRAY_BUFFER, new Uint16Array(indices), context.STATIC_DRAW); return { buffer: buffer, normalBuffer: normalBuffer, indexBuffer: indexBuffer, count: indices.length }; }
  function identity() { return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]; }
  function multiply(a, b) { const out = Array(16).fill(0); for (let row = 0; row < 4; row += 1) for (let col = 0; col < 4; col += 1) for (let k = 0; k < 4; k += 1) out[col * 4 + row] += a[k * 4 + row] * b[col * 4 + k]; return out; }
  function translate(x, y, z) { const m = identity(); m[12] = x; m[13] = y; m[14] = z; return m; }
  function scale(x, y, z) { const m = identity(); m[0] = x; m[5] = y; m[10] = z; return m; }
  function rotateY(a) { const m = identity(); m[0] = Math.cos(a); m[2] = -Math.sin(a); m[8] = Math.sin(a); m[10] = Math.cos(a); return m; }
  function perspective(fov, aspect, near, far) { const f = 1 / Math.tan(fov / 2), nf = 1 / (near - far); return [f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * nf, -1, 0, 0, 2 * far * near * nf, 0]; }
  function lookAt(eye, center, up) { const z = normalize([eye[0] - center[0], eye[1] - center[1], eye[2] - center[2]]), x = normalize(cross(up, z)), y = cross(z, x); return [x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0, -dot(x, eye), -dot(y, eye), -dot(z, eye), 1]; }
  function normalize(v) { const n = Math.hypot.apply(Math, v) || 1; return v.map(function (x) { return x / n; }); }
  function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
  function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
  function clamp(value, low, high) { return Math.max(low, Math.min(high, value)); }
  function number(value, fallback) { const result = Number.parseFloat(value); return Number.isFinite(result) ? result : fallback; }
  function drawFallback(target) { const context = target.getContext("2d"); if (!context) return; context.clearRect(0, 0, target.width, target.height); context.fillStyle = "#3c6e55"; context.beginPath(); context.ellipse(320, 105, 45, 52, 0, 0, Math.PI * 2); context.fill(); context.fillRect(278, 160, 84, 245); context.fillRect(205, 175, 54, 220); context.fillRect(381, 175, 54, 220); context.fillRect(270, 390, 45, 260); context.fillRect(325, 390, 45, 260); context.fillRect(252, 635, 65, 34); context.fillRect(323, 635, 65, 34); }
}());
