/* A private, dependency-free generic 3D body landmark.
 *
 * This is intentionally a visual orientation model, not a body scanner. It
 * does not read profile, lab, or DEXA data. Those values can be layered on
 * only after the user confirms them in a future data view.
 */
(function () {
  "use strict";

  const canvas = document.getElementById("bodyModel");
  if (!canvas) return;

  const gl = canvas.getContext("webgl", { antialias: true, alpha: true });
  if (!gl) {
    drawFallback(canvas);
    return;
  }

  const vertexSource = `
    attribute vec3 aPosition;
    attribute vec3 aNormal;
    uniform mat4 uModel;
    uniform mat4 uView;
    uniform mat4 uProjection;
    varying vec3 vNormal;
    varying vec3 vPosition;
    void main() {
      vec4 world = uModel * vec4(aPosition, 1.0);
      vPosition = world.xyz;
      vNormal = mat3(uModel) * aNormal;
      gl_Position = uProjection * uView * world;
    }
  `;
  const fragmentSource = `
    precision mediump float;
    varying vec3 vNormal;
    varying vec3 vPosition;
    uniform vec3 uColor;
    uniform vec3 uLight;
    void main() {
      vec3 normal = normalize(vNormal);
      float light = 0.42 + 0.58 * max(dot(normal, normalize(uLight - vPosition)), 0.0);
      float edge = 1.0 - smoothstep(0.46, 0.9, length(vPosition.xy) * 0.12);
      gl_FragColor = vec4(uColor * light * (0.93 + 0.07 * edge), 1.0);
    }
  `;

  const program = makeProgram(gl, vertexSource, fragmentSource);
  if (!program) {
    drawFallback(canvas);
    return;
  }
  gl.useProgram(program);
  gl.enable(gl.DEPTH_TEST);
  gl.enable(gl.CULL_FACE);
  gl.clearColor(0, 0, 0, 0);

  const locations = {
    position: gl.getAttribLocation(program, "aPosition"),
    normal: gl.getAttribLocation(program, "aNormal"),
    model: gl.getUniformLocation(program, "uModel"),
    view: gl.getUniformLocation(program, "uView"),
    projection: gl.getUniformLocation(program, "uProjection"),
    color: gl.getUniformLocation(program, "uColor"),
    light: gl.getUniformLocation(program, "uLight")
  };

  const mesh = sphereMesh(gl, 16, 10);
  const parts = [
    ["head", 0, 2.75, 0, 0.34, 0.39, 0.34],
    ["neck", 0, 2.32, 0, 0.17, 0.2, 0.17],
    ["chest", 0, 1.65, 0, 0.67, 0.78, 0.36],
    ["abdomen", 0, 0.85, 0, 0.49, 0.72, 0.3],
    ["pelvis", 0, 0.15, 0, 0.52, 0.38, 0.31],
    ["left-arm", -0.82, 1.57, 0, 0.18, 0.68, 0.18],
    ["right-arm", 0.82, 1.57, 0, 0.18, 0.68, 0.18],
    ["left-forearm", -0.96, 0.72, 0, 0.15, 0.57, 0.15],
    ["right-forearm", 0.96, 0.72, 0, 0.15, 0.57, 0.15],
    ["left-hand", -1.0, 0.05, 0, 0.17, 0.2, 0.16],
    ["right-hand", 1.0, 0.05, 0, 0.17, 0.2, 0.16],
    ["left-thigh", -0.29, -0.74, 0, 0.27, 0.77, 0.27],
    ["right-thigh", 0.29, -0.74, 0, 0.27, 0.77, 0.27],
    ["left-shin", -0.29, -1.78, 0, 0.2, 0.72, 0.2],
    ["right-shin", 0.29, -1.78, 0, 0.2, 0.72, 0.2],
    ["left-foot", -0.29, -2.62, -0.1, 0.24, 0.38, 0.45],
    ["right-foot", 0.29, -2.62, -0.1, 0.24, 0.38, 0.45]
  ];

  let rotation = 0;
  let dragging = false;
  let previousX = 0;

  function render() {
    resizeCanvas();
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    const aspect = canvas.width / canvas.height;
    const projection = perspective(Math.PI / 4, aspect, 0.1, 100);
    const view = lookAt([0, 0.05, 8.4], [0, 0, 0], [0, 1, 0]);
    gl.uniformMatrix4fv(locations.view, false, view);
    gl.uniformMatrix4fv(locations.projection, false, projection);
    gl.uniform3f(locations.light, -3.5, 5.5, 6.5);
    gl.bindBuffer(gl.ARRAY_BUFFER, mesh.buffer);
    gl.enableVertexAttribArray(locations.position);
    gl.vertexAttribPointer(locations.position, 3, gl.FLOAT, false, 24, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, mesh.normalBuffer);
    gl.enableVertexAttribArray(locations.normal);
    gl.vertexAttribPointer(locations.normal, 3, gl.FLOAT, false, 24, 0);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, mesh.indexBuffer);
    const yaw = rotation;
    parts.forEach(function (part) {
      const model = multiply(rotateY(yaw), translate(part[1], part[2], part[3]));
      const scaled = multiply(model, scale(part[4], part[5], part[6]));
      gl.uniformMatrix4fv(locations.model, false, scaled);
      gl.uniform3f(locations.color, 0.32, 0.50, 0.40);
      gl.drawElements(gl.TRIANGLES, mesh.count, gl.UNSIGNED_SHORT, 0);
    });
  }

  function resizeCanvas() {
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.max(1, Math.floor(canvas.clientWidth * ratio));
    const height = Math.max(1, Math.floor(canvas.clientHeight * ratio));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
  }

  canvas.addEventListener("keydown", function (event) {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      rotation += event.key === "ArrowLeft" ? -0.12 : 0.12;
      render();
    }
  });
  canvas.addEventListener("pointerdown", function (event) {
    dragging = true;
    previousX = event.clientX;
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", function (event) {
    if (!dragging) return;
    rotation += (event.clientX - previousX) * 0.01;
    previousX = event.clientX;
    render();
  });
  canvas.addEventListener("pointerup", function () { dragging = false; });
  canvas.addEventListener("pointercancel", function () { dragging = false; });
  window.addEventListener("resize", render, { passive: true });
  render();

  function makeProgram(context, vertex, fragment) {
    const vs = compile(context, context.VERTEX_SHADER, vertex);
    const fs = compile(context, context.FRAGMENT_SHADER, fragment);
    if (!vs || !fs) return null;
    const result = context.createProgram();
    context.attachShader(result, vs);
    context.attachShader(result, fs);
    context.linkProgram(result);
    return context.getProgramParameter(result, context.LINK_STATUS) ? result : null;
  }
  function compile(context, type, source) {
    const shader = context.createShader(type);
    context.shaderSource(shader, source);
    context.compileShader(shader);
    return context.getShaderParameter(shader, context.COMPILE_STATUS) ? shader : null;
  }
  function sphereMesh(context, bands, rings) {
    const vertices = [], normals = [], indices = [];
    for (let y = 0; y <= rings; y += 1) {
      const v = y / rings, phi = v * Math.PI;
      for (let x = 0; x <= bands; x += 1) {
        const u = x / bands, theta = u * Math.PI * 2;
        const px = Math.sin(phi) * Math.cos(theta), py = Math.cos(phi), pz = Math.sin(phi) * Math.sin(theta);
        vertices.push(px, py, pz); normals.push(px, py, pz);
      }
    }
    for (let y = 0; y < rings; y += 1) for (let x = 0; x < bands; x += 1) {
      const a = y * (bands + 1) + x, b = a + bands + 1;
      indices.push(a, b, a + 1, b, b + 1, a + 1);
    }
    const buffer = context.createBuffer(); context.bindBuffer(context.ARRAY_BUFFER, buffer);
    context.bufferData(context.ARRAY_BUFFER, new Float32Array(vertices), context.STATIC_DRAW);
    const normalBuffer = context.createBuffer(); context.bindBuffer(context.ARRAY_BUFFER, normalBuffer);
    context.bufferData(context.ARRAY_BUFFER, new Float32Array(normals), context.STATIC_DRAW);
    const indexBuffer = context.createBuffer(); context.bindBuffer(context.ELEMENT_ARRAY_BUFFER, indexBuffer);
    context.bufferData(context.ELEMENT_ARRAY_BUFFER, new Uint16Array(indices), context.STATIC_DRAW);
    return { buffer: buffer, normalBuffer: normalBuffer, indexBuffer: indexBuffer, count: indices.length };
  }
  function identity() { return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]; }
  function multiply(a, b) { const out = Array(16).fill(0); for (let row = 0; row < 4; row += 1) for (let col = 0; col < 4; col += 1) for (let k = 0; k < 4; k += 1) out[col * 4 + row] += a[k * 4 + row] * b[col * 4 + k]; return out; }
  function translate(x, y, z) { const m = identity(); m[12] = x; m[13] = y; m[14] = z; return m; }
  function scale(x, y, z) { const m = identity(); m[0] = x; m[5] = y; m[10] = z; return m; }
  function rotateY(a) { const m = identity(); m[0] = Math.cos(a); m[2] = -Math.sin(a); m[8] = Math.sin(a); m[10] = Math.cos(a); return m; }
  function perspective(fov, aspect, near, far) { const f = 1 / Math.tan(fov / 2), nf = 1 / (near - far); return [f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * nf, -1, 0, 0, 2 * far * near * nf, 0]; }
  function lookAt(eye, center, up) {
    const z = normalize([eye[0] - center[0], eye[1] - center[1], eye[2] - center[2]]), x = normalize(cross(up, z)), y = cross(z, x);
    return [x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0, -dot(x, eye), -dot(y, eye), -dot(z, eye), 1];
  }
  function normalize(v) { const n = Math.hypot.apply(Math, v) || 1; return v.map(function (x) { return x / n; }); }
  function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
  function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
  function drawFallback(target) {
    const context = target.getContext("2d");
    if (!context) return;
    context.clearRect(0, 0, target.width, target.height);
    context.fillStyle = "#3c6e55";
    context.beginPath(); context.ellipse(320, 105, 45, 52, 0, 0, Math.PI * 2); context.fill();
    context.fillRect(278, 160, 84, 245); context.fillRect(205, 175, 54, 220); context.fillRect(381, 175, 54, 220);
    context.fillRect(270, 390, 45, 260); context.fillRect(325, 390, 45, 260);
    context.fillRect(252, 635, 65, 34); context.fillRect(323, 635, 65, 34);
  }
}());
