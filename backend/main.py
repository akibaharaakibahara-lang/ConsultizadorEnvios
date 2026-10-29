
from contextlib import asynccontextmanager
from datetime import date

from postal_codes import get_postal_code_info
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from database import SessionLocal
from models import Cotizacion, Paqueteria, Tarifa, SolicitudCotizacion
from models.schemas import CotizacionRequest, SolicitudCotizacionRequest
from schema_migrations import upgrade_schema
from tariff_dates import select_applicable_tariffs
import math


@asynccontextmanager
async def lifespan(_app):
    upgrade_schema()
    yield


app = FastAPI(
    title="V1 API",
    description="API para cotizaciones de servicios de paquetería",
    version="1.0.0",
    lifespan=lifespan,
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

    dimensiones_completas = all(
        dimension is not None
        for dimension in (request.largo, request.ancho, request.alto)
    )
    peso_volumetrico = None
    if dimensiones_completas:
        peso_volumetrico = (
            request.largo * request.ancho * request.alto
        ) / 5000

    with SessionLocal() as session:
        solicitud = None
        if request.solicitud_id is not None:
            solicitud = session.get(
                SolicitudCotizacion,
                request.solicitud_id,
            )
            if solicitud is None:
                raise HTTPException(
                    status_code=404,
                    detail="No se encontró la solicitud de cotización.",
                )

        # Consultar tarifas de la zona y aplicar el booleano volumetrico
        # guardado para cada paquetería.
        consulta = (
            select(Tarifa, Paqueteria)
            .join(
                Paqueteria,
                Tarifa.id_empresas == Paqueteria.carrier_id,
            )
            .where(
                Tarifa.zona == request.zona,
                Paqueteria.activo.is_(True),
            )
        )

        resultados = session.execute(consulta).all()
        tarifas_por_paqueteria = {}
        for tarifa, paqueteria in resultados:
            tarifas_por_paqueteria.setdefault(
                paqueteria.carrier_id,
                {"paqueteria": paqueteria, "tarifas": []},
            )["tarifas"].append(tarifa)

        opciones = []
        hoy = date.today()
        for data in tarifas_por_paqueteria.values():
            paqueteria = data["paqueteria"]
            usa_volumetrico = (
                paqueteria.volumetrico
                and peso_volumetrico is not None
                and (
                    paqueteria.volumetrico_desde is None
                    or hoy >= paqueteria.volumetrico_desde
                )
            )
            pesos_a_cotizar = [request.peso]
            if usa_volumetrico:
                pesos_a_cotizar.append(peso_volumetrico)

            candidatas = []
            for peso_facturable in pesos_a_cotizar:
                tarifas_aplicables = select_applicable_tariffs(
                    data["tarifas"],
                    peso_facturable,
                    hoy,
                )
                for tarifa in tarifas_aplicables:
                    candidatas.append(
                        {
                            "id_empresas": tarifa.id_empresas,
                            "paqueteria": paqueteria.nombre,
                            "zona": tarifa.zona,
                            "peso_min": float(tarifa.peso_min),
                            "peso_max": float(tarifa.peso_max),
                            "precio": float(tarifa.precio),
                            "dias_entrega": tarifa.dias_entrega,
                            "vigencia_desde": tarifa.vigencia_desde,
                            "peso_real": request.peso,
                            "peso_volumetrico": (
                                peso_volumetrico if usa_volumetrico else None
                            ),
                            "peso_facturable": peso_facturable,
                        }
                    )

            if usa_volumetrico and candidatas:
                opciones.append(
                    max(candidatas, key=lambda opcion: opcion["precio"])
                )
            else:
                opciones.extend(candidatas)

        opciones.sort(key=lambda opcion: opcion["precio"])

        if solicitud is not None:
            if (
                solicitud.zona != request.zona
                or float(solicitud.peso) != request.peso
            ):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "La solicitud no coincide con la zona y el peso "
                        "de la cotización."
                    ),
                )

            dimensiones_solicitud = (
                solicitud.largo,
                solicitud.ancho,
                solicitud.alto,
            )
            dimensiones_cotizacion = (
                request.largo,
                request.ancho,
                request.alto,
            )
            dimensiones_coinciden = all(
                (
                    guardada is None
                    and enviada is None
                    or guardada is not None
                    and enviada is not None
                    and float(guardada) == enviada
                )
                for guardada, enviada in zip(
                    dimensiones_solicitud,
                    dimensiones_cotizacion,
                )
            )
            if not dimensiones_coinciden:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Las dimensiones no coinciden con la solicitud "
                        "guardada."
                    ),
                )

            for opcion in opciones:
                session.add(
                    Cotizacion(
                        solicitud_id=solicitud.id,
                        paqueteria=opcion["paqueteria"],
                        precio_cotizado=opcion["precio"],
                        peso_min=opcion["peso_min"],
                        peso_max=opcion["peso_max"],
                        peso_facturable=opcion["peso_facturable"],
                        dias_entrega=opcion["dias_entrega"],
                        vigencia_desde=opcion["vigencia_desde"],
                    )
                )
            session.commit()

    return {
        "zona": request.zona,
        "peso_kg": request.peso,
        "peso_volumetrico_kg": peso_volumetrico,
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
    dimensiones_completas = all(
        dimension is not None
        for dimension in (request.largo, request.ancho, request.alto)
    )
    peso_volumetrico = None
    if dimensiones_completas:
        peso_volumetrico = (
            request.largo * request.ancho * request.alto
        ) / 5000

    nueva_solicitud = SolicitudCotizacion(
        email=str(request.email),
        codigo_postal1=origen["postal_code"],
        codigo_postal2=destino["postal_code"],
        peso=request.peso,
        zona=zona,
        largo=request.largo,
        ancho=request.ancho,
        alto=request.alto,
        peso_volumetrico=peso_volumetrico,
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
            "largo": nueva_solicitud.largo,
            "ancho": nueva_solicitud.ancho,
            "alto": nueva_solicitud.alto,
            "peso_volumetrico": nueva_solicitud.peso_volumetrico,
            "fecha_creacion": (
                nueva_solicitud.fecha_creacion.isoformat()
            ),
        }


@app.get("/solicitudes-cotizacion/{solicitud_id}")
def consultar_solicitud_cotizacion(
    solicitud_id: int,
    email: EmailStr,
):
    with SessionLocal() as session:
        solicitud = session.get(SolicitudCotizacion, solicitud_id)
        if (
            solicitud is None
            or solicitud.email.casefold() != str(email).casefold()
        ):
            raise HTTPException(
                status_code=404,
                detail="No se encontró la solicitud de cotización.",
            )

        cotizaciones = session.execute(
            select(Cotizacion)
            .where(Cotizacion.solicitud_id == solicitud_id)
            .order_by(Cotizacion.id.asc())
        ).scalars().all()

        return {
            "id": solicitud.id,
            "email": solicitud.email,
            "codigo_postal1": solicitud.codigo_postal1,
            "codigo_postal2": solicitud.codigo_postal2,
            "peso": float(solicitud.peso),
            "zona": solicitud.zona,
            "largo": (
                float(solicitud.largo)
                if solicitud.largo is not None
                else None
            ),
            "ancho": (
                float(solicitud.ancho)
                if solicitud.ancho is not None
                else None
            ),
            "alto": (
                float(solicitud.alto)
                if solicitud.alto is not None
                else None
            ),
            "peso_volumetrico": (
                float(solicitud.peso_volumetrico)
                if solicitud.peso_volumetrico is not None
                else None
            ),
            "fecha_creacion": solicitud.fecha_creacion.isoformat(),
            "total_opciones": len(cotizaciones),
            "opciones": [
                {
                    "paqueteria": cotizacion.paqueteria,
                    "precio": float(cotizacion.precio_cotizado),
                    "peso_min": (
                        float(cotizacion.peso_min)
                        if cotizacion.peso_min is not None
                        else None
                    ),
                    "peso_max": (
                        float(cotizacion.peso_max)
                        if cotizacion.peso_max is not None
                        else None
                    ),
                    "peso_facturable": (
                        float(cotizacion.peso_facturable)
                        if cotizacion.peso_facturable is not None
                        else None
                    ),
                    "dias_entrega": cotizacion.dias_entrega,
                    "vigencia_desde": cotizacion.vigencia_desde,
                    "referencia_historica": cotizacion.referencia_historica,
                }
                for cotizacion in cotizaciones
            ],
        }
