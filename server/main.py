from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from auth import router as auth_router

app = FastAPI(title="Stockit API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/svc/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api")
def root():
    return {"message": "Stockit API", "version": "0.1.0"}