export interface LiquidPalette {
  accent: string;
  accentHover: string;
  text: string;
  highlight: string;
  bg: string;
}

interface Blob {
  x: number;
  y: number;
  r: number;
  ax: number;
  ay: number;
  fx: number;
  fy: number;
  p: number;
  q: number;
  s1: number;
  s2: number;
  sq: number;
}

const BLOBS: Blob[] = [
  {
    x: 0.12,
    y: 0.18,
    r: 0.52,
    ax: 0.1,
    ay: 0.05,
    fx: 0.23,
    fy: 0.19,
    p: 0,
    q: 1,
    s1: 0.5,
    s2: 0.37,
    sq: 1.15,
  },
  {
    x: 0.92,
    y: 0.44,
    r: 0.44,
    ax: 0.08,
    ay: 0.05,
    fx: 0.17,
    fy: 0.21,
    p: 2,
    q: 0.5,
    s1: 0.42,
    s2: 0.55,
    sq: 1.25,
  },
  {
    x: 0.18,
    y: 0.76,
    r: 0.56,
    ax: 0.09,
    ay: 0.04,
    fx: 0.15,
    fy: 0.18,
    p: 4,
    q: 3,
    s1: 0.36,
    s2: 0.47,
    sq: 1.05,
  },
  {
    x: 0.86,
    y: 0.94,
    r: 0.42,
    ax: 0.1,
    ay: 0.03,
    fx: 0.2,
    fy: 0.14,
    p: 1,
    q: 5,
    s1: 0.55,
    s2: 0.33,
    sq: 1.1,
  },
];

/** Un colore esadecimale dei token in componenti «r,g,b», per comporlo con l'alfa; `null` se non lo è. */
export function hexToRgb(hex: string): string | null {
  const match = /^#([0-9a-f]{6})$/i.exec(hex.trim());
  if (!match) return null;
  const value = parseInt(match[1], 16);
  return `${(value >> 16) & 255},${(value >> 8) & 255},${value & 255}`;
}

/** I colori del liquido, letti dai token CSS (nessun valore scritto qui). */
export function readPalette(style: CSSStyleDeclaration): LiquidPalette | null {
  const read = (name: string) => hexToRgb(style.getPropertyValue(name));
  const accent = read("--color-accent");
  const accentHover = read("--color-accent-hover");
  const text = read("--color-text");
  const highlight = read("--color-liquid-highlight");
  const bg = read("--color-bg");
  if (!accent || !accentHover || !text || !highlight || !bg) return null;
  return { accent, accentHover, text, highlight, bg };
}

function shape(blob: Blob, t: number, width: number, height: number, scale: number) {
  const cx = blob.x * width + blob.ax * Math.sin(t * blob.fx + blob.p) * width;
  const cy = blob.y * height + blob.ay * Math.cos(t * blob.fy + blob.q) * height;
  const n = 8;
  const radius = blob.r * scale;
  const points: [number, number][] = [];
  for (let i = 0; i < n; i++) {
    const angle = (i / n) * Math.PI * 2;
    const rr =
      radius *
      (1 +
        0.16 * Math.sin(t * blob.s1 + i * 2.1 + blob.p) +
        0.09 * Math.sin(t * blob.s2 + i * 3.7 + blob.q));
    points.push([cx + Math.cos(angle) * rr, cy + Math.sin(angle) * rr * blob.sq]);
  }
  const path = new Path2D();
  const middle = (k: number): [number, number] => {
    const a = points[k % n];
    const b = points[(k + 1) % n];
    return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  };
  const start = middle(n - 1);
  path.moveTo(start[0], start[1]);
  for (let i = 0; i < n; i++) {
    const end = middle(i);
    path.quadraticCurveTo(points[i][0], points[i][1], end[0], end[1]);
  }
  path.closePath();
  return { path, cx, cy, radius: radius * blob.sq };
}

/** Un fotogramma dello sfondo liquido: quattro blob dal contorno morbido, riflessi e vignetta. */
export function drawLiquid(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  t: number,
  intensity: number,
  palette: LiquidPalette,
) {
  const rgba = (rgb: string, alpha: number) => `rgba(${rgb},${alpha})`;
  const scale = Math.min(width, height * 0.5);
  ctx.clearRect(0, 0, width, height);
  BLOBS.forEach((blob, k) => {
    const o = shape(blob, t, width, height, scale);
    let g = ctx.createRadialGradient(
      o.cx - o.radius * 0.25,
      o.cy - o.radius * 0.3,
      0,
      o.cx,
      o.cy,
      o.radius * 1.1,
    );
    g.addColorStop(0, rgba(palette.accentHover, 0.22 * intensity));
    g.addColorStop(0.6, rgba(palette.accent, 0.12 * intensity));
    g.addColorStop(1, rgba(palette.accent, 0.05 * intensity));
    ctx.fillStyle = g;
    ctx.fill(o.path);

    ctx.save();
    ctx.clip(o.path);
    g = ctx.createLinearGradient(
      o.cx - o.radius,
      o.cy - o.radius,
      o.cx + o.radius * 0.2,
      o.cy + o.radius * 0.2,
    );
    g.addColorStop(0, rgba(palette.text, 0.12 * intensity));
    g.addColorStop(0.55, rgba(palette.text, 0));
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, width, height);
    ctx.translate(
      o.cx - o.radius * 0.25 + Math.sin(t * 0.4 + k) * o.radius * 0.12,
      o.cy - o.radius * 0.38 + Math.cos(t * 0.33 + k) * o.radius * 0.06,
    );
    ctx.rotate(-0.55 + Math.sin(t * 0.25 + k * 2) * 0.18);
    ctx.scale(1, 0.2);
    g = ctx.createRadialGradient(0, 0, 0, 0, 0, o.radius * 0.5);
    g.addColorStop(0, rgba(palette.text, 0.16 * intensity));
    g.addColorStop(1, rgba(palette.text, 0));
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(0, 0, o.radius * 0.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();

    g = ctx.createLinearGradient(
      o.cx - o.radius,
      o.cy - o.radius,
      o.cx + o.radius,
      o.cy + o.radius,
    );
    g.addColorStop(0, rgba(palette.highlight, 0.4 * intensity));
    g.addColorStop(0.5, rgba(palette.accent, 0.1 * intensity));
    g.addColorStop(1, rgba(palette.accent, 0.04 * intensity));
    ctx.strokeStyle = g;
    ctx.lineWidth = 1.5;
    ctx.stroke(o.path);
  });
  const vignette = ctx.createRadialGradient(
    width / 2,
    height * 0.42,
    0,
    width / 2,
    height * 0.42,
    Math.min(width, height) * 0.8,
  );
  vignette.addColorStop(0, rgba(palette.bg, 0.6));
  vignette.addColorStop(1, rgba(palette.bg, 0));
  ctx.fillStyle = vignette;
  ctx.fillRect(0, 0, width, height);
}
