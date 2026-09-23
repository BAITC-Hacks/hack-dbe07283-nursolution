"""Защищённое редактирование каталога PostgreSQL."""
from dataclasses import asdict
from secrets import compare_digest
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.domain.models import Contractor
from app.domain.validation import iso_date
from app.repositories.postgres import CatalogConflict

router = APIRouter(prefix='/admin/api', tags=['Редактор'])
Text = Annotated[str, Field(min_length=1, max_length=200)]


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,80}$')
    anon_name: Text
    city: Text
    categories: list[Text] = Field(min_length=1, max_length=30)
    event_formats: list[Text] = Field(min_length=1, max_length=30)
    languages: list[Text] = Field(min_length=1, max_length=30)
    price_from_kzt: int = Field(ge=0)
    max_hours: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    busy_dates: list[str] = Field(default_factory=list, max_length=3660)
    description: str = Field(default='', max_length=10000)

    @field_validator('busy_dates')
    @classmethod
    def dates(cls, values):
        return sorted(set(iso_date(value) for value in values))

    def contractor(self):
        fields = self.model_dump()
        for key in ('categories', 'event_formats', 'languages', 'busy_dates'):
            fields[key] = tuple(dict.fromkeys(fields[key]))
        return Contractor(**fields)


class UpdateInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    profile: ProfileInput
    revision: int = Field(ge=1)


def authorized(request: Request):
    expected = request.app.state.admin_token
    if not expected:
        raise HTTPException(503, 'Редактор выключен: задайте ADMIN_TOKEN.')
    supplied = request.headers.get('authorization', '')
    if not compare_digest(supplied.encode(), f'Bearer {expected}'.encode()):
        raise HTTPException(401, 'Требуется ключ редактора.')
    return request.app.state.matcher.repository


@router.get('/contractors')
def list_contractors(repository=Depends(authorized)):
    records = repository.records() if repository.backend == 'postgres' else [
        dict(profile=asdict(profile), revision=None) for profile in repository.load()]
    return dict(backend=repository.backend, editable=repository.backend == 'postgres', records=records)


def save(repository, profile, revision=None):
    if repository.backend != 'postgres':
        raise HTTPException(409, 'CSV доступен только для чтения. Переключите CATALOG_BACKEND на postgres.')
    try:
        return repository.save(profile.contractor(), revision)
    except CatalogConflict as exc:
        raise HTTPException(409, str(exc)) from None


@router.post('/contractors', status_code=201)
def create_profile(profile: ProfileInput, repository=Depends(authorized)):
    return save(repository, profile)


@router.put('/contractors/{identifier}')
def update_profile(identifier: str, payload: UpdateInput, repository=Depends(authorized)):
    if identifier != payload.profile.id:
        raise HTTPException(422, 'ID профиля нельзя изменить.')
    return save(repository, payload.profile, payload.revision)
