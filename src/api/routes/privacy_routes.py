"""Self-service data export and deletion (Phase 21).

Both endpoints act only on the authenticated caller's own data — there is no
admin-on-others variant here, deliberately: a learner exporting or deleting
someone else's data would be exactly the authorization gap the rest of the API
is careful to avoid (every route threads the auth-resolved ``user_id``, never
a client-supplied one).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.deps import get_current_user
from src.api.schemas import DataDeletionResponse, DataExportResponse

router = APIRouter(prefix="/api/v1/privacy", tags=["privacy"])


@router.get("/export", response_model=DataExportResponse)
def export_my_data(user_id: str = Depends(get_current_user)) -> DataExportResponse:
    """Export everything stored about the authenticated user."""
    from src.memory.privacy import export_user_data

    return DataExportResponse(data=export_user_data(user_id))


@router.delete("/data", response_model=DataDeletionResponse)
def delete_my_data(user_id: str = Depends(get_current_user)) -> DataDeletionResponse:
    """Permanently delete every stored record for the authenticated user.

    Irreversible: this also invalidates the caller's own bearer token (the
    account row and every token for it are removed), so the request that
    triggers this is the last authenticated request that account can make.
    """
    from src.memory.privacy import delete_user_data

    result = delete_user_data(user_id)
    return DataDeletionResponse(deleted=result)
