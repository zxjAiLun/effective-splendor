import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "League · Effective Splendor",
  description: "Start a rated Studio League match between two registered agents.",
};

export default function LeagueLayout({ children }: { children: React.ReactNode }) {
  return children;
}
