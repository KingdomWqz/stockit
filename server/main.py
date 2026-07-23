from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from auth import get_current_user, router as auth_router
from stocks import router as stocks_router

import inngest_app

app = FastAPI(title="Stockit API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/svc/api")
app.include_router(
    stocks_router, prefix="/svc/api", dependencies=[Depends(get_current_user)]
)


@app.get("/svc/api/health")
def health():
    return {"status": "ok"}


@app.get("/svc/api")
def root():
    return {"message": "Stockit API", "version": "0.1.0"}

inngest_app.register(app)
