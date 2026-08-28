import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import catalog
from app.middleware import CorrelationMiddleware
from app.routes import router, search_index
from smart_home_common import configure_logging, get_logger

configure_logging(service="bfa", level=os.environ.get("LOG_LEVEL", "INFO"))
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    result = catalog.build(search_index)
    logger.info(
        "catalog built: %d entries from %d sources (%d errors)",
        result["indexed"],
        len(result["sources"]),
        len(result["errors"]),
    )
    for err in result["errors"]:
        logger.warning("catalog source unreachable: %s (%s)", err["source"], err["error"])
    yield


app = FastAPI(title="Smart Home AI - BFA", lifespan=lifespan)
app.add_middleware(CorrelationMiddleware)
app.include_router(router)
