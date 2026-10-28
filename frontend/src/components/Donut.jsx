// Distribution donut: one slice per entity, total (or a given value) in the centre. Slices animate when values change.

// Categorical slots in fixed order (validated for colour-vision deficiency). An entity keeps its slot across charts.
export const SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];
// Neutral fill for the part of a whole that hasn't happened yet (for example "not recovered yet").
export const REMAINDER = "#e2e8f0";

const usd0 = (v) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(v || 0);
const usdK = (v) => (v >= 1000 ? `$${(v / 1000).toFixed(1)}k` : usd0(v));

export default function Donut({ slices, label, value, size = 128, stroke = 16 }) {
  const total = slices.reduce((a, s) => a + s.value, 0);
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const gap = slices.filter((s) => s.value > 0).length > 1 ? 2 : 0;
  let start = 0;
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#f1f5f9" strokeWidth={stroke} />
        {slices.map((s) => {
          const len = total ? (s.value / total) * c : 0;
          const offset = -start;
          start += len;
          return (
            <circle
              key={s.id}
              cx={size / 2}
              cy={size / 2}
              r={r}
              fill="none"
              stroke={s.color}
              strokeWidth={stroke}
              strokeDasharray={`${Math.max(0, len - gap)} ${c}`}
              strokeDashoffset={offset}
              style={{ transition: "stroke-dasharray 700ms ease, stroke-dashoffset 700ms ease" }}
            >
              <title>{`${s.label}: ${usd0(s.value)} (${total ? Math.round((s.value / total) * 100) : 0}%)${
                s.note ? `, ${s.note}` : ""
              }`}</title>
            </circle>
          );
        })}
      </svg>
      <div className="pointer-events-none absolute inset-0 grid place-items-center text-center">
        <div>
          <div className="text-[10px] text-slate-500">{label}</div>
          <div className="font-mono text-sm font-semibold tabular-nums">{value ?? usdK(total)}</div>
        </div>
      </div>
    </div>
  );
}
