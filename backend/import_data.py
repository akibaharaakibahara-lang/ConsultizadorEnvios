
import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path
from models import Base, Paqueteria, Tarifa
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from database import engine, SessionLocal 


DATA_DIR = Path(__file__).resolve().parent / "data" 
PAQUETERIAS_FILE = DATA_DIR / "paqueterias.csv"
TARIFAS_FILE = DATA_DIR / "tarifas.csv"


def clean(value):
    """Convierte cadenas vacías y 'null' en None."""
    if value is None:
        return None

    value = value.strip()

    if not value or value.lower() in {"null", "none", "nan"}:
        return None

    return value


def read_csv(path):
    if not path.exists():
        raise FileNotFoundError(f"No se encontró el archivo: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def parse_bool(value):
    value = clean(value)

    if value is None:
        raise ValueError("El campo activo está vacío")

    normalized = value.lower()

    if normalized in {"si", "sí", "true", "1", "activo"}:
        return True

    if normalized in {"no", "false", "0", "inactivo"}:
        return False

    raise ValueError(f"Valor de activo no reconocido: {value}")


def parse_decimal(value, field):
    value = clean(value)

    if value is None:
        raise ValueError(f"El campo {field} no puede estar vacío")

    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"Valor inválido en {field}: {value}") from exc


def import_data():
    # Crear las tablas si no existen.
    Base.metadata.create_all(bind=engine)

    carrier_rows = read_csv(PAQUETERIAS_FILE)
    tariff_rows = read_csv(TARIFAS_FILE)

    loaded_carriers = 0
    loaded_tariffs = 0
    skipped_tariffs = 0

    with SessionLocal() as session:
        try:
            # 1. Importar o actualizar las paqueterías.
            for row in carrier_rows:
                carrier_id = clean(row.get("carrier_id"))
                nombre = clean(row.get("nombre"))
                tipo_servicio = clean(row.get("tipo_servicio"))
                activo = parse_bool(row.get("activo"))

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
                loaded_carriers += 1

            session.flush()

            # 2. Leer las tarifas y relacionarlas por id_empresas.
            for line_number, row in enumerate(tariff_rows, start=2):
                try:
                    carrier_id = clean(row.get("id_empresas"))

                    if not carrier_id:
                        raise ValueError("Falta id_empresas")

                    carrier = session.get(Paqueteria, carrier_id)

                    if carrier is None:
                        raise ValueError(
                            f"No existe la empresa {carrier_id}"
                        )

                    zona = int(clean(row.get("zona")))
                    peso_min = parse_decimal(row.get("peso_min"), "peso_min")
                    peso_max = parse_decimal(row.get("peso_max"), "peso_max")
                    precio = parse_decimal(row.get("precio"), "precio")
                    unidad = clean(row.get("unidad"))

                    if zona not in {1, 2, 3, 4}:
                        raise ValueError("La zona debe ser de 1 a 4")

                    if peso_min < 0 or peso_max <= peso_min:
                        raise ValueError("Rango de peso inválido")

                    if precio < 0:
                        raise ValueError("El precio no puede ser negativo")

                    if not unidad:
                        raise ValueError("Falta la unidad de peso")

                    dias_entrega = clean(row.get("dias_entrega"))
                    vigencia_desde = clean(row.get("vigencia_desde"))

                    # No duplicar una tarifa ya existente.
                    existing = session.scalar(
                        select(Tarifa).where(
                            Tarifa.id_empresas == carrier_id,
                            Tarifa.zona == zona,
                            Tarifa.peso_min == peso_min,
                            Tarifa.peso_max == peso_max,
                            Tarifa.unidad == unidad,
                            Tarifa.vigencia_desde == vigencia_desde,
                        )
                    )

                    if existing:
                        # Actualizar datos de la tarifa existente.
                        existing.precio = precio
                        existing.dias_entrega = dias_entrega
                        skipped_tariffs += 1
                        continue

                    session.add(
                        Tarifa(
                            id_empresas=carrier_id,
                            zona=zona,
                            peso_min=peso_min,
                            peso_max=peso_max,
                            unidad=unidad,
                            precio=precio,
                            dias_entrega=dias_entrega,
                            vigencia_desde=vigencia_desde,
                        )
                    )
                    loaded_tariffs += 1

                except (ValueError, TypeError) as exc:
                    print(
                        f"Tarifa rechazada, línea {line_number}: {exc}"
                    )

            session.commit()

        except Exception:
            session.rollback()
            raise

    print("Importación finalizada.")
    print(f"Paqueterías procesadas: {loaded_carriers}")
    print(f"Tarifas nuevas: {loaded_tariffs}")
    print(f"Tarifas existentes actualizadas: {skipped_tariffs}")


if __name__ == "__main__":
    import_data()
