"""Personal API tokens for the Open API (integrations, scripts, BI tools).

The plain token is shown once at creation; only its SHA-256 is stored.
Use it as `Authorization: Bearer twk_…` with any endpoint in /docs.
Tokens cannot manage other tokens (no privilege bootstrapping)."""

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ApiToken, User
from app.security import API_TOKEN_PREFIX, get_current_user, hash_api_token

router = APIRouter(prefix="/api/tokens", tags=["api tokens"])


class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    read_only: bool = True
    expires_days: int | None = Field(None, ge=1, le=3650)


class TokenOut(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    read_only: bool
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None


class TokenCreated(TokenOut):
    token: str


def _session_only(request: Request) -> None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer ") and auth[7:].startswith(API_TOKEN_PREFIX):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API tokens cannot manage tokens")


@router.get("", response_model=list[TokenOut])
def list_tokens(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _session_only(request)
    return db.query(ApiToken).filter(ApiToken.user_id == user.id).order_by(ApiToken.created_at.desc()).all()


@router.post("", response_model=TokenCreated, status_code=status.HTTP_201_CREATED)
def create_token(body: TokenIn, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _session_only(request)
    plain = API_TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = ApiToken(
        user_id=user.id, name=body.name, prefix=plain[:12], token_hash=hash_api_token(plain), read_only=body.read_only,
        expires_at=datetime.now(timezone.utc) + timedelta(days=body.expires_days) if body.expires_days else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return TokenCreated(**TokenOut.model_validate(row, from_attributes=True).model_dump(), token=plain)


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_token(token_id: uuid.UUID, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _session_only(request)
    n = db.query(ApiToken).filter(ApiToken.id == token_id, ApiToken.user_id == user.id).delete()
    db.commit()
    if not n:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
