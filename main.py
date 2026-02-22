from fastapi import FastAPI
from routers.events import router
from database import engine, Base
from models.db_event import DBEvent

app = FastAPI()
app.include_router(router)

@app.get("/")
def read_root():
    return {"message": "SportMap API is running"}

Base.metadata.create_all(bind=engine)