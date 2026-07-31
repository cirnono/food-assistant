from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import DATA_DIR, get_db
from app.models import RecipeSource, SourceRecipe


router = APIRouter(
    prefix="/api/v1/sources",
    tags=["recipe-sources"],
)

SOURCES_DIR = DATA_DIR / "sources"


class GitSourceError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class GitHubSourceCreate(StrictModel):
    url: str = Field(
        min_length=10,
        max_length=2000,
    )

    name: str | None = Field(
        default=None,
        max_length=160,
    )

    branch: str | None = Field(
        default=None,
        max_length=255,
    )

    include_path: str = Field(
        default="dishes",
        min_length=1,
        max_length=1000,
    )

    sync_interval_minutes: int | None = Field(
        default=None,
        ge=5,
        le=10080,
    )


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_github_url(
    raw_url: str,
    requested_branch: str | None,
    requested_path: str,
) -> tuple[str, str, str | None, str]:
    """
    Accept:

    https://github.com/owner/repository
    https://github.com/owner/repository.git
    https://github.com/owner/repository/tree/master/dishes
    """
    parsed = urlparse(raw_url.strip())

    if parsed.scheme != "https":
        raise GitSourceError(
            "Only HTTPS GitHub URLs are allowed"
        )

    if parsed.hostname not in {
        "github.com",
        "www.github.com",
    }:
        raise GitSourceError(
            "Only github.com repositories are allowed"
        )

    parts = [
        unquote(part)
        for part in parsed.path.strip("/").split("/")
        if part
    ]

    if len(parts) < 2:
        raise GitSourceError(
            "GitHub URL must contain owner and repository"
        )

    owner = parts[0]
    repository = parts[1]

    if repository.endswith(".git"):
        repository = repository[:-4]

    safe_component = re.compile(
        r"^[A-Za-z0-9_.-]+$"
    )

    if not safe_component.fullmatch(owner):
        raise GitSourceError(
            "Invalid GitHub owner"
        )

    if not safe_component.fullmatch(repository):
        raise GitSourceError(
            "Invalid GitHub repository name"
        )

    branch = requested_branch
    include_path = requested_path

    if len(parts) >= 4 and parts[2] == "tree":
        if branch is None:
            branch = parts[3]

        if len(parts) >= 5 and requested_path == "dishes":
            include_path = "/".join(parts[4:])

    if branch is not None:
        if (
            branch.startswith("/")
            or ".." in branch
            or not re.fullmatch(
                r"[A-Za-z0-9._/-]+",
                branch,
            )
        ):
            raise GitSourceError(
                "Invalid Git branch name"
            )

    pure_path = PurePosixPath(include_path)

    if (
        pure_path.is_absolute()
        or ".." in pure_path.parts
        or include_path.strip() in {"", "."}
    ):
        raise GitSourceError(
            "Invalid include_path"
        )

    repo_url = (
        f"https://github.com/{owner}/{repository}.git"
    )

    default_name = repository

    return (
        repo_url,
        default_name,
        branch,
        pure_path.as_posix(),
    )


def run_git(
    arguments: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 180,
) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitSourceError(
            "Git operation timed out"
        ) from exc
    except OSError as exc:
        raise GitSourceError(
            "Git executable is unavailable"
        ) from exc

    if result.returncode != 0:
        detail = (
            result.stderr.strip()
            or result.stdout.strip()
            or f"exit code {result.returncode}"
        )

        raise GitSourceError(
            detail[:1500]
        )

    return result.stdout.strip()


def source_repo_dir(
    source_id: int,
) -> Path:
    return SOURCES_DIR / str(source_id) / "repo"


def extract_title(
    content: str,
    fallback: str,
) -> str:
    match = re.search(
        r"(?m)^\s*#\s+(.+?)\s*$",
        content,
    )

    if match:
        title = match.group(1).strip()

        title = re.sub(
            r"\s*的做法\s*$",
            "",
            title,
        ).strip()

        if title:
            return title[:300]

    return fallback[:300]


