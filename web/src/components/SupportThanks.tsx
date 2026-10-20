// Thanks visitors who come back from Stripe (`?danke=<tier id>`). Not proof of payment: it only
// stops the support prompt on this device.
import { type CSSProperties, useEffect, useRef, useState } from "react";
import { type SupportTier, support } from "../lib/config";
import { parseThanks, withoutThanks } from "../lib/support";
import {
  CloseButton,
  closeOnBackdrop,
  loadMemory,
  saveMemory,
} from "./SupportPrompt";
import "./Support.css";

const CONFETTI_COLOURS = [
  "var(--accent)",
  "var(--support-water)",
  "var(--c2)",
  "var(--c1)",
  "var(--support-text)",
];
const CONFETTI_SHAPES = ["", "round", "slim"];
const CONFETTI = Array.from({ length: 24 }, (_, index) => ({
  className: CONFETTI_SHAPES[index % 3],
  style: {
    left: `${2 + ((index * 41) % 96)}%`,
    background: CONFETTI_COLOURS[index % 5],
    animationDuration: `${2.6 + (index % 5) * 0.35}s`,
    animationDelay: `${(index % 7) * 0.15}s`,
  } satisfies CSSProperties,
}));

export default function SupportThanks() {
  const dialog = useRef<HTMLDialogElement>(null);
  const [thanks, setThanks] = useState<{ tier: SupportTier | null } | null>(
    null,
  );

  useEffect(() => {
    const found = parseThanks(location.search, support.tiers);
    if (!found) return;
    const stored = loadMemory();
    if (stored) saveMemory({ ...stored, supported: true });
    // A reload or shared link must not thank again.
    history.replaceState(
      history.state,
      "",
      location.pathname + withoutThanks(location.search) + location.hash,
    );
    setThanks(found);
  }, []);

  useEffect(() => {
    if (thanks) dialog.current?.showModal();
  }, [thanks]);

  if (!thanks) return null;
  const { tier } = thanks;

  return (
    // biome-ignore lint/a11y/useKeyWithClickEvents: Escape closes a modal dialog natively; this adds backdrop clicks
    <dialog
      ref={dialog}
      className="support-dialog support-thanks"
      aria-labelledby="support-thanks-title"
      onClick={closeOnBackdrop}
    >
      <div className="confetti" aria-hidden="true">
        {CONFETTI.map((piece, index) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: a fixed list that never reorders
          <span key={index} className={piece.className} style={piece.style} />
        ))}
      </div>
      <form method="dialog" className="support-card">
        <CloseButton />
        <div className="support-badge">
          <svg width="96" height="96" viewBox="0 0 96 96" aria-hidden="true">
            <path d="M30 50l12 12 24-26" />
          </svg>
        </div>
        {tier && (
          <span className="support-chip">
            {tier.name} · {tier.eur_per_month} € / Monat
          </span>
        )}
        <h2 id="support-thanks-title">Danke!</h2>
        <p className="support-lead">Sie halten die Vorhersage am Laufen.</p>
        <p className="support-text">
          Die Quittung kommt per E-Mail von Stripe.
          {/* A one-off gift has nothing to change or cancel. */}
          {tier &&
            " Über den Link darin können Sie jederzeit ändern oder kündigen."}
        </p>
        <button type="submit" className="support-back">
          Zur Vorhersage
        </button>
        <p className="support-note">
          Wir fragen Sie auf dieser Seite nicht mehr nach Unterstützung.
        </p>
      </form>
    </dialog>
  );
}
