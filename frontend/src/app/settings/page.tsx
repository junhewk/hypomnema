import { Suspense } from "react";
import { SettingsPage } from "@/components/SettingsPage";

export default function SettingsRoute() {
  return (
    <Suspense>
      <SettingsPage />
    </Suspense>
  );
}
