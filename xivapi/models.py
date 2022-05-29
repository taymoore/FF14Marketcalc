from typing import Any, Dict, List, Optional, Tuple, Type, Union
from pydantic import BaseModel


class ClassJob(BaseModel):
    ID: int
    Icon: str
    Name: str
    Url: str


class Pagination(BaseModel):
    Page: int
    PageNext: Any
    PagePrev: Any
    PageTotal: int
    Results: int
    ResultsPerPage: int
    ResultsTotal: int


class Page(BaseModel):
    Pagination: Pagination
    Results: List[Any]


class ClassJobCategory(BaseModel):
    Name: str


class ClassJobInfo(BaseModel):
    Abbreviation: str
    ClassJobCategory: ClassJobCategory
