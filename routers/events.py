from fastapi import APIRouter
from models.event import Event, EventCreate
from sqlalchemy.orm import Session
from fastapi import Depends
from database import get_db
from models.db_event import DBEvent

router = APIRouter()

@router.post("/sports-events", response_model=Event)
async def create_event(event: EventCreate, db: Session = Depends(get_db)):
    new_event = DBEvent(**event.model_dump())
    db.add(new_event)
    db.commit()
    db.refresh(new_event)
    return new_event

@router.get("/sports-events", response_model=list[Event])
async def get_events(db: Session = Depends(get_db)):
    events = db.query(DBEvent).all()
    return events