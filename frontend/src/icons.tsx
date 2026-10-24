const shapes = {
  globe: <><circle cx="12" cy="12" r="9" /><path d="M3 12h18" /><path d="M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18" /></>,
  lock: <><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></>,
  mic: <><path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z" /><path d="M19 11a7 7 0 0 1-14 0" /><path d="M12 18v3" /></>,
  send: <><path d="M5 12h14" /><path d="M13 6l6 6-6 6" /></>,
  clip: <path d="M21 11.5l-8.6 8.6a5 5 0 0 1-7.1-7.1l8.6-8.6a3.3 3.3 0 0 1 4.7 4.7l-8.6 8.6a1.7 1.7 0 0 1-2.4-2.4l7.9-7.9" />,
  upload: <><path d="M12 15V4" /><path d="M7 9l5-5 5 5" /><path d="M5 20h14" /></>,
  speaker: <><path d="M4 9v6h4l5 4V5L8 9H4z" /><path d="M16.5 8.5a5 5 0 0 1 0 7" /></>,
  camera: <><path d="M4 8h3l2-3h6l2 3h3v11H4z" /><circle cx="12" cy="13" r="3.5" /></>,
  check: <path d="M5 12l5 5 9-10" />,
}

export function Icon({ name, size = 16, color = 'currentColor', weight = 1.75 }: { name: keyof typeof shapes; size?: number; color?: string; weight?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={weight} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {shapes[name]}
    </svg>
  )
}

// The attorney flag: gold pennant on a pole.
export function Flag({ size, pole }: { size: number; pole: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 21V3" stroke={pole} strokeWidth="1.75" strokeLinecap="round" />
      <path d="M6 4h12l-3 4.5 3 4.5H6z" fill="#f2c66d" />
    </svg>
  )
}
