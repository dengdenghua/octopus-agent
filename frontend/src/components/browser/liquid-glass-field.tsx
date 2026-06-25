import { useEffect, useRef } from "react";

const prefersReducedMotion = () =>
  typeof window !== "undefined" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const vertexShader = `
attribute vec2 aPosition;
varying vec2 vUv;

void main() {
  vUv = aPosition * 0.5 + 0.5;
  gl_Position = vec4(aPosition, 0.0, 1.0);
}
`;

const fragmentShader = `
precision highp float;

uniform vec2 uResolution;
uniform float uTime;
uniform vec2 uPointer;
uniform float uPointerActive;
varying vec2 vUv;

float hash(vec2 p) {
  p = fract(p * vec2(123.34, 345.45));
  p += dot(p, p + 34.345);
  return fract(p.x * p.y);
}

float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  float a = hash(i);
  float b = hash(i + vec2(1.0, 0.0));
  float c = hash(i + vec2(0.0, 1.0));
  float d = hash(i + vec2(1.0, 1.0));
  return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

float fbm(vec2 p) {
  float v = 0.0;
  float a = 0.5;
  for (int i = 0; i < 5; i++) {
    v += a * noise(p);
    p = mat2(1.62, -1.12, 1.12, 1.62) * p + 7.13;
    a *= 0.52;
  }
  return v;
}

void main() {
  vec2 uv = vUv;
  vec2 aspect = vec2(uResolution.x / uResolution.y, 1.0);
  vec2 p = (uv - 0.5) * aspect;
  vec2 pointer = (uPointer - 0.5) * aspect;

  float t = uTime * 0.10;
  float flowA = fbm(p * 2.2 + vec2(t * 1.7, -t));
  float flowB = fbm(p * 4.0 + vec2(-t * 0.8, t * 1.3) + flowA);
  float ridge = abs(flowA - flowB);
  float caustic = pow(1.0 - smoothstep(0.02, 0.42, ridge), 2.2);

  vec2 warp = vec2(
    fbm(p * 3.0 + vec2(t, 2.4)) - 0.5,
    fbm(p * 3.0 + vec2(-1.8, -t)) - 0.5
  );
  float ribbon = smoothstep(
    0.11,
    0.0,
    abs(sin((p.x + warp.x * 0.18) * 5.2 + flowB * 2.8 + t * 5.0) + p.y * 0.72)
  );

  float pointerGlow = 0.0;
  if (uPointerActive > 0.001) {
    float d = length(p - pointer);
    pointerGlow = exp(-d * 6.0) * uPointerActive;
  }

  vec3 cool = vec3(0.45, 0.78, 1.0);
  vec3 warm = vec3(1.0, 0.95, 0.82);
  vec3 violet = vec3(0.78, 0.68, 1.0);
  vec3 color =
    warm * caustic * 0.16 +
    cool * ribbon * 0.09 +
    violet * flowB * 0.035 +
    warm * pointerGlow * 0.12;

  float alpha = clamp(caustic * 0.18 + ribbon * 0.12 + pointerGlow * 0.14, 0.0, 0.32);
  gl_FragColor = vec4(color, alpha);
}
`;

export function LiquidGlassField() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || prefersReducedMotion()) return;

    const webgl = createWebGlField(canvas);
    if (webgl) return webgl;
    return createCanvasField(canvas);
  }, []);

  return (
    <canvas ref={canvasRef} aria-hidden className="octo-liquid-glass-field" />
  );
}

