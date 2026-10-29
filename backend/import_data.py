
import csv
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import select

from models import Cotizacion, Paqueteria, SolicitudCotizacion, Tarifa
from database import SessionLocal
from schema_migrations import upgrade_schema
from tariff_dates import parse_tariff_date


DATA_DIR = Path(__file__).resolve().parent / "data"
PAQUETERIAS_FILE = DATA_DIR / "paqueterias.csv"
TARIFAS_FILE = DATA_DIR / "tarifas.csv"
COTIZACIONES_FILE = DATA_DIR / "cotizaciones_historicas.csv"


def clean(value):
    """Convierte cadenas vacías y valores nulos de texto en None."""
    if value is None:
        return None

    value = str(value).strip()

    if not value or value.lower() in {"null", "none", "nan"}:
        return None

    return value


def read_csv(path):
    """Lee un CSV y devuelve sus filas como diccionarios."""
    if not path.exists():
        raise FileNotFoundError(f"No se encontró el archivo: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def parse_bool(value, field="activo", default=None):
    """Convierte valores comunes de texto a booleanos."""
    value = clean(value)

    if value is None:
        if default is not None:
            return default
        raise ValueError(f"El campo {field} está vacío")

    normalized = value.lower()

    if normalized in {"si", "sí", "true", "1", "activo"}:
        return True

    if normalized in {"no", "false", "0", "inactivo"}:
        return False

    raise ValueError(f"Valor de {field} no reconocido: {value}")


def parse_decimal(value, field):
    """Convierte un valor a Decimal y valida que no esté vacío."""
    value = clean(value)

    if value is None:
        raise ValueError(f"El campo {field} no puede estar vacío")

    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(
            f"Valor inválido en {field}: {value}"
        ) from exc


def normalized_tariff_fields(row, carrier_ids_by_name):
    carrier = clean(row.get("id_empresas") or row.get("paqueteria"))
    carrier_id = carrier_ids_by_name.get(carrier.casefold()) if carrier else None
    if carrier_id is None:
        raise ValueError(f"No se reconoce la paquetería: {carrier}")

    vigencia_desde = clean(row.get("vigencia_desde"))
    if vigencia_desde:
        parse_tariff_date(vigencia_desde)

    return {
        "carrier_id": carrier_id,
        "zona": int(clean(row.get("zona"))),
        "peso_min": parse_decimal(
            row.get("peso_min") or row.get("peso_min_kg"),
            "peso_min",
        ),
        "peso_max": parse_decimal(
            row.get("peso_max") or row.get("peso_max_kg"),
            "peso_max",
        ),
        "unidad": clean(row.get("unidad")) or "kg",
        "precio": parse_decimal(
            row.get("precio") or row.get("precio_mxn"),
            "precio",
        ),
        "dias_entrega": clean(row.get("dias_entrega")),
        "vigencia_desde": vigencia_desde,
    }


def import_tariff_rows(session, tariff_rows, carrier_ids_by_name):
    loaded_tariffs = 0
    updated_tariffs = 0
    rejected_tariffs = 0

    for line_number, row in tariff_rows:
        try:
            fields = normalized_tariff_fields(row, carrier_ids_by_name)
            if fields["zona"] not in {1, 2, 3, 4}:
                raise ValueError("La zona debe ser de 1 a 4")
            if fields["peso_min"] < 0 or fields["peso_max"] <= fields["peso_min"]:
                raise ValueError("Rango de peso inválido")
            if fields["precio"] < 0:
                raise ValueError("El precio no puede ser negativo")

            existing = session.scalar(
                select(Tarifa).where(
                    Tarifa.id_empresas == fields["carrier_id"],
                    Tarifa.zona == fields["zona"],
                    Tarifa.peso_min == fields["peso_min"],
                    Tarifa.peso_max == fields["peso_max"],
                    Tarifa.unidad == fields["unidad"],
                    Tarifa.vigencia_desde == fields["vigencia_desde"],
                )
            )

            if existing:
                existing.precio = fields["precio"]
                existing.dias_entrega = fields["dias_entrega"]
                updated_tariffs += 1
                continue

            session.add(
                Tarifa(
                    id_empresas=fields["carrier_id"],
                    zona=fields["zona"],
                    peso_min=fields["peso_min"],
                    peso_max=fields["peso_max"],
                    unidad=fields["unidad"],
                    precio=fields["precio"],
                    dias_entrega=fields["dias_entrega"],
                    vigencia_desde=fields["vigencia_desde"],
                )
            )
            loaded_tariffs += 1

        except (ValueError, TypeError) as exc:
            rejected_tariffs += 1
            print(f"Tarifa rechazada, línea {line_number}: {exc}")

    return loaded_tariffs, updated_tariffs, rejected_tariffs


def import_cotizaciones_historicas(session):
    """Importa cotizaciones telefónicas conservando su precio original."""
    if not COTIZACIONES_FILE.exists():
        print(
            f"No se encontró el archivo {COTIZACIONES_FILE}. "
            "Se omite la importación histórica."
        )
        return 0, 0

    filas = read_csv(COTIZACIONES_FILE)

    if not filas:
        print("El CSV histórico no contiene registros.")
        return 0, 0

    insertadas = 0
    existentes = 0

    for numero, fila in enumerate(filas, start=2):
        try:
            referencia = clean(fila.get("cotizacion_id"))
            if not referencia:
                raise ValueError("Falta cotizacion_id")

            if session.scalar(
                select(Cotizacion.id).where(
                    Cotizacion.referencia_historica == referencia
                )
            ) is not None:
                existentes += 1
                continue

            correo = clean(fila.get("correo"))
            codigo_postal1 = clean(fila.get("cp_origen"))
            codigo_postal2 = clean(fila.get("cp_destino"))
            paqueteria = clean(fila.get("paqueteria"))
            fecha = clean(fila.get("fecha"))
            if not all(
                (correo, codigo_postal1, codigo_postal2, paqueteria, fecha)
            ):
                raise ValueError("Faltan datos obligatorios")

            zona = int(clean(fila.get("zona")))
            peso = parse_decimal(fila.get("peso_kg"), "peso_kg")
            precio = parse_decimal(
                fila.get("precio_cotizado"),
                "precio_cotizado",
            )
            if zona not in {1, 2, 3, 4} or peso <= 0 or precio < 0:
                raise ValueError("Zona, peso o precio fuera de rango")

            fecha_creacion = datetime.combine(
                date.fromisoformat(fecha),
                time.min,
                tzinfo=timezone.utc,
            )
            solicitud = SolicitudCotizacion(
                email=correo,
                codigo_postal1=codigo_postal1,
                codigo_postal2=codigo_postal2,
                peso=peso,
                zona=zona,
                fecha_creacion=fecha_creacion,
            )
            session.add(solicitud)
            session.flush()

            session.add(
                Cotizacion(
                    solicitud_id=solicitud.id,
                    referencia_historica=referencia,
                    paqueteria=paqueteria,
                    precio_cotizado=precio,
                )
            )
            insertadas += 1

        except (ValueError, TypeError, InvalidOperation) as exc:
            raise ValueError(
                f"Error en la fila {numero} del CSV histórico: {exc}"
            ) from exc

    return insertadas, existentes


def import_data():
    """Importa paqueterías, tarifas y cotizaciones históricas."""
    upgrade_schema()

    carrier_rows = read_csv(PAQUETERIAS_FILE)
    tariff_rows = [
        (line_number, row)
        for line_number, row in enumerate(read_csv(TARIFAS_FILE), start=2)
    ]
    for tariff_file in sorted(DATA_DIR.glob("tarifas_*_v*.csv")):
        tariff_rows.extend(
            (line_number, row)
            for line_number, row in enumerate(read_csv(tariff_file), start=2)
        )

    loaded_carriers = 0
    loaded_tariffs = 0
    updated_tariffs = 0
    rejected_tariffs = 0

    with SessionLocal() as session:
        try:
            # 1. Importar o actualizar las paqueterías.
            for row in carrier_rows:
                carrier_id = clean(row.get("carrier_id"))
                nombre = clean(row.get("nombre"))
                tipo_servicio = clean(row.get("tipo_servicio"))
                activo = parse_bool(row.get("activo"), "activo")
                if not carrier_id or not nombre or not tipo_servicio:
                    raise ValueError(
                        f"Paquetería con datos obligatorios faltantes: {row}"
                    )

                carrier = session.get(Paqueteria, carrier_id)

                if carrier is None:
                    carrier = Paqueteria(carrier_id=carrier_id)
                    session.add(carrier)

                carrier.nombre = nombre
                carrier.tipo_servicio = tipo_servicio
                carrier.activo = activo
                if "volumetrico" in row and clean(row["volumetrico"]):
                    carrier.volumetrico = parse_bool(
                        row["volumetrico"],
                        field="volumetrico",
                    )
                if "volumetrico_desde" in row:
                    vigencia_volumetrica = clean(
                        row["volumetrico_desde"]
                    )
                    carrier.volumetrico_desde = (
                        date.fromisoformat(vigencia_volumetrica)
                        if vigencia_volumetrica
                        else None
                    )

                loaded_carriers += 1

            session.flush()

            # 2. Importar tarifas base y archivos versionados por paquetería.
            carrier_ids_by_name = {}
            for carrier in session.scalars(select(Paqueteria)):
                carrier_ids_by_name[carrier.carrier_id.casefold()] = (
                    carrier.carrier_id
                )
                carrier_ids_by_name[carrier.nombre.casefold()] = (
                    carrier.carrier_id
                )
            (
                loaded_tariffs,
                updated_tariffs,
                rejected_tariffs,
            ) = import_tariff_rows(
                session,
                tariff_rows,
                carrier_ids_by_name,
            )

            # 3. Importar cotizaciones históricas.
            historical_inserted, historical_existing = (
                import_cotizaciones_historicas(session)
            )

            session.commit()

        except Exception:
            session.rollback()
            raise

    print("Importación finalizada.")
    print(f"Paqueterías procesadas: {loaded_carriers}")
    print(f"Tarifas nuevas: {loaded_tariffs}")
    print(f"Tarifas existentes actualizadas: {updated_tariffs}")
    print(f"Tarifas rechazadas: {rejected_tariffs}")
    print(f"Cotizaciones históricas insertadas: {historical_inserted}")
    print(f"Cotizaciones históricas ya existentes: {historical_existing}")


if __name__ == "__main__":
    import_data()
