import asyncio
import json
import logging
from pathlib import Path
from typing import Annotated

import typer

from opsintel.config import get_settings
from opsintel.db import connect, migrate

app = typer.Typer(no_args_is_help=True, add_completion=False, help="OpsIntel command-line interface")


def _conn():
    conn = connect(get_settings())
    migrate(conn)
    return conn


@app.command()
def serve(
    host: Annotated[str | None, typer.Option()] = None,
    port: Annotated[int | None, typer.Option()] = None,
    reload: Annotated[bool, typer.Option(help="Auto-reload on code changes (development)")] = False,
) -> None:
    """Run the API server with Uvicorn."""
    import uvicorn

    s = get_settings()
    bind_host = host or s.api_host
    if bind_host.lower() not in {"127.0.0.1", "localhost", "::1"}:
        typer.echo("OpsIntel has no authentication yet; bind to a loopback address until M5 is complete.", err=True)
        raise typer.Exit(2)
    uvicorn.run(
        "opsintel.main:app", host=bind_host, port=port or s.api_port, reload=reload,
        loop="asyncio", workers=1,
    )


@app.command("migrate")
def migrate_cmd() -> None:
    """Create or upgrade the database schema."""
    conn = connect(get_settings())
    applied = migrate(conn)
    typer.echo(f"applied migrations: {applied}" if applied else "database is up to date")


@app.command()
def doctor() -> None:
    """Check the runtime environment."""
    from opsintel.doctor import run_checks

    checks = run_checks(get_settings())
    width = max(len(c.name) for c in checks)
    for c in checks:
        color = {"OK": typer.colors.GREEN, "WARN": typer.colors.YELLOW, "FAIL": typer.colors.RED}[c.level]
        typer.echo(f"{typer.style(c.level.ljust(4), fg=color)}  {c.name.ljust(width)}  {c.detail}")
    if any(c.level == "FAIL" for c in checks):
        raise typer.Exit(1)


@app.command("index-path")
def index_path(
    path: Annotated[Path, typer.Argument(exists=True, file_okay=False, resolve_path=True)],
    name: Annotated[str | None, typer.Option(help="Repository name (defaults to folder name)")] = None,
) -> None:
    """Register a local folder as a repository and index it incrementally."""
    from opsintel.indexing import LocalIndexer, register_local_repo

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    conn = _conn()
    repo_id = register_local_repo(conn, name or path.name, path)
    stats = LocalIndexer(conn, get_settings()).index_repo(repo_id)
    typer.echo(json.dumps(stats.__dict__, indent=2))


@app.command()
def sync(
    name: str,
    branch: Annotated[str | None, typer.Option(help="Only this branch (Gitea repos)")] = None,
    now: Annotated[bool, typer.Option("--now", help="Run in this process instead of queueing for the worker")] = False,
) -> None:
    """Synchronise and index a registered repository (Gitea or local folder)."""
    from opsintel.indexing import LocalIndexer, get_repo
    from opsintel.sync import GiteaSyncer, tracked_branches
    from opsintel.tasks import enqueue_repo_sync

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    conn, s = _conn(), get_settings()
    repo = get_repo(conn, name)
    if not now:
        for job_id, created in enqueue_repo_sync(conn, s, repo, branch=branch):
            typer.echo(f"job {job_id} {'queued' if created else 'already queued'}")
        return
    if repo["kind"] == "local":
        typer.echo(json.dumps(LocalIndexer(conn, s).index_repo(repo["id"]).__dict__, indent=2))
        return
    for b in [branch] if branch else tracked_branches(conn, repo["id"]):
        stats = GiteaSyncer(conn, s).sync(repo["id"], b)
        typer.echo(f"{name}@{b}: {json.dumps(stats.__dict__)}")


@app.command()
def repos() -> None:
    """List registered repositories and tracked branches."""
    conn = _conn()
    for r in conn.execute("SELECT id, name, kind, is_private, last_indexed_at, location FROM repositories "
                          "ORDER BY name").fetchall():
        private = " private" if r["is_private"] else ""
        typer.echo(f"{r['id']:>4}  {r['name']:<30} {r['kind']}{private:<9} {r['last_indexed_at'] or '-':<20} "
                   f"{r['location']}")
        for b in conn.execute("SELECT * FROM repo_branches WHERE repo_id = ? ORDER BY branch", (r["id"],)):
            sha = (b["indexed_sha"] or "-")[:10]
            err = f"  ERROR: {b['last_error']}" if b["last_error"] else ""
            typer.echo(f"        @{b['branch']:<20} indexed {sha}  at {b['indexed_at'] or '-'}{err}")


