from sqlalchemy import select, or_
from src.models.migration import Migration
def published(model):
    # 未完成迁入（importing/failed）的对象对业务不可见；待确认与已完成批次可见
    done=select(Migration.id).where(Migration.status.in_(['awaiting_confirm','completed']))
    return or_(model.migration_id==None, model.migration_id.in_(done))
