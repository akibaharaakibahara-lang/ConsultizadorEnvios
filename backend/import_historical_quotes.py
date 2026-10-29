from database import SessionLocal
from import_data import import_cotizaciones_historicas
from schema_migrations import upgrade_schema


def import_historical_quotes():
    upgrade_schema()

    with SessionLocal() as session:
        try:
            inserted, existing = import_cotizaciones_historicas(session)
            session.commit()
        except Exception:
            session.rollback()
            raise

    print(f"Cotizaciones históricas insertadas: {inserted}")
    print(f"Cotizaciones históricas existentes: {existing}")


if __name__ == "__main__":
    import_historical_quotes()
