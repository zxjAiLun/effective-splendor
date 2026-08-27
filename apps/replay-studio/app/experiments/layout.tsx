import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Experiment Replay Library · Effective Splendor",
  description: "Browse and replay verified experiment matches (M35A) directly from run directories.",
};

export default function ExperimentsLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return children;
}
