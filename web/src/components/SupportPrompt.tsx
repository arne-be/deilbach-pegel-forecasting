// Asks regular visitors for a monthly contribution, from the configured visit on, only on calm days.
import { type MouseEvent, useEffect, useRef, useState } from "react";
import { support } from "../lib/config";
import type { State } from "../lib/forecast";
import {
  parseMemory,
  recordVisit,
  type SupportMemory,
  shouldPrompt,
} from "../lib/support";
import "./Support.css";

const STORAGE_KEY = "deilbach-pegel:support";

/** null when the browser blocks storage (private mode): then the page never asks. */
export function loadMemory(): SupportMemory | null {
  try {
    return parseMemory(localStorage.getItem(STORAGE_KEY));
  } catch {
    return null;
  }
}

/** False when the browser blocks storage; callers then stay quiet rather than nag. */
export function saveMemory(memory: SupportMemory): boolean {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(memory));
    return true;
  } catch {
    return false;
  }
}

/** Closes a full-screen dialog when the click lands outside its card. */
export function closeOnBackdrop(event: MouseEvent<HTMLDialogElement>) {
  if (event.target === event.currentTarget) event.currentTarget.close();
}

/** Submits the surrounding `<form method="dialog">`, which closes the dialog. */
export function CloseButton() {
  return (
    <button type="submit" className="support-close" aria-label="Schließen">
      <svg
        width="20"
        height="20"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        aria-hidden="true"
      >
        <path d="M6 6l12 12M6 18L18 6" />
      </svg>
    </button>
  );
}

interface SupportPromptProps {
  state: State;
  categoryNumber: number;
}

export default function SupportPrompt({
  state,
  categoryNumber,
}: SupportPromptProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const memory = useRef<SupportMemory | null>(null);
  // Set once when the prompt is due; the dialog opens after it rendered with the count.
  const [visits, setVisits] = useState<number | null>(null);

  useEffect(() => {
    const stored = loadMemory();
    if (!stored) return;
    const next = recordVisit(stored, Date.now());
    if (next !== stored && !saveMemory(next)) return;
    memory.current = next;
  }, []);

  useEffect(() => {
    const current = memory.current;
    if (visits !== null || !current) return;
    const ask = shouldPrompt(
      current,
      support.prompt_after_visits,
      state,
      categoryNumber,
      Date.now(),
    );
    if (!ask) return;
    setVisits(current.visits);
  }, [state, categoryNumber, visits]);

  useEffect(() => {
    if (visits !== null) dialog.current?.showModal();
  }, [visits]);

  const remember = (change: Partial<SupportMemory>) => {
    if (!memory.current) return;
    memory.current = { ...memory.current, ...change };
    saveMemory(memory.current);
  };
  const featured = Math.floor(support.tiers.length / 2);

  return (
    // biome-ignore lint/a11y/useKeyWithClickEvents: Escape closes a modal dialog natively; this adds backdrop clicks
    <dialog
      ref={dialog}
      className="support-dialog support-prompt"
      aria-labelledby="support-prompt-title"
      onClose={() => remember({ dismissedMs: Date.now() })}
      onClick={closeOnBackdrop}
    >
      <form method="dialog" className="support-card">
        <CloseButton />
        <span className="support-handle" aria-hidden="true" />
        <div className="support-staff">
          <svg
            width="80"
            height="260"
            viewBox="0 0 80 260"
            role="img"
            aria-label={`Besuchspegel: ${visits} Besuche`}
          >
            <rect
              className="frame"
              x="18"
              y="2"
              width="36"
              height="256"
              rx="6"
            />
            <rect
              className="water"
              x="18"
              y="52"
              width="36"
              height="206"
              rx="6"
            />
            <path
              className="ticks"
              d="M18 52h22M18 103h22M18 154h22M18 205h22"
            />
            {[0, 1, 2, 3]
              .filter((step) => (visits ?? 0) - step > 0)
              .map((step) => (
                <text
                  key={step}
                  className={step === 0 ? "top" : undefined}
                  x="62"
                  y={57 + step * 51}
                >
                  {(visits ?? 0) - step}
                </text>
              ))}
          </svg>
          <span className="support-staff-label">Besuche</span>
        </div>
        <div className="support-bar">
          <svg
            width="120"
            height="16"
            viewBox="0 0 120 16"
            role="img"
            aria-label={`Besuchspegel: ${visits} Besuche`}
          >
            <rect
              className="frame"
              x="1"
              y="1"
              width="118"
              height="14"
              rx="4"
            />
            <rect className="water" x="1" y="1" width="96" height="14" rx="4" />
            <path className="ticks" d="M24 1v8M48 1v8M72 1v8M96 1v8" />
          </svg>
          <span aria-hidden="true">{visits} Besuche</span>
        </div>
        <div className="support-body">
          <p className="support-eyebrow">Ihr Besuchspegel steigt</p>
          <h2 id="support-prompt-title">
            Halten Sie die Vorhersage am Laufen.
          </h2>
          <p className="support-text">
            Sie schauen regelmäßig vorbei. Mit einem kleinen monatlichen Beitrag
            bleibt sie kostenlos und ohne Werbung.
          </p>
          <div className="support-tiers">
            {support.tiers.map((tier, index) => (
              <a
                key={tier.id}
                className={index === featured ? "tier featured" : "tier"}
                href={tier.url ?? undefined}
                onClick={() => remember({ supported: true })}
              >
                <b>{tier.name}</b>
                <span>
                  {tier.eur_per_month} € <small>/ Monat</small>
                </span>
              </a>
            ))}
          </div>
          <div className="support-foot">
            <button
              type="button"
              className="support-once"
              onClick={() => {
                dialog.current?.close();
                document.getElementById("unterstuetzen")?.scrollIntoView();
              }}
            >
              Einmalig geben
            </button>
            <button type="submit" className="support-later">
              Später
            </button>
          </div>
        </div>
      </form>
    </dialog>
  );
}
