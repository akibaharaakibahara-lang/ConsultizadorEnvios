from sqlalchemy import inspect, text

from database import engine
from models import Base


def upgrade_schema():
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    additions = {
        "paqueterias": {
            "volumetrico": "BOOLEAN NOT NULL DEFAULT FALSE",
            "volumetrico_desde": "DATE",
        },
        "solicitudes_cotizacion": {
            "largo": "NUMERIC(10, 2)",
            "ancho": "NUMERIC(10, 2)",
            "alto": "NUMERIC(10, 2)",
            "peso_volumetrico": "NUMERIC(10, 2)",
        },
    }

    with engine.begin() as connection:
        for table_name, columns in additions.items():
            existing_columns = {
                column["name"]
                for column in inspector.get_columns(table_name)
            }
            for column_name, sql_type in columns.items():
                if column_name not in existing_columns:
                    connection.execute(
                        text(
                            f"ALTER TABLE {table_name} "
                            f"ADD COLUMN {column_name} {sql_type}"
                        )
                    )
