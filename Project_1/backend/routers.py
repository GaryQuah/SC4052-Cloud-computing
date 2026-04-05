from fastapi import APIRouter, Body
from typing import Optional
import models
import controller

router = APIRouter()

@router.post("/query")
def query(req: models.QueryRequest):
    history = [{"role": m.role, "content": m.content} for m in req.history]
    return {"answer": controller.query_graph(req.query, history)}

@router.post("/load-meetings")
def load(notes_body: Optional[models.NotesBody] = Body(None)):
    notes = notes_body.notes if notes_body else None
    return controller.process_load_meetings(notes)

@router.get("/graph")
def get_graph():
    return controller.get_graph_data()