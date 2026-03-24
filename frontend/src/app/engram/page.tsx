import { Suspense } from "react";
import { EngramDetailQueryPage } from "@/components/EngramDetailQueryPage";

export default function EngramQueryPage() {
  return (
    <Suspense fallback={null}>
      <EngramDetailQueryPage />
    </Suspense>
  );
}
