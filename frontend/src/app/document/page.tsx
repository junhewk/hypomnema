import { Suspense } from "react";
import { DocumentDetailQueryPage } from "@/components/DocumentDetailQueryPage";

export default function DocumentQueryPage() {
  return (
    <Suspense fallback={null}>
      <DocumentDetailQueryPage />
    </Suspense>
  );
}
