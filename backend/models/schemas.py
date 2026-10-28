from pydantic import BaseModel, Field


class CotizacionRequest(BaseModel):
    zona: int = Field(ge=1, le=4)
    peso: float = Field(gt=0)