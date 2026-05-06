import os
import uuid
from typing import Any, Literal, TypedDict

import httpx  # Assuming httpx is available for internal HTTP requests


EncliiStatus = Literal["success", "failed", "retryable", "unknown", "unsafe"]


class EncliiOperationResult(TypedDict, total=False):
    status: EncliiStatus
    success: bool
    retryable: bool
    unsafe: bool
    run_id: str
    pod_name: str
    operation: str
    status_code: int
    error: str
    error_type: str
    raw_response: Any


class EncliiActionResult(dict[str, Any]):
    """Dict result that remains compatible with boolean lifecycle checks."""

    def __bool__(self) -> bool:
        return bool(self.get("success", False))


class EncliiAdapter:
    """
    Adapter for communicating with the Enclii deployment orchestration system.
    Handles the provisioning and teardown of ephemeral ACP cleanroom pods.
    """

    def __init__(self, endpoint: str | None = None, token: str | None = None):
        # We default to the local cluster or pull from environment
        self.endpoint = endpoint or os.environ.get(
            "ENCLII_API_URL", "http://enclii.local:4200/api/v1"
        )
        self.token = token or os.environ.get("ENCLII_API_TOKEN")
        self.client = httpx.AsyncClient(
            base_url=self.endpoint,
            headers={"Authorization": f"Bearer {self.token}"} if self.token else {},
        )

    def _successful_deploy_result(
        self, response: httpx.Response, run_id: str, pod_name: str
    ) -> EncliiOperationResult:
        try:
            result = response.json()
        except ValueError as e:
            return {
                "status": "unknown",
                "success": False,
                "retryable": False,
                "unsafe": True,
                "run_id": run_id,
                "pod_name": pod_name,
                "status_code": response.status_code,
                "error": f"deployment response was not valid JSON: {e}",
                "error_type": type(e).__name__,
            }

        if not isinstance(result, dict):
            return {
                "status": "unknown",
                "success": False,
                "retryable": False,
                "unsafe": True,
                "run_id": run_id,
                "pod_name": pod_name,
                "status_code": response.status_code,
                "error": "deployment response JSON was not an object",
                "raw_response": result,
            }

        return {
            **result,
            "status": result.get("status", "success"),
            "success": result.get("success", True),
            "retryable": result.get("retryable", False),
            "unsafe": result.get("unsafe", False),
            "run_id": result.get("run_id", run_id),
            "pod_name": result.get("pod_name", pod_name),
            "status_code": response.status_code,
        }

    def _failure_result(
        self, operation: str, error: httpx.HTTPError, run_id: str | None = None
    ) -> EncliiOperationResult:
        retryable = isinstance(error, (httpx.TimeoutException, httpx.NetworkError))
        status_code = None

        if isinstance(error, httpx.HTTPStatusError):
            status_code = error.response.status_code
            retryable = status_code in {408, 409, 425, 429} or status_code >= 500

        status: EncliiStatus
        if operation == "teardown":
            status = "unsafe"
        elif retryable:
            status = "retryable"
        else:
            status = "failed"

        result: EncliiOperationResult = {
            "status": status,
            "success": False,
            "retryable": retryable,
            "unsafe": operation == "teardown",
            "operation": operation,
            "error": str(error),
            "error_type": type(error).__name__,
        }
        if run_id is not None:
            result["run_id"] = run_id
        if status_code is not None:
            result["status_code"] = status_code
        return result

    def _successful_action_result(
        self, operation: str, response: httpx.Response, run_id: str
    ) -> EncliiActionResult:
        return EncliiActionResult(
            {
                "status": "success",
                "success": True,
                "retryable": False,
                "unsafe": False,
                "operation": operation,
                "run_id": run_id,
                "status_code": response.status_code,
            }
        )

    async def deploy_dirty_pod(self, target_url: str) -> dict[str, Any]:
        """
        Deploys Phase I Analyst pod with full internet egress.
        """
        run_id = f"acp-dirty-{uuid.uuid4().hex[:8]}"
        payload = {
            "template": "acp-dirty-pod",
            "run_id": run_id,
            "environment": {"TARGET_URL": target_url},
        }
        pod_name = f"acp-dirty-analyst-{run_id}"
        try:
            response = await self.client.post("/deployments", json=payload)
            response.raise_for_status()
            return self._successful_deploy_result(response, run_id, pod_name)
        except httpx.HTTPError as e:
            return self._failure_result("deploy_dirty", e, run_id)

    async def deploy_clean_pod(self, sanitized_spec: str) -> dict[str, Any]:
        """
        Deploys Phase III Clean Swarm pod in a strictly airgapped network.
        Mounts the sanitized PRD as an environment variable or via tmpfs.
        """
        run_id = f"acp-clean-{uuid.uuid4().hex[:8]}"
        payload = {
            "template": "acp-clean-pod",
            "run_id": run_id,
            "airgap": True,
            "payloads": {"PRD_SPEC": sanitized_spec},
        }
        pod_name = f"acp-clean-swarm-{run_id}"

        try:
            response = await self.client.post("/deployments", json=payload)
            response.raise_for_status()
            return self._successful_deploy_result(response, run_id, pod_name)
        except httpx.HTTPError as e:
            return self._failure_result("deploy_clean", e, run_id)

    async def suspend_pod(self, run_id: str) -> EncliiActionResult:
        """
        Hibernates the specific Enclii cluster pod to scale-to-zero compute footprint
        while retaining state, mirroring the Hermes Daytona/Modal architecture.
        """
        try:
            response = await self.client.post(f"/deployments/{run_id}/suspend")
            response.raise_for_status()
            return self._successful_action_result("suspend", response, run_id)
        except httpx.HTTPError as e:
            return EncliiActionResult(self._failure_result("suspend", e, run_id))

    async def resume_pod(self, run_id: str) -> EncliiActionResult:
        """
        Wakes up a historically suspended Enclii cluster pod.
        """
        try:
            response = await self.client.post(f"/deployments/{run_id}/resume")
            response.raise_for_status()
            return self._successful_action_result("resume", response, run_id)
        except httpx.HTTPError as e:
            return EncliiActionResult(self._failure_result("resume", e, run_id))

    async def teardown_cleanroom(self, run_id: str) -> EncliiActionResult:
        """
        Destroys all associated pods/volumes for an ACP run immediately to prevent
        cross-contamination or context leakage.
        """
        try:
            response = await self.client.delete(f"/deployments/{run_id}")
            response.raise_for_status()
            return self._successful_action_result("teardown", response, run_id)
        except httpx.HTTPError as e:
            return EncliiActionResult(self._failure_result("teardown", e, run_id))
