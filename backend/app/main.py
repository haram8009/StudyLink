from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from .adapters.telemetry import flush
from .db import init_db, recover_interrupted_documents
from .routers.api import router
from .routers.chats import router as chats_router
from .routers.notes import router as notes_router
from .routers.quizzes import router as quizzes_router

@asynccontextmanager
async def lifespan(app):
    init_db()
    recover_interrupted_documents()
    yield
    flush()

app = FastAPI(title='StudyLink', lifespan=lifespan)
app.include_router(router)
app.include_router(chats_router)
app.include_router(notes_router)
app.include_router(quizzes_router)

@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={'detail': '내부 처리 오류가 발생했습니다. 다시 시도하세요'})

@app.get('/api/health')
def health():
    return {'status': 'ok'}
