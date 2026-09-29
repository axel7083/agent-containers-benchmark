export const pct = (v) => (v == null ? '–' : `${Math.round(v * 100)}%`);

export const ci = (pair) =>
  pair && pair[0] != null && pair[1] != null ? `${Math.round(pair[0] * 100)}–${Math.round(pair[1] * 100)}` : '';

export const usd = (v) => (v == null ? '–' : v < 0.01 && v > 0 ? `$${v.toFixed(4)}` : `$${v.toFixed(2)}`);

export const secs = (v) => (v == null ? '–' : v < 90 ? `${Math.round(v)}s` : `${(v / 60).toFixed(1)}m`);

// Sequential blue ramp (steps 100 → 700) for pass rates 0 → 1.
const RAMP = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b'];

export function rampColor(rate) {
  const i = Math.min(RAMP.length - 1, Math.floor(rate * RAMP.length));
  return { fill: RAMP[i], ink: i >= 3 ? '#ffffff' : '#0b0b0b' };
}

export const ARMS = ['implicit', 'nudge', 'explicit'];

export const ARM_HELP = {
  implicit: 'natural request, no practices named',
  nudge: 'one generic "follow best practices" sentence',
  explicit: 'every graded rule spelled out',
};
