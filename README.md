<p align="center">
  <img src="./frontend/public/hypomnema.png" alt="Hypomnema logo" width="180">
</p>

# Hypomnema

Hypomnema is a research notebook that organizes itself.

You drop in quick thoughts, PDFs, DOCX files, or Markdown notes. The app stores the raw text, extracts the main concepts, links related ideas together, and lets you move through your material as a living network instead of a folder tree.

## What It Is For

Hypomnema is built for people doing serious reading, writing, and synthesis:

- capturing fleeting ideas without stopping to tag or file them
- pulling concepts out of notes and documents automatically
- showing which ideas connect, support, contradict, or extend each other
- helping you spot clusters, bridges, and missing links in your research

It is not meant to be a manual PKM system where you spend time maintaining folders, backlinks, and taxonomy by hand.

## How It Feels To Use

The app is centered around a few simple views:

- `Stream`: your chronological inbox for scribbles and uploaded files
- `Document view`: the full text of one note or file, plus the concepts extracted from it
- `Engram view`: a concept page showing connected documents and related concepts
- `Search`: two modes, one for finding documents and one for exploring concept relationships
- `Visualization`: a 3D spatial map of your concept network — constellation-style nodes sized by PageRank, cinematic camera controls, cluster color reveal on focus
- `Settings`: where you choose or update the language model provider used for extraction

In practice, the workflow is:

1. Write a note or upload a file.
2. Let the app process it in the background.
3. Open the document to see which concepts were extracted.
4. Follow those concepts into other related material.
5. Use search and visualization when you want a wider view of the territory.

## What Hypomnema Does Behind The Scenes

When you add material, Hypomnema:

- saves the original text in a local SQLite database
- generates embeddings so related material can be found semantically
- creates concept nodes called "engrams"
- links those engrams with relationship types such as support, contradiction, critique, or extension
- builds projection data for the visualization view

The point is not just storage. The point is to turn a pile of notes into something you can think with.

## First-Run Setup

On first launch, Hypomnema asks you to choose:

- an embedding provider
- optionally, an LLM provider for concept extraction and edge generation

Important user-facing detail:

- the embedding choice is effectively permanent for that database, because changing embedding models would make old vectors incompatible
- the LLM provider can be changed later in Settings

API keys are stored locally and encrypted at rest.

## What You Can Add

Today, the app accepts:

- plain text scribbles
- `PDF` files
- `DOCX` files
- `Markdown` files

The backend also supports scheduled feed ingestion for always-on/server setups, but the current user interface is mainly focused on manual capture and exploration.

## Running Modes

Hypomnema can be used in three ways:

- `Local mode`: runs on your machine and opens in the browser
- `Server mode`: runs as an always-on private service for continuous ingestion and access from multiple devices
- `Desktop mode`: packaged desktop app with the same core workflow

All three modes use the same basic model: capture material, process it, then navigate it by concept.

## Quick Start

If you just want to use the app locally:

```bash
cd backend
uv sync
uv run hypomnema dev
```

Then open `http://localhost:3000`.

You will need:

- Python 3.12+
- Node.js 20+
- `uv`

The app will install frontend dependencies automatically if needed.

## Current Product Scope

What is already present in the app:

- first-run setup wizard
- chronological note/file stream
- file upload and text extraction
- background ontology processing
- document detail pages
- concept detail pages
- document search
- knowledge-graph search
- interactive visualization
- provider settings with runtime LLM switching

## Development Notes

This README is intentionally user-facing. For implementation details and developer workflow, see [DEVELOPMENT.md](./DEVELOPMENT.md).
