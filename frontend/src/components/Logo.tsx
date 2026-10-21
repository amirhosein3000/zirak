export function Logo({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 512 512" className={className} aria-label="زیرک" role="img">
      <defs>
        <linearGradient id="zirak-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#14967f" />
          <stop offset="1" stopColor="#0a5a4e" />
        </linearGradient>
      </defs>
      <rect width="512" height="512" rx="116" fill="url(#zirak-g)" />
      <path d="M136 168 H352 L168 344 H376" fill="none" stroke="#fff" strokeWidth="44" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="376" cy="344" r="34" fill="#f0a63a" />
    </svg>
  );
}
