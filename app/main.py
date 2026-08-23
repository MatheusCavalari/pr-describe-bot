from fastapi import FastAPI

from app.routers import webhook

app = FastAPI(title="PR Describe Bot")
app.include_router(webhook.router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
