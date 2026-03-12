import { Suspense } from "react";
import { SearchPage } from "@/components/SearchPage";

export default function SearchRoute() {
  return (
    <Suspense>
      <SearchPage />
    </Suspense>
  );
}
