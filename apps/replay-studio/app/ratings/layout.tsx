import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Ratings · Effective Splendor",
  description:
    "Studio League current standings: the league's own Elo, read from the ledger. Research reports live under /ratings/reports.",
};

export default function RatingsLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return children;
}