def synchronize_source(
    db: Session,
    source: RecipeSource,
) -> dict:
    repo_dir = source_repo_dir(source.id)
    repo_parent = repo_dir.parent

    repo_parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        if not (repo_dir / ".git").exists():
            if repo_dir.exists():
                shutil.rmtree(repo_dir)

            clone_arguments = [
                "clone",
                "--depth",
                "1",
                "--single-branch",
            ]

            if source.branch:
                clone_arguments.extend(
                    ["--branch", source.branch]
                )

            clone_arguments.extend(
                [
                    source.repo_url,
                    str(repo_dir),
                ]
            )

            run_git(
                clone_arguments,
                timeout=300,
            )
        else:
            branch = source.branch

            if not branch:
                branch = run_git(
                    [
                        "rev-parse",
                        "--abbrev-ref",
                        "HEAD",
                    ],
                    cwd=repo_dir,
                )

                source.branch = branch

            run_git(
                [
                    "fetch",
                    "--depth",
                    "1",
                    "origin",
                    branch,
                ],
                cwd=repo_dir,
                timeout=300,
            )

            run_git(
                [
                    "reset",
                    "--hard",
                    "FETCH_HEAD",
                ],
                cwd=repo_dir,
            )

        if not source.branch:
            source.branch = run_git(
                [
                    "rev-parse",
                    "--abbrev-ref",
                    "HEAD",
                ],
                cwd=repo_dir,
            )

        commit = run_git(
            ["rev-parse", "HEAD"],
            cwd=repo_dir,
        )

        root_resolved = repo_dir.resolve()
        scan_root = (
            repo_dir / source.include_path
        ).resolve()

        if (
            scan_root != root_resolved
            and root_resolved
            not in scan_root.parents
        ):
            raise GitSourceError(
                "include_path escapes repository"
            )

        if not scan_root.is_dir():
            raise GitSourceError(
                "Directory not found in repository: "
                f"{source.include_path}"
            )

        existing_rows = db.scalars(
            select(SourceRecipe).where(
                SourceRecipe.source_id == source.id
            )
        ).all()

        existing = {
            row.path: row
            for row in existing_rows
        }

        seen_paths: set[str] = set()

        new_count = 0
        changed_count = 0
        unchanged_count = 0

        for markdown_path in sorted(
            scan_root.rglob("*.md")
        ):
            if not markdown_path.is_file():
                continue

            relative_repo_path = (
                markdown_path
                .relative_to(repo_dir)
                .as_posix()
            )

            relative_scan_path = (
                markdown_path
                .relative_to(scan_root)
            )

            content = markdown_path.read_text(
                encoding="utf-8",
                errors="replace",
            )

            digest = hashlib.sha256(
                content.encode("utf-8")
            ).hexdigest()

            title = extract_title(
                content,
                markdown_path.stem,
            )

            category = (
                relative_scan_path.parts[0]
                if len(relative_scan_path.parts) > 1
                else "未分类"
            )

            seen_paths.add(relative_repo_path)

            row = existing.get(
                relative_repo_path
            )

            if row is None:
                row = SourceRecipe(
                    source_id=source.id,
                    path=relative_repo_path,
                    title=title,
                    category=category,
                    search_text=content,
                    content_sha256=digest,
                    source_commit=commit,
                    status="available",
                    active=True,
                )

                db.add(row)
                new_count += 1
                continue

            if row.content_sha256 != digest:
                changed_count += 1

                if row.status == "imported":
                    row.status = "source_updated"
            else:
                unchanged_count += 1

            row.title = title
            row.category = category
            row.search_text = content
            row.content_sha256 = digest
            row.source_commit = commit
            row.active = True

        removed_count = 0

        for path, row in existing.items():
            if path in seen_paths:
                continue

            if row.active:
                removed_count += 1

            row.active = False

        source.last_commit = commit
        source.last_synced_at = utc_now()
        source.last_error = None

        db.commit()

        total_active = db.scalar(
            select(func.count())
            .select_from(SourceRecipe)
            .where(
                SourceRecipe.source_id
                == source.id,
                SourceRecipe.active.is_(True),
            )
        ) or 0

        return {
            "source_id": source.id,
            "commit": commit,
            "branch": source.branch,
            "include_path": source.include_path,
            "total_active": total_active,
            "new": new_count,
            "changed": changed_count,
            "unchanged": unchanged_count,
            "removed": removed_count,
        }

    except Exception as exc:
        db.rollback()

        source.last_error = str(exc)[:2000]
        source.updated_at = utc_now()

        db.add(source)
        db.commit()

        if isinstance(exc, GitSourceError):
            raise

        raise GitSourceError(
            str(exc)
        ) from exc


