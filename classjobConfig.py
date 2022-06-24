from pydantic import BaseModel
from xivapi.models import ClassJob


class ClassJobConfig(ClassJob):
    level: int
