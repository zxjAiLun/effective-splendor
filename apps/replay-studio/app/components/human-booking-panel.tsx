"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { API_BASE } from "../api-base.mjs";
import { bookingView, eloText, humanEloRows } from "../human-play-runtime.mjs";

export type HumanCompletion = {
  status: string; retryable: boolean; error: string | null;
  receipt: Record<string, unknown> | null;
};

/** The terminal result stays in the parent. This panel reports only booking. */
export function HumanBookingPanel({ completion, sessionId, humanSeat, busy, onRetry }: {
  completion: HumanCompletion | null | undefined; sessionId: string; humanSeat: number;
  busy: boolean; onRetry: () => void;
}) {
  const view = bookingView(completion, sessionId);
  const [detail, setDetail] = useState<unknown>(null);
  const [detailError, setDetailError] = useState("");
  const matchId = view.receipt?.match_id;
  useEffect(() => {
    if (typeof matchId !== "string") return;
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(`${API_BASE}/league/matches/${encodeURIComponent(matchId)}`, { signal: controller.signal });
        if (!response.ok) throw new Error(`Match details unavailable (${response.status}).`);
        const body = await response.json();
        if (!controller.signal.aborted) { setDetail(body); setDetailError(""); }
      } catch (error) {
        if (!controller.signal.aborted) setDetailError(error instanceof Error ? error.message : String(error));
      }
    })();
    return () => controller.abort();
  }, [matchId]);
  const rows: Array<{ participantId: string; label: string; before: number; after: number; delta: number }> =
    humanEloRows(view.receipt, detail, sessionId, humanSeat);
  return <section className="human-booking" aria-live="polite" aria-label="Studio League booking">
    <span className="section-kicker">STUDIO LEAGUE</span>
    {view.kind === "booked" && <small>Booked into Studio League — Elo events below.</small>}
    <h3>{view.headline}</h3><p>{view.message}</p>
    {view.error ? <p role="alert">{view.error}</p> : null}
    {view.kind === "booked" ? <>
      {rows.length ? <ul>{rows.map(row => <li key={row.participantId}>
        <b>{row.label}</b>: {eloText(row.before)} → {eloText(row.after)} ({row.delta >= 0 ? "+" : ""}{eloText(row.delta)})
      </li>)}</ul> : <p>{detailError || (detail ? "Seat-to-participant binding could not be verified." : "Reading seat-to-participant binding…")} Booking remains confirmed; ratings are not guessed.</p>}
      <small>This match’s Studio Elo event, not a claim about your current rating or the research official_elo.</small>
      <p><Link href="/league">Studio League standings</Link>{view.replayHref ? <> · <Link href={view.replayHref}>League replay</Link></> : null}</p>
    </> : null}
    {view.retryable ? <button type="button" disabled={busy} onClick={onRetry}>{busy ? "Checking booking…" : "Retry booking"}</button> : null}
    <details><summary>Session / receipt</summary><code>{sessionId}</code>{view.receipt ? <pre>{JSON.stringify(view.receipt, null, 2)}</pre> : null}</details>
  </section>;
}
