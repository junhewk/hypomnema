"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import type { RelatedDocument } from "@/lib/types";

export function useRelatedDocuments(id: string) {
  const [related, setRelated] = useState<RelatedDocument[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    api
      .getRelatedDocuments(id)
      .then((docs) => {
        if (!cancelled) setRelated(docs);
      })
      .catch(() => {
        if (!cancelled) setRelated([]);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  return { related, isLoading };
}
