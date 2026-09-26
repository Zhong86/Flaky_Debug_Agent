from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from api.router import api_router
from core.config import get_settings
from graph.graph import compile_graph
from services import log_buffer


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    async with AsyncPostgresSaver.from_conn_string(settings.database_url) as checkpointer:
        await checkpointer.setup()
        app.state.graph = compile_graph(checkpointer=checkpointer)
        yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Not in lifespan(): tests build TestClient(app) without `with` so lifespan
    # (which needs Postgres) never runs, but this needs no async setup.
    app.state.log_buffer = log_buffer.install(capacity=settings.demo_log_buffer_size)

    app.include_router(api_router, prefix="/api")
    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
