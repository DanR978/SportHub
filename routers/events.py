import json
from uuid import UUID
from fastapi import APIRouter, Depends, Query, HTTPException, Header
from models.db_event_participant import DBEventParticipant
from models.db_host_rating import DBHostRating
from schemas.event import Event, EventCreate
from sqlalchemy.orm import Session
from database import get_db
from models.db_event import DBEvent
from models.db_archived_event import DBArchivedEvent
from auth import get_current_user
from models.db_user import DBUser
from typing import List, Optional
from datetime import date, datetime, timedelta
from geopy.geocoders import Nominatim
from better_profanity import profanity
from geopy.distance import geodesic
from jose import jwt as jose_jwt
from pydantic import BaseModel
import os

router = APIRouter()
geolocator = Nominatim(user_agent="sporthub")

SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key")
ALGORITHM = os.getenv("ALGORITHM", "HS256")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_user_id_from_header(authorization: Optional[str], db: Session) -> Optional[UUID]:
    if not authorization:
        return None
    try:
        token = authorization.replace("Bearer ", "")
        payload = jose_jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if not email:
            return None
        user = db.query(DBUser).filter(DBUser.email == email).first()
        return user.user_id if user else None
    except Exception:
        return None


def enrich_event(event, db, current_user_id=None):
    event.participant_count = (
        db.query(DBEventParticipant).filter_by(event_id=event.event_id).count()
    )
    if event.organizer_id:
        organizer = db.query(DBUser).filter(DBUser.user_id == event.organizer_id).first()
        if organizer:
            event.organizer_name = f"{organizer.first_name or ''} {organizer.last_name or ''}".strip()
            event.organizer_avatar = organizer.avatar_config
            event.organizer_photo = organizer.avatar_photo
            event.host_rating = float(organizer.host_rating) if organizer.host_rating else None
            event.total_ratings = organizer.total_ratings or 0
    if current_user_id:
        event.joined = (
            db.query(DBEventParticipant)
            .filter_by(event_id=event.event_id, user_id=current_user_id)
            .first() is not None
        )
        event.is_organizer = (event.organizer_id == current_user_id)
    else:
        event.joined = False
        event.is_organizer = False
    return event


