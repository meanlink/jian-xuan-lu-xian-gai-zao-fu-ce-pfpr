import time
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from src.config.database import get_db
from src.models import Migration
from src.schemas.migration import ExportInput
from src.middlewares.auth import current_user, can_write, admin_only
from src.services import migrations
from src.services.audit import record
from src.utils.serialization import migration_dict
router=APIRouter(prefix='/migrations')
@router.get('')
def listing(db=Depends(get_db),u=Depends(current_user)):
    return [migration_dict(m) for m in db.scalars(select(Migration).order_by(Migration.id.desc()).limit(100))]
@router.get('/{id}')
def detail(id:int,db=Depends(get_db),u=Depends(current_user)):
    m=db.get(Migration,id)
    if not m: raise HTTPException(404,'迁移批次不存在')
    return migrations.detail(db,m)
@router.post('/export')
def export(data:ExportInput,db=Depends(get_db),u=Depends(can_write)):
    bundle=migrations.build_bundle(db,data.job_ids,u)
    m=Migration(bundle_id=bundle['bundle_id'],direction='export',status='completed',package_checksum=bundle['checksum'],counts={k:len(v) for k,v in bundle['items'].items()},created_by=u.id,created_at=time.time(),finished_at=time.time())
    db.add(m); record(db,u.email,'migration.export',{'bundle':bundle['bundle_id'],'jobs':data.job_ids}); db.commit()
    return JSONResponse(bundle,headers={'Content-Disposition':f'attachment; filename="migration-{bundle["bundle_id"]}.json"'})
@router.post('/import')
async def import_(request:Request,db=Depends(get_db),u=Depends(admin_only)):
    try: bundle=await request.json()
    except Exception: raise HTTPException(422,'迁移包不是有效的 JSON 文件')
    mig,created=migrations.import_bundle(db,bundle,u)
    record(db,u.email,'migration.import' if created else 'migration.retry',{'bundle':mig.bundle_id,'status':mig.status})
    db.commit()
    return migrations.detail(db,mig)
@router.post('/{id}/confirm')
def confirm(id:int,db=Depends(get_db),u=Depends(admin_only)):
    m=db.get(Migration,id)
    if not m: raise HTTPException(404,'迁移批次不存在')
    migrations.confirm(db,m); record(db,u.email,'migration.confirm',{'bundle':m.bundle_id}); db.commit()
    return migrations.detail(db,m)
