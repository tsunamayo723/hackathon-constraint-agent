"""
マスタデータモデル
person / position / role / skill の正規化辞書。
ID参照はすべてここで解決する。
"""

from pydantic import BaseModel, ConfigDict


class Person(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    role_id: str | None = None   # None = 無役職
    skill_ids: list[str] = []


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str


class Role(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str


class Skill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str


class Masters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persons: list[Person]
    positions: list[Position]
    roles: list[Role]
    skills: list[Skill]
