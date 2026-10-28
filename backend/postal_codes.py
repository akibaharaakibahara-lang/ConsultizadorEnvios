
import httpx
from fastapi import HTTPException


ZIPPOTAM_URL = "https://api.zippopotam.us/mx"


def get_postal_code_info(postal_code: str) -> dict:
    postal_code = postal_code.strip()

    if len(postal_code) != 5 or not postal_code.isdigit():
        raise HTTPException(
            status_code=400,
            detail="El código postal debe contener exactamente 5 dígitos.",
        )

    try:
        response = httpx.get(
            f"{ZIPPOTAM_URL}/{postal_code}",
            timeout=10.0,
        )
    except httpx.RequestError:
        raise HTTPException(
            status_code=503,
            detail="No fue posible consultar el servicio de códigos postales.",
        )

    if response.status_code == 404:
        raise HTTPException(
            status_code=404,
            detail="No se encontró el código postal.",
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail="El servicio de códigos postales respondió con un error.",
        )

    data = response.json()
    places = data.get("places", [])

    if not places:
        raise HTTPException(
            status_code=404,
            detail="El código postal no tiene ubicaciones disponibles.",
        )

    place = places[0]

    try:
        latitude = float(place["latitude"])
        longitude = float(place["longitude"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=502,
            detail="El servicio no devolvió coordenadas válidas.",
        )

    return {
        "postal_code": data.get("post code", postal_code),
        "place": place.get("place name"),
        "state": place.get("state"),
        "latitude": latitude,
        "longitude": longitude,
    }
