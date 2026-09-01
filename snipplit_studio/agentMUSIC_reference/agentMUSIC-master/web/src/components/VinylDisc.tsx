import { useEffect, useRef } from 'react';
import type { Stats } from '../types';

const RING_COLORS = ['#00d2ff', '#be32ff', '#ff3caa', '#22c55e', '#ff8c00', '#00d2ff', '#be32ff', '#ff3caa', '#00d2ff', '#be32ff'];
const RING_RADII = [168, 156, 144, 132, 120, 108, 96, 84, 72, 62];
const RING_SPEEDS = [0.3, -0.5, 0.7, -0.4, 0.6, -0.8, 0.45, -0.35, 0.55, -0.65];
const NUM_RINGS = RING_RADII.length;
const SEGS_PER_RING = 12;

const hex2rgb = (h: string): [number, number, number] => {
  const x = h.replace('#', '');
  return [parseInt(x.slice(0, 2), 16), parseInt(x.slice(2, 4), 16), parseInt(x.slice(4, 6), 16)];
};
const RING_RGB: [number, number, number][] = RING_COLORS.map(hex2rgb);

const PREFERS_REDUCED_MOTION =
  typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;

interface Particle {
  a: number;
  r: number;
  speed: number;
  size: number;
  brightness: number;
  rgb: [number, number, number];
}

interface Props {
  isPlaying: boolean;
  stats: Stats;
  activeJobs: number;
}

