from datetime import date, datetime
from sqlalchemy import Date, DateTime
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Paqueteria(Base):
    __tablename__ = "paqueterias"

    carrier_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    tipo_servicio: Mapped[str] = mapped_column(String(50), nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False)
    volumetrico: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    volumetrico_desde: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )


class Tarifa(Base):
    __tablename__ = "tarifas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id_empresas: Mapped[str] = mapped_column(
        ForeignKey("paqueterias.carrier_id"), nullable=False
    )
    zona: Mapped[int] = mapped_column(Integer, nullable=False)
    peso_min: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    peso_max: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    unidad: Mapped[str] = mapped_column(String(10), nullable=False)
    precio: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    dias_entrega: Mapped[str | None] = mapped_column(String(20), nullable=True)
    vigencia_desde: Mapped[str | None] = mapped_column(String(10), nullable=True)

    __table_args__ = (
        CheckConstraint("zona BETWEEN 1 AND 4"),
        CheckConstraint("peso_min >= 0"),
        CheckConstraint("peso_max > peso_min"),
        CheckConstraint("precio >= 0"),
        UniqueConstraint(
            "id_empresas",
            "zona",
            "peso_min",
            "peso_max",
            "unidad",
            "vigencia_desde",
            name="uq_tarifa_empresa_zona_peso_vigencia",
        ),
    )

class SolicitudCotizacion(Base):
    __tablename__ = "solicitudes_cotizacion"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    codigo_postal1: Mapped[str] = mapped_column(String(10), nullable=False)
    codigo_postal2: Mapped[str] = mapped_column(String(10), nullable=False)
    peso: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    zona: Mapped[int] = mapped_column(Integer, nullable=False)
    largo: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    ancho: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    alto: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    peso_volumetrico: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    fecha_creacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now().astimezone(),
        nullable=False,
    )


class Cotizacion(Base):
    __tablename__ = "cotizaciones"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    solicitud_id: Mapped[int] = mapped_column(
        ForeignKey("solicitudes_cotizacion.id"), nullable=False, index=True
    )
    referencia_historica: Mapped[str | None] = mapped_column(
        String(30), unique=True, nullable=True
    )
    paqueteria: Mapped[str] = mapped_column(String(100), nullable=False)
    precio_cotizado: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    peso_min: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    peso_max: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    peso_facturable: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    dias_entrega: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    vigencia_desde: Mapped[str | None] = mapped_column(
        String(10), nullable=True
    )
