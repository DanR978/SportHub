from sqlalchemy import Column, Date, String, Time
from sqlalchemy.dialects.postgresql import UUID
import uuid
from database import Base

class DBEvent(Base):
    __tablename__ = "events"

    event_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(100), index=True)
    sport = Column(String(100))
    start_date = Column(Date)
    start_time = Column(Time)
    location = Column(String(100))
    experience_level = Column(String(50))
    created_by = Column(String(100))