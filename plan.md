
Project Requirements: Universal Gitea Workspace Search & Knowledge Intelligence Platform

1. Project Objective

Build a production-oriented, offline-first application that indexes, searches, navigates, and understands the contents of one or more Gitea repositories.

The repositories contain mixed content, including:

* Source code: Java, Python, JavaScript, TypeScript if present, CSS, HTML, SQL, JSP and shell scripts.
* Documents: PDF, DOC, DOCX, Markdown, TXT, RST and HTML.
* Spreadsheets: XLS, XLSX, CSV, TSV and ODS.
* Structured data: JSON, XML, YAML, TOML, INI and properties files.
* Operational content: logs, configuration files, deployment manifests and technical manuals.
* Other formats supported by future parser plugins.

The repository will continue to grow. The application must therefore support incremental indexing, efficient storage, bounded resource consumption and accurate source navigation.

The system must provide useful search functionality even when Ollama is stopped or the AI subsystem is disabled.

2. Existing Environment and Hard Constraints

Design for the following environment:

* Operating mode: offline-first, with no runtime dependency on public cloud services.
* Repository source: self-hosted Gitea.
* Backend: Python 3.12+ and FastAPI.
* Frontend: React with JavaScript ES2020+; use TypeScript only if explicitly approved.
* AI runtime: existing Ollama installation.
* Chat model: Qwen 2.5 9B GGUF, CPU inference, no GPU.
* Available system RAM: approximately 50 GB total.
* Hardware acceleration: assume unavailable.
* Deployment: containerized deployment where supported, with persistent local storage.
* External APIs: prohibited by default.
* Network: Gitea and Ollama may be accessible only on internal addresses.

Do not assume that all 50 GB of RAM is available to the application. The operating system, Ollama, the model, search engine, file parsers and other processes share this memory.

Before implementation, inspect the existing environment, installed versions, available storage, Ollama configuration and repository size. Do not replace working infrastructure without justification.

3. Core Architectural Principles
4. Exact search must work independently of AI.
5. Preserve the original location of every indexed text segment.
6. Index only changed content during normal operation.
7. Keep CPU, RAM, disk I/O and concurrent processing bounded.
8. Use asynchronous jobs for expensive operations.
9. Never send every file or the entire repository to the LLM.
10. Retrieve relevant evidence before generating an answer.
11. Every AI-generated factual answer must have verifiable source citations.
12. Never invent file paths, page numbers, line numbers or cell references.
13. Make indexing, AI processing, caching and queue settings configurable.
14. Recover gracefully from process restarts, interrupted jobs and corrupt files.
15. Preserve access controls from Gitea and prevent unauthorized content from appearing in search results or AI context.
16. Recommended Architecture

Implement the system as logically separated modules:

A. Repository Integration Service

* Connect to Gitea using configurable base URL and credentials or tokens.
* Support repository discovery and explicit repository configuration.
* Support push webhooks and scheduled polling.
* Track repository, branch, commit SHA and file status.
* Identify added, modified, renamed and deleted files.
* Handle webhook retries, duplicate deliveries and missed events.
* Support a manual full synchronization operation.
* Use the Gitea API or Git operations according to the selected synchronization strategy.

B. File Discovery and Processing Service

* Identify file types using extensions and content signatures where appropriate.
* Ignore Git internals, generated directories, dependency folders, binary artifacts and configured exclusions.
* Enforce configurable file-size and processing-time limits.
* Dispatch each file to the correct parser.
* Process large files in bounded batches.
* Preserve the source revision and file metadata.
* Record unsupported formats and extraction errors instead of silently skipping files.

C. Indexing Service

Maintain separate responsibilities for:

* Repository and file metadata.
* Extracted text and source coordinates.
* Full-text search.
* Optional semantic embeddings.
* Indexing jobs and failures.

Use SQLite FTS5 and a relational metadata database for a lightweight initial deployment, or use OpenSearch when repository size, concurrency and search requirements justify it. Benchmark before choosing a more resource-intensive engine.

Do not introduce multiple databases or distributed infrastructure without a concrete requirement.

D. Search API

Provide APIs for:

* Exact and full-text search.
* Phrase search.
* File-type and repository filters.
* Branch and commit filters.
* Search result previews.
* Source-location navigation.
* Optional semantic and hybrid search.
* AI-assisted question answering.
* Indexing status and administration.

E. AI Retrieval and Answer Service

* Integrate with the existing local Ollama endpoint.
* Use Qwen 2.5 9B for answer generation.
* Retrieve only the most relevant indexed evidence.
* Limit the context size and output length.
* Include source citations in the response.
* Cache eligible results.
* Enforce concurrency limits and queueing.
* Provide clear error messages if the model is unavailable or overloaded.

F. Frontend

Build a responsive React interface containing:

