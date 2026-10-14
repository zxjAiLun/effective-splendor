import Link from "next/link";
import type { ReactNode } from "react";

export type StudioSection = "games" | "play" | "league" | "ratings";
type GlyphName = "gem" | "play" | "games" | "league" | "ratings" | "arrow" | "layers";

const glyphs: Record<GlyphName, string> = {
  gem: "M6 3h12l4 6-10 13L2 9l4-6Zm-4 6h20M6 3l6 19 6-19M6 3l6 6 6-6",
  play: "m9 5 10 7-10 7V5Z",
  games: "M8 3h11a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2ZM3 7v12a3 3 0 0 0 3 3h10M10 8h7m-7 4h5",
  league: "M8 3h8v5a4 4 0 0 1-8 0V3Zm0 2H4v2a4 4 0 0 0 4 4m8-6h4v2a4 4 0 0 1-4 4m-4 1v6m-4 3h8m-6-3h4",
  ratings: "M4 20V10h4v10m2 0V4h4v16m2 0v-7h4v7M2 20h20",
  arrow: "M4 12h16m-6-6 6 6-6 6",
  layers: "m12 3 10 5-10 5L2 8l10-5ZM2 12l10 5 10-5M2 16l10 5 10-5",
};

export function StudioGlyph({ name, className = "" }: { name: GlyphName; className?: string }) {
  return <svg className={`studio-glyph ${className}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><path d={glyphs[name]} /></svg>;
}

export function StudioBrand({ compact = false }: { compact?: boolean }) {
  return <Link className={`studio-brand${compact ? " studio-brand-compact" : ""}`} href="/" aria-label="Splendor Studio — Games">
    <span className="studio-brand-mark"><StudioGlyph name="gem" /></span>
    <span><strong>SPLENDOR</strong><small>Replay Studio</small></span>
  </Link>;
}

export function StudioNavigation({ active }: { active: StudioSection }) {
  const links: Array<{ id: StudioSection; href: string; label: string }> = [
    { id: "games", href: "/", label: "Games" },
    { id: "play", href: "/play", label: "Play" },
    { id: "league", href: "/league", label: "League" },
    { id: "ratings", href: "/ratings", label: "Ratings" },
  ];
  return <nav className="studio-navigation" aria-label="Studio navigation">
    <div className="studio-primary-links">{links.map(link => <Link href={link.href} key={link.id} aria-current={active === link.id ? "page" : undefined}><StudioGlyph name={link.id} /><span>{link.label}</span></Link>)}</div>
    <details className="studio-more">
      <summary>More <span aria-hidden="true">⌄</span></summary>
      <div className="studio-more-menu">
        <small>REPLAYS & RESEARCH</small>
        <Link href="/experiments">Experiment replay library</Link>
        <Link href="/ratings/reports">Research reports</Link>
        <Link href="/advanced">Legacy AnalysisTraceV1 viewer</Link>
      </div>
    </details>
  </nav>;
}

export function StudioHeader({ active }: { active: StudioSection }) {
  return <header className="studio-header"><StudioBrand /><StudioNavigation active={active} /><span className="studio-header-note">PLAYER-VIEW FIRST</span></header>;
}

export function StudioIntro({ eyebrow, title, children, action }: { eyebrow: string; title: string; children: ReactNode; action?: ReactNode }) {
  return <section className="studio-intro"><div><span className="section-kicker">{eyebrow}</span><h1>{title}</h1><div className="studio-intro-copy">{children}</div></div>{action ? <div className="studio-intro-action">{action}</div> : null}</section>;
}

/** Decorative card backs, not an example position or a second source of game data. */
export function StudioTableArt() {
  return <div className="studio-table-art" aria-hidden="true"><div className="studio-art-orbit" />{["green", "blue", "gold"].map(tone => <div className={`studio-art-card studio-art-${tone}`} key={tone}><span>SPLENDOR</span><StudioGlyph name="gem" /><i /><small>THE ART OF THE NEXT MOVE</small></div>)}<div className="studio-art-chips"><i /><i /><i /></div></div>;
}
