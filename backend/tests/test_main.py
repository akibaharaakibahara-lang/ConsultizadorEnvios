import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uuid

import pytest
from sqlalchemy import select
from fastapi.testclient import TestClient

from database import SessionLocal
from models import SolicitudCotizacion
from main import clasificar_zona, app

client = TestClient(app)

def test_distancia_negativa_es_rechazada():
    """Una distancia negativa no debe aceptarse para clasificar zonas."""
    with pytest.raises(ValueError, match="negativa"):
        clasificar_zona(-1)


def test_invertir_origen_y_destino_no_produce_distancia_negativa(monkeypatch):
    """Invertir origen y destino debe conservar la distancia."""

    ubicaciones = {
        "64000": {
            "postal_code": "64000",
            "place": "Monterrey",
            "state": "Nuevo León",
            "latitude": 25.6866,
            "longitude": -100.3161,
        },
        "44100": {
            "postal_code": "44100",
            "place": "Guadalajara",
            "state": "Jalisco",
            "latitude": 20.6597,
            "longitude": -103.3496,
        },
    }

    monkeypatch.setattr(
        "main.get_postal_code_info",
        lambda codigo: ubicaciones[codigo],
    )

    ida = client.post(
        "/distance",
        json={
            "codigo_postal1": "64000",
            "codigo_postal2": "44100",
        },
    )

    vuelta = client.post(
        "/distance",
        json={
            "codigo_postal1": "44100",
            "codigo_postal2": "64000",
        },
    )

    assert ida.status_code == 200
    assert vuelta.status_code == 200

    distancia_ida = ida.json()["distancia_km"]
    distancia_vuelta = vuelta.json()["distancia_km"]

    assert distancia_ida >= 0
    assert distancia_vuelta >= 0
    assert distancia_ida == pytest.approx(distancia_vuelta, abs=0.01)
    assert ida.json()["zona"] == vuelta.json()["zona"]


def test_correo_se_guarda_correctamente_en_postgresql(monkeypatch):
    """El correo enviado debe existir en la base de datos."""

    ubicaciones = {
        "64000": {
            "postal_code": "64000",
            "place": "Monterrey",
            "state": "Nuevo León",
            "latitude": 25.6866,
            "longitude": -100.3161,
        },
        "44100": {
            "postal_code": "44100",
            "place": "Guadalajara",
            "state": "Jalisco",
            "latitude": 20.6597,
            "longitude": -103.3496,
        },
    }

    monkeypatch.setattr(
        "main.get_postal_code_info",
        lambda codigo: ubicaciones[codigo],
    )

    email_prueba = f"test-{uuid.uuid4().hex}@ejemplo.com"

    try:
        response = client.post(
            "/solicitudes-cotizacion",
            json={
                "email": email_prueba,
                "codigo_postal1": "64000",
                "codigo_postal2": "44100",
                "peso": 2.5,
            },
        )

        assert response.status_code == 200
        assert response.json()["email"] == email_prueba

        with SessionLocal() as session:
            solicitud = session.execute(
                select(SolicitudCotizacion).where(
                    SolicitudCotizacion.email == email_prueba
                )
            ).scalar_one_or_none()

            assert solicitud is not None
            assert solicitud.email == email_prueba
            assert solicitud.codigo_postal1 == "64000"
            assert solicitud.codigo_postal2 == "44100"
            assert float(solicitud.peso) == pytest.approx(2.5)
    finally:
        # Eliminar únicamente el registro temporal creado por esta prueba.
        with SessionLocal() as session:
            solicitud = session.execute(
                select(SolicitudCotizacion).where(
                    SolicitudCotizacion.email == email_prueba
                )
            ).scalar_one_or_none()

            if solicitud is not None:
                session.delete(solicitud)
                session.commit()

def test_peso_cero_es_rechazado():
    """No se debe aceptar un peso igual a cero."""
    response = client.post(
        "/solicitudes-cotizacion",
        json={
            "email": "peso-cero@ejemplo.com",
            "codigo_postal1": "64000",
            "codigo_postal2": "44100",
            "peso": 0,
        },
    )

    assert response.status_code == 422


def test_peso_negativo_es_rechazado():
    """No se debe aceptar un peso negativo."""
    response = client.post(
        "/solicitudes-cotizacion",
        json={
            "email": "peso-negativo@ejemplo.com",
            "codigo_postal1": "64000",
            "codigo_postal2": "44100",
            "peso": -2,
        },
    )

    assert response.status_code == 422


def test_correo_invalido_no_se_guarda():
    """Un correo inválido debe rechazarse antes de guardar."""
    response = client.post(
        "/solicitudes-cotizacion",
        json={
            "email": "esto-no-es-un-correo",
            "codigo_postal1": "64000",
            "codigo_postal2": "44100",
            "peso": 2.5,
        },
    )

    assert response.status_code == 422


def test_cotizaciones_rechaza_peso_cero():
    """El endpoint de tarifas debe rechazar un peso igual a cero."""
    response = client.post(
        "/cotizaciones",
        json={
            "zona": 1,
            "peso": 0,
        },
    )

    assert response.status_code == 422


def test_cotizaciones_rechaza_zona_invalida():
    """La zona debe estar entre 1 y 4."""
    response = client.post(
        "/cotizaciones",
        json={
            "zona": 5,
            "peso": 2.5,
        },
    )

    assert response.status_code == 422


def test_codigo_postal_inexistente_devuelve_error(monkeypatch):
    """Un código postal desconocido no debe producir un error 500."""

    def fake_postal_code_info(codigo):
        raise ValueError("Código postal no encontrado")

    monkeypatch.setattr(
        "main.get_postal_code_info",
        fake_postal_code_info,
    )

    response = client.post(
        "/distance",
        json={
            "codigo_postal1": "00000",
            "codigo_postal2": "44100",
        },
    )

    assert response.status_code in [400, 404, 422]
