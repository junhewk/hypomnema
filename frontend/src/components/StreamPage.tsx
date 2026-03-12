"use client";

import Link from "next/link";
import { useDocuments } from "@/hooks/useDocuments";
import { ScribbleInput } from "./ScribbleInput";
import { FileDropZone } from "./FileDropZone";
import { DocumentCard } from "./DocumentCard";

export function StreamPage() {
  const { documents, isLoading, hasMore, loadMore, refresh } = useDocuments();

  return (
    <div className="mx-auto max-w-2xl px-4 py-12 sm:py-16">
      <header className="mb-10">
        <h1 className="font-mono text-lg font-bold tracking-[0.2em] uppercase">
          hypomnema
        </h1>
        <div className="mt-1 flex items-center gap-4">
          <p className="font-mono text-xs text-muted tracking-wide">
            notes &rarr; knowledge graph
          </p>
          <Link
            href="/search"
            className="rounded-full border border-border px-3 py-0.5 font-mono text-[10px] text-muted no-underline transition-colors hover:border-border-focus hover:text-foreground"
            data-testid="search-link"
          >
            search →
          </Link>
          <Link
            href="/viz"
            className="rounded-full border border-border px-3 py-0.5 font-mono text-[10px] text-muted no-underline transition-colors hover:border-border-focus hover:text-foreground"
            data-testid="viz-link"
          >
            viz →
          </Link>
          <Link
            href="/settings"
            className="rounded-full border border-border px-3 py-0.5 font-mono text-[10px] text-muted no-underline transition-colors hover:border-border-focus hover:text-foreground"
            data-testid="settings-link"
          >
            settings →
          </Link>
        </div>
      </header>

      <ScribbleInput onSubmit={refresh} />
      <FileDropZone onUpload={refresh} />

      <section>
        {documents.map((doc, i) => (
          <DocumentCard
            key={doc.id}
            document={doc}
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
