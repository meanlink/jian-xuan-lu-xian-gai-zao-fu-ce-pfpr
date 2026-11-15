from sqlalchemy import String, Double, JSON, ForeignKey, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class Migration(Base):
    __tablename__ = 'migrations'
    __table_args__ = (UniqueConstraint('bundle_id', 'direction'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    bundle_id: Mapped[str] = mapped_column(String(64))
    direction: Mapped[str] = mapped_column(String(10), default='import')
    status: Mapped[str] = mapped_column(String(20), default='importing')
    package_checksum: Mapped[str] = mapped_column(String(64), default='')
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(String(1000), default='')
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    confirmed_at: Mapped[float | None] = mapped_column(Double, nullable=True)
class MigrationItem(Base):
    __tablename__ = 'migration_items'
    __table_args__ = (UniqueConstraint('migration_id', 'kind', 'source_ref'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    migration_id: Mapped[int] = mapped_column(ForeignKey('migrations.id'))
    kind: Mapped[str] = mapped_column(String(20))
    source_ref: Mapped[str] = mapped_column(String(40))
    source_name: Mapped[str] = mapped_column(String(200), default='')
    local_id: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='pending')
    renamed: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str] = mapped_column(String(1000), default='')
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
