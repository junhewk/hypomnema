"use client";

import { useState } from "react";
import { useDocuments } from "@/hooks/useDocuments";
import { ScribbleInput } from "./ScribbleInput";
import { FileDropZone } from "./FileDropZone";
import { DocumentCard } from "./DocumentCard";
import type { Document } from "@/lib/types";

export function StreamPage() {
  const { documents, isLoading, hasMore, loadMore, refresh } = useDocuments();
  const [editing, setEditing] = useState<Document | null>(null);

  return (
    <div className="mx-auto max-w-2xl px-4 py-8">
      <ScribbleInput
        onSubmit={() => {
          setEditing(null);
          refresh();
        }}
        editingDocument={editing}
        onCancelEdit={() => setEditing(null)}
      />
      <FileDropZone onUpload={refresh} />

      <section>
        {documents.map((doc, i) => (
          <DocumentCard
            key={doc.id}
            document={doc}
            onEdit={setEditing}
            style={{ animationDelay: `${i * 50}ms` }}
          />
        ))}

        {hasMore && (
          <button
            onClick={loadMore}
            className="mt-6 w-full rounded border border-border py-2.5 text-center font-mono text-xs text-muted transition-colors hover:border-border-focus hover:text-foreground"
          >
            load more
          </button>
        )}

        {isLoading && (
          <p className="py-8 text-center font-mono text-xs text-muted animate-pulse-dot">
            Loading...
          </p>
        )}

        {!isLoading && documents.length === 0 && (
          <div className="py-16 text-center">
            <p className="font-mono text-sm text-muted">
              Start by writing something above.
            </p>
            <p className="mt-2 font-mono text-xs text-muted/50">
              Your notes become nodes in a knowledge graph.
            </p>
          </div>
        )}
      </section>
    </div>
  );
}
