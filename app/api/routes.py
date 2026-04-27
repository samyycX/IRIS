from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from sse_starlette import EventSourceResponse

from app.models import (
    AppConfig,
    AuthLoginRequest,
    AuthStatusResponse,
    ConfigSummaryResponse,
    DataSourceKind,
    EmbeddingProfile,
    IndexJobRequest,
    IndexPreparationRequest,
    IndexScope,
    IndexStatusResponse,
    JobRequest,
    JobStatus,
    LLMProfile,
    Neo4jProfile,
    SearchApiCapabilitiesResponse,
    SearchApiSettingsUpdateRequest,
    SearchEntityQueryRequest,
    SearchEntityQueryResponse,
    SearchPermissionSource,
    SearchPermissionSourceCreateRequest,
    SearchPermissionSourceCreateResponse,
    SearchPermissionSourceUpdateRequest,
    SearchQueryRequest,
    SearchQueryResponse,
    SearchSourceByKeyRequest,
    SearchSourceDetailResponse,
    SearchPreviewRequest,
    SearchPreviewResponse,
    RuntimeStatusResponse
)
from app.services.search_api import (
    build_permission_source_from_create_request,
    build_permission_source_from_update_request,
)

router = APIRouter(prefix="/api", tags=["api"])


def _container(request: Request):
    return request.app.state.container


def _find_search_permission_source(request: Request, source_id: str) -> SearchPermissionSource:
    config = _container(request).config_service.get_config()
    for source in config.search_api.permission_sources:
        if source.id == source_id:
            return source
    raise HTTPException(status_code=404, detail="Permission source not found")


def _auth_status_response(request: Request, *, authenticated: bool) -> AuthStatusResponse:
    container = _container(request)
    auth = container.auth
    return AuthStatusResponse(
        bypass_enabled=auth.bypass_enabled,
        authenticated=authenticated,
        ui_language=container.config_service.get_config().runtime.ui_language,
    )


@router.get("/auth/status")
async def auth_status(request: Request) -> AuthStatusResponse:
    auth = _container(request).auth
    return _auth_status_response(request, authenticated=auth.is_request_authenticated(request))