@app.command("repo-remove")
def repo_remove(
    name: str,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation")] = False,
) -> None:
    """Remove a repository from OpsIntel (index, branches, queued jobs, mirror). Gitea is not modified."""
    from opsintel.indexing import get_repo
    from opsintel.sync import remove_repository

    conn = _conn()
    repo = get_repo(conn, name)
    if not yes:
        typer.confirm(f"Remove '{repo['name']}' ({repo['kind']}) and all its indexed data?", abort=True)
    typer.echo(json.dumps(remove_repository(conn, get_settings(), repo["id"])))


gitea_app = typer.Typer(no_args_is_help=True, help="Gitea repository registration")
app.add_typer(gitea_app, name="gitea")


@gitea_app.command("list")
def gitea_list() -> None:
    """List repositories visible to GITEA_TOKEN."""
    from opsintel.gitea import GiteaClient

    with GiteaClient(get_settings()) as g:
        for r in g.list_repos():
            flags = ",".join(f for f, on in (("private", r.private), ("empty", r.empty), ("archived", r.archived))
                             if on)
            typer.echo(f"{r.id:>5}  {r.full_name:<40} {r.default_branch:<12} {flags}")


@gitea_app.command("add")
def gitea_add(
    full_names: Annotated[list[str], typer.Argument(help="owner/name, one or more")],
    branch: Annotated[list[str] | None, typer.Option(help="Extra branch to track (repeatable)")] = None,
) -> None:
    """Register Gitea repositories (default branch is tracked automatically)."""
    from opsintel.gitea import GiteaClient
    from opsintel.sync import register_gitea_repo, track_branch

    conn = _conn()
    with GiteaClient(get_settings()) as g:
        for full_name in full_names:
            repo = g.get_repo(full_name)
            repo_id = register_gitea_repo(conn, repo)
            for b in branch or []:
                track_branch(conn, repo_id, b)
            typer.echo(f"registered {repo.full_name} (id {repo_id}, default branch {repo.default_branch or '-'})")


@gitea_app.command("add-all")
def gitea_add_all(include_archived: bool = False) -> None:
    """Register every repository visible to GITEA_TOKEN."""
    from opsintel.gitea import GiteaClient
    from opsintel.sync import register_gitea_repo

    conn = _conn()
    with GiteaClient(get_settings()) as g:
        for repo in g.list_repos():
            if repo.archived and not include_archived:
                continue
            typer.echo(f"registered {repo.full_name} (id {register_gitea_repo(conn, repo)})")


@gitea_app.command("webhook")
def gitea_webhook(
    full_name: str,
    url: Annotated[str | None, typer.Option(help="Public URL of /api/webhooks/gitea as seen from Gitea")] = None,
) -> None:
    """Create a push webhook in Gitea pointing at this OpsIntel instance."""
    from opsintel.gitea import GiteaClient

    s = get_settings()
    secret = s.gitea_webhook_secret.get_secret_value()
    if not secret:
        typer.echo("GITEA_WEBHOOK_SECRET must be set in .env first", err=True)
        raise typer.Exit(1)
    target = url or f"http://{s.api_host}:{s.api_port}/api/webhooks/gitea"
    with GiteaClient(s) as g:
        hook_id, created = g.ensure_push_hook(full_name, target, secret)
    typer.echo(f"webhook {hook_id} {'created' if created else 'already exists'} -> {target}")


@app.command()
def worker() -> None:
    """Run the background worker (sync/index jobs, scheduled polling, resource throttling)."""
    from opsintel.worker import Worker

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    w = Worker(get_settings())
    w.install_signal_handlers()
    try:
        w.run_forever()
    finally:
        w.close()


jobs_app = typer.Typer(no_args_is_help=True, help="Background job queue")
app.add_typer(jobs_app, name="jobs")