def get_source_or_404(
    db: Session,
    source_id: int,
) -> RecipeSource:
    source = db.get(
        RecipeSource,
        source_id,
    )

    if source is None:
        raise HTTPException(
            status_code=404,
            detail="Recipe source not found",
        )

    return source


@router.post(
    "/github",
    status_code=status.HTTP_201_CREATED,
)
def create_github_source(
    request: GitHubSourceCreate,
    db: Session = Depends(get_db),
) -> dict:
    try:
        (
            repo_url,
            default_name,
            branch,
            include_path,
        ) = parse_github_url(
            request.url,
            request.branch,
            request.include_path,
        )
    except GitSourceError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    existing = db.scalar(
        select(RecipeSource).where(
            RecipeSource.repo_url == repo_url
        )
    )

    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Repository already exists"
                ),
                "source_id": existing.id,
            },
        )

    source = RecipeSource(
        name=request.name or default_name,
        repo_url=repo_url,
        branch=branch,
        include_path=include_path,
        sync_interval_minutes=(
            request.sync_interval_minutes
        ),
    )

    db.add(source)

    try:
        db.commit()
        db.refresh(source)
    except IntegrityError as exc:
        db.rollback()

        raise HTTPException(
            status_code=409,
            detail="Repository already exists",
        ) from exc

    try:
        sync_result = synchronize_source(
            db,
            source,
        )
    except GitSourceError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": (
                    "Source created but initial "
                    "synchronization failed"
                ),
                "source_id": source.id,
                "error": str(exc),
            },
        ) from exc

    return {
        "source": {
            "id": source.id,
            "name": source.name,
            "repo_url": source.repo_url,
            "branch": source.branch,
            "include_path": source.include_path,
            "sync_interval_minutes": (
                source.sync_interval_minutes
            ),
        },
        "sync": sync_result,
    }


@router.get("")
def list_sources(
    db: Session = Depends(get_db),
) -> list[dict]:
    sources = db.scalars(
        select(RecipeSource)
        .order_by(RecipeSource.name.asc())
    ).all()

    result = []

    for source in sources:
        recipe_count = db.scalar(
            select(func.count())
            .select_from(SourceRecipe)
            .where(
                SourceRecipe.source_id
                == source.id,
                SourceRecipe.active.is_(True),
            )
        ) or 0

        result.append(
            {
                "id": source.id,
                "name": source.name,
                "repo_url": source.repo_url,
                "branch": source.branch,
                "include_path": source.include_path,
                "sync_interval_minutes": (
                    source.sync_interval_minutes
                ),
                "last_commit": source.last_commit,
                "last_synced_at": (
                    source.last_synced_at
                ),
                "last_error": source.last_error,
                "active_recipe_count": recipe_count,
            }
        )

    return result


@router.post("/{source_id}/sync")
def sync_github_source(
    source_id: int,
    db: Session = Depends(get_db),
) -> dict:
    source = get_source_or_404(
        db,
        source_id,
    )

    try:
        return synchronize_source(
            db,
            source,
        )
    except GitSourceError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": (
                    "Source synchronization failed"
                ),
                "error": str(exc),
            },
        ) from exc


