from __future__ import annotations

from fastapi import APIRouter, Request

from squashvision.model_assets import (
    ModelAssetError,
    ModelManifest,
    ResolvedAsset,
    public_source_label,
)
from squashvision.schemas import ApiError, ErrorResponse, ModelAssetDetail

router = APIRouter(
    tags=["models"],
    responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)


def _manifest(request: Request) -> ModelManifest:
    return request.app.state.model_manifest


def _detail(asset: ResolvedAsset) -> ModelAssetDetail:
    return ModelAssetDetail(
        name=asset.name,
        filename=asset.filename,
        requested_revision=asset.requested_revision,
        source_label=public_source_label(asset),
        resolved_revision=asset.resolved_revision,
        byte_size=asset.byte_size,
        sha256=asset.sha256,
        declared_license=asset.declared_license,
        downloaded_at=asset.downloaded_at,
        compatibility_version=asset.compatibility_version,
        required=asset.required,
        state=asset.state,
        error_code=asset.error_code,
    )


def _safe_error(error: ModelAssetError) -> ApiError:
    status = error.status_code
    if error.code in {
        "model_incompatible",
        "model_asset_corrupt",
        "model_download_failed",
        "model_revision_unavailable",
    }:
        status = 503
    messages = {
        "model_not_found": "model asset is not in the approved manifest",
        "model_incompatible": "model asset is incompatible with this application version",
        "model_asset_corrupt": "model asset failed integrity validation",
        "model_download_failed": "model asset could not be obtained safely",
        "model_revision_unavailable": "approved model revision is unavailable",
        "model_asset_too_large": "model asset exceeds the configured size limit",
    }
    return ApiError(
        error.code,
        messages.get(error.code, "model operation could not be completed"),
        status,
    )


@router.get(
    "/models",
    response_model=list[ModelAssetDetail],
    operation_id="listModels",
)
def list_models(request: Request) -> list[ModelAssetDetail]:
    return [_detail(asset) for asset in _manifest(request).states()]


@router.post(
    "/models/{name}/ensure",
    response_model=ModelAssetDetail,
    operation_id="ensureModel",
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def ensure_model(
    name: str, request: Request, offline: bool = False
) -> ModelAssetDetail:
    manifest = _manifest(request)
    try:
        spec = manifest.spec(name)
        return _detail(manifest.manager.ensure(spec, offline=offline))
    except ModelAssetError as error:
        raise _safe_error(error) from error
