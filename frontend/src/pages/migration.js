import {jobs,migrations} from '../api/entities.js';
import {exportBundle,download} from '../api/client.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {MigrationStatus,MigrationKind} from '../constants/enums.js';
import {esc,date,notify} from '../utils/dom.js';
let pendingBundle=null,pendingName='';
const counts=c=>['datasets','jobs','reports','deliveries'].map(k=>({datasets:'批次',jobs:'分析',reports:'计划',deliveries:'归档'}[k])+' '+(c?.[k]||0)).join(' · ');
const badge=s=>'<span class="status mig-'+esc(s)+'">'+esc(MigrationStatus[s]||s)+'</span>';
function mappingRows(items){
 if(!items.length)return '<p class="empty">该批次没有对象映射记录。</p>';
 return '<div class="table-wrap"><table><thead><tr><th>类型</th><th>源编号</th><th>源名称</th><th>本地编号</th><th>状态</th><th>说明</th></tr></thead><tbody>'+items.map(i=>'<tr><td>'+esc(MigrationKind[i.kind]||i.kind)+'</td><td>'+esc(i.source_ref)+'</td><td>'+esc(i.source_name)+'</td><td>'+(i.local_id??'—')+'</td><td>'+(i.status==='imported'?'已建档':i.status==='failed'?'<span class="mig-failed">失败</span>':esc(i.status))+'</td><td>'+(i.error?esc(i.error):i.renamed?'名称与本地撞车，已命名为「'+esc(i.detail?.local_name||'')+'」':'—')+'</td></tr>').join('')+'</tbody></table></div>';
}
function archiveRows(archives){
 if(!archives.length)return '<p class="empty">该批次没有历史归档。</p>';
 return '<div class="table-wrap"><table><thead><tr><th>源端归档</th><th>源端指纹</th><th>本地归档</th><th>本地指纹</th><th>内容一致</th><th>下载</th></tr></thead><tbody>'+archives.map(a=>'<tr><td>'+esc(a.source_filename||'—')+'</td><td>'+esc((a.source_checksum||'').slice(0,20))+'…</td><td>'+esc(a.local_filename||'—')+'</td><td>'+esc((a.local_checksum||'').slice(0,20))+'…</td><td>'+(a.match?'<span class="approval">一致</span>':'<span class="mig-failed">不一致</span>')+'</td><td>'+(a.local_id?'<button class="text-button" data-download="'+a.local_id+'" data-format="csv">CSV ↓</button> <button class="text-button" data-download="'+a.local_id+'" data-format="json">JSON ↓</button>':'—')+'</td></tr>').join('')+'</tbody></table></div>';
}
export async function migrationPage(){
 const [allJobs,list]=await Promise.all([jobs.list(),migrations.list()]);
 const approved=allJobs.filter(j=>j.approved&&j.status==='completed');
 if(!workspace.selectedMigration&&list.length)workspace.selectedMigration=list[0].id;
 const detail=workspace.selectedMigration?await migrations.get(workspace.selectedMigration).catch(()=>null):null;
 if(!detail)workspace.selectedMigration=null;
 const canImport=session.user.role==='admin';
 return heading('06 / MIGRATION','环境迁移与核对','把选定的已完成分析连同测时批次、批准结论、分发计划与历史归档打包迁入。两端编号撞车保留各自身份，迁入完成前资料不可见。')
 +'<div class="migration-grid"><section class="panel"><div class="section-title"><h2>打包迁出</h2><span>'+approved.length+' 项可打包</span></div><div class="check-list">'+approved.map(j=>'<label class="check-item"><input type="checkbox" name="export-job" value="'+j.id+'"><span><strong>'+esc(j.name)+'</strong><small>'+date(j.created_at)+' · 已获批准</small></span></label>').join('')+'</div><button class="primary" id="export-bundle" '+(session.user.role==='viewer'||!approved.length?'disabled':'')+'>导出迁移包 ↓</button><p class="hint">打包内容：所选分析、关联测时批次、批准结论、全部分发计划与历史归档文件。包内含 SHA256 校验指纹。</p></section>'
 +'<section class="panel"><div class="section-title"><h2>打包迁入</h2><span>仅业务负责人</span></div><label>迁移包 JSON<input type="file" id="bundle-file" accept=".json"></label><p class="hint" id="bundle-name">'+(pendingName?'已选择：'+esc(pendingName):'缺件、内容被改或依赖不全的包会被拒绝发布，不产生任何资料。')+'</p><button class="primary" id="import-bundle" '+(canImport?'':'disabled')+'>校验并迁入 ↗</button><p class="hint">迁入的分析与归档关联原依赖；批次名撞车自动改名，不覆盖本地资料。迁入的分发计划先暂停，确认后才恢复分发。中断后重新上传同一迁移包即可续迁，不会重复建档。</p></section></div>'
 +'<section class="panel"><div class="section-title"><h2>迁移批次</h2><span>'+list.length+' 批</span></div><div class="schedule-list">'+list.map(m=>'<article><div><strong>'+esc(m.bundle_id)+'</strong> '+(m.direction==='export'?'<small>迁出</small>':'<small>迁入</small>')+' '+badge(m.status)+'<p>'+counts(m.counts)+' · '+date(m.created_at)+'</p>'+(m.error?'<p class="mig-failed">'+esc(m.error)+'</p>':'')+'</div><div class="mig-actions"><button class="button small" data-select="'+m.id+'">核对映射</button>'+(m.direction==='import'&&m.status==='awaiting_confirm'?'<button class="button small" data-confirm="'+m.id+'" '+(canImport?'':'disabled')+'>确认恢复分发</button>':'')+'</div></article>').join('')+'</div>'+(!list.length?'<p class="empty">尚无迁移批次。先打包迁出，或迁入来自旧环境的迁移包。</p>':'')+'</section>'
 +(detail?'<section class="panel"><div class="section-title"><h2>对象映射 · '+esc(detail.bundle_id)+'</h2><span>'+badge(detail.status)+'</span></div>'+mappingRows(detail.items)+'<div class="section-title mig-sub"><h2>两端归档核对</h2><span>'+detail.archives.length+' 份</span></div>'+archiveRows(detail.archives)+'</section>':'');
}
export function bindMigration(refresh){
 document.querySelector('#export-bundle')?.addEventListener('click',async()=>{try{const ids=[...document.querySelectorAll('[name=export-job]:checked')].map(c=>Number(c.value));if(!ids.length)return notify('请先勾选要打包的分析',true);await exportBundle(ids);notify('迁移包已导出');await refresh();}catch(e){notify(e.message,true);}});
 document.querySelector('#bundle-file')?.addEventListener('change',async e=>{try{const file=e.target.files[0];if(!file)return;pendingBundle=JSON.parse(await file.text());pendingName=file.name;document.querySelector('#bundle-name').textContent='已选择：'+file.name;}catch(err){pendingBundle=null;pendingName='';notify('迁移包不是有效的 JSON 文件',true);}});
 document.querySelector('#import-bundle')?.addEventListener('click',async()=>{try{if(!pendingBundle)return notify('请先选择迁移包文件',true);const d=await migrations.importBundle(pendingBundle);workspace.selectedMigration=d.id;pendingBundle=null;pendingName='';notify(d.status==='awaiting_confirm'?'迁入完成，分发计划已暂停，请核对映射后确认恢复':'该包此前已迁入，未重复建档');await refresh();}catch(e){notify(e.message,true);await refresh();}});
 document.querySelectorAll('[data-select]').forEach(b=>b.onclick=async()=>{workspace.selectedMigration=Number(b.dataset.select);await refresh();});
 document.querySelectorAll('[data-confirm]').forEach(b=>b.onclick=async()=>{try{await migrations.confirm(b.dataset.confirm);notify('已确认，迁入计划恢复分发');await refresh();}catch(e){notify(e.message,true);}});
 document.querySelectorAll('[data-download]').forEach(b=>b.onclick=()=>download(b.dataset.download,b.dataset.format).catch(e=>notify(e.message,true)));
}
