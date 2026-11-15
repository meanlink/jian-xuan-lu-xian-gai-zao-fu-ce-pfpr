import time, os, hashlib, json
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select
from src.config.settings import ARTIFACT_DIR
from src.models import Dataset, Job, Report, Delivery, Migration, MigrationItem
from src.services.business import metadata
from src.utils.serialization import checksum, migration_dict, migration_item_dict
from src.utils.visibility import published
FORMAT='pick-paired/migration'
VERSION=1
KINDS=['datasets','jobs','reports','deliveries']
KIND_LABEL={'dataset':'数据批次','job':'分析任务','report':'分发计划','delivery':'历史归档'}
def build_bundle(db, job_ids, user):
    jobs=[]
    for jid in dict.fromkeys(job_ids):
        j=db.scalar(select(Job).where(Job.id==jid,published(Job)))
        if not j or j.status!='completed' or not j.approved:
            raise HTTPException(409,f'分析 {jid} 尚未完成或未获批准，不能打包迁出')
        jobs.append(j)
    if not jobs: raise HTTPException(422,'请先选择要打包的已完成分析')
    datasets={j.dataset_id:db.get(Dataset,j.dataset_id) for j in jobs}
    reports=list(db.scalars(select(Report).where(Report.job_id.in_([j.id for j in jobs]))))
    deliveries=list(db.scalars(select(Delivery).where(Delivery.report_id.in_([r.id for r in reports])))) if reports else []
    packed_deliveries=[]
    for d in deliveries:
        csv_path=os.path.join(ARTIFACT_DIR,d.filename)
        json_path=csv_path+'.json'
        if not os.path.exists(csv_path) or not os.path.exists(json_path):
            raise HTTPException(422,f'归档 {d.filename} 的文件缺失，无法打包；请重新安排分发后再导出')
        with open(csv_path,'rb') as f: csv_bytes=f.read()
        if hashlib.sha256(csv_bytes).hexdigest()!=d.checksum:
            raise HTTPException(422,f'归档 {d.filename} 内容与指纹不符，无法打包')
        with open(json_path,encoding='utf-8') as f: sidecar=f.read()
        packed_deliveries.append({'ref':f'dl-{d.id}','report_ref':f'rp-{d.report_id}','created_at':d.created_at,'checksum':d.checksum,'filename':d.filename,'destination':d.destination,'csv':csv_bytes.decode('utf-8'),'json':sidecar})
    items={
        'datasets':[{'ref':f'ds-{d.id}','name':d.name,'source':d.source,'records':d.records,'checksum':d.checksum,'created_at':d.created_at} for d in datasets.values()],
        'jobs':[{'ref':f'job-{j.id}','dataset_ref':f'ds-{j.dataset_id}','name':j.name,'params':j.params,'status':j.status,'result':j.result,'approved':j.approved,'created_at':j.created_at,'finished_at':j.finished_at} for j in jobs],
        'reports':[{'ref':f'rp-{r.id}','job_ref':f'job-{r.job_id}','name':r.name,'destination':r.destination,'interval_seconds':r.interval_seconds,'next_run':r.next_run,'enabled':r.enabled} for r in reports],
        'deliveries':packed_deliveries}
    m=metadata()
    bundle={'format':FORMAT,'version':VERSION,'bundle_id':'mg-'+uuid4().hex[:16],'exported_at':time.time(),'source':{'app':m['name'],'short':m['short']},'items':items}
    bundle['checksum']=checksum(items)
    return bundle
def verify_bundle(bundle):
    if not isinstance(bundle,dict): raise HTTPException(422,'迁移包不是有效的 JSON 对象')
    if bundle.get('format')!=FORMAT or bundle.get('version')!=VERSION: raise HTTPException(422,'迁移包格式或版本不受支持')
    if not isinstance(bundle.get('bundle_id'),str) or not bundle['bundle_id']: raise HTTPException(422,'迁移包缺少批次编号')
    items=bundle.get('items')
    if not isinstance(items,dict): raise HTTPException(422,'迁移包缺少内容清单')
    if checksum(items)!=bundle.get('checksum'): raise HTTPException(422,'迁移包内容校验失败，文件可能被修改，已拒绝发布')
    for kind in KINDS:
        if not isinstance(items.get(kind) or [],list): raise HTTPException(422,f'迁移包 {kind} 清单损坏')
    datasets,jobs,reports,deliveries=(items.get(k) or [] for k in KINDS)
    if not jobs: raise HTTPException(422,'迁移包内没有分析结果')
    for d in datasets:
        if checksum(d.get('records'))!=d.get('checksum'): raise HTTPException(422,f'数据批次「{d.get("name","")}」内容校验失败，已拒绝发布')
    for dl in deliveries:
        if dl.get('csv') is None or dl.get('json') is None: raise HTTPException(422,f'归档 {dl.get("filename","")} 缺少文件内容，迁移包不完整')
        if hashlib.sha256(dl['csv'].encode('utf-8')).hexdigest()!=dl.get('checksum'): raise HTTPException(422,f'归档 {dl.get("filename","")} 内容校验失败，已拒绝发布')
        try: json.loads(dl['json'])
        except Exception: raise HTTPException(422,f'归档 {dl.get("filename","")} 的 JSON 附件损坏')
    refs={}
    for kind,rows,key in [('dataset',datasets,'ref'),('job',jobs,'ref'),('report',reports,'ref'),('delivery',deliveries,'ref')]:
        seen=set()
        for row in rows:
            ref=row.get(key)
            if not ref or ref in seen: raise HTTPException(422,f'迁移包内{KIND_LABEL[kind]}编号缺失或重复')
            seen.add(ref)
        refs[kind]=seen
    for j in jobs:
        if j.get('dataset_ref') not in refs['dataset']: raise HTTPException(422,f'分析「{j.get("name","")}」依赖的数据批次不在包内，已拒绝发布')
        if j.get('status')!='completed' or not j.get('approved'): raise HTTPException(422,f'分析「{j.get("name","")}」未完成或未获批准，不能迁入')
    for r in reports:
        if r.get('job_ref') not in refs['job']: raise HTTPException(422,f'分发计划「{r.get("name","")}」依赖的分析不在包内，已拒绝发布')
    for dl in deliveries:
        if dl.get('report_ref') not in refs['report']: raise HTTPException(422,f'归档 {dl.get("filename","")} 依赖的分发计划不在包内，已拒绝发布')
