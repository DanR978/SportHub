from fastapi import APIRouter
from models.user import User, UserCreate
from models.db_user import DBUser
from sqlalchemy.orm import Session
from fastapi import Depends
from database import get_db
from fastapi import HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from auth import hash_password, verify_password, create_access_token

router = APIRouter()

@router.post("/users/signup", response_model=User)
async def create_user(user: UserCreate, db: Session = Depends(get_db)):
    hashed = hash_password(user.password)
    new_user = DBUser(**user.model_dump(exclude={"password"}), hashed_password=hashed)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@router.post("/users/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(DBUser).filter(DBUser.email == form_data.username).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    if not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    token = create_access_token(data={"sub": user.email})
    return {"access_token": token, "token_type": "bearer"}