from typing import Any, Dict, Optional

import httpx

from . import config


class DomoDatasetUploader:
    def __init__(self, developer_token: str | None = None, base_url: str | None = None):
        self.developer_token = developer_token or config.DOMO_API_KEY
        root_url = base_url or config.DOMO_BASE_URL.removesuffix("/api")
        if not self.developer_token or not root_url:
            raise ValueError(
                "DOMO_API_KEY / DOMO_BASE_URL are not configured in the shared .env."
            )
        self.base_url = root_url.rstrip("/")
        self.headers = {
            "X-DOMO-Developer-Token": self.developer_token,
            "Content-Type": "application/json",
        }

    async def _create_upload_session(self, datasource_id: str, action: str = "APPEND") -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}/api/data/v3/datasources/{datasource_id}/uploads"
        payload = {
            "action": action,
            "message": "Uploading",
        }
        if action == "APPEND":
            payload["appendId"] = "latest"

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=self.headers, timeout=30.0)
                response.raise_for_status()
                return response.json()
            except Exception:
                return None

    async def _commit_upload(self, datasource_id: str, upload_id: int, action: str = "APPEND") -> bool:
        url = f"{self.base_url}/api/data/v3/datasources/{datasource_id}/uploads/{upload_id}/commit"
        payload = {
            "index": True,
            "message": "Dataset Updated Successfully"
        }
        if action == "APPEND":
            payload["appendId"] = "latest"

        async with httpx.AsyncClient() as client:
            try:
                response = await client.put(url, json=payload, headers=self.headers, timeout=30.0)
                response.raise_for_status()
                return True
            except Exception:
                return False

    async def upload_csv_data(self, datasource_id: str, csv_data: str, action: str = "APPEND") -> bool:
        session_info = await self._create_upload_session(datasource_id, action=action)
        if not session_info or "uploadId" not in session_info:
            return False

        upload_id = session_info["uploadId"]
        url = f"{self.base_url}/api/data/v3/datasources/{datasource_id}/uploads/{upload_id}/parts/1"
        
        headers = self.headers.copy()
        headers["Content-Type"] = "text/csv"

        async with httpx.AsyncClient() as client:
            try:
                response = await client.put(url, content=csv_data, headers=headers, timeout=60.0)
                response.raise_for_status()
                return await self._commit_upload(datasource_id, upload_id, action=action)
            except Exception:
                return False