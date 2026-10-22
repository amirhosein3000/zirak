import { faNum } from "@/lib/fa";

/** Half-circle market mood gauge, 0 (extreme fear) to 100 (euphoria). Our own design, not a clone of any index. */
export function MoodGauge({ score, label }: { score: number; label: string }) {
  const r = 70;
  const cx = 90;
  const cy = 84;
  const clamped = Math.max(0, Math.min(100, score));
  const angle = Math.PI * (1 - clamped / 100); // 180° (left) -> 0° (right)
  const nx = cx + (r - 14) * Math.cos(angle);
  const ny = cy - (r - 14) * Math.sin(angle);
  const arc = (from: number, to: number) => {
    const a0 = Math.PI * (1 - from / 100);
    const a1 = Math.PI * (1 - to / 100);
    return `M${cx + r * Math.cos(a0)},${cy - r * Math.sin(a0)} A${r},${r} 0 0 1 ${cx + r * Math.cos(a1)},${cy - r * Math.sin(a1)}`;
  };
  // Five bands from fear (warm red) to euphoria (amber), with a calm teal middle.
  const bands = [
    { from: 0, to: 20, color: "var(--down)" },
    { from: 20, to: 40, color: "color-mix(in srgb, var(--down) 55%, var(--surface))" },
    { from: 40, to: 60, color: "var(--primary)" },
    { from: 60, to: 80, color: "color-mix(in srgb, var(--accent) 60%, var(--surface))" },
    { from: 80, to: 100, color: "var(--accent)" },
  ];
  return (
    <div className="flex flex-col items-center" dir="ltr">
      <svg viewBox="0 0 180 100" className="w-full max-w-[220px]" role="img" aria-label={`حال بازار: ${label}، ${score} از ۱۰۰`}>
        {bands.map((b) => (
          <path key={b.from} d={arc(b.from + 0.8, b.to - 0.8)} stroke={b.color} strokeWidth="12" fill="none" strokeLinecap="butt" />
        ))}
        <line x1={cx} y1={cy} x2={nx} y2={ny} stroke="var(--text)" strokeWidth="3" strokeLinecap="round" className="transition-all duration-700" />
        <circle cx={cx} cy={cy} r="6" fill="var(--text)" />
      </svg>
      <div dir="rtl" className="-mt-1 text-center">
        <div className="num text-2xl font-bold">{faNum(score, 0)}</div>
        <div className="text-sm font-bold text-muted">{label}</div>
      </div>
    </div>
  );
}

const GRADE_COLOR: Record<string, string> = {
  A: "var(--up)",
  B: "var(--primary)",
  C: "var(--accent)",
  D: "color-mix(in srgb, var(--down) 70%, var(--accent))",
  E: "var(--down)",
};

/** Circular Zirak Score with the letter grade in the middle. */
export function ScoreRing({ score, grade, size = 112 }: { score: number; grade: string; size?: number }) {
  const r = 46;
  const c = 2 * Math.PI * r;
  const color = GRADE_COLOR[grade] ?? "var(--primary)";
  return (
    <svg viewBox="0 0 110 110" width={size} height={size} role="img" aria-label={`امتیاز زیرک ${score} از ۱۰۰، رتبه ${grade}`}>
      <circle cx="55" cy="55" r={r} stroke="var(--surface-2)" strokeWidth="10" fill="none" />
      <circle
        cx="55"
        cy="55"
        r={r}
        stroke={color}
        strokeWidth="10"
        fill="none"
        strokeLinecap="round"
        strokeDasharray={`${(c * Math.max(0, Math.min(100, score))) / 100} ${c}`}
        transform="rotate(-90 55 55)"
        className="transition-all duration-1000"
      />
      <text x="55" y="52" textAnchor="middle" fontSize="30" fontWeight="700" fill={color}>
        {grade}
      </text>
      <text x="55" y="74" textAnchor="middle" fontSize="13" fill="var(--muted)">
        {faNum(score, 0)}/۱۰۰
      </text>
    </svg>
  );
}
