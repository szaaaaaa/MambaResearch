"""Research task UI contribution owned by the Codex App workbench."""

from pathlib import Path
import sys

from fastapi import APIRouter, HTTPException, Query

from src.server.kernel.contracts import KernelContext, McpStdioConfig, PluginManifest
from src.server.workbench.tasks import list_tasks
from src.server.projects.registry import ProjectNotFoundError


router = APIRouter()


@router.get("/api/workbench/tasks")
def tasks(project_id: str = Query(...)):
    try:
        return {"tasks": list_tasks(project_id)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


class WorkbenchPlugin:
    manifest = PluginManifest(id="core.workbench", requires=("core.http",))
    id = "mamba_workbench"
    label = "科研工作台"

    def resolve_config(self):
        return McpStdioConfig(command=sys.executable, args=("-m", "src.server.workbench.mcp_server"),
                             env={"PYTHONPATH": str(Path(__file__).resolve().parents[3])})

    def register(self, context: KernelContext):
        context.capabilities.http.register(contribution_id=self.manifest.id, plugin_id=self.manifest.id, router=router)
        context.capabilities.mcp.register(plugin_id=self.manifest.id, provider=self)

    async def start(self, context):
        return None