@jobs_app.command("status")
def jobs_status(limit: int = 15) -> None:
    """Queue depth per state and the most recent jobs."""
    from opsintel import jobs
    from opsintel.tasks import indexing_paused

    conn = _conn()
    typer.echo(json.dumps({"paused": indexing_paused(conn), **jobs.stats(conn)}, indent=2))
    for j in jobs.recent(conn, limit):
        err = f"  {j['last_error'][:80]}" if j["last_error"] else ""
        typer.echo(f"{j['id']:>6}  {j['status']:<9} {j['dedupe_key']:<40} attempts {j['attempts']}/"
                   f"{j['max_attempts']}{err}")


@jobs_app.command("retry")
def jobs_retry(job_id: Annotated[int | None, typer.Argument()] = None) -> None:
    """Requeue dead (failed) jobs; all of them unless JOB_ID is given."""
    from opsintel import jobs

    typer.echo(f"requeued {jobs.retry(_conn(), job_id)} job(s)")


@jobs_app.command("pause")
def jobs_pause() -> None:
    """Pause background indexing (running job pauses at the next file)."""
    from opsintel.tasks import set_setting

    set_setting(_conn(), "indexing_paused", "1")
    typer.echo("indexing paused")


@jobs_app.command("resume")
def jobs_resume() -> None:
    """Resume background indexing."""
    from opsintel.tasks import set_setting

    set_setting(_conn(), "indexing_paused", "0")
    typer.echo("indexing resumed")


experimental_app = typer.Typer(no_args_is_help=True, help="Isolated experimental features")
app.add_typer(experimental_app, name="experimental")


def _shadow_path(settings, database: Path | None) -> Path:
    return (database or settings.metadata_search_path).expanduser()


@experimental_app.command("metadata-index")
def metadata_index(
    repo: Annotated[str | None, typer.Option(help="Limit refresh to this registered repository name")] = None,
    database: Annotated[Path | None, typer.Option(help="Shadow database path (separate from opsintel.db)")] = None,
) -> None:
    """Refresh the isolated metadata-aware search index without modifying live search data."""
    from opsintel.experiments.metadata_search import MetadataShadowIndex

    settings = get_settings()
    conn = connect(settings)
    try:
        repo_id = None
        if repo:
            row = conn.execute("SELECT id FROM repositories WHERE name = ? AND enabled = 1", (repo,)).fetchone()
            if row is None:
                raise typer.BadParameter(f"unknown enabled repository '{repo}'")
            repo_id = row["id"]
        shadow = MetadataShadowIndex(_shadow_path(settings, database))
        try:
            typer.echo(json.dumps(shadow.refresh(conn, repo_id), indent=2))
        finally:
            shadow.close()
    finally:
        conn.close()


@experimental_app.command("metadata-search")
def metadata_search(
    query: str,
    repo: Annotated[str | None, typer.Option(help="Limit search to this registered repository name")] = None,
    mode: Annotated[str, typer.Option(help="fulltext, phrase or exact")] = "fulltext",
    limit: Annotated[int, typer.Option(min=1, max=100)] = 20,
    database: Annotated[Path | None, typer.Option(help="Shadow database path (separate from opsintel.db)")] = None,
) -> None:
    """Search the experimental metadata-aware shadow index; production search is unchanged."""
    from opsintel.experiments.metadata_search import MetadataShadowIndex

    settings = get_settings()
    conn = connect(settings)
    try:
        repo_id = None
        if repo:
            row = conn.execute("SELECT id FROM repositories WHERE name = ? AND enabled = 1", (repo,)).fetchone()
            if row is None:
                raise typer.BadParameter(f"unknown enabled repository '{repo}'")
            repo_id = row["id"]
        shadow = MetadataShadowIndex(_shadow_path(settings, database))
        try:
            result = shadow.search(query, mode=mode, repo_id=repo_id, limit=limit)
        finally:
            shadow.close()
    finally:
        conn.close()
    typer.echo(f"{result['total']} shadow-index matches (experimental; live search is unchanged)")
    for hit in result["results"]:
        location = ", ".join(f"{key}={value}" for key, value in hit["location"].items()
                              if key != "kind" and value is not None)
        typer.echo(typer.style(f"{hit['repo']}:{hit['path']} [{location}]", fg=typer.colors.CYAN))
        for line in hit["preview"]:
            typer.echo(f"  {line['label']:>8}  {line['text']}")


