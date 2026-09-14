"""Optional FastAPI application; mount separately from the CAD generation API."""

from .models import CFDError, SimulationSpec


def create_app(service):
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse

    app = FastAPI(title="SeekFlow CFD", version="0.1.0")

    @app.exception_handler(CFDError)
    async def cfd_error(_request, exc):
        return JSONResponse(
            status_code=409, content=exc.diagnostic.model_dump(mode="json")
        )

    @app.get("/cfd/schema")
    def schema():
        return SimulationSpec.model_json_schema()

    @app.post("/cfd/jobs", status_code=202)
    def submit(spec: SimulationSpec):
        try:
            return service.submit(spec.model_dump(mode="json"))
        except RuntimeError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc

    @app.get("/cfd/jobs/{job_id}")
    def status(job_id: str):
        return service.status(job_id)

    @app.post("/cfd/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        return service.cancel(job_id)

    @app.post("/cfd/jobs/{job_id}/resume", status_code=202)
    def resume(job_id: str):
        try:
            return service.resume(job_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return app
