from postal_codes import get_postal_code_info
from fastapi import FastAPI
import math
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

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
    central_angle = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return round(earth_radius_km * central_angle, 2)

@app.get("/postal-codes/{postal_code}")
def postal_code_lookup(postal_code: str):
    return get_postal_code_info(postal_code)

class DistanceRequest(BaseModel):
    codigo_postal1: str
    codigo_postal2: str


@app.post("/distance")
def get_distance(request: DistanceRequest):
    origin = get_postal_code_info(request.codigo_postal1)
    destination = get_postal_code_info(request.codigo_postal2)

    distance = calculate_distance_km(
        origin["latitude"],
        origin["longitude"],
        destination["latitude"],
        destination["longitude"],
    )

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
        "distancia_km": distance,
    }