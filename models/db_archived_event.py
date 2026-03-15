from sqlalchemy import Column, Date, DateTime, Integer, Numeric, String, Text, Time, func
from sqlalchemy.dialects.postgresql import UUID
import uuid
from database import Base

class DBArchivedEvent(Base):
    __tablename__ = "archived_events"

    archive_id        = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id          = Column(UUID(as_uuid=True), nullable=False)
    title             = Column(String(200))
    sport             = Column(String(50))
    organizer_id      = Column(UUID(as_uuid=True), nullable=True)
    organizer_name    = Column(String(100))
    location          = Column(String(300))
    start_date        = Column(Date)
    start_time        = Column(Time)
    end_time          = Column(Time)
    max_players       = Column(Integer)
    participant_count = Column(Integer)
    experience_level  = Column(String(50))
    cost              = Column(Numeric(6, 2))
    description       = Column(String)
    archived_at       = Column(DateTime, default=func.now())
    archive_reason    = Column(String(50), default='expired')
    participant_ids   = Column(Text, nullable=True)
