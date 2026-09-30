import { useId } from "react";

/**
 * Q-GreenFleet mark: a ship's load-line disc (the Plimsoll mark painted on every hull) with a waterline running
 * through it. The ring takes `currentColor`; the waterline takes `wave`.
 */
export function LogoMark({ size = 32, wave = "var(--brand-wave)", title }: { size?: number; wave?: string; title?: string }) {
  const id = `wl${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} role={title ? "img" : undefined} aria-label={title}
      aria-hidden={title ? undefined : true} style={{ flex: "none" }}>
      <mask id={id}>
        <rect width="64" height="64" fill="#fff" />
        <path d="M0 34 C8 29 14 29 21 33.5 S33 38 40 33.5 S54 29 64 34" stroke="#000" strokeWidth="10.5" fill="none" />
      </mask>
      <circle cx="32" cy="32" r="18.5" fill="none" stroke="currentColor" strokeWidth="5.2" mask={`url(#${id})`} />
      <path d="M5 34 C11.5 30.1 16 30.1 22.2 33.8 S34.4 37.6 40.6 33.8 S52 30.1 59 33.3" stroke={wave}
        strokeWidth="4.6" strokeLinecap="round" fill="none" />
    </svg>
  );
}

/** Mark + wordmark, as used in the sidebar. */
export function Wordmark({ sub = "green fleet decisions" }: { sub?: string }) {
  return (
    <div className="brand">
      <LogoMark size={38} title="Q-GreenFleet" />
      <div>
        <div className="brand-name">Q-GreenFleet</div>
        <div className="brand-sub">{sub}</div>
      </div>
    </div>
  );
}
