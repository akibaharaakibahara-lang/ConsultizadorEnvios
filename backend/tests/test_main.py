import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from database import SessionLocal
from models import (
    Base,
    Cotizacion,
    Paqueteria,
    SolicitudCotizacion,
    Tarifa,
)
import main
import import_data
from tariff_dates import select_applicable_tariffs
from main import clasificar_zona, app
from models.schemas import CotizacionRequest
from schema_migrations import upgrade_schema

upgrade_schema()
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


@pytest.mark.parametrize(
    ("endpoint", "payload"),
    [
        (
            "/cotizaciones",
            {"zona": 1, "peso": 2, "largo": 20},
        ),
        (
            "/solicitudes-cotizacion",
            {
                "email": "dimensiones@ejemplo.com",
                "codigo_postal1": "64000",
                "codigo_postal2": "44100",
                "peso": 2,
                "ancho": 20,
            },
        ),
    ],
)
def test_endpoints_rechazan_dimensiones_incompletas(endpoint, payload):
    """Las dimensiones deben venir completas o no enviarse."""
    response = client.post(endpoint, json=payload)

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


def test_importacion_historica_es_idempotente(tmp_path, monkeypatch):
    """La segunda importación conserva una sola copia de cada referencia."""
    csv_path = tmp_path / "cotizaciones_historicas.csv"
    csv_path.write_text(
        "cotizacion_id,fecha,correo,cp_origen,cp_destino,zona,peso_kg,"
        "paqueteria,precio_cotizado\n"
        "COT-TEST-1,2026-10-15,cliente@ejemplo.com,06600,64000,2,2,DHL,150.50\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(import_data, "COTIZACIONES_FILE", csv_path)

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    test_session_factory = sessionmaker(bind=engine)

    try:
        with test_session_factory() as session:
            assert import_data.import_cotizaciones_historicas(session) == (1, 0)
            session.commit()

            assert import_data.import_cotizaciones_historicas(session) == (0, 1)
            session.commit()

            assert session.scalar(
                select(func.count(Cotizacion.id)).where(
                    Cotizacion.referencia_historica == "COT-TEST-1"
                )
            ) == 1
            cotizacion = session.scalar(
                select(Cotizacion).where(
                    Cotizacion.referencia_historica == "COT-TEST-1"
                )
            )
            solicitud = session.get(
                SolicitudCotizacion,
                cotizacion.solicitud_id,
            )
            assert solicitud.codigo_postal1 == "06600"
            assert float(cotizacion.precio_cotizado) == pytest.approx(150.50)
    finally:
        engine.dispose()


def test_importa_tarifas_versionadas_de_csv_por_nombre_y_vigencia():
    """Los CSV versionados pueden usar los encabezados comerciales."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    test_session_factory = sessionmaker(bind=engine)
    fila_csv = {
        "paqueteria": "DHL",
        "zona": "1",
        "peso_min_kg": "0",
        "peso_max_kg": "1",
        "precio_mxn": "266.40",
        "dias_entrega": "1",
        "vigencia_desde": "2026-12-01",
    }

    try:
        with test_session_factory() as session:
            session.add(
                Paqueteria(
                    carrier_id="CARR-DHL",
                    nombre="DHL",
                    tipo_servicio="aéreo",
                    activo=True,
                )
            )
            session.commit()
            carrier_lookup = {"carr-dhl": "CARR-DHL", "dhl": "CARR-DHL"}

            assert import_data.import_tariff_rows(
                session,
                [(2, fila_csv)],
                carrier_lookup,
            ) == (1, 0, 0)
            session.commit()

            assert import_data.import_tariff_rows(
                session,
                [(2, fila_csv)],
                carrier_lookup,
            ) == (0, 1, 0)
            session.commit()

            tariff = session.scalar(select(Tarifa))
            assert tariff.id_empresas == "CARR-DHL"
            assert tariff.vigencia_desde == "2026-12-01"
            assert float(tariff.precio) == pytest.approx(266.40)
            assert session.scalar(
                select(func.count(Tarifa.id))
            ) == 1
    finally:
        engine.dispose()


def test_tarifas_versionadas_se_activan_desde_su_vigencia():
    tarifa_anterior = SimpleNamespace(
        peso_min=0,
        peso_max=1,
        vigencia_desde=None,
        precio=244.40,
    )
    tarifa_nueva = SimpleNamespace(
        peso_min=0,
        peso_max=1,
        vigencia_desde="2026-12-01",
        precio=266.40,
    )
    tarifas = [tarifa_anterior, tarifa_nueva]

    antes_de_vigencia = select_applicable_tariffs(
        tarifas,
        0.5,
        date(2026, 11, 30),
    )
    desde_vigencia = select_applicable_tariffs(
        tarifas,
        0.5,
        date(2026, 12, 1),
    )

    assert antes_de_vigencia == [tarifa_anterior]
    assert desde_vigencia == [tarifa_nueva]


@pytest.mark.parametrize(
    (
        "volumetrico",
        "volumetrico_desde",
        "precio_esperado",
        "peso_esperado",
    ),
    [
        (True, date.today(), 250.0, 8.0),
        (False, None, 100.0, 2.0),
        (True, date.today() + timedelta(days=1), 100.0, 2.0),
    ],
)
def test_cotizaciones_aplica_booleano_y_fecha_volumetrica(
    monkeypatch,
    volumetrico,
    volumetrico_desde,
    precio_esperado,
    peso_esperado,
):
    carrier = SimpleNamespace(
        carrier_id="CARR-TEST",
        nombre="Paquetería de prueba",
        volumetrico=volumetrico,
        volumetrico_desde=volumetrico_desde,
        activo=True,
    )
    tarifas = [
        SimpleNamespace(
            id_empresas="CARR-TEST",
            zona=1,
            peso_min=0,
            peso_max=5,
            precio=100,
            dias_entrega="1-2",
            vigencia_desde=None,
        ),
        SimpleNamespace(
            id_empresas="CARR-TEST",
            zona=1,
            peso_min=5,
            peso_max=10,
            precio=250,
            dias_entrega="2-3",
            vigencia_desde=None,
        ),
    ]

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, _):
            return SimpleNamespace(
                all=lambda: [(tarifa, carrier) for tarifa in tarifas]
            )

    monkeypatch.setattr(main, "SessionLocal", FakeSession)

    response = main.consultar_cotizaciones(
        CotizacionRequest(
            zona=1,
            peso=2,
            largo=20,
            ancho=40,
            alto=50,
        )
    )

    assert response["total_opciones"] == 1
    opcion = response["opciones"][0]
    assert opcion["precio"] == precio_esperado
    assert opcion["peso_facturable"] == peso_esperado
    assert response["peso_volumetrico_kg"] == pytest.approx(8)


def test_cotizacion_guarda_dimensiones_y_opciones_historicas(monkeypatch):
    monkeypatch.setattr(
        "main.get_postal_code_info",
        lambda codigo: {
            "postal_code": codigo,
            "place": "Monterrey",
            "state": "Nuevo León",
            "latitude": 25.6866,
            "longitude": -100.3161,
        },
    )
    carrier_id = f"T-{uuid.uuid4().hex[:12]}"
    email_prueba = f"volumetrico-{uuid.uuid4().hex}@ejemplo.com"
    solicitud_id = None

    with SessionLocal() as session:
        session.add(
            Paqueteria(
                carrier_id=carrier_id,
                nombre="Paquetería volumétrica de prueba",
                tipo_servicio="terrestre",
                activo=True,
                volumetrico=True,
                volumetrico_desde=date.today() - timedelta(days=1),
            )
        )
        session.add_all(
            [
                Tarifa(
                    id_empresas=carrier_id,
                    zona=1,
                    peso_min=0,
                    peso_max=5,
                    unidad="kg",
                    precio=100,
                    dias_entrega="1-2",
                    vigencia_desde=None,
                ),
                Tarifa(
                    id_empresas=carrier_id,
                    zona=1,
                    peso_min=5,
                    peso_max=10,
                    unidad="kg",
                    precio=250,
                    dias_entrega="2-3",
                    vigencia_desde=None,
                ),
            ]
        )
        session.commit()

    try:
        with TestClient(app) as test_client:
            solicitud_response = test_client.post(
                "/solicitudes-cotizacion",
                json={
                    "email": email_prueba,
                    "codigo_postal1": "64000",
                    "codigo_postal2": "44100",
                    "peso": 2,
                    "largo": 20,
                    "ancho": 40,
                    "alto": 50,
                },
            )
            assert solicitud_response.status_code == 200
            solicitud_id = solicitud_response.json()["id"]

            cotizacion_response = test_client.post(
                "/cotizaciones",
                json={
                    "zona": solicitud_response.json()["zona"],
                    "peso": 2,
                    "largo": 20,
                    "ancho": 40,
                    "alto": 50,
                    "solicitud_id": solicitud_id,
                },
            )
            assert cotizacion_response.status_code == 200
            option = next(
                item
                for item in cotizacion_response.json()["opciones"]
                if item["id_empresas"] == carrier_id
            )
            assert option["precio"] == 250
            assert option["peso_facturable"] == 8

            history_response = test_client.get(
                f"/solicitudes-cotizacion/{solicitud_id}",
                params={"email": email_prueba},
            )
            assert history_response.status_code == 200
            history = history_response.json()
            assert history["peso_volumetrico"] == 8
            saved_option = next(
                item
                for item in history["opciones"]
                if item["paqueteria"]
                == "Paquetería volumétrica de prueba"
            )
            assert saved_option["precio"] == 250
            assert saved_option["peso_facturable"] == 8
    finally:
        with SessionLocal() as session:
            if solicitud_id is not None:
                session.query(Cotizacion).filter_by(
                    solicitud_id=solicitud_id
                ).delete()
                solicitud = session.get(
                    SolicitudCotizacion,
                    solicitud_id,
                )
                if solicitud is not None:
                    session.delete(solicitud)
            session.query(Tarifa).filter_by(id_empresas=carrier_id).delete()
            carrier = session.get(Paqueteria, carrier_id)
            if carrier is not None:
                session.delete(carrier)
            session.commit()
