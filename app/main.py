import os

from fastapi import FastAPI

from app.middleware import CorrelationMiddleware
from app.routes import router
from smart_home_common import configure_logging

configure_logging(service="bfa", level=os.environ.get("LOG_LEVEL", "INFO"))

app = FastAPI(title="Smart Home AI - BFA")
app.add_middleware(CorrelationMiddleware)
app.include_router(router)
