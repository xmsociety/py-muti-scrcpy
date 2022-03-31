from socket import socket
from typing import Dict, List, Optional

from pydantic import BaseModel


class RunMode(BaseModel):
    Pvp: str
    Earning: str
    All: List[str]


class ServerInfo(BaseModel):
    host: str
    port: int
    server: socket = None

    class Config:
        arbitrary_types_allowed = True


runmode = RunMode(Pvp="pvp", Earning="earning", All=["pvp", "earning"])