def archive_event(db, event, reason='expired'):
    """Move an event to archived_events, preserving participant IDs."""
    participants = db.query(DBEventParticipant).filter_by(event_id=event.event_id).all()
    participant_id_list = [str(p.user_id) for p in participants]
    count = len(participants)

    organizer = db.query(DBUser).filter(DBUser.user_id == event.organizer_id).first() if event.organizer_id else None

    archived = DBArchivedEvent(
        event_id          = event.event_id,
        title             = event.title,
        sport             = event.sport,
        organizer_id      = event.organizer_id,
        organizer_name    = f"{organizer.first_name} {organizer.last_name}" if organizer else None,
        location          = event.location,
        start_date        = event.start_date,
        start_time        = event.start_time,
        end_time          = getattr(event, 'end_time', None),
        max_players       = event.max_players,
        participant_count = count,
        experience_level  = event.experience_level,
        cost              = event.cost,
        description       = getattr(event, 'description', None),
        archive_reason    = reason,
        participant_ids   = json.dumps(participant_id_list),
    )
    db.add(archived)
    db.query(DBEventParticipant).filter(DBEventParticipant.event_id == event.event_id).delete()
    db.delete(event)


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.post("/sports-events", response_model=Event)
async def create_event(event: EventCreate, db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    geo = geolocator.geocode(event.location)
    lat = geo.latitude if geo else 0.0
    lng = geo.longitude if geo else 0.0

    if profanity.contains_profanity(event.title) or profanity.contains_profanity(event.description or ""):
        raise HTTPException(status_code=400, detail="Content contains inappropriate language")

    new_event = DBEvent(
        **event.model_dump(exclude={"sport", "experience_level", "latitude", "longitude", "title", "location", "description"}),
        title=event.title.strip(),
        location=event.location.strip(),
        sport=event.sport.lower().strip(),
        experience_level=event.experience_level.lower().strip(),
        description=event.description.strip() if event.description else None,
        latitude=lat,
        longitude=lng,
        organizer_id=current_user.user_id,
    )

    db.add(new_event)
    db.commit()
    db.refresh(new_event)

    # Auto-add creator as first participant
    db.add(DBEventParticipant(event_id=new_event.event_id, user_id=current_user.user_id))
    db.commit()

    return enrich_event(new_event, db, current_user.user_id)


@router.get("/sports-events", response_model=list[Event])
async def get_events(
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(default=None),
):
    current_user_id = _get_user_id_from_header(authorization, db)
    today = date.today()
    events = db.query(DBEvent).filter(
        DBEvent.status == 'active',
        DBEvent.start_date >= today,
    ).all()
    for event in events:
        enrich_event(event, db, current_user_id)
    return events


@router.get("/sports-events/filter", response_model=list[Event])
async def filter_event(
    sports: List[str] = Query(default=None),
    experience_levels: List[str] = Query(default=None),
    start_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    db: Session = Depends(get_db),
    latitude: Optional[float] = Query(default=None),
    longitude: Optional[float] = Query(default=None),
    radius_miles: Optional[float] = Query(default=20.0),
    authorization: Optional[str] = Header(default=None),
):
    current_user_id = _get_user_id_from_header(authorization, db)
    today = date.today()
    query = db.query(DBEvent).filter(DBEvent.status == 'active', DBEvent.start_date >= today)

    if sports:
        query = query.filter(DBEvent.sport.in_([s.lower() for s in sports]))
    if experience_levels:
        query = query.filter(DBEvent.experience_level.in_([l.lower() for l in experience_levels]))
    if start_from:
        query = query.filter(DBEvent.start_date >= start_from)
    if date_to:
        query = query.filter(DBEvent.start_date <= date_to)

    events = query.all()

    if latitude and longitude:
        nearby = []
        for event in events:
            if event.latitude and event.longitude:
                dist = geodesic((latitude, longitude), (event.latitude, event.longitude)).miles
                if dist <= radius_miles:
                    enrich_event(event, db, current_user_id)
                    nearby.append(event)
        return nearby

    for event in events:
        enrich_event(event, db, current_user_id)
    return events


@router.get("/sports-events/{event_id}", response_model=Event)
async def get_event(
    event_id: UUID,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(default=None),
):
    current_user_id = _get_user_id_from_header(authorization, db)
    event = db.query(DBEvent).filter(DBEvent.event_id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return enrich_event(event, db, current_user_id)


# ── Join / Leave ──────────────────────────────────────────────────────────────

@router.post("/sports-events/{event_id}/join")
async def join_event(event_id: UUID, db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    event = db.query(DBEvent).filter(DBEvent.event_id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if event.status != 'active':
        raise HTTPException(status_code=400, detail="Event is not active")
    if db.query(DBEventParticipant).filter_by(event_id=event_id, user_id=current_user.user_id).first():
        raise HTTPException(status_code=400, detail="Already joined this event")
    count = db.query(DBEventParticipant).filter_by(event_id=event_id).count()
    if count >= event.max_players:
        raise HTTPException(status_code=400, detail="Event is full")

    db.add(DBEventParticipant(event_id=event_id, user_id=current_user.user_id))
    db.commit()
    return {"message": "Joined event successfully"}


@router.delete("/sports-events/{event_id}/leave")
async def leave_event(event_id: UUID, db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    event = db.query(DBEvent).filter(DBEvent.event_id == event_id).first()
    if event and event.organizer_id == current_user.user_id:
        raise HTTPException(status_code=400, detail="Organizer cannot leave their own event")
    participant = db.query(DBEventParticipant).filter_by(event_id=event_id, user_id=current_user.user_id).first()
    if not participant:
        raise HTTPException(status_code=404, detail="You are not a participant of this event")
    db.delete(participant)
    db.commit()
    return {"message": "Left event successfully"}


@router.delete("/sports-events/{event_id}")
async def delete_event(event_id: UUID, db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    event = db.query(DBEvent).filter(DBEvent.event_id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if event.organizer_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="Only the organizer can delete this event")
    archive_event(db, event, reason='deleted_by_organizer')
    db.commit()
    return {"message": "Event archived"}


# ── Rate Host ─────────────────────────────────────────────────────────────────
# Works for BOTH active events and archived events

class RateHostRequest(BaseModel):
    rating: int
    comment: Optional[str] = None


@router.post("/sports-events/{event_id}/rate-host")
async def rate_host(
    event_id: UUID,
    body: RateHostRequest,
    db: Session = Depends(get_db),
    current_user: DBUser = Depends(get_current_user),
):
    # Try active events first
    organizer_id = None
    event = db.query(DBEvent).filter(DBEvent.event_id == event_id).first()
    if event:
        organizer_id = event.organizer_id
    else:
        # Check archived events
        archived = db.query(DBArchivedEvent).filter(DBArchivedEvent.event_id == event_id).first()
        if not archived:
            raise HTTPException(status_code=404, detail="Event not found")
        organizer_id = archived.organizer_id
        # Verify user was a participant
        participant_ids = json.loads(archived.participant_ids) if archived.participant_ids else []
        if str(current_user.user_id) not in participant_ids:
            raise HTTPException(status_code=403, detail="You did not attend this event")

    if organizer_id == current_user.user_id:
        raise HTTPException(status_code=400, detail="Cannot rate yourself")
    if body.rating < 1 or body.rating > 5:
        raise HTTPException(status_code=400, detail="Rating must be 1-5")

    existing = db.query(DBHostRating).filter_by(
        event_id=event_id, rater_id=current_user.user_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Already rated this host for this event")

    new_rating = DBHostRating(
        event_id=event_id,
        rater_id=current_user.user_id,
        host_id=organizer_id,
        rating=body.rating,
        comment=body.comment,
    )
    db.add(new_rating)

    # Update host average
    host = db.query(DBUser).filter(DBUser.user_id == organizer_id).first()
    if host:
        all_ratings = db.query(DBHostRating).filter(DBHostRating.host_id == host.user_id).all()
        total = len(all_ratings) + 1
        avg = (sum(r.rating for r in all_ratings) + body.rating) / total
        host.host_rating = round(avg, 2)
        host.total_ratings = total

    db.commit()
    return {
        "message": "Rating submitted",
        "new_average": float(host.host_rating) if host and host.host_rating else None,
        "total_ratings": host.total_ratings if host else 0,
    }


# ── Archive ───────────────────────────────────────────────────────────────────

@router.post("/sports-events/archive-expired")
async def archive_expired_events(db: Session = Depends(get_db)):
    """Archives events whose date has passed or whose end_time today has passed."""
    now = datetime.utcnow()
    today = date.today()

    # All events with start_date before today
    expired = db.query(DBEvent).filter(DBEvent.start_date < today).all()

    # Also grab today's events where end_time has passed
    if now.hour > 0:  # avoid edge case at midnight
        today_events = db.query(DBEvent).filter(DBEvent.start_date == today).all()
        for event in today_events:
            if event.end_time and datetime.combine(today, event.end_time) < now:
                expired.append(event)
            elif not event.end_time and event.start_time:
                # No end_time: assume 2 hour duration
                assumed_end = datetime.combine(today, event.start_time) + timedelta(hours=2)
                if assumed_end < now:
                    expired.append(event)

    # Deduplicate
    seen = set()
    unique_expired = []
    for e in expired:
        if e.event_id not in seen:
            seen.add(e.event_id)
            unique_expired.append(e)

    count = len(unique_expired)
    for event in unique_expired:
        archive_event(db, event, reason='expired')
    db.commit()
    return {"archived": count}


# ── Event History ─────────────────────────────────────────────────────────────

@router.get("/users/me/event-history")
async def get_event_history(current_user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    organized = db.query(DBArchivedEvent).filter(
        DBArchivedEvent.organizer_id == current_user.user_id
    ).order_by(DBArchivedEvent.start_date.desc()).limit(20).all()

    def serialize(e):
        return {
            "archive_id":       str(e.archive_id),
            "event_id":         str(e.event_id),
            "title":            e.title,
            "sport":            e.sport,
            "start_date":       str(e.start_date),
            "location":         e.location,
            "participant_count":e.participant_count,
            "archive_reason":   e.archive_reason,
        }
    return {"organized": [serialize(e) for e in organized]}


# ── Pending Ratings (unrated events user attended) ────────────────────────────

@router.get("/users/me/pending-ratings")
async def get_pending_ratings(
    current_user: DBUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Returns archived events the user attended but hasn't rated yet."""
    user_id_str = str(current_user.user_id)
    two_weeks_ago = date.today() - timedelta(days=14)

    # Get archived events from last 2 weeks
    archived = db.query(DBArchivedEvent).filter(
        DBArchivedEvent.start_date >= two_weeks_ago,
        DBArchivedEvent.archive_reason == 'expired',
    ).order_by(DBArchivedEvent.start_date.desc()).all()

    pending = []
    for event in archived:
        # Check if user was a participant
        participant_ids = json.loads(event.participant_ids) if event.participant_ids else []
        if user_id_str not in participant_ids:
            continue
        # Skip if user was the organizer
        if event.organizer_id == current_user.user_id:
            continue
        # Check if already rated
        already_rated = db.query(DBHostRating).filter_by(
            event_id=event.event_id, rater_id=current_user.user_id
        ).first()
        if already_rated:
            continue

        pending.append({
            "event_id":       str(event.event_id),
            "title":          event.title,
            "sport":          event.sport,
            "start_date":     str(event.start_date),
            "start_time":     str(event.start_time) if event.start_time else None,
            "location":       event.location,
            "organizer_id":   str(event.organizer_id) if event.organizer_id else None,
            "organizer_name": event.organizer_name,
        })

    return {"pending": pending}


# ── Recent Activity (past events from last 2 weeks) ──────────────────────────

@router.get("/users/me/recent-activity")
async def get_recent_activity(
    current_user: DBUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Returns past events the user attended in the last 2 weeks, with rating status."""
    user_id_str = str(current_user.user_id)
    two_weeks_ago = date.today() - timedelta(days=14)

    archived = db.query(DBArchivedEvent).filter(
        DBArchivedEvent.start_date >= two_weeks_ago,
    ).order_by(DBArchivedEvent.start_date.desc()).all()

    activities = []
    for event in archived:
        participant_ids = json.loads(event.participant_ids) if event.participant_ids else []
        if user_id_str not in participant_ids and event.organizer_id != current_user.user_id:
            continue

        is_organizer = (event.organizer_id == current_user.user_id)

        # Check if user rated this event's host
        my_rating = None
        if not is_organizer:
            rating = db.query(DBHostRating).filter_by(
                event_id=event.event_id, rater_id=current_user.user_id
            ).first()
            if rating:
                my_rating = rating.rating

        activities.append({
            "event_id":       str(event.event_id),
            "title":          event.title,
            "sport":          event.sport,
            "start_date":     str(event.start_date),
            "start_time":     str(event.start_time) if event.start_time else None,
            "location":       event.location,
            "organizer_name": event.organizer_name,
            "is_organizer":   is_organizer,
            "my_rating":      my_rating,      # null = not yet rated, int = already rated
            "can_rate":       not is_organizer and my_rating is None,
        })

    return {"activities": activities}


# ── Public Recent Activity (for viewing other profiles) ───────────────────────

@router.get("/users/{user_id}/recent-activity")
async def get_user_recent_activity(user_id: UUID, db: Session = Depends(get_db)):
    """Public view of a user's recent events — no rating info shown."""
    user_id_str = str(user_id)
    two_weeks_ago = date.today() - timedelta(days=14)

    archived = db.query(DBArchivedEvent).filter(
        DBArchivedEvent.start_date >= two_weeks_ago,
    ).order_by(DBArchivedEvent.start_date.desc()).all()

    activities = []
    for event in archived:
        participant_ids = json.loads(event.participant_ids) if event.participant_ids else []
        if user_id_str not in participant_ids and str(event.organizer_id) != user_id_str:
            continue

        activities.append({
            "event_id":       str(event.event_id),
            "title":          event.title,
            "sport":          event.sport,
            "start_date":     str(event.start_date),
            "location":       event.location,
            "is_organizer":   str(event.organizer_id) == user_id_str,
        })

    return {"activities": activities}