export function VinylDisc({ isPlaying, stats, activeJobs }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const frameRef = useRef<number>(0);
  const levelsRef = useRef<number[]>(
    Array.from({ length: NUM_RINGS * SEGS_PER_RING }, () => Math.random() * 0.2 + 0.05),
  );
  const anglesRef = useRef<number[]>(Array.from({ length: NUM_RINGS }, () => 0));
  const pulseRef = useRef(0);
  const particlesRef = useRef<Particle[]>(
    Array.from({ length: 40 }, () => ({
      a: Math.random() * Math.PI * 2,
      r: 80 + Math.random() * 100,
      speed: 0.002 + Math.random() * 0.004,
      size: 1 + Math.random() * 2,
      brightness: 0.2 + Math.random() * 0.4,
      rgb: RING_RGB[Math.floor(Math.random() * RING_RGB.length)],
    })),
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    let running = true;
    let time = 0;

    const resize = () => {
      const rect = canvas.parentElement!.getBoundingClientRect();
      const s = Math.min(rect.width, rect.height);
      canvas.width = s * devicePixelRatio;
      canvas.height = s * devicePixelRatio;
      canvas.style.width = s + 'px';
      canvas.style.height = s + 'px';
    };
    resize();
    window.addEventListener('resize', resize);

    const draw = () => {
      if (!running) return;
      if (document.hidden || PREFERS_REDUCED_MOTION) {
        frameRef.current = requestAnimationFrame(draw);
        return;
      }
      time += 1 / 60;
      const w = canvas.width;
      const h = canvas.height;
      const cx = w / 2;
      const cy = h / 2;
      const scale = w / 400;
      ctx.clearRect(0, 0, w, h);

      const active = isPlaying;
      const targetPulse = active ? 0.8 : 0.15;
      pulseRef.current += (targetPulse - pulseRef.current) * 0.03;
      const pulse = pulseRef.current;

      // Update levels
      const levels = levelsRef.current;
      for (let i = 0; i < levels.length; i++) {
        const target = active ? 0.25 + Math.random() * 0.65 : 0.05 + Math.random() * 0.15;
        levels[i] += (target - levels[i]) * (active ? 0.12 : 0.04);
      }

      // Update ring angles
      const angles = anglesRef.current;
      for (let i = 0; i < NUM_RINGS; i++) {
        angles[i] += RING_SPEEDS[i] * (active ? 2.5 : 0.4) * (1 / 60);
      }

      // Outer glow ring
      const glowAngle = time * 0.5;
      for (let a = 0; a < Math.PI * 2; a += 0.02) {
        const ga = a + glowAngle;
        const t = (ga % (Math.PI * 2)) / (Math.PI * 2);
        const r2 = 185 * scale;
        const px = cx + Math.cos(a) * r2;
        const py = cy + Math.sin(a) * r2;
        const hue = t * 360;
        const bright = 0.3 + pulse * 0.3 + Math.sin(a * 3 + time * 2) * 0.1;
        ctx.beginPath();
        ctx.arc(px, py, (1.5 + pulse) * scale, 0, Math.PI * 2);
        ctx.fillStyle = `hsla(${hue},85%,60%,${bright})`;
        ctx.fill();
      }

      // Groove rings
      for (let i = 0; i < 14; i++) {
        const gr = (30 + i * 11) * scale;
        const shimmer = 0.015 + Math.sin(time * 1.5 + i * 0.7) * 0.01 * (1 + pulse * 2);
        ctx.beginPath();
        ctx.arc(cx, cy, gr, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(255,255,255,${shimmer})`;
        ctx.lineWidth = 0.5 * scale;
        ctx.stroke();
      }

      // Mixer rings
      const segAngle = (Math.PI * 2) / SEGS_PER_RING;
      ctx.lineCap = 'round';
      for (let ri = 0; ri < NUM_RINGS; ri++) {
        const r = RING_RADII[ri] * scale;
        const [rr, gg, bb] = RING_RGB[ri];
        const baseAngle = angles[ri];

        for (let si = 0; si < SEGS_PER_RING; si++) {
          const lvl = levels[ri * SEGS_PER_RING + si];
          const startA = baseAngle + si * segAngle;
          const endA = startA + segAngle * (0.15 + lvl * 0.7);

          const alpha = 0.1 + lvl * 0.65;
          const lw = (1.5 + lvl * 2.5) * scale;

          ctx.beginPath();
          ctx.arc(cx, cy, r, startA, endA);
          ctx.strokeStyle = `rgba(${rr},${gg},${bb},${alpha * 0.3})`;
          ctx.lineWidth = lw + 4 * scale;
          ctx.stroke();

          ctx.beginPath();
          ctx.arc(cx, cy, r, startA, endA);
          ctx.strokeStyle = `rgba(${rr},${gg},${bb},${alpha})`;
          ctx.lineWidth = lw;
          ctx.stroke();
        }
      }

      // Particles
      for (const p of particlesRef.current) {
        p.a += p.speed * (active ? 3 : 0.5);
        const pr = p.r * scale * (1 + Math.sin(time + p.a * 2) * 0.05);
        const px = cx + Math.cos(p.a) * pr;
        const py = cy + Math.sin(p.a) * pr;
        const sz = p.size * scale * (0.6 + pulse * 0.8);
        const br = p.brightness * (0.5 + pulse);
        const [rr, gg, bb] = p.rgb;

        ctx.beginPath();
        ctx.arc(px, py, sz * 3, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${rr},${gg},${bb},${br * 0.15})`;
        ctx.fill();
        ctx.beginPath();
        ctx.arc(px, py, sz, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${rr},${gg},${bb},${br})`;
        ctx.fill();
      }

      // Center disc background
      const discR = 55 * scale;
      const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, discR);
      grad.addColorStop(0, 'rgba(12,12,24,.95)');
      grad.addColorStop(0.7, 'rgba(8,8,16,.9)');
      grad.addColorStop(1, 'rgba(0,210,255,.06)');
      ctx.beginPath();
      ctx.arc(cx, cy, discR, 0, Math.PI * 2);
      ctx.fillStyle = grad;
      ctx.fill();

      ctx.beginPath();
      ctx.arc(cx, cy, discR, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(0,210,255,${0.12 + pulse * 0.2})`;
      ctx.lineWidth = 2 * scale;
      ctx.stroke();

      if (active) {
        const pw = (time * 1.5) % 3;
        const pwR = discR + pw * 40 * scale;
        const pwAlpha = Math.max(0, 0.2 - pw * 0.07);
        ctx.beginPath();
        ctx.arc(cx, cy, pwR, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(0,210,255,${pwAlpha})`;
        ctx.lineWidth = 1.5 * scale;
        ctx.stroke();
      }

      frameRef.current = requestAnimationFrame(draw);
    };

    frameRef.current = requestAnimationFrame(draw);

    return () => {
      running = false;
      cancelAnimationFrame(frameRef.current);
      window.removeEventListener('resize', resize);
    };
  }, [isPlaying]);

  const pods = [
    { angle: -70, icon: '🎵', val: stats.tracks, label: 'Треки', c: '0,210,255' },
    { angle: -10, icon: '🎤', val: stats.choruses, label: 'Припевы', c: '190,50,255' },
    { angle: 50, icon: '🎬', val: stats.videos, label: 'Видео', c: '255,60,170' },
    { angle: 130, icon: '⚡', val: stats.active_jobs ?? 0, label: 'Активные', c: '34,197,94' },
  ];

  return (
    <div className="vinyl-universe">
      <canvas
        ref={canvasRef}
        style={{ position: 'absolute', inset: 0, borderRadius: '50%', zIndex: 2 }}
        aria-hidden="true"
      />
      {pods.map((p, i) => {
        const rad = (p.angle * Math.PI) / 180;
        const x = 50 + 48 * Math.sin(rad);
        const y = 50 - 48 * Math.cos(rad);
        return (
          <div
            key={i}
            className="stat-pod"
            style={{
              left: x + '%',
              top: y + '%',
              borderColor: `rgba(${p.c},.18)`,
              boxShadow: `0 4px 20px rgba(0,0,0,.4),0 0 15px rgba(${p.c},.08)`,
            }}
          >
            <div className="stat-pod-icon" aria-hidden="true">
              {p.icon}
            </div>
            <div className="stat-pod-val">{p.val}</div>
            <div className="stat-pod-label">{p.label}</div>
          </div>
        );
      })}
      <div className="hub" style={{ background: 'transparent', border: 'none', boxShadow: 'none' }}>
        <div className="hub-inner">
          <div className="hub-label">agent</div>
          <div className="hub-title">MUSIC</div>
          <div className="hub-status">{isPlaying ? `${activeJobs} в работе` : 'Ожидание'}</div>
        </div>
      </div>
      <div className={`arm ${isPlaying ? 'play' : ''}`} aria-hidden="true" />
    </div>
  );
}