@experimental_app.command("embedding-index")
def embedding_index(
    repo: Annotated[str | None, typer.Option(help="Limit indexing to this registered repository name")] = None,
    batch_size: Annotated[int, typer.Option(min=1, max=256)] = 32,
) -> None:
    """Populate the opt-in Ollama embedding cache without changing lexical search."""
    from opsintel.embeddings import index_embeddings

    settings = get_settings()
    if not settings.semantic_search_enabled:
        raise typer.BadParameter("set SEMANTIC_SEARCH_ENABLED=true to build the embedding cache")
    if not settings.ollama_embed_model:
        raise typer.BadParameter("set OLLAMA_EMBED_MODEL to an installed embedding model")
    conn = _conn()
    try:
        repo_ids = None
        if repo:
            row = conn.execute("SELECT id FROM repositories WHERE name = ? AND enabled = 1", (repo,)).fetchone()
            if row is None:
                raise typer.BadParameter(f"unknown enabled repository '{repo}'")
            repo_ids = [row["id"]]
        result = asyncio.run(index_embeddings(
            conn, settings.ollama_base_url, settings.ollama_embed_model, repo_ids, batch_size, settings.ai_timeout_s,
        ))
        typer.echo(json.dumps(result, indent=2))
    finally:
        conn.close()


@experimental_app.command("eval-search")
def eval_search(
    queries: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="JSON query set with expected files")],
    model: Annotated[str | None, typer.Option(help="Embedding model (defaults to OLLAMA_EMBED_MODEL)")] = None,
    show_misses: Annotated[bool, typer.Option(help="List queries whose expected file is not in the top 5")] = False,
) -> None:
    """Compare full-text, keyword-fusion, semantic and hybrid rankings (MRR@10, hit@1, hit@5)."""
    from opsintel.evaluation import evaluate, load_queries

    settings = get_settings().model_copy(update={
        "semantic_search_enabled": True,
        "ollama_embed_model": model or get_settings().ollama_embed_model,
    })
    if not settings.ollama_embed_model:
        raise typer.BadParameter("pass --model or set OLLAMA_EMBED_MODEL")
    repo_name, items = load_queries(queries)
    conn = _conn()
    try:
        row = conn.execute("SELECT id FROM repositories WHERE name = ? AND enabled = 1", (repo_name,)).fetchone()
        if row is None:
            raise typer.BadParameter(f"unknown enabled repository '{repo_name}'")
        groups = {"all": items}
        for kind in dict.fromkeys(item.get("kind", "natural") for item in items):
            groups[kind] = [item for item in items if item.get("kind", "natural") == kind]
        summaries = {label: evaluate(conn, settings, subset, [row["id"]]) for label, subset in groups.items()}
    finally:
        conn.close()
    typer.echo(f"{len(items)} queries on {repo_name}, embedding model {settings.ollama_embed_model}")
    for label, summary in summaries.items():
        typer.echo(f"\n[{label}: {summary['hybrid']['queries']} queries]")
        typer.echo(f"{'mode':<10} {'MRR@10':>7} {'hit@1':>7} {'hit@5':>7} {'no results':>11}")
        for name, row_summary in summary.items():
            typer.echo(f"{name:<10} {row_summary['mrr']:>7} {row_summary['hit@1']:>7} {row_summary['hit@5']:>7} "
                       f"{row_summary['no_results']:>11}")
    if show_misses:
        for name in ("hybrid", "fulltext"):
            typer.echo(f"\n{name} misses:")
            for miss in summaries["all"][name]["misses"]:
                typer.echo(f"  rank={miss['rank']}  {miss['q']}  -> {miss['top']}")


@app.command("search")
def search_cmd(
    q: str,
    mode: Annotated[str, typer.Option()] = "fulltext",
    limit: Annotated[int, typer.Option()] = 10,
) -> None:
    """Search from the terminal."""
    from opsintel.search import SearchRequest, search

    res = search(_conn(), SearchRequest(q=q, mode=mode, page_size=limit))  # type: ignore[arg-type]
    typer.echo(f"{res['total']}{'+' if res['total_is_lower_bound'] else ''} matching chunks")
    for r in res["results"]:
        loc = r["location"]
        where = ", ".join(f"{k}={v}" for k, v in loc.items() if k not in ("kind", "start_line", "end_line") and v)
        typer.echo(typer.style(f"{r['repo']['name']}:{r['path']} [{where}]", fg=typer.colors.CYAN))
        for p in r["preview"]:
            typer.echo(f"  {p['label']:>8}  {p['text']}")


if __name__ == "__main__":
    app()
