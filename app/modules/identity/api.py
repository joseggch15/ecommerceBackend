"""Endpoints del módulo de identidad."""

import uuid

from fastapi import APIRouter, Depends, Response, status

from app.core.config import settings
from app.core.rate_limit import rate_limit
from app.modules.identity.deps import get_auth_service, get_current_user, get_user_service
from app.modules.identity.models import Address, User
from app.modules.identity.schemas import (
    AddressCreate,
    AddressOut,
    AddressUpdate,
    EmailRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenPair,
    UserOut,
    UserUpdate,
    VerifyEmailRequest,
)
from app.modules.identity.service import AuthService, UserService

router = APIRouter(tags=["identity"])

# Rate limits por endpoint (se construyen una sola vez al importar el módulo).
register_rate_limit = Depends(
    rate_limit("register", settings.RATE_LIMIT_REGISTER_MAX, settings.RATE_LIMIT_WINDOW_SECONDS)
)
login_rate_limit = Depends(
    rate_limit("login", settings.RATE_LIMIT_LOGIN_MAX, settings.RATE_LIMIT_WINDOW_SECONDS)
)
password_reset_rate_limit = Depends(
    rate_limit(
        "password_reset", settings.RATE_LIMIT_PASSWORD_RESET_MAX, settings.RATE_LIMIT_WINDOW_SECONDS
    )
)


# ---------- Auth ----------


@router.post(
    "/auth/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[register_rate_limit],
)
async def register(
    data: RegisterRequest,
    service: AuthService = Depends(get_auth_service),
) -> User:
    return await service.register(data)


@router.post("/auth/login", response_model=TokenPair, dependencies=[login_rate_limit])
async def login(
    data: LoginRequest,
    service: AuthService = Depends(get_auth_service),
) -> TokenPair:
    return await service.login(data.email, data.password)


@router.post("/auth/refresh", response_model=TokenPair)
async def refresh(
    data: RefreshRequest,
    service: AuthService = Depends(get_auth_service),
) -> TokenPair:
    return await service.refresh(data.refresh_token)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    data: LogoutRequest,
    service: AuthService = Depends(get_auth_service),
) -> Response:
    await service.logout(data.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/auth/verify-email", status_code=status.HTTP_204_NO_CONTENT)
async def verify_email(
    data: VerifyEmailRequest,
    service: AuthService = Depends(get_auth_service),
) -> Response:
    await service.verify_email(data.token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/auth/resend-verification",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[password_reset_rate_limit],
)
async def resend_verification(
    data: EmailRequest,
    service: AuthService = Depends(get_auth_service),
) -> Response:
    await service.resend_verification(data.email)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/auth/forgot-password",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[password_reset_rate_limit],
)
async def forgot_password(
    data: EmailRequest,
    service: AuthService = Depends(get_auth_service),
) -> Response:
    await service.request_password_reset(data.email)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post(
    "/auth/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[password_reset_rate_limit],
)
async def reset_password(
    data: ResetPasswordRequest,
    service: AuthService = Depends(get_auth_service),
) -> Response:
    await service.reset_password(data.token, data.new_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- Perfil ----------


@router.get("/users/me", response_model=UserOut)
async def get_me(user: User = Depends(get_current_user)) -> User:
    return user


@router.patch("/users/me", response_model=UserOut)
async def update_me(
    data: UserUpdate,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
) -> User:
    return await service.update_profile(user, data)


# ---------- Direcciones ----------


@router.get("/users/me/addresses", response_model=list[AddressOut])
async def list_addresses(
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
) -> list[Address]:
    return await service.list_addresses(user.id)


@router.post(
    "/users/me/addresses",
    response_model=AddressOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_address(
    data: AddressCreate,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
) -> Address:
    return await service.create_address(user.id, data)


@router.patch("/users/me/addresses/{address_id}", response_model=AddressOut)
async def update_address(
    address_id: uuid.UUID,
    data: AddressUpdate,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
) -> Address:
    return await service.update_address(user.id, address_id, data)


@router.delete("/users/me/addresses/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_address(
    address_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
) -> Response:
    await service.delete_address(user.id, address_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
