from pydantic import BaseModel
from typing import List

class HistoryMessage(BaseModel):
    role: str
    content: str

class QueryRequest(BaseModel):
    query: str
    history: List[HistoryMessage] = []

class NotesBody(BaseModel):
    notes: str
