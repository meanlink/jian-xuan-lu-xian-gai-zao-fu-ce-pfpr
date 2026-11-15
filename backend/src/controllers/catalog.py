from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from src.config.database import get_db
from src.middlewares.auth import current_user
from src.models import Dataset, Job, Report, Audit
from src.services.business import metadata
from src.utils.visibility import published
router=APIRouter()
@router.get('/meta')
def meta():return metadata()
@router.get('/overview')
def overview(db=Depends(get_db),user=Depends(current_user)):
    return {'datasets':db.scalar(select(func.count()).select_from(Dataset).where(published(Dataset))), 'records':sum(len(d.records) for d in db.scalars(select(Dataset).where(published(Dataset)))), 'jobs':db.scalar(select(func.count()).select_from(Job).where(published(Job))), 'approved':db.scalar(select(func.count()).select_from(Job).where(Job.approved==True,published(Job))), 'reports':db.scalar(select(func.count()).select_from(Report).where(published(Report)))}
@router.get('/audits')
def audits(db=Depends(get_db),user=Depends(current_user)):
    return [{'id':a.id,'actor':a.actor,'action':a.action,'detail':a.detail,'at':a.at} for a in db.scalars(select(Audit).order_by(Audit.id.desc()).limit(50))]