* Global search bar.
* Search mode selector.
* Repository, branch and file-type filters.
* Search results with highlighted matches.
* Source previews and navigation.
* AI question-and-answer interface.
* Indexing dashboard.
* Queue and error monitoring.
* Administrative configuration for resource limits.

5. Supported File Extraction and Source Coordinates

Implement parser adapters with a common interface.

Source code and text

Index text while preserving line numbers and surrounding context.

Support exact search for class names, function names, identifiers, SQL statements, configuration keys and phrases. Add language-aware parsing for definitions and references where practical.

PDF

Use PyMuPDF for text extraction.

Store:

* File path.
* Page number.
* Extracted text.
* Optional section and bounding-box metadata.

Detect scanned PDFs and support optional OCR through a local OCR engine.

Word documents

Support DOCX using python-docx and legacy DOC using an appropriate local extraction tool.

Preserve headings, paragraphs and tables. Return the best available section and paragraph reference. Do not claim that Word paragraphs have universally stable page numbers; pagination may change between viewers.

Excel and spreadsheets

Support XLSX, XLS, CSV, TSV and ODS.

For Excel, index workbook name, sheet name, cell address, cell value and relevant row context. Index formulas separately when possible. Handle cached formula results carefully because they may be missing or stale.

For CSV and TSV, preserve row numbers, headers and column names. Support quoted fields, different delimiters, encodings and large files.

Structured data and logs

Support line references and structured paths, such as JSON paths and configuration keys.

Common parser contract

Each parser should return normalized text chunks and metadata, including:

* Repository and revision.
* Relative file path.
* File type.
* Chunk identifier.
* Extracted text.
* Start and end coordinates appropriate to that format.
* Parser name and version.
* Extraction status and warnings.

The search engine must never have to infer the original location from the text after extraction.

6. Incremental Indexing and Data Consistency

Implement incremental indexing as a first-class requirement.

* Track content hashes for files.
* Skip reprocessing when the content and relevant parser configuration have not changed.
* Replace stale chunks atomically when a file changes.
* Remove all corresponding records when a file is deleted.
* Handle file renames without retaining obsolete paths.
* Track branch and commit identity to prevent results from being attributed to the wrong revision.
* Make job processing idempotent.
* Persist indexing state so a restart does not require a full reindex.
* Retry transient failures with bounded exponential backoff.
* Use a dead-letter or failed-job state for files that repeatedly fail.
* Support a full reindex operation when extraction logic or index schema changes.
* Report progress, throughput, pending files, failures and last successful synchronization.

For large repositories, avoid loading the entire repository or entire index into application memory.

7. CPU and Memory Management

The system must be designed for CPU-only AI inference and approximately 50 GB of total system RAM.

Resource budgets

* Measure actual baseline RAM usage before selecting limits.
* Configure separate memory and concurrency limits for the API, indexing workers, search engine and Ollama.
* Do not allocate all available memory to Ollama.
* Keep configurable safety headroom for the operating system and unexpected workloads.
* Monitor process RSS, available RAM, CPU utilization and queue depth.
* Pause or throttle background indexing when the system becomes resource-constrained.
* Never load large document collections entirely into memory.
* Avoid unbounded in-memory caches and result collections.

Implement a configurable resource policy. Initial conservative settings should be validated by load testing rather than treated as guaranteed optimal values.

Ollama-specific requirements

* Use the existing local model; do not download or replace models automatically.
* Check model availability and runtime health during startup and before AI requests.
* Default to one concurrent Qwen generation request.
* Make concurrency configurable after benchmarking.
* Use configurable request timeouts, generation limits and context limits.
* Set appropriate Ollama keep-alive and model-unloading behavior.
* Do not force the model to remain loaded indefinitely if memory pressure makes that undesirable.
* Do not repeatedly reload the model for every question.
* Avoid long-running AI requests blocking exact search or indexing APIs.
* Handle model overload, timeout, cancellation and connection failures gracefully.
* Provide an option to disable AI without disabling search.

The application must not assume that a 9B model has a fixed RAM footprint. Actual usage depends on GGUF quantization, context size, KV cache, runtime settings and other processes.

8. Queueing and Background Processing

Implement bounded, persistent job queues.

Use separate logical queues for:

1. Repository synchronization.
2. File extraction and indexing.
3. Optional embedding generation.
4. AI question answering.
5. OCR and other expensive processing.

Do not allow one expensive task category to starve the others.

Queue requirements

* Persist job state across application restarts.
* Support configurable worker counts and queue capacity.
* Use backpressure when queues approach capacity.
* Deduplicate jobs for the same file revision.
* Apply retry limits and exponential backoff.
* Support cancellation where safe.
* Prioritize interactive work appropriately.
* Track queued, running, completed, failed and retried jobs.
* Expose queue depth, wait time and processing duration.
* Never drop repository changes silently when the queue is full.
* Provide a reconciliation mechanism to discover missed updates.

