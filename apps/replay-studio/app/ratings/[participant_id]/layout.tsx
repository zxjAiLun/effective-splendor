import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Participant Profile · Effective Splendor",
  description: "Studio League participant profile, rating progression, and head-to-head records.",
};

export default function ParticipantProfileLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return children;
}
