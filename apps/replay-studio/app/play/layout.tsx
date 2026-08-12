import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Human Play Studio · Effective Splendor",
  description: "Local player-view 1v1 Splendor sessions against registered agents.",
};

export default function PlayLayout({ children }: { children: React.ReactNode }) {
  return children;
}
