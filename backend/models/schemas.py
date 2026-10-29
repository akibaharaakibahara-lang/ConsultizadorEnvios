from pydantic import BaseModel, EmailStr, Field, model_validator


class CotizacionRequest(BaseModel):
    zona: int = Field(ge=1, le=4)
    peso: float = Field(gt=0)
    largo: float | None = Field(default=None, gt=0)
    ancho: float | None = Field(default=None, gt=0)
    alto: float | None = Field(default=None, gt=0)
    solicitud_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validar_dimensiones_completas(self):
        dimensiones = (self.largo, self.ancho, self.alto)
        if any(dimension is not None for dimension in dimensiones) and any(
            dimension is None for dimension in dimensiones
        ):
            raise ValueError(
                "Debes enviar largo, ancho y alto, o dejar las tres dimensiones vacías."
            )
        return self


class SolicitudCotizacionRequest(BaseModel):
    email: EmailStr
    codigo_postal1: str = Field(min_length=5, max_length=10)
    codigo_postal2: str = Field(min_length=5, max_length=10)
    peso: float = Field(gt=0)
    largo: float | None = Field(default=None, gt=0)
    ancho: float | None = Field(default=None, gt=0)
    alto: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validar_dimensiones_completas(self):
        dimensiones = (self.largo, self.ancho, self.alto)
        if any(dimension is not None for dimension in dimensiones) and any(
            dimension is None for dimension in dimensiones
        ):
            raise ValueError(
                "Debes enviar largo, ancho y alto, o dejar las tres dimensiones vacías."
            )
        return self