@router.post("/auth/login")
async def login(request: Request, payload: AuthLoginRequest, response: Response) -> AuthStatusResponse:
    auth = _container(request).auth
    if auth.bypass_enabled:
        return _auth_status_response(request, authenticated=True)
    if not auth.verify_password(payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")
    auth.attach_session_cookie(response)
    return _auth_status_response(request, authenticated=True)


@router.post("/auth/logout")
async def logout(request: Request, response: Response) -> AuthStatusResponse:
    auth = _container(request).auth
    auth.clear_session_cookie(request, response)
    return _auth_status_response(
        request,
        authenticated=False if not auth.bypass_enabled else True,
    )

@router.get("/status", tags=["health"])
async def runtime_status(request: Request) -> RuntimeStatusResponse:
    return await request.app.state.container.runtime_status.get_status()

@router.post("/jobs")
async def create_job(request: Request, payload: JobRequest):
    container = _container(request)
    return await container.jobs.create_job(payload)


@router.get("/jobs")
async def list_jobs(request: Request):
    container = _container(request)
    return await container.jobs.list_jobs()


@router.get("/jobs/{job_id}")
async def get_job(request: Request, job_id: str):
    container = _container(request)
    job = await container.jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/jobs/{job_id}/resume")
async def resume_job(request: Request, job_id: str):
    container = _container(request)
    job = await container.jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    resumed = await container.jobs.resume_job(job_id)
    if resumed is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if resumed.status not in {JobStatus.queued, JobStatus.running}:
        raise HTTPException(status_code=409, detail="Job is not resumable")
    return resumed


@router.post("/jobs/{job_id}/pause")
async def pause_job(request: Request, job_id: str):
    container = _container(request)
    job = await container.jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    paused = await container.jobs.pause_job(job_id)
    if paused is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if paused.status != JobStatus.paused:
        raise HTTPException(status_code=409, detail="Job is not pausable")
    return paused


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(request: Request, job_id: str):
    container = _container(request)
    job = await container.jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    cancelled = await container.jobs.cancel_job(job_id)
    if cancelled is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if cancelled.status != JobStatus.cancelled:
        raise HTTPException(status_code=409, detail="Job is not cancellable")
    return cancelled


@router.get("/jobs/{job_id}/events")
async def get_job_events(request: Request, job_id: str):
    container = _container(request)
    job = await container.jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return await container.jobs.get_events(job_id)


@router.get("/jobs/{job_id}/stream")
async def stream_job_events(request: Request, job_id: str):
    container = _container(request)
    job = await container.jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return EventSourceResponse(container.jobs.stream_events(job_id))


@router.post("/indexing/backfill")
async def create_index_backfill_job(request: Request, payload: IndexJobRequest):
    container = _container(request)
    return await container.indexing.create_backfill_job(payload)


@router.post("/indexing/reindex")
async def create_index_reindex_job(request: Request, payload: IndexJobRequest):
    container = _container(request)
    return await container.indexing.create_reindex_job(payload)


@router.post("/indexing/prepare")
async def prepare_index_job(request: Request, payload: IndexPreparationRequest):
    container = _container(request)
    return await container.indexing.prepare(payload)


@router.get("/indexing/jobs")
async def list_index_jobs(request: Request):
    container = _container(request)
    return await container.indexing.list_jobs()


@router.get("/indexing/jobs/{job_id}")
async def get_index_job(request: Request, job_id: str):
    container = _container(request)
    job = await container.indexing.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Index job not found")
    return job


@router.get("/indexing/jobs/{job_id}/events")
async def get_index_job_events(request: Request, job_id: str):
    container = _container(request)
    job = await container.indexing.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Index job not found")
    return await container.indexing.get_events(job_id)


@router.get("/indexing/status")
async def get_index_statuses(request: Request) -> IndexStatusResponse:
    container = _container(request)
    return await container.indexing.get_statuses()


@router.post("/indexing/fulltext/build")
async def ensure_fulltext_indexes(request: Request) -> IndexStatusResponse:
    container = _container(request)
    return await container.indexing.ensure_fulltext_indexes()


@router.post("/indexing/fulltext/rebuild/{scope}")
async def rebuild_fulltext_indexes(request: Request, scope: IndexScope) -> IndexStatusResponse:
    container = _container(request)
    return await container.indexing.rebuild_fulltext_indexes(scope)


@router.post("/indexing/query-preview")
async def query_index_preview(
    request: Request,
    payload: SearchPreviewRequest,
) -> SearchPreviewResponse:
    container = _container(request)
    return await container.indexing.query_preview(payload)


@router.get(
    "/search/v1/capabilities",
    tags=["search"],
    response_model=SearchApiCapabilitiesResponse,
    summary="Get current search API capabilities",
)
async def get_search_api_capabilities(request: Request) -> SearchApiCapabilitiesResponse:
    container = _container(request)
    return await container.search_api.get_capabilities(request)


@router.post(
    "/search/v1/entities/query",
    tags=["search"],
    response_model=SearchEntityQueryResponse,
    summary="Query entities by entity_id, exact name, or exact alias",
)
async def query_search_entities(
    request: Request,
    payload: SearchEntityQueryRequest,
) -> SearchEntityQueryResponse:
    container = _container(request)
    await container.search_api.authorize_request(request)
    return await container.search_api.query_entities(payload)


@router.post(
    "/search/v1/sources/query",
    tags=["search"],
    response_model=SearchSourceDetailResponse,
    summary="Get a source by source_key",
)
async def get_search_source(
    request: Request,
    payload: SearchSourceByKeyRequest,
) -> SearchSourceDetailResponse:
    container = _container(request)
    await container.search_api.authorize_request(request)
    return await container.search_api.get_source_detail(payload)


@router.post(
    "/search/v1/search",
    tags=["search"],
    response_model=SearchQueryResponse,
    summary="Execute a unified search query",
)
async def query_search_api(
    request: Request,
    payload: SearchQueryRequest,
) -> SearchQueryResponse:
    container = _container(request)
    access = await container.search_api.authorize_request(request)
    return await container.search_api.query(payload, access)


@router.get("/config")
async def get_config(request: Request) -> AppConfig:
    container = _container(request)
    return container.config_service.get_config()


@router.put("/config")
async def replace_config(request: Request, payload: AppConfig) -> AppConfig:
    container = _container(request)
    container.config_service.save_config(payload)
    await container.reload_runtime()
    return container.config_service.get_config()


@router.get("/config/summary")
async def get_config_summary(request: Request) -> ConfigSummaryResponse:
    container = _container(request)
    return ConfigSummaryResponse.model_validate(container.config_service.get_summary())


@router.post("/config/reload")
async def reload_config(request: Request) -> ConfigSummaryResponse:
    container = _container(request)
    await container.reload_runtime()
    return ConfigSummaryResponse.model_validate(container.config_service.get_summary())


@router.put("/config/search-api/settings")
async def update_search_api_settings(
    request: Request,
    payload: SearchApiSettingsUpdateRequest,
) -> AppConfig:
    container = _container(request)
    container.config_service.update_search_api_settings(
        enabled=payload.enabled,
        validation_enabled=payload.validation_enabled,
    )
    await container.reload_search_api_config()
    return container.config_service.get_config()


@router.post("/config/search-api/permissions")
async def create_search_permission_source(
    request: Request,
    payload: SearchPermissionSourceCreateRequest,
) -> SearchPermissionSourceCreateResponse:
    container = _container(request)
    permission_source, generated_api_key = build_permission_source_from_create_request(payload)
    try:
        container.config_service.create_search_permission_source(permission_source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await container.reload_search_api_config()
    return SearchPermissionSourceCreateResponse(
        permission_source=permission_source,
        generated_api_key=generated_api_key,
    )


@router.put("/config/search-api/permissions/{source_id}")
async def update_search_permission_source(
    request: Request,
    source_id: str,
    payload: SearchPermissionSourceUpdateRequest,
) -> SearchPermissionSource:
    container = _container(request)
    existing = _find_search_permission_source(request, source_id)
    updated_source = build_permission_source_from_update_request(existing, payload)
    try:
        container.config_service.update_search_permission_source(source_id, updated_source)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Permission source not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await container.reload_search_api_config()
    return updated_source


@router.delete("/config/search-api/permissions/{source_id}")
async def delete_search_permission_source(request: Request, source_id: str) -> AppConfig:
    container = _container(request)
    try:
        container.config_service.delete_search_permission_source(source_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Permission source not found") from exc
    await container.reload_search_api_config()
    return container.config_service.get_config()


@router.get("/config/data-sources")
async def list_data_sources(request: Request) -> dict[str, Any]:
    container = _container(request)
    config = container.config_service.get_config()
    return {
        "active_neo4j_profile_id": config.active_neo4j_profile_id,
        "active_llm_profile_id": config.active_llm_profile_id,
        "active_embedding_profile_id": config.active_embedding_profile_id,
        "neo4j_profiles": config.neo4j_profiles,
        "llm_profiles": config.llm_profiles,
        "embedding_profiles": config.embedding_profiles,
    }


@router.post("/config/data-sources/{kind}")
async def create_data_source_profile(
    request: Request,
    kind: DataSourceKind,
    payload: dict[str, Any],
) -> AppConfig:
    container = _container(request)
    try:
        profile = _parse_profile(kind, payload)
        container.config_service.create_profile(kind, profile)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await container.reload_runtime()
    return container.config_service.get_config()


@router.put("/config/data-sources/{kind}/{profile_id}")
async def update_data_source_profile(
    request: Request,
    kind: DataSourceKind,
    profile_id: str,
    payload: dict[str, Any],
) -> AppConfig:
    container = _container(request)
    try:
        profile = _parse_profile(kind, payload)
        container.config_service.update_profile(kind, profile_id, profile)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Profile not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await container.reload_runtime()
    return container.config_service.get_config()


@router.delete("/config/data-sources/{kind}/{profile_id}")
async def delete_data_source_profile(
    request: Request,
    kind: DataSourceKind,
    profile_id: str,
) -> AppConfig:
    container = _container(request)
    try:
        container.config_service.delete_profile(kind, profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Profile not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await container.reload_runtime()
    return container.config_service.get_config()


@router.put("/config/data-sources/{kind}/active/{profile_id}")
async def set_active_data_source_profile(
    request: Request,
    kind: DataSourceKind,
    profile_id: str,
) -> AppConfig:
    container = _container(request)
    try:
        container.config_service.set_active_profile(kind, profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Profile not found") from exc
    await container.reload_runtime()
    return container.config_service.get_config()


@router.delete("/config/data-sources/{kind}/active")
async def clear_active_data_source_profile(
    request: Request,
    kind: DataSourceKind,
) -> AppConfig:
    container = _container(request)
    container.config_service.set_active_profile(kind, None)
    await container.reload_runtime()
    return container.config_service.get_config()


def _parse_profile(
    kind: DataSourceKind,
    payload: dict[str, Any],
) -> Neo4jProfile | LLMProfile | EmbeddingProfile:
    if kind == DataSourceKind.neo4j:
        return Neo4jProfile.model_validate(payload)
    if kind == DataSourceKind.llm:
        return LLMProfile.model_validate(payload)
    if kind == DataSourceKind.embedding:
        return EmbeddingProfile.model_validate(payload)
    raise ValueError(f"Unsupported data source kind: {kind}")