def _item(db,mig_id,kind,ref):
    return db.scalar(select(MigrationItem).where(MigrationItem.migration_id==mig_id,MigrationItem.kind==kind,MigrationItem.source_ref==ref))
def _done(db,mig_id,kind):
    return {i.source_ref:i.local_id for i in db.scalars(select(MigrationItem).where(MigrationItem.migration_id==mig_id,MigrationItem.kind==kind,MigrationItem.status=='imported'))}
def _save_item(db,mig_id,kind,ref,source_name,local_id,renamed,detail):
    item=_item(db,mig_id,kind,ref)
    if not item: item=MigrationItem(migration_id=mig_id,kind=kind,source_ref=ref); db.add(item)
    item.source_name=source_name; item.local_id=local_id; item.status='imported'; item.renamed=renamed; item.error=''; item.detail=detail
def _fail(db,mig,kind,ref,name,exc):
    db.rollback()
    mig=db.get(Migration,mig.id)
    mig.status='failed'; mig.error=f'{KIND_LABEL[kind]}「{name}」迁入失败：{str(exc)[:200]}'
    item=_item(db,mig.id,kind,ref)
    if not item: item=MigrationItem(migration_id=mig.id,kind=kind,source_ref=ref); db.add(item)
    item.source_name=name; item.status='failed'; item.error=str(exc)[:990]
    db.commit()
    raise HTTPException(422,mig.error+'。修正后重新上传同一迁移包即可续迁，已建档对象不会重复')
def _unique_dataset_name(db,name):
    base=(name or '').strip()[:148] or '迁入数据批次'
    if not db.scalar(select(Dataset).where(Dataset.name==base)): return base
    candidate,n=base+'（迁入）',2
    while db.scalar(select(Dataset).where(Dataset.name==candidate)):
        candidate=f'{base}（迁入 {n}）'; n+=1
    return candidate
def _import_datasets(db,mig,rows):
    done=_done(db,mig.id,'dataset')
    for d in rows:
        ref=d['ref']
        if ref in done: continue
        try:
            name=_unique_dataset_name(db,d.get('name'))
            row=Dataset(name=name,source=d.get('source','migration.json'),records=d['records'],checksum=checksum(d['records']),created_at=d.get('created_at') or time.time(),migration_id=mig.id)
            db.add(row); db.flush()
            _save_item(db,mig.id,'dataset',ref,d.get('name',''),row.id,name!=d.get('name'),{'local_name':name,'source_checksum':d.get('checksum')})
            db.commit(); done[ref]=row.id
        except HTTPException: raise
        except Exception as e: _fail(db,mig,'dataset',ref,d.get('name',''),e)
    return done
def _import_jobs(db,mig,rows,ds_map,user):
    done=_done(db,mig.id,'job')
    for j in rows:
        ref=j['ref']
        if ref in done: continue
        try:
            row=Job(name=j['name'],dataset_id=ds_map[j['dataset_ref']],params=j.get('params') or {},status='completed',result=j.get('result') or {},error='',approved=True,created_by=user.id,created_at=j.get('created_at') or time.time(),finished_at=j.get('finished_at'),migration_id=mig.id)
            db.add(row); db.flush()
            _save_item(db,mig.id,'job',ref,j.get('name',''),row.id,False,{'dataset_local_id':ds_map[j['dataset_ref']]})
            db.commit(); done[ref]=row.id
        except HTTPException: raise
        except Exception as e: _fail(db,mig,'job',ref,j.get('name',''),e)
    return done
