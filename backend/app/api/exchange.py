from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import audit, get_session
from app.exchange import credentials as creds

router = APIRouter(prefix="/api/exchange", tags=["exchange"])


@router.get("/credentials")
def get_status():
    return [creds.status("testnet"), creds.status("mainnet")]


class CredentialsIn(BaseModel):
    api_key: str = Field(min_length=16, max_length=128)
    api_secret: str = Field(min_length=16, max_length=128)


@router.put("/credentials/{env}")
def put_credentials(env: creds.Env, body: CredentialsIn, session: Session = Depends(get_session)):
    creds.save_credentials(env, body.api_key.strip(), body.api_secret.strip())
    audit(session, "exchange.credentials.save", {"env": env})  # 키 값은 기록하지 않음
    session.commit()
    return creds.status(env)


@router.delete("/credentials/{env}")
def delete_credentials(env: creds.Env, session: Session = Depends(get_session)):
    creds.delete_credentials(env)
    audit(session, "exchange.credentials.delete", {"env": env})
    session.commit()
    return creds.status(env)


@router.post("/credentials/{env}/test")
def test_credentials(env: creds.Env):
    return creds.test_connection(env)
