import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Rating Studio · Effective Splendor",
  description: "Provenance-bound 1v1 league ratings and head-to-head analysis.",
};

export default function RatingsLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return children;
}
