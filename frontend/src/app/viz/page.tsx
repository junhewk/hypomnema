"use client";

import dynamic from "next/dynamic";

const VizPage = dynamic(
  () => import("@/components/VizPage").then((m) => ({ default: m.VizPage })),
  { ssr: false },
);

export default function VizRoute() {
  return <VizPage />;
}