function createShader(gl: WebGLRenderingContext, type: number, source: string) {
  const shader = gl.createShader(type);
  if (!shader) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

function createWebGlField(canvas: HTMLCanvasElement) {
  const gl = canvas.getContext("webgl", {
    alpha: true,
    antialias: false,
    depth: false,
    premultipliedAlpha: false,
    stencil: false,
  });
  if (!gl) return null;
  canvas.dataset.glassFieldMode = "webgl";

  const vertex = createShader(gl, gl.VERTEX_SHADER, vertexShader);
  const fragment = createShader(gl, gl.FRAGMENT_SHADER, fragmentShader);
  if (!vertex || !fragment) return null;

  const program = gl.createProgram();
  if (!program) return null;
  gl.attachShader(program, vertex);
  gl.attachShader(program, fragment);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return null;

  const buffer = gl.createBuffer();
  const positionLocation = gl.getAttribLocation(program, "aPosition");
  const resolutionLocation = gl.getUniformLocation(program, "uResolution");
  const timeLocation = gl.getUniformLocation(program, "uTime");
  const pointerLocation = gl.getUniformLocation(program, "uPointer");
  const pointerActiveLocation = gl.getUniformLocation(
    program,
    "uPointerActive",
  );
  if (
    !buffer ||
    positionLocation < 0 ||
    !resolutionLocation ||
    !timeLocation ||
    !pointerLocation ||
    !pointerActiveLocation
  ) {
    return null;
  }

  const pointer = { x: 0.5, y: 0.34, active: 0 };
  let targetPointerActive = 0;
  let raf = 0;
  let width = 1;
  let height = 1;
  let dpr = 1;

  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(
    gl.ARRAY_BUFFER,
    new Float32Array([-1, -1, 3, -1, -1, 3]),
    gl.STATIC_DRAW,
  );
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
  gl.clearColor(0, 0, 0, 0);

  const resize = () => {
    const rect = canvas.getBoundingClientRect();
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    width = Math.max(1, Math.floor(rect.width));
    height = Math.max(1, Math.floor(rect.height));
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    gl.viewport(0, 0, canvas.width, canvas.height);
  };

  const onPointerMove = (event: PointerEvent) => {
    const rect = canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    pointer.x = (event.clientX - rect.left) / rect.width;
    pointer.y = 1 - (event.clientY - rect.top) / rect.height;
    targetPointerActive = 1;
  };

  const onPointerLeave = () => {
    targetPointerActive = 0;
  };

  const render = (time: number) => {
    pointer.active += (targetPointerActive - pointer.active) * 0.06;
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.useProgram(program);
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.enableVertexAttribArray(positionLocation);
    gl.vertexAttribPointer(positionLocation, 2, gl.FLOAT, false, 0, 0);
    gl.uniform2f(resolutionLocation, width * dpr, height * dpr);
    gl.uniform1f(timeLocation, time * 0.001);
    gl.uniform2f(pointerLocation, pointer.x, pointer.y);
    gl.uniform1f(pointerActiveLocation, pointer.active);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    raf = window.requestAnimationFrame(render);
  };

  resize();
  const observer = new ResizeObserver(resize);
  observer.observe(canvas);
  window.addEventListener("pointermove", onPointerMove);
  window.addEventListener("pointerleave", onPointerLeave);
  raf = window.requestAnimationFrame(render);

  return () => {
    observer.disconnect();
    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerleave", onPointerLeave);
    window.cancelAnimationFrame(raf);
    gl.deleteBuffer(buffer);
    gl.deleteProgram(program);
    gl.deleteShader(vertex);
    gl.deleteShader(fragment);
    gl.getExtension("WEBGL_lose_context")?.loseContext();
  };
}

function createCanvasField(canvas: HTMLCanvasElement) {
  const context = canvas.getContext("2d", { alpha: true });
  if (!context) return;
  canvas.dataset.glassFieldMode = "2d";

  let frame = 0;
  let raf = 0;
  let width = 0;
  let height = 0;
  let dpr = 1;

  const resize = () => {
    const rect = canvas.getBoundingClientRect();
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    width = Math.max(1, Math.floor(rect.width));
    height = Math.max(1, Math.floor(rect.height));
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
  };

  const draw = () => {
    frame += 0.008;
    context.clearRect(0, 0, width, height);
    context.globalCompositeOperation = "lighter";

    const bands = [
      { x: 0.16, y: 0.18, r: 0.48, hue: "rgba(255,255,255,0.18)" },
      { x: 0.82, y: 0.24, r: 0.42, hue: "rgba(125,211,252,0.10)" },
      { x: 0.58, y: 0.86, r: 0.52, hue: "rgba(196,181,253,0.10)" },
    ];

    for (const band of bands) {
      const x = width * (band.x + Math.sin(frame * 0.7 + band.x * 8) * 0.035);
      const y = height * (band.y + Math.cos(frame * 0.6 + band.y * 9) * 0.05);
      const radius = Math.max(width, height) * band.r;
      const gradient = context.createRadialGradient(x, y, 0, x, y, radius);
      gradient.addColorStop(0, band.hue);
      gradient.addColorStop(0.42, "rgba(255,255,255,0.035)");
      gradient.addColorStop(1, "rgba(255,255,255,0)");
      context.fillStyle = gradient;
      context.fillRect(0, 0, width, height);
    }

    context.globalCompositeOperation = "screen";
    context.lineWidth = 1;
    for (let i = 0; i < 7; i += 1) {
      const phase = frame + i * 0.72;
      const y = height * (0.16 + i * 0.12);
      context.beginPath();
      for (let x = -40; x <= width + 40; x += 28) {
        const wave =
          Math.sin(x * 0.009 + phase * 1.8) * 14 +
          Math.sin(x * 0.017 - phase) * 6;
        const px = x;
        const py = y + wave + Math.cos(phase + i) * 10;
        if (x === -40) context.moveTo(px, py);
        else context.lineTo(px, py);
      }
      context.strokeStyle = `rgba(255,255,255,${0.018 + i * 0.002})`;
      context.stroke();
    }

    context.globalCompositeOperation = "source-over";
    raf = window.requestAnimationFrame(draw);
  };

  resize();
  const observer = new ResizeObserver(resize);
  observer.observe(canvas);
  raf = window.requestAnimationFrame(draw);

  return () => {
    observer.disconnect();
    window.cancelAnimationFrame(raf);
  };
}