For a single-host deployment, prefer a lightweight persistent job store and worker system. Add Redis, Celery or other infrastructure only when required by measured throughput or reliability needs.

AI requests should use a dedicated bounded queue and a configurable admission policy. When overloaded, return a clear busy or retry response rather than allowing unlimited requests to accumulate.

9. Caching Strategy

Implement caching at multiple layers with explicit size limits, expiration policies and invalidation rules.

A. Search result cache

Cache normalized queries and their filter parameters.

Cache keys must include all relevant dimensions, including repository, branch, revision, permissions scope and search configuration.

B. Parsed file cache

Cache extracted text or parser results keyed by content hash, parser version and extraction options.

Unchanged files should not need to be parsed again.

C. Embedding cache

Cache embedding vectors keyed by text hash, model identity, model version and embedding configuration.

Do not regenerate embeddings for unchanged text.

D. AI response cache

Cache suitable AI answers using a key derived from:

* Normalized user question.
* Retrieval parameters.
* Model identity and relevant generation settings.
* Retrieved evidence identifiers and versions.
* Permission scope.

Invalidate or bypass cached answers when their evidence becomes stale or the user’s permissions change.

E. Metadata and configuration cache

Cache frequently accessed repository and file metadata where useful.

Cache implementation rules

* Use an LRU or equivalent bounded eviction strategy for in-memory caches.
* Use TTLs where freshness is required.
* Persist expensive reusable artifacts only when the storage benefit justifies it.
* Make cache sizes and TTLs configurable.
* Record hit rate, miss rate, evictions and memory usage.
* Prevent cache stampedes for identical expensive requests.
* Provide safe invalidation after changes and reindexing.
* Never share private results across users with different access rights.

Caching must improve performance without allowing stale or unauthorized information to be returned.

10. AI Search and Embedding Strategy

Implement semantic search as an optional layer over full-text search.

Embeddings

* Do not use Qwen 2.5 9B as an embedding model unless the selected model explicitly supports embeddings.
* Use a separate, small, locally available embedding model compatible with the environment.
* Evaluate models such as all-MiniLM-L6-v2 or another suitable local embedding model.
* Do not download models at runtime.
* Make embedding model selection configurable.
* Benchmark CPU throughput and RAM use before choosing the default.
* Generate embeddings only for eligible text chunks.
* Skip unchanged chunks when their content hash and embedding configuration match.
* Queue embedding work separately from AI generation.
* Support disabling semantic search while preserving full-text search.

Hybrid retrieval

Combine lexical search and semantic retrieval, using a measurable ranking strategy such as reciprocal rank fusion or another evaluated method.

* Retrieve relevant chunks.
* Deduplicate overlapping chunks.
* Apply repository, branch, version and permission filters.
* Rank evidence using relevance and source quality.
* Pass only the best evidence to Qwen.
* Keep source references attached to every chunk throughout retrieval.

Do not embed binary files or arbitrary raw file contents without an appropriate parser.

11. AI Question Answering Requirements

The user should be able to ask questions such as:

* Where is the authentication header validated?
* Which files configure the DB2 connection timeout?
* Which Java methods call a particular service?
* Which PDF describes a deployment procedure?
* Which spreadsheet contains a specified table or identifier?
* How does the application handle logout?
* What is the difference between two configuration files?

For each answer:

* Cite the source file and relevant line, page, section or cell.
* Distinguish verified evidence from inference.
* Link citations to the source viewer.
* State when evidence is insufficient.
* Avoid claiming to have inspected content that was not retrieved.
* Never invent a source location.
* Respect context and output limits.
* Keep answers concise by default.
* Support cancellation and clear failure messages.

Treat repository content as untrusted input. Documents may contain prompt-injection instructions. The LLM must not follow instructions embedded in retrieved content that attempt to override system rules, reveal secrets or initiate tool actions.

AI must remain read-only by default. It must not modify source files, execute repository code or run shell commands based on retrieved instructions.

12. Source Viewer and Search Interface

Provide a unified result card containing:

* File name and relative path.
* Repository, branch and revision.
* File type.
* Matching excerpt with highlighted terms.
* Exact source coordinates.
* Relevance score or ranking explanation where appropriate.
* File modification and indexing status where available.

Viewer behavior:

* Source code: open at the matching line range.
* PDF: open at the matching page.
* Excel: display the workbook, sheet, cell and surrounding row/column context.
* CSV: show the matching row with headers.
* Word: show the matching section and paragraph/table context.
* Structured text: highlight the matching line or key path.

Provide filters, sorting, pagination, keyboard navigation and useful empty states. Preserve search context when the user returns from a result.

13. Security and Offline Operation

