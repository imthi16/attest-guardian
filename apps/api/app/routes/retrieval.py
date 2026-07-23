"""Retrieval endpoint under `/api/v1/workspaces/{workspace_id}/retrieval`.

Querying requires the `QUERY` capability. The route runs inside the workspace
context, so membership is proven and row-level security is bound before any
retrieval touches tenant data. The service itself only ever reads through
workspace-scoped repositories, so unauthorized chunks cannot be returned.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth.dependencies import SessionDep, get_app_settings
from app.auth.permissions import WorkspaceAction
from app.auth.workspace import RequireAction, WorkspaceContext
from app.config import Settings
from app.retrieval.service import HybridRetrievalService, RetrievalConfig
from app.retrieval.types import RetrievalFilters
from app.schemas.retrieval import RetrievalRequest, RetrievalResponse

logger = logging.getLogger("app.retrieval")

router = APIRouter(prefix="/workspaces/{workspace_id}/retrieval", tags=["retrieval"])

QuerierContext = Annotated[WorkspaceContext, Depends(RequireAction(WorkspaceAction.QUERY))]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]


@router.post("/search", response_model=RetrievalResponse)
async def search(
    payload: RetrievalRequest,
    context: QuerierContext,
    session: SessionDep,
    settings: SettingsDep,
) -> RetrievalResponse:
    config = RetrievalConfig(
        rrf_k=settings.retrieval_rrf_k,
        candidate_limit=settings.retrieval_candidate_limit,
        top_k=settings.retrieval_top_k,
    )
    # Clamp caller-supplied top_k to a safe maximum; never trust the request.
    top_k = None
    if payload.top_k is not None:
        top_k = min(payload.top_k, settings.retrieval_max_top_k)

    service = HybridRetrievalService(session, config=config)
    result = await service.search(
        workspace_id=context.workspace.id,
        query=payload.query,
        filters=RetrievalFilters(
            document_id=payload.document_id,
            language=payload.language,
        ),
        top_k=top_k,
    )
    logger.info(
        "retrieval completed",
        extra={
            "workspace_id": str(context.workspace.id),
            "trace": result.trace.as_metadata(),
        },
    )
    return RetrievalResponse.from_result(result)
