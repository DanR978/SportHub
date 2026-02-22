from fastapi import APIRouter, Depends, Query
from models.event import Event, EventCreate
from sqlalchemy.orm import Session
from database import get_db
from models.db_event import DBEvent
from auth import get_current_user
from models.db_user import DBUser
from typing import List, Optional
from datetime import date


router = APIRouter()


@router.post("/sports-events", response_model=Event)
async def create_event(event: EventCreate, db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    new_event = DBEvent(
        **event.model_dump(exclude={"created_by", "sport", "experience_level"}),
        sport=event.sport.lower(),
        experience_level=event.experience_level.lower(),
        created_by=str(current_user.user_id)
        )
    db.add(new_event)
    db.commit()
    db.refresh(new_event)
    return new_event


@router.get("/sports-events", response_model=list[Event])
async def get_events(db: Session = Depends(get_db)):
    events = db.query(DBEvent).all()
    return events


@router.get("/sports-events/filter", response_model=list[Event])
async def filter_event(
    sports: List[str] = Query(default=None), 
    experience_levels: List[str] = Query(default=None), 
    start_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    db: Session = Depends(get_db)
    ):


    query = db.query(DBEvent)
    if sports:
        sports = [sport.lower() for sport in sports]
        query = query.filter(DBEvent.sport.in_(sports))
    if experience_levels:
        experience_levels = [level.lower() for level in experience_levels]
        query = query.filter(DBEvent.experience_level.in_(experience_levels))
    if start_from:
        query = query.filter(DBEvent.start_date >= start_from)
    if date_to:
        query = query.filter(DBEvent.start_date <= date_to)
    return query.all()