@router.get("/{source_id}/recipes")
def list_source_recipes(
    source_id: int,
    q: str | None = Query(
        default=None,
        max_length=200,
    ),
    category: str | None = Query(
        default=None,
        max_length=300,
    ),
    recipe_status: str | None = Query(
        default=None,
        alias="status",
        max_length=40,
    ),
    active_only: bool = True,
    limit: int = Query(
        default=100,
        ge=1,
        le=1000,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
    db: Session = Depends(get_db),
) -> dict:
    get_source_or_404(
        db,
        source_id,
    )

    statement = select(SourceRecipe).where(
        SourceRecipe.source_id == source_id
    )

    if active_only:
        statement = statement.where(
            SourceRecipe.active.is_(True)
        )

    if q:
        query_text = q.casefold()

        statement = statement.where(
            or_(
                func.lower(
                    SourceRecipe.title
                ).contains(query_text),
                func.lower(
                    SourceRecipe.path
                ).contains(query_text),
                func.lower(
                    SourceRecipe.search_text
                ).contains(query_text),
            )
        )

    if category:
        statement = statement.where(
            SourceRecipe.category == category
        )

    if recipe_status:
        statement = statement.where(
            SourceRecipe.status
            == recipe_status
        )

    count_statement = select(
        func.count()
    ).select_from(
        statement.subquery()
    )

    total = db.scalar(
        count_statement
    ) or 0

    rows = db.scalars(
        statement
        .order_by(
            SourceRecipe.category.asc(),
            SourceRecipe.title.asc(),
        )
        .offset(offset)
        .limit(limit)
    ).all()

    return {
        "source_id": source_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": row.id,
                "title": row.title,
                "category": row.category,
                "path": row.path,
                "content_sha256": (
                    row.content_sha256
                ),
                "source_commit": (
                    row.source_commit
                ),
                "status": row.status,
                "active": row.active,
            }
            for row in rows
        ],
    }


@router.get(
    "/{source_id}/recipes/{recipe_id}/content"
)
def read_source_recipe_content(
    source_id: int,
    recipe_id: int,
    db: Session = Depends(get_db),
) -> dict:
    source = get_source_or_404(
        db,
        source_id,
    )

    recipe = db.scalar(
        select(SourceRecipe).where(
            SourceRecipe.id == recipe_id,
            SourceRecipe.source_id == source_id,
        )
    )

    if recipe is None:
        raise HTTPException(
            status_code=404,
            detail="Source recipe not found",
        )

    repo_dir = source_repo_dir(
        source.id
    ).resolve()

    file_path = (
        repo_dir / recipe.path
    ).resolve()

    if (
        file_path != repo_dir
        and repo_dir not in file_path.parents
    ):
        raise HTTPException(
            status_code=500,
            detail="Invalid indexed path",
        )

    if not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Recipe file no longer exists",
        )

    content = file_path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    return {
        "id": recipe.id,
        "source_id": source.id,
        "title": recipe.title,
        "category": recipe.category,
        "path": recipe.path,
        "source_commit": recipe.source_commit,
        "content": content,
    }


def normalize_datetime(
    value: datetime | None,
) -> datetime | None:
    """
    SQLite may return stored datetimes without timezone
    information. Convert them to UTC-aware datetimes.
    """
    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)

    return value.astimezone(UTC)


@router.post("/sync-due")
def sync_due_sources(
    db: Session = Depends(get_db),
) -> dict:
    """
    Synchronize only sources whose configured interval
    has elapsed.
    """
    now = utc_now()

    sources = db.scalars(
        select(RecipeSource)
        .where(
            RecipeSource
            .sync_interval_minutes
            .is_not(None)
        )
        .order_by(RecipeSource.id.asc())
    ).all()

    synced: list[dict] = []
    skipped: list[dict] = []
    failed: list[dict] = []

    for source in sources:
        interval = (
            source.sync_interval_minutes
            or 0
        )

        last_synced = normalize_datetime(
            source.last_synced_at
        )

        due = (
            last_synced is None
            or now - last_synced
            >= timedelta(minutes=interval)
        )

        if not due:
            skipped.append(
                {
                    "source_id": source.id,
                    "name": source.name,
                    "reason": "not_due",
                    "last_synced_at": (
                        source.last_synced_at
                    ),
                    "sync_interval_minutes": (
                        interval
                    ),
                }
            )
            continue

        try:
            result = synchronize_source(
                db,
                source,
            )
            synced.append(result)

        except GitSourceError as exc:
            failed.append(
                {
                    "source_id": source.id,
                    "name": source.name,
                    "error": str(exc),
                }
            )

    return {
        "checked": len(sources),
        "synced": synced,
        "skipped": skipped,
        "failed": failed,
    }
