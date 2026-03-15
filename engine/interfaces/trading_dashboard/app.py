"""BTC_선물_봇 + 알트_데일리_봇 트레이딩 대시보드.

실행:
    .venv/bin/python -m engine.interfaces.trading_dashboard.app
    → http://localhost:8501
"""

import logging

import uvicorn
from fastapi import FastAPI

from engine.interfaces.trading_dashboard.routes import router

app = FastAPI(title="Trading Bot Dashboard")
app.include_router(router)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=8501)