* Do not send repository content to external AI providers.
* Do not use external CDNs or remote fonts at runtime.
* Bundle or locally host required frontend assets.
* Store credentials in environment configuration or an appropriate secrets mechanism, not in source code.
* Use least-privilege Gitea tokens.
* Never log credentials, access tokens or sensitive document contents unnecessarily.
* Validate repository paths to prevent path traversal.
* Restrict access to indexing and administration endpoints.
* Enforce repository permissions for results, previews, embeddings and AI answers.
* Keep audit records for administrative operations.
* Protect API endpoints with appropriate authentication.
* Provide configurable retention and deletion policies.

The application must start and operate without internet access after its dependencies, frontend assets, parser packages and required local models have been provisioned.

14. Observability and Administration

Create an administrative dashboard showing:

* Number of repositories and files.
* Indexed, pending, skipped and failed files.
* Last synchronization time and indexed commit.
* Queue depth and job latency.
* Average parsing and indexing duration.
* Search latency and cache hit rate.
* Ollama availability and AI queue status.
* CPU, RAM and disk consumption.
* Embedding backlog.
* Parser errors and retry counts.

Provide controls for:

* Triggering repository synchronization.
* Pausing and resuming background indexing.
* Retrying failed files.
* Rebuilding selected indexes.
* Running a full reindex.
* Adjusting resource limits.
* Enabling or disabling AI and semantic search.
* Viewing logs and exporting diagnostics.

Do not expose secrets or sensitive file contents in administrative diagnostics.

15. Testing Requirements

Implement automated unit, integration and load tests.

Include:

* Every supported file type.
* Empty and malformed files.
* Scanned and text-based PDFs.
* Legacy DOC and XLS files.
* Large CSV and Excel workbooks.
* Duplicate content and identical files at different paths.
* File modification, rename and deletion.
* Duplicate webhooks and interrupted jobs.
* Application restart during indexing.
* Stale cache invalidation.
* Permission changes and private repositories.
* Ollama offline, busy, timed out or unavailable.
* Prompt injection inside indexed documents.
* Concurrent searches and AI requests.
* Memory pressure and queue saturation.

Verify that returned line, page, section, row and cell locations correspond to the original files.

Measure exact-search latency separately from AI latency.

16. Acceptance Criteria

The implementation is complete only when the following are demonstrated:

1. A user can search across all supported file categories through one interface.
2. Search results provide correct source coordinates and useful matching excerpts.
3. A changed file is reindexed without requiring a complete repository reindex.
4. Deleted and renamed files do not leave stale search results.
5. Duplicate synchronization events do not create duplicate index records.
6. Exact search remains available when Ollama is unavailable.
7. Semantic search and AI answers can be disabled independently.
8. AI answers cite actual retrieved evidence and never fabricate locations.
9. Background jobs survive application restarts and failed jobs can be retried.
10. Cache invalidation prevents stale results from being returned.
11. Queue limits prevent unlimited accumulation of expensive jobs.
12. Resource usage stays within configured limits during representative load tests.
13. The system operates without public internet access after provisioning.
14. Unauthorized repository content cannot be discovered through search or AI.
15. The administrative dashboard reports meaningful indexing, queue and resource metrics.

Do not claim production readiness until these criteria have been tested and documented.

17. Required Implementation Deliverables

Produce the following artifacts and working implementation:

1. High-level architecture and component diagram.
2. Detailed design for repository synchronization, extraction, indexing, caching, queues and AI retrieval.
3. Database schema and index mappings.
4. API specification with request and response examples.
5. Repository structure and module responsibilities.
6. Configurable environment file with documented defaults.
7. Docker Compose or the selected deployment configuration.
8. Offline dependency and model provisioning instructions.
9. Automated tests and a reproducible benchmark suite.
10. Setup, deployment, backup, recovery and troubleshooting documentation.
11. Resource profiling results for the actual CPU-only Qwen 2.5 9B configuration.
12. A list of implemented features, known limitations and deferred features.
13. Instructions to the Coding Agent

Before writing implementation code:

1. Inspect the existing repository and runtime environment.
2. Produce an implementation plan with milestones and dependency decisions.
3. Identify missing requirements and state assumptions explicitly.
4. Define resource budgets and queue/cache configuration.
5. Design source-coordinate preservation and incremental indexing first.
6. Separate the deterministic search engine from optional AI capabilities.
7. Implement in small, testable phases.
8. Run tests and benchmarks after each major phase.
9. Avoid unnecessary dependencies, microservices and premature distributed architecture.
10. Do not replace the existing Ollama model or download additional artifacts without approval.
11. Do not leave placeholder methods or mock behavior in features claimed as complete.
12. Document every limitation honestly.

Prioritize correctness, resource efficiency, explainability, maintainability and reliable offline operation over adding AI features for their own sake.

The first milestone must deliver useful full-text search and precise source navigation. AI-assisted search is the next layer, not a prerequisite for the application to function.
