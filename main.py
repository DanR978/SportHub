from fastapi import FastAPI
from routers.events import router
from database import engine, Base
from routers.users import router as users_router

app = FastAPI()
app.include_router(router)
app.include_router(users_router)

@app.get("/")
def read_root():
    return {"message": "SportMap API is running"}

Base.metadata.create_all(bind=engine)