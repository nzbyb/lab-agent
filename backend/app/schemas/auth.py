from pydantic import BaseModel, Field

from app.schemas.user import UserResponse


class LoginRequest(BaseModel):
    username: str = Field(max_length=50)
    password: str


class LoginResponse(BaseModel):
    token: str
    user: UserResponse


class RegisterRequest(BaseModel):
    username: str = Field(max_length=50)
    password: str
    name: str | None = Field(default=None, max_length=50)
