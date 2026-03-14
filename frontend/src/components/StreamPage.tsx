"use client";

import { useState, useCallback } from "react";
import { useDocuments } from "@/hooks/useDocuments";
import { ScribbleInput } from "./ScribbleInput";
import { FileDropZone } from "./FileDropZone";
import { DocumentCard } from "./DocumentCard";
import { DraftBar } from "./DraftBar";
import { StreamFooter } from "./StreamFooter";
import type { Document } from "@/lib/types";

export function StreamPage() {
  const { documents, isLoading, refresh } = useDocuments();
  const [editing, setEditing] = useState<Document | null>(null);
  const [draftSignal, setDraftSignal] = useState(0);

  const bumpDrafts = useCallback(() => {
    setDraftSignal((n) => n + 1);
  }, []);

  return (
    <div className="mx-auto max-w-2xl px-4 py-8">
      <ScribbleInput
        onSubmit={() => {
          setEditing(null);
          refresh();
          bumpDrafts();
        }}
        onDraft={bumpDrafts}
        editingDocument={editing}
        onCancelEdit={() => setEditing(null)}
      />
      <FileDropZone onUpload={refresh} />

      <DraftBar onEdit={setEditing} refreshSignal={draftSignal} />

      <section>
        {documents.map((doc, i) => (
          <DocumentCard
            key={doc.id}
            document={doc}
            engrams={doc.engrams}
            onEdit={setEditing}
            style={{ animationDelay: `${i * 50}ms` }}
          />
        ))}

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

      {!isLoading && documents.length > 0 && (
        <StreamFooter visibleCount={documents.length} />
      )}
    </div>
  );
}
