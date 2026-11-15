from sqlalchemy import inspect, text
from src.config.database import Base, engine
from src import models
def migrate():
    Base.metadata.create_all(engine)
    # 既有环境补列：迁移功能为四类业务对象新增可空的 migration_id
    with engine.begin() as conn:
        for table in ['datasets','jobs','reports','deliveries']:
            columns={c['name'] for c in inspect(conn).get_columns(table)}
            if 'migration_id' not in columns:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN migration_id INTEGER NULL'))
if __name__=='__main__':migrate()
