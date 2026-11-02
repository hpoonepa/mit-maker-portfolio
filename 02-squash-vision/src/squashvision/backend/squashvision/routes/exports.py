from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from squashvision.db import Database
from squashvision.exports import (
    ExportBundle,
    ExportError,
    build_export,
    get_export,
    open_export_download,
)
from squashvision.schemas import ApiError, ErrorResponse, ExportCreateRequest, ExportDetail
from squashvision.storage import LocalStorage

router = APIRouter(
    prefix="/matches/{match_id}/exports",
    tags=["exports"],
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        410: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)


def _api_error(error: ExportError) -> ApiError:
    return ApiError(error.code, error.message, error.status_code)


def _services(request: Request) -> tuple[Database, LocalStorage]:
    return request.app.state.database, request.app.state.storage


def _detail(bundle: ExportBundle) -> ExportDetail:
    return ExportDetail(
        id=bundle.public_id,
        match_id=bundle.match_id,
        revision=bundle.revision,
        state="completed",
        selection=bundle.selection,
        relative_path=bundle.relative_path.as_posix(),
        byte_size=bundle.byte_size,
        sha256=bundle.sha256,
    )


@router.post(
    "",
    operation_id="createExport",
    response_model=ExportDetail,
    status_code=201,
    responses={200: {"model": ExportDetail}},
)
def create_export(
    match_id: str,
    body: ExportCreateRequest,
    request: Request,
) -> ExportDetail | JSONResponse:
    database, storage = _services(request)
    try:
        bundle = build_export(
            match_id,
            body.revision,
            body.selection,
            database=database,
            storage=storage,
        )
    except ExportError as error:
        raise _api_error(error) from error
    detail = _detail(bundle)
    if bundle.created:
        return detail
    return JSONResponse(
        status_code=200,
        content=detail.model_dump(mode="json", by_alias=True),
    )


@router.get(
    "/{export_id}",
    operation_id="getExport",
    response_model=ExportDetail,
)
def export_status(match_id: str, export_id: str, request: Request) -> ExportDetail:
    database, storage = _services(request)
    try:
        return _detail(
            get_export(
                match_id,
                export_id,
                database=database,
                storage=storage,
            )
        )
    except ExportError as error:
        raise _api_error(error) from error


@router.get(
    "/{export_id}/download",
    operation_id="downloadExport",
    response_class=StreamingResponse,
)
def download_export(
    match_id: str,
    export_id: str,
    request: Request,
) -> StreamingResponse:
    database, storage = _services(request)
    try:
        bundle, stream = open_export_download(
            match_id,
            export_id,
            database=database,
            storage=storage,
        )
    except ExportError as error:
        raise _api_error(error) from error
    filename = (
        f"squashvision-{match_id[:8]}-r{bundle.revision}-{export_id[:8]}.zip"
    )
    return StreamingResponse(
        stream,
        media_type="application/zip",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "ETag": f'"{bundle.sha256}"',
            "Content-Length": str(bundle.byte_size),
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