def _import_reports(db,mig,rows,job_map):
    done=_done(db,mig.id,'report')
    for r in rows:
        ref=r['ref']
        if ref in done: continue
        try:
            interval=int(r.get('interval_seconds') or 86400)
            # 迁入计划先暂停，确认后才恢复分发
            row=Report(name=r['name'],job_id=job_map[r['job_ref']],destination=r.get('destination','业务复核组'),interval_seconds=interval,next_run=time.time()+interval,enabled=False,migration_id=mig.id)
            db.add(row); db.flush()
            _save_item(db,mig.id,'report',ref,r.get('name',''),row.id,False,{'job_local_id':job_map[r['job_ref']],'source_enabled':bool(r.get('enabled'))})
            db.commit(); done[ref]=row.id
        except HTTPException: raise
        except Exception as e: _fail(db,mig,'report',ref,r.get('name',''),e)
    return done
def _import_deliveries(db,mig,rows,rp_map):
    done=_done(db,mig.id,'delivery')
    for dl in rows:
        ref=dl['ref']
        if ref in done: continue
        try:
            row=Delivery(report_id=rp_map[dl['report_ref']],created_at=dl.get('created_at') or time.time(),checksum=dl['checksum'],filename='',destination=dl.get('destination','业务复核组'),migration_id=mig.id)
            db.add(row); db.flush()
            # 归档文件按本地新编号命名，绝不覆盖本地既有文件
            row.filename=f'report-{row.report_id}-delivery-{row.id}.csv'
            os.makedirs(ARTIFACT_DIR,exist_ok=True)
            with open(os.path.join(ARTIFACT_DIR,row.filename),'wb') as f: f.write(dl['csv'].encode('utf-8'))
            with open(os.path.join(ARTIFACT_DIR,row.filename+'.json'),'w',encoding='utf-8') as f: f.write(dl['json'])
            _save_item(db,mig.id,'delivery',ref,dl.get('filename',''),row.id,False,{'source_filename':dl.get('filename'),'source_checksum':dl.get('checksum'),'local_filename':row.filename})
            db.commit(); done[ref]=row.id
        except HTTPException: raise
        except Exception as e: _fail(db,mig,'delivery',ref,dl.get('filename',''),e)
    return done
def import_bundle(db,bundle,user):
    try:
        verify_bundle(bundle)
    except HTTPException as e:
        # 拒绝发布的包也留下失败记录，便于迁移页核对失败原因；已有迁入记录则不覆盖
        bid=bundle.get('bundle_id') if isinstance(bundle,dict) else None
        if isinstance(bid,str) and bid:
            if not db.scalar(select(Migration).where(Migration.bundle_id==bid,Migration.direction=='import')):
                db.add(Migration(bundle_id=bid,direction='import',status='failed',package_checksum=str(bundle.get('checksum') or '')[:64],counts={},error=str(e.detail)[:990],created_by=user.id,created_at=time.time(),finished_at=time.time()))
                db.commit()
        raise
    items=bundle['items']; bundle_id=bundle['bundle_id']
    mig=db.scalar(select(Migration).where(Migration.bundle_id==bundle_id,Migration.direction=='import'))
    if mig and mig.status in ('awaiting_confirm','completed'):
        return mig,False # 同一包已完成迁入，直接返回既有映射，不重复建档
    if not mig:
        mig=Migration(bundle_id=bundle_id,direction='import',status='importing',package_checksum=bundle['checksum'],counts={k:len(items.get(k) or []) for k in KINDS},created_by=user.id,created_at=time.time())
        db.add(mig); db.commit()
    else:
        mig.status='importing'; mig.error=''; db.commit()
    ds_map=_import_datasets(db,mig,items.get('datasets') or [])
    job_map=_import_jobs(db,mig,items['jobs'],ds_map,user)
    rp_map=_import_reports(db,mig,items.get('reports') or [],job_map)
    _import_deliveries(db,mig,items.get('deliveries') or [],rp_map)
    mig=db.get(Migration,mig.id)
    mig.status='awaiting_confirm'; mig.finished_at=time.time(); db.commit()
    return mig,True
def confirm(db,mig):
    if mig.status!='awaiting_confirm': raise HTTPException(409,'当前批次不在待确认状态，无需恢复分发')
    now=time.time()
    for item in db.scalars(select(MigrationItem).where(MigrationItem.migration_id==mig.id,MigrationItem.kind=='report',MigrationItem.status=='imported')):
        r=db.get(Report,item.local_id)
        if r: r.enabled=True; r.next_run=now+r.interval_seconds
    mig.status='completed'; mig.confirmed_at=now
def detail(db,mig):
    items=[migration_item_dict(i) for i in db.scalars(select(MigrationItem).where(MigrationItem.migration_id==mig.id).order_by(MigrationItem.id))]
    archives=[]
    for i in items:
        if i['kind']!='delivery': continue
        d=db.get(Delivery,i['local_id']) if i['local_id'] else None
        archives.append({'source_filename':i['detail'].get('source_filename'),'source_checksum':i['detail'].get('source_checksum'),'local_id':d.id if d else None,'local_filename':d.filename if d else None,'local_checksum':d.checksum if d else None,'created_at':d.created_at if d else None,'match':bool(d and d.checksum==i['detail'].get('source_checksum'))})
    return {**migration_dict(mig),'items':items,'archives':archives}
