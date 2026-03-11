### App Specification: Automated Ontological Synthesizer

**1. Product Vision & Core Philosophy**

* **The Goal:** Facilitate "research thought building" and idea generation by automatically constructing a knowledge graph (KG) from zero-friction inputs. The system highlights structural "gaps" and novel connections without requiring secondary user effort for organization.
* **The Anti-Goal:** This is not a manual Personal Knowledge Management (PKM) tool, a file-folder system, or a copycat of Obsidian with a visual graph plugin.
* **Target User:** Researchers who need to externalize their cognitive load, treating the application as an active network of memory traces (engrams) rather than a static filing cabinet.

---

**2. Data Ingestion & Triage Pipeline**

The system accepts both high-signal manual inputs and high-volume automated feeds, unifying them into a single processing stream.

* **Manual Ingestion (High-Signal):**
* **"Scribbles":** Zero-friction text entry for fleeting thoughts, discussions, and observations. No tags or folders required.
* **File "Throws":** Drag-and-drop support for PDFs, DOCX, and MD files. The app parses the text and feeds it into the pipeline.


* **Periodic Archive (Variable-Signal):**
* Automated ingestion of papers, news, webpage scrapes, and YouTube transcripts via cronjobs.


* **The Triage Layer ("The Bouncer"):**
* To protect the pay-as-you-go API budget from low-value automated noise, periodic feeds pass through a lightweight filter before full processing.
* **Mechanism:** A fast, low-cost LLM call (or a cheap embedding similarity check against core research themes) evaluates the incoming text. If it lacks novel concepts or relevance, the payload is dropped or sent to cold storage, preventing graph bloat.

---

**3. The Ontology Engine (Processing & Extraction)**
This is the core engine where raw inputs are "tidied" into a semantic network. The raw content of any accepted input is stored cleanly in a central database (e.g., mapping the main body to a `text` column) before extraction begins.

* **Entity Resolution & Engram Generation:**
* **Extraction:** A highly capable LLM (e.g., via your Claude or Google API keys) processes the text to extract core entities and concepts.
* **Normalization:** The LLM normalizes the entity into a canonical string.
* **Deduplication & Storage:** The system generates an embedding of the concept and assigns it an "Engram" (a concept hash). This provides an $O(1)$ lookup mechanism, ensuring that "AI Ethics" and "Artificial Intelligence Morality" map to the exact same node instantly.


* **Contextual Linking (Edge Generation):**
* **Top-K Retrieval:** To avoid an $O(N^2)$ explosion of API calls, the system embeds the new note and performs a vector search to retrieve only the top $K$ most semantically related existing engrams.
* **Predicate Assignment:** A targeted LLM call evaluates the new note against the $K$ retrieved engrams to define the specific relational predicate (e.g., *contradicts*, *provides methodology for*, *is an example of*), creating a context-rich edge.

---

**4. Visualization & Discovery Interface**
The UI is designed specifically for pattern recognition and identifying research gaps, moving away from traditional node-and-link "hairballs."

* **Dimensionality Reduction:** The system applies algorithms like UMAP or t-SNE to project the high-dimensional embeddings into a navigable space.
* **Spatial Clustering:** Engrams and notes are clustered conceptually in a 2D or shallow 3D visual plane.
* **Gap Highlighting:** By mapping the density of the clusters, the UI visually surfaces the "voids"—the structural spaces where concepts border each other but lack connections—triggering the researcher's insight generation.
* **Contextual Retrieval:** Clicking any node instantly surfaces the attached raw `text` and the specific LLM-generated predicates explaining *why* it connects to its neighbors.

---

With this specification, the architectural foundation is solidified.

Would you like to draft the specific LLM prompts for the **Entity Normalization** step, or should we define the exact database schema (tables and relationships) for storing the Engrams and their edges?

### 5. User Interface & Retrieval (The Rhizomatic Frontend)

**Core Paradigm: The Flat Backend & Topological Navigation**
The application completely abandons traditional file-and-folder tree structures. Recognizing that research concepts do not exist in isolated silos, the system utilizes a flat database architecture where every input (scribble, PDF, automated feed) is saved simply as a record with a `text` column. The "structure" is entirely dynamic, generated on-the-fly by the relational edges connecting documents to Engrams.

**5.1. Dynamic Contextual Streams (The View Layer)**
Instead of forcing the user to navigate directories, the UI relies on dynamic aggregations based on time and conceptual gravity.

