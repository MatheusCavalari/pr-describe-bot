from fastapi import FastAPI

app = FastAPI(title="PR Describe Bot")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
