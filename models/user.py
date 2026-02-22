from uuid import UUID, uuid4
from pydantic import BaseModel, EmailStr, Field
from datetime import date

class UserBase(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    date_of_birth: date
    nationality: str
    phone_number: str | None = None

class UserCreate(UserBase):
    password: str

class User(UserBase):
    user_id: UUID = Field(default_factory=uuid4)