* **The Chronological Stream (Default State):** The primary landing view is a reverse-chronological feed of all manual and automated inputs. This provides immediate orientation and a zero-friction drop zone for new thoughts, without demanding categorization.
* **The Actor-Network Reading View:**  When a specific document or scribble is opened, there is no "file path" displayed. Instead, a dynamic side-panel visualizes the active network of actors—the specific Engrams extracted from that text.
* **Dynamic Clusters (Replacing Folders):** Clicking any Engram (e.g., "Algorithmic Bias") instantly aggregates and displays all documents, notes, and periodic feeds connected to that concept. The user navigates by pulling conceptual threads rather than opening nested folders.

**5.2. Dual-Layer Retrieval System**
Because the raw text is separated from the structural ontology, the search interface serves two distinct, specialized functions.

* **Doc Search (Artifact Retrieval):** * **Function:** Locating specific, tangible inputs.
* **Mechanism:** Standard semantic (vector) and lexical (keyword) search over the central `text` column.
* **Use Case:** Searching for a specific phrase, author, or remembered quote (e.g., "Latour's definition of translation") to pull up the exact PDF or scribble.


* **Knowledge Search (Structural Retrieval):**
* **Function:** Querying the graph to uncover structural intersections and research gaps.
* **Mechanism:** Searching for the *relational edges* between Engrams rather than the documents themselves.
* **Use Case:** Querying the intersection of two distinct Engrams. Instead of just returning documents that contain both terms, the system visualizes *how* the concepts interact, displaying bridging predicates or highlighting the empty structural void where a novel connection has yet to be made.

---

### 6. Architecture & Technology Stack (Bare-Metal & Dual-Mode)

**Core Paradigm: Zero-Container, Single Codebase**
The application achieves a "neat," highly performant architecture by abandoning heavy containerization (Docker) and complex database instances (PostgreSQL). It utilizes a single, decoupled codebase running natively on bare metal, allowing the user to seamlessly switch between an isolated desktop experience and an always-on server environment.

**6.1. The Backend Engine (Python / FastAPI)**
The backend acts as the heavy-duty orchestration layer.

* **Framework:** **FastAPI**. Provides the asynchronous foundation required to manage non-blocking periodic cronjobs (fetching RSS, scraping transcripts) alongside live UI requests.
* **AI & Extraction:** Python natively interfaces with the AI ecosystem, allowing the backend to efficiently parse complex documents (PDFs, DOCXs), orchestrate API calls to modern LLMs (e.g., Claude, Google) for predicate extraction, and run local embedding models natively on high-end GPUs to eliminate vectorization costs.

**6.2. The Database Layer (Portable SQLite)**
The system relies entirely on a single, portable `.db` file, stripping away all database administration overhead.

* **Engine:** **SQLite** configured with `PRAGMA journal_mode=WAL;` (Write-Ahead Logging). This crucial configuration allows concurrent operations—meaning the backend cronjobs can continuously write new automated feeds to the graph without locking the database or slowing down the user's frontend queries.
* **Vector Search:** Utilizes the **`sqlite-vec`** extension. This embeds high-speed vector similarity search directly into the SQLite file, handling the Top-K retrieval and engram mapping natively without requiring a dedicated vector database.
* **Portability:** Backing up the entire knowledge graph is as simple as syncing or copying a single file via `rsync`.

**6.3. The Frontend Client (Next.js PWA)**
The user interface is decoupled from the heavy processing engine.

* **Framework:** **Next.js**. Serves the dynamic topological UI, the chronological streams, and the dual-pane reading views as a Progressive Web App (PWA).
* **Thin Client:** The frontend performs no heavy compute. It merely acts as the interactive "glass," querying the FastAPI backend for data and rendering the graph, ensuring a frictionless experience on any device.

**6.4. Dual-Mode Deployment Strategy**
The application supports two distinct operational modes using simple startup scripts, allowing the user to choose how the app is served based on their current needs.

* **Mode A: Isolated Local Mode (`start-web.sh`)**
* **Use Case:** A private, zero-dependency "desktop" experience running directly on the user's primary machine.
* **Execution:** Binds strictly to `localhost`. The frontend opens automatically in the default web browser.
* **Limitation:** Background cronjobs for automated page archiving only execute while the script is actively running.

* **Mode B: Server-Backed Mode (`start-server.sh`)**
* **Use Case:** An "always-on" service for heavy continuous processing and multi-device access.
* **Execution:** Deployed natively on a dedicated machine (e.g., a headless Ubuntu workstation). The backend runs 24/7 as a background process, meaning cronjobs continuously ingest and ontologize periodic feeds.
* **Network Access:** The FastAPI backend binds to a secure mesh VPN interface (like Tailscale). The Next.js frontend can be accessed seamlessly from a smartphone or laptop browser via the server's internal Tailnet IP, keeping the data completely invisible to the public internet while remaining globally accessible to the user.

