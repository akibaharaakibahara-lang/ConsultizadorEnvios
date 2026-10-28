
from postal_codes import get_postal_code_info
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from database import SessionLocal
from models import Paqueteria, Tarifa, SolicitudCotizacion
from models.schemas import CotizacionRequest
import math


app = FastAPI(
    title="V1 API",
    description="API para cotizaciones de servicios de paquetería",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "V1 API",
    }


def calculate_distance_km(
    latitude1: float,
    longitude1: float,
    latitude2: float,
    longitude2: float,
) -> float:
    earth_radius_km = 6371.0

    lat1 = math.radians(latitude1)
    lon1 = math.radians(longitude1)
    lat2 = math.radians(latitude2)
    lon2 = math.radians(longitude2)

    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )

    a = min(1.0, max(0.0, a))

    central_angle = 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a),
    )

    return round(earth_radius_km * central_angle, 2)


def clasificar_zona(distancia_km: float) -> int:
    if distancia_km < 0:
        raise ValueError("La distancia no puede ser negativa")

    if distancia_km <= 100:
        return 1
    elif distancia_km <= 500:
        return 2
    elif distancia_km <= 1000:
        return 3
    else:
        return 4


def obtener_codigo_postal(codigo_postal: str):
    try:
        return get_postal_code_info(codigo_postal)
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc


@app.get("/postal-codes/{postal_code}")
def postal_code_lookup(postal_code: str):
    return obtener_codigo_postal(postal_code)


class DistanceRequest(BaseModel):
    codigo_postal1: str
    codigo_postal2: str


class SolicitudCotizacionRequest(BaseModel):
    email: EmailStr
    codigo_postal1: str = Field(min_length=5, max_length=10)
    codigo_postal2: str = Field(min_length=5, max_length=10)
    peso: float = Field(gt=0)


@app.post("/distance")
def get_distance(request: DistanceRequest):
    origin = obtener_codigo_postal(request.codigo_postal1)
    destination = obtener_codigo_postal(request.codigo_postal2)

    distance = calculate_distance_km(
        origin["latitude"],
        origin["longitude"],
        destination["latitude"],
        destination["longitude"],
    )

    zona = clasificar_zona(distance)

    return {
        "codigo_postal1": origin["postal_code"],
        "codigo_postal2": destination["postal_code"],
        "origen": {
            "localidad": origin["place"],
            "estado": origin["state"],
            "latitud": origin["latitude"],
            "longitud": origin["longitude"],
        },
        "destino": {
            "localidad": destination["place"],
            "estado": destination["state"],
            "latitud": destination["latitude"],
            "longitud": destination["longitude"],
        },
        "distancia_km": round(distance, 2),
        "zona": zona,
    }


@app.post("/cotizaciones")
def consultar_cotizaciones(request: CotizacionRequest):
    if request.zona not in {1, 2, 3, 4}:
        raise HTTPException(
            status_code=400,
            detail="La zona debe ser un número del 1 al 4",
        )

    if request.peso <= 0:
        raise HTTPException(
            status_code=400,
            detail="El peso debe ser mayor que cero",
        )

    with SessionLocal() as session:
        consulta = (
            select(Tarifa, Paqueteria)
            .join(
                Paqueteria,
                Tarifa.id_empresas == Paqueteria.carrier_id,
            )
            .where(
                Tarifa.zona == request.zona,
                Tarifa.peso_min <= request.peso,
                Tarifa.peso_max > request.peso,
                Paqueteria.activo.is_(True),
            )
            .order_by(Tarifa.precio.asc())
        )

        resultados = session.execute(consulta).all()

        opciones = [
            {
                "id_empresas": tarifa.id_empresas,
                "paqueteria": paqueteria.nombre,
                "zona": tarifa.zona,
                "peso_min": float(tarifa.peso_min),
                "peso_max": float(tarifa.peso_max),
                "precio": float(tarifa.precio),
                "dias_entrega": tarifa.dias_entrega,
                "vigencia_desde": tarifa.vigencia_desde,
            }
            for tarifa, paqueteria in resultados
        ]

    return {
        "zona": request.zona,
        "peso_kg": request.peso,
        "total_opciones": len(opciones),
        "opciones": opciones,
    }


@app.post("/solicitudes-cotizacion")
def crear_solicitud_cotizacion(
    request: SolicitudCotizacionRequest,
):
    origen = obtener_codigo_postal(request.codigo_postal1)
    destino = obtener_codigo_postal(request.codigo_postal2)

    distancia = calculate_distance_km(
        origen["latitude"],
        origen["longitude"],
        destino["latitude"],
        destino["longitude"],
    )

    zona = clasificar_zona(distancia)

    nueva_solicitud = SolicitudCotizacion(
        email=str(request.email),
        codigo_postal1=origen["postal_code"],
        codigo_postal2=destino["postal_code"],
        peso=request.peso,
        zona=zona,
    )

    with SessionLocal() as session:
        session.add(nueva_solicitud)
        session.commit()
        session.refresh(nueva_solicitud)

        return {
            "mensaje": "Solicitud guardada correctamente",
            "id": nueva_solicitud.id,
            "email": nueva_solicitud.email,
            "codigo_postal1": nueva_solicitud.codigo_postal1,
            "codigo_postal2": nueva_solicitud.codigo_postal2,
            "peso": float(nueva_solicitud.peso),
            "zona": nueva_solicitud.zona,
            "fecha_creacion": (
                nueva_solicitud.fecha_creacion.isoformat()
            ),
        }
