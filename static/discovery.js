const discoveryState = {providers:[],runs:[],run:null,selected:new Set(),busy:false,error:'',form:{provider:'club',platform:'youtube',topic:'',limit:10,content_type:'all',followers_min:null,followers_max:null,average_views_min:null}};
async function loadDiscovery(redraw=true){
  const data=await api('/api/discovery');discoveryState.providers=data.providers;discoveryState.runs=data.runs;
  if(discoveryState.run){const r=data.runs.find(x=>x.id===discoveryState.run.id);if(r)discoveryState.run=r;}
  if(redraw)render();
}
function providerName(id){return discoveryState.providers.find(p=>p.id===id)?.name||id;}
function discoveryStatus(status){return ({prepared:'待确认',running:'搜索中 / 待确认',done:'已找到',failed:'未完成'})[status]||status;}
function discoveryView(){
  const d=discoveryState,f=d.form,source=d.providers.find(p=>p.id===f.provider),r=d.run;
  return pageHead('为这次推广，找到合适的达人','按游戏品类、内容方向和粉丝规模寻找达人，再加入项目备选名单。',`${state.user.role==='admin'?`<button data-action="connect-sources">${icon('link')}连接达人库</button>`:''}<button data-action="reload-discovery">${icon('history')}更新搜索进度</button>`)+`
  <div class="source-strip">${d.providers.map(p=>`<div><span class="source-dot ${p.configured?'connected':''}"></span><strong>${esc(p.name)}</strong><span>${p.verified_at?'可使用':p.configured?'待检查是否可用':'尚未连接'}</span></div>`).join('')}<span class="source-note">搜索会消耗所选达人库的服务积分，开始前会请你确认</span></div>
  ${!d.providers.some(p=>p.configured)?`<div class="info warning">先连接一个达人库，即可开始找达人。点击右上方“连接达人库”，使用团队已有的服务账号；暂时没有账号，也可以在“备选名单”中手动添加达人。</div>`:''}
  <section class="panel compact"><form id="discover-form"><fieldset ${!canEdit()||d.busy?'disabled':''}><div class="discovery-form-grid">
  ${selectField('从哪个达人库找','provider',f.provider,d.providers.map(p=>[p.id,p.name]))}
  ${selectField('达人发布平台','platform',f.platform,(source?.platforms||['youtube']).map(x=>[x,({youtube:'YouTube',tiktok:'TikTok',instagram:'Instagram',twitch:'Twitch'})[x]]))}
  ${field('想找哪类达人','topic',f.topic,'text',true,f.provider==='nox'?'例如 strategy games, PC gaming；用逗号分开时，会要求同时符合这些关键词。':'写游戏名、品类或内容方向，例如“策略游戏评测”或 strategy games。',true)}
  ${field('至少多少粉丝','followers_min',f.followers_min,'number')}${field('最多多少粉丝','followers_max',f.followers_max,'number')}
  ${selectField('关注哪类内容','content_type',f.content_type,f.platform==='youtube'?[['all','不限内容形式'],['long','长视频'],['short','YouTube 短视频']]:[['all',f.platform==='twitch'?'直播观看':'不限内容形式']])}
  ${field('平均观看量至少多少','average_views_min',f.average_views_min,'number',false,'按上面选的内容类型筛选，不限则留空。')}
  ${selectField('这次最多找几位','limit',f.limit,[[5,'5 位'],[10,'10 位'],[20,'20 位']])}
  </div><div class="search-foot"><p>想找特定地区或语言的达人？可以写进搜索描述。找到后仍需确认其内容语言、粉丝来自哪里，以及是否符合目标玩家。</p><button class="primary" type="submit" ${d.busy||!source?.configured?'disabled':''}>${icon('search')}${d.busy?'正在寻找…':'确认条件与积分'}</button></div></fieldset></form></section>
  ${d.error?`<div class="info error">${esc(d.error)}</div>`:''}
  <div class="discovery-layout"><section class="panel"><div class="panel-head"><div><div class="panel-title">${r?.status==='done'?'本次找到的达人':'找到的达人'}</div><div class="panel-sub">${r?`${esc(providerName(r.query.provider))} · ${esc(r.query.platform)} · 第 ${r.page} 页 · ${esc(discoveryStatus(r.status))}`:'找到的达人会保存在这里，方便查看和挑选。'}</div></div>${r?.fetched_at?`<button class="ghost small" data-action="download-search" data-id="${r.id}">${icon('download')}下载搜索留档</button>`:''}</div>
  ${r?discoveryResults(r):`<div class="empty">${icon('search')}<h2>这次想和哪类达人合作？</h2><p>填写上方条件，确认服务积分后开始寻找。找到的达人可以加入备选名单，再比较内容、受众和报价。</p></div>`}</section>
  <aside class="panel search-history"><div class="panel-head"><div class="panel-title">找过的名单</div><span class="version">最近 25 次</span></div>${d.runs.length?d.runs.map(run=>`<button class="history-run ${r?.id===run.id?'active':''}" data-action="open-search" data-id="${run.id}"><strong>${esc(run.query.topic)}</strong><span>${esc(providerName(run.query.provider))} · 第 ${run.page} 页</span><small>${when(run.created_at)} · ${esc(discoveryStatus(run.status))}${run.status==='done'?` · ${run.items.length} 位`:''}</small></button>`).join(''):'<p class="blank">还没有搜索过达人。</p>'}</aside></div>`;
}
function discoveryResults(r){
  if(r.status==='prepared')return `<div class="empty"><h2>搜索条件已备好</h2><p>确认条件和服务积分后，即可开始找达人。</p>${canEdit()?`<button class="primary" data-action="confirm-search" data-id="${r.id}">确认条件与积分</button>`:''}</div>`;
  if(r.status==='running')return '<div class="empty"><h2>正在等待达人库的搜索结果</h2><p>点击“更新搜索进度”查看结果，不会再次搜索。如果等待过久或程序曾关闭，请先到达人库检查是否已扣积分。</p></div>';
  if(r.status==='failed')return `<div class="empty"><h2>这次搜索没有完成</h2><p>${esc(r.error||'请检查达人库账号和服务积分。')}</p></div>`;
  if(!r.items.length)return '<div class="empty"><h2>这次没有找到符合条件的达人</h2><p>试试更换内容方向，或放宽粉丝数、观看量要求后重新搜索。</p></div>';
  const hasProject=!!state.pid;
  return `<div class="search-result-note">搜索内容：${esc(r.query.topic)} · 搜索时间 ${when(r.fetched_at)}。名单按达人库推荐顺序展示，还需结合游戏判断是否适合。达人居住地不代表粉丝所在地。</div><div class="discovered-list">${r.items.map((x,i)=>`<article class="discovered-card"><div class="discovered-head">${canEdit()?`<input type="checkbox" data-discovered="${i}" ${discoveryState.selected.has(i)?'checked':''} ${!x.importable?'disabled':''} aria-label="选择 ${esc(x.name)}">`:''}${avatar(x.name,i)}<div><strong>${esc(x.name)}</strong><span class="subline">${esc(x.platform)}${x.account_id?' · '+esc(x.account_id):''}${r.query.provider==='nox'?' · 达人库可能隐藏部分名称':''}</span></div>${x.profile_url?`<a href="${esc(x.profile_url)}" target="_blank" rel="noopener noreferrer" class="profile-link">主页 ${icon('link')}</a>`:''}</div><div class="discovered-stats"><div><span>粉丝 / 订阅</span><b>${num(x.followers)}</b></div><div><span>${esc(x.metric_label)}</span><b>${num(x.average_views)}</b></div><div><span>达人所在地</span><b>${esc(x.creator_location||'暂无资料')}</b></div></div>${x.tags?`<p class="discovered-tags">${esc(x.tags)}</p>`:''}${x.description?`<p class="discovered-bio">${esc(x.description)}</p>`:''}<details><summary>合作前还要确认</summary><ul>${x.gaps.map(g=>`<li>${esc(g)}</li>`).join('')}</ul></details></article>`).join('')}</div><div class="search-import-bar"><div><strong id="discovery-selected-count">已选 ${discoveryState.selected.size} 位</strong><span>${hasProject?`将加入：${esc(state.data.project.name)}`:'先建立推广项目，再保存为该项目的备选达人。'}</span></div>${canEdit()?hasProject?'<button class="primary" data-action="import-search">加入项目备选</button>':'<button class="primary" data-action="new-project">创建项目</button>':''}</div><div class="table-footer"><span>已保存 ${r.items.length} 位 · 可随时回看，不会因查看再次扣积分</span>${r.more_available&&canEdit()?`<button class="small" data-action="next-search" data-id="${r.id}">继续找下一批 ${icon('arrow')}</button>`:'<span>本次名单已全部展示</span>'}</div>`;
}
function sourceModal(){
  modal('连接团队的达人库','选择团队已经购买或开通的达人库，完成一次设置后就能在这里找达人。',`<div class="info">保存后，点击“检查能否使用”确认账号可用。这里不会开始找达人，也不会消耗搜索积分。关闭程序后，需要重新连接。</div><div class="source-settings">${discoveryState.providers.map(p=>`<form class="source-form" data-provider="${p.id}"><h3>${esc(p.name)}</h3><p>${p.verified_at?'已连接，可以开始找达人':p.configured?'已保存，请检查能否使用':'尚未连接'} · ${p.platforms.map(x=>x.toUpperCase()).join(' / ')}</p><label class="field"><span>达人库授权码</span><input type="password" name="key" autocomplete="off" placeholder="粘贴达人库后台提供的授权码" required></label><div class="actions spacer"><button type="submit" class="primary small">保存授权码</button><button type="button" class="small" data-action="check-source" data-provider="${p.id}" ${!p.configured?'disabled':''}>检查能否使用</button><button type="button" class="ghost small" data-action="clear-source" data-provider="${p.id}" ${!p.configured?'disabled':''}>断开连接</button><a href="${esc(p.portal)}" target="_blank" rel="noopener noreferrer">前往达人库后台</a></div><details class="spacer"><summary>授权码在哪里找？</summary><p>打开上方达人库后台，查找 API Key（供工具使用的授权码）。它不是登录密码；如后台没有这一项，请让账号负责人确认套餐是否支持。请勿把授权码填到搜索描述或项目备注中。</p></details><div class="source-check-result" data-provider="${p.id}"></div></form>`).join('')}</div>`);
  $$('.source-form').forEach(form=>form.addEventListener('submit',e=>{e.preventDefault();run(async()=>{const button=$('button[type=submit]',form);button.disabled=true;try{const data=await api('/api/discovery/config',{method:'POST',body:{provider:form.dataset.provider,key:form.elements.key.value}});form.reset();discoveryState.providers=data.providers;render();sourceModal();toast('授权码已保存，可以检查是否能使用。尚未开始找达人。');}finally{button.disabled=false;}});}));
}
function searchPreviewModal(plan){
  const q=plan.query;
  modal('确认本次找达人','只搜索下面这批达人。继续找更多达人时，会另行确认积分。',`<dl class="snapshot-grid"><dt>使用的达人库</dt><dd>${esc(providerName(q.provider))}</dd><dt>平台</dt><dd>${esc(q.platform)}</dd><dt>想找的达人</dt><dd>${esc(q.topic)}</dd><dt>粉丝范围</dt><dd>${q.followers_min==null?'不限下限':num(q.followers_min)} 至 ${q.followers_max==null?'不限上限':num(q.followers_max)}</dd><dt>内容类型 / 最少平均观看量</dt><dd>${({all:'不限内容形式',long:'长视频',short:'YouTube 短视频'})[q.content_type]} / ${q.average_views_min==null?'不限观看量':num(q.average_views_min)}</dd><dt>本次搜索数量</dt><dd>第 ${plan.page} 页，最多 ${q.limit} 位达人</dd><dt>预计消耗</dt><dd>最多约 ${esc(plan.price.estimated_credit)} 服务积分（不是人民币）</dd></dl><div class="info warning">${esc(plan.price.basis)} 不会自动获取联系方式、解锁详情或发送邀约。</div><div class="info">${q.provider==='club'?'选择长视频或短视频，只表示达人发布过这类内容，不一定是其主要内容。':'达人库可能隐藏部分名称，请在决定合作前确认真实账号与主页。'} 描述中的地区和语言仅供搜索参考，粉丝是否来自目标市场仍需核实。</div><form id="confirm-search-form"><label class="check-field"><input type="checkbox" required name="accept_cost"><span>我已确认以上条件，同意使用这个达人库账号的服务积分。</span></label><div class="form-footer"><button type="button" data-action="close">再改改条件</button><button type="submit" class="primary">确认，开始找达人</button></div></form>`);
  $('#confirm-search-form').addEventListener('submit',e=>{e.preventDefault();run(async()=>{
    const button=$('button[type=submit]',e.target);button.disabled=true;closeModal(true);discoveryState.busy=true;discoveryState.error='';discoveryState.run={...plan,status:'running'};discoveryState.selected.clear();render();
    try{discoveryState.run=await api('/api/discovery/runs/'+plan.id+'/execute',{method:'POST',body:{accept_cost:true}});toast(`这次找到 ${discoveryState.run.items.length} 位达人。`);}catch(err){discoveryState.error=err.message;}finally{discoveryState.busy=false;await loadDiscovery();}
  });});
}
async function prepareSearch(body){
  discoveryState.busy=true;discoveryState.error='';render();
  try{const plan=await api('/api/discovery/preview',{method:'POST',body});discoveryState.run=plan;discoveryState.selected.clear();await loadDiscovery(false);searchPreviewModal(plan);}
  catch(err){discoveryState.error=err.message;}
  finally{discoveryState.busy=false;render();}
}
function bindDiscovery(){
  const form=$('#discover-form');if(!form)return;
  form.addEventListener('input',()=>{discoveryState.form={...readForm(form),limit:Number(form.elements.limit.value)};});
  form.addEventListener('change',e=>{discoveryState.form={...readForm(form),limit:Number(form.elements.limit.value)};
    if(e.target.name==='provider'){const source=discoveryState.providers.find(p=>p.id===e.target.value);if(!source.platforms.includes(discoveryState.form.platform))discoveryState.form.platform=source.platforms[0];render();}
    else if(e.target.name==='platform'){if(e.target.value!=='youtube')discoveryState.form.content_type='all';render();}
  });
  form.addEventListener('submit',e=>{e.preventDefault();run(()=>prepareSearch({...readForm(form),limit:Number(form.elements.limit.value)}));});
}
document.addEventListener('click',e=>{
  const button=e.target.closest('[data-action]');if(!button)return;
  const action=button.dataset.action;
  run(async()=>{
    if(action==='connect-sources')sourceModal();
    if(action==='reload-discovery')await loadDiscovery();
    if(action==='clear-source'){const data=await api('/api/discovery/config',{method:'POST',body:{provider:button.dataset.provider,key:''}});discoveryState.providers=data.providers;render();sourceModal();}
    if(action==='check-source'){button.disabled=true;const output=$(`.source-check-result[data-provider="${button.dataset.provider}"]`);output.textContent='正在检查达人库账号是否可用…';try{await api('/api/discovery/check',{method:'POST',body:{provider:button.dataset.provider}});await loadDiscovery(false);output.textContent='账号可用，可以开始找达人了。本次检查没有搜索达人。';render();}catch(err){output.textContent=err.message;}finally{button.disabled=false;}}
    if(action==='open-search'){discoveryState.run=await api('/api/discovery/runs/'+button.dataset.id);discoveryState.selected.clear();discoveryState.error='';render();}
    if(action==='confirm-search')searchPreviewModal(discoveryState.runs.find(r=>r.id===button.dataset.id)||discoveryState.run);
    if(action==='download-search')window.location='/api/discovery/runs/'+button.dataset.id+'/raw';
    if(action==='next-search')await prepareSearch({parent_id:button.dataset.id});
    if(action==='import-search'){
      if(!discoveryState.selected.size)throw new Error('先勾选想加入备选名单的达人。');
      button.disabled=true;const projectId=state.pid,runId=discoveryState.run.id;
      try{const result=await api('/api/discovery/runs/'+runId+'/import',{method:'POST',body:{project_id:projectId,indices:[...discoveryState.selected]}});discoveryState.selected.clear();await refresh();toast(`已加入备选 ${result.count} 位；${result.skipped} 位已在名单中，无需重复添加。`);}finally{button.disabled=false;}
    }
  });
});
document.addEventListener('change',e=>{
  if(e.target.matches('[data-discovered]')){const i=Number(e.target.dataset.discovered);if(e.target.checked)discoveryState.selected.add(i);else discoveryState.selected.delete(i);$('#discovery-selected-count').textContent=`已选 ${discoveryState.selected.size} 位`;}
});
