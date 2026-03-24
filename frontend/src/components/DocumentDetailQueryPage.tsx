"use client";

import { useSearchParams } from "next/navigation";
import { DocumentDetailPage } from "./DocumentDetailPage";

export function DocumentDetailQueryPage() {
  const searchParams = useSearchParams();
  const id = searchParams.get("id");

  if (!id) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-8">
        <p className="font-mono text-sm text-red-500">Missing document id.</p>
      </div>
    );
  }

  return <DocumentDetailPage id={id} />;
}
