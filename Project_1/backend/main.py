from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import controller
import routers

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup():
    controller.load_cache()
    print("[STARTUP] Ready")

app.include_router(routers.router)