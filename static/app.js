const $ = (q, root = document) => root.querySelector(q);
const $$ = (q, root = document) => [...root.querySelectorAll(q)];
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icons = {
  grid:'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',
  compare:'M5 4v16M12 4v16M19 4v16M2 8h6M9 16h6M16 11h6',
  history:'M4 6v5h5M4.5 10a8 8 0 1 1 1 7M12 7v5l3 2',
  users:'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M20 21v-2a4 4 0 0 0-3-3.9M16 3a4 4 0 0 1 0 8M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0',
  plus:'M12 5v14M5 12h14', search:'M21 21l-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
  arrow:'M5 12h14M14 7l5 5-5 5', upload:'M12 16V3M7 8l5-5 5 5M4 16v5h16v-5',
  download:'M12 3v13M7 11l5 5 5-5M4 17v4h16v-4', check:'M5 12l4 4L19 6',
  clock:'M12 8v5l3 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
  wallet:'M3 6h16v14H3zM3 6V3h14v3M15 11h6v5h-6z',
  flag:'M5 21V3M5 3c5-4 9 4 14 0v10c-5 4-9-4-14 0',
  logout:'M9 4H4v16h5M10 12h11M16 7l5 5-5 5',
  edit:'M15 4l5 5M4 20l4-1L20 7a2 2 0 0 0-4-4L4 15z',
  link:'M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-3 3M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l3-3',
  alert:'M12 3L2 21h20zM12 9v5M12 17v1', file:'M6 2h9l4 4v16H6zM14 2v5h5M9 12h7M9 16h7',
  shield:'M12 2L3 6v6c0 5 9 10 9 10s9-5 9-10V6zM8 12l3 3 5-6'
};
const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${icons[name] || icons.grid}"/></svg>`;
const roles = {admin:'管理员',editor:'项目执行',reviewer:'审批人'};
const states = {draft:['草拟中','gray'],pending:['待审批','blue'],approved:['已批准','green'],changes:['需补充','amber'],rejected:['暂不合作','red']};
const actions = {project_created:'项目建立',project_updated:'项目条件变更',created:'新增候选',updated:'更新记录',selected:'调整组合',submitted:'提交决策',review_approve:'内部批准',review_changes:'退回补充',review_reject:'暂不合作',comment:'团队讨论'};
const state = {user:null,projects:[],users:[],pid:localStorage.getItem('kol_project'),data:null,view:'discover',filter:'all',query:'',modalTab:'evidence'};
let toastTimer, dirty = false, previewCsv = '';
const canEdit = () => ['admin','editor'].includes(state.user?.role);
const canReview = () => ['admin','reviewer'].includes(state.user?.role);
const money = (v, currency) => v == null ? '待确认' : new Intl.NumberFormat(window.KOL_LANG==='en'?'en-US':'zh-CN',{style:'currency',currency:currency || state.data?.project.currency || 'USD',maximumFractionDigits:2}).format(v);
const num = v => v == null ? '—' : new Intl.NumberFormat(window.KOL_LANG==='en'?'en-US':'zh-CN',{maximumFractionDigits:0}).format(v);
const when = v => v ? new Date(v).toLocaleString(window.KOL_LANG==='en'?'en-US':'zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}) : '—';
const tag = (text,color='gray') => `<span class="tag ${color}">${esc(text)}</span>`;
const status = d => tag(...(states[d.state] || states.draft));
const safeURL = v => /^https?:\/\//.test(v || '') ? v : '#';
const ownerName = id => state.users.find(u=>u.id===id)?.name || '未分配';
const avatar = (name,index=0) => `<div class="creator-avatar a${index%4}">${esc((name||'K').split(' ').map(w=>w[0]).slice(0,2).join('').toUpperCase())}</div>`;

function toast(message, error=false){
  const el=$('#toast'); el.textContent=message; el.className='show'+(error?' error':'');
  clearTimeout(toastTimer); toastTimer=setTimeout(()=>el.className='',error?6500:3500);
}
async function api(url,options={}){
  const headers={'Content-Type':'application/json','X-KOL-Language':window.KOL_LANG||'zh',...(state.user?.csrf?{'X-CSRF-Token':state.user.csrf}:{}),...options.headers};
  let res;try{res=await fetch(url,{...options,headers,body:options.body!==undefined?JSON.stringify(options.body):undefined});}catch(_){throw new Error(window.KOL_LANG==='en'?'The workspace is not running. Open the launcher and refresh this page.':'工作台没有运行，请打开启动程序后刷新页面。');}
  const data=await res.json();
  if(!res.ok){
    if(res.status===401 && state.user){state.user=null;closeModal(true);await boot();}
    throw new Error(data.error || '操作未完成，请稍后再试。');
  }
  return data;
}
async function run(fn){try{await fn();}catch(err){toast(err.message,true);}}
async function boot(){
  const b=await api('/api/bootstrap'); state.user=b.user; state.projects=b.projects; state.users=b.users; state.localMode=b.local_mode;
  if(!state.user){renderAuth(b.needs_setup);return;}
  await loadDiscovery(false);
  if(!state.projects.some(p=>p.id===state.pid)) state.pid=state.projects[0]?.id || null;
  if(state.pid) await loadProject(state.pid); else {state.data=null;render();}
}
async function loadProject(pid){
  state.pid=pid;localStorage.setItem('kol_project',pid);
  state.data=await api('/api/projects/'+pid);
  state.projects=state.projects.map(p=>p.id===pid?state.data.project:p);render();
}
async function refresh(){await loadProject(state.pid);}
function nav(view,label,ico,count=''){
  return `<button class="navbutton ${state.view===view?'active':''}" data-action="nav" data-view="${view}" title="${label}">${icon(ico)}<span class="navtext">${label}</span>${count!==''?`<span class="count">${count}</span>`:''}</button>`;
}
function languageButton(){return `<button type="button" class="language-switch" data-action="language" aria-label="${window.KOL_LANG==='en'?'Switch to Chinese':'Switch to English'}">${window.KOL_LANG==='en'?'\u4e2d\u6587':'English'}</button>`;}
function render(){
  const p=state.data?.project,s=state.data?.summary;
  const labels={discover:'找达人',pool:'备选名单',compare:'报价对比',history:'合作审批',team:state.localMode?'使用说明':'团队成员'};
  $('#app').innerHTML=`<div class="shell"><aside class="sidebar">
    <div class="brand"><span class="brandmark">k.</span><span class="brand-name">KOL Desk</span></div><div class="brand-sub">游戏达人合作工作台</div>
    <nav><div class="nav-label">合作流程</div>${nav('discover','找达人','search')}${nav('pool','备选名单','grid',s?.total??'')}${nav('compare','报价对比','compare',s?.selected_count??'')}${nav('history','合作审批','history',s?.pending||'')}<div class="nav-label">${state.localMode?'帮助':'团队'}</div>${nav('team',state.localMode?'使用说明':'成员与权限',state.localMode?'file':'users')}</nav>
    <div class="side-note">找到对的达人，谈清每项合作<br>每一笔预算，都有依据。</div>
    <div class="side-user"><span class="avatar">${esc(state.user.name[0])}</span><div class="user-info"><strong>${esc(state.user.name)}</strong><small>${state.localMode?'免登录 · 本机保存':roles[state.user.role]}</small></div>${state.localMode?'<span class="workspace-online" aria-label="工作台已就绪"></span>':`<button class="ghost" data-action="logout" title="退出登录">${icon('logout')}</button>`}</div>
    </aside><main class="main"><header class="topbar"><div class="breadcrumb">工作空间 <span>/</span> <strong>${labels[state.view]}</strong></div><div class="top-tools">${languageButton()}<span class="local-badge"><span class="dot"></span>本地工作台</span>
    <select class="project-select" id="project-switch" aria-label="切换项目"><option value="">${state.projects.length?'选择项目':'暂无项目'}</option>${state.projects.map(x=>`<option value="${x.id}" ${x.id===state.pid?'selected':''}>${esc(x.name)}</option>`).join('')}</select>
    ${canEdit()?`<button class="small" data-action="new-project">${icon('plus')}新建项目</button>`:''}</div></header>
    <div class="content">${state.view==='discover'?discoveryView():state.view==='team'?teamView():!p?emptyWorkspace():`${p.is_demo?`<div class="demo-notice">${icon('flag')}<span><strong>示例项目</strong> · 达人、报价和证据均为合成数据，可自由体验工作流程。</span><button class="ghost" data-action="new-project">创建真实项目 ${icon('arrow')}</button></div>`:''}${state.view==='pool'?poolView():state.view==='compare'?compareView():historyView()}`}</div></main></div>`;
  if(state.view==='discover')bindDiscovery();
}
function emptyWorkspace(){return `<section class="panel welcome"><div class="welcome-icon">${icon('grid')}</div><div class="eyebrow">开始新的达人合作</div><h1>从合适的达人，<br>开始下一次合作。</h1><p>把玩家匹配、完整报价和合作决定放在同一张工作台。创建一个项目，逐步整理每一条证据与每一笔预算。</p><div class="actions">${canEdit()?`<button class="primary" data-action="new-project">${icon('plus')}创建第一个项目</button><button data-action="demo">体验示例项目 ${icon('arrow')}</button>`:'项目建立后，即可参与合作评审。'}</div></section><div class="guide-grid"><section class="panel compact"><span class="guide-step">01 / 找达人</span><h3>选对达人</h3><p>从目标玩家与内容匹配出发，记录可回查的证据。</p></section><section class="panel compact"><span class="guide-step">02 / 比报价</span><h3>看清完整报价</h3><p>交付、授权与费用逐项对齐，再比较组合预算。</p></section><section class="panel compact"><span class="guide-step">03 / 定合作</span><h3>留下决策依据</h3><p>记下为什么合作；报价或要求变化后，再确认一次。</p></section></div><div class="footer-note">${state.localMode?'无需登录 · 数据本机保存 · 随时继续上次的工作':'项目与决策按当前成员权限管理'}</div>`;}
function pageHead(title,description,buttons=''){return `<div class="page-head"><div><div class="eyebrow">达人合作管理</div><h1>${esc(title)}</h1><p>${esc(description)}</p></div><div class="actions">${buttons}</div></div>`;}
function metric(label,value,foot,ico,accent=false){return `<div class="metric ${accent?'accent':''}"><div class="metric-top">${label}${icon(ico)}</div><div class="metric-number">${value}</div><div class="metric-foot">${foot}</div></div>`;}
function poolView(){
  const {project:p,summary:s,candidates}=state.data;
  const missing=candidates.filter(x=>!x.assessment.ready), ready=candidates.filter(x=>x.assessment.ready);
  const filters=[['all','全部',s.total],['gaps','待补充',missing.length],['ready','可决策',ready.length],['pending','待审批',s.pending]];
  return pageHead(p.name,`${p.game} · ${p.market} · 以${p.goal}为目标`,`${canEdit()?`<button data-action="nav" data-view="discover">${icon('search')}找达人</button><button data-action="import">${icon('upload')}导入名单</button><button class="primary" data-action="new-candidate">${icon('plus')}新增达人</button>`:`<button data-action="report">${icon('download')}导出报告</button>`}`)+`
    <div class="metrics">${metric('项目总预算',money(p.budget,p.currency),'含已约定权利及最高绩效承诺','wallet')}${metric('候选达人',`${s.total}<small> 位</small>`,`${ready.length} 位满足当前决策条件`,'users')}${metric('所选合作最高总费用',s.selection_complete?money(s.selected_max_cost,p.currency):`${money(s.known_selected_cost,p.currency)}<small> + 待定</small>`,`${s.selected_count} 位已入组合${s.over_budget?' · 已知费用超预算':''}`,'compare')}${metric('可用预算',s.remaining!==null?`<span class="${s.remaining<0?'negative':''}">${money(s.remaining,p.currency)}</span>`:'待补齐费用',s.selection_complete?'按完整组合成本测算':'补齐费用后计算剩余预算','flag',true)}</div>
    <div class="project-strip"><div class="strip-item">主要目标<b>${esc(p.goal)}</b></div><div class="strip-item">市场 / 语言<b>${esc(p.market)} / ${esc(p.language||'未限定')}</b></div><div class="strip-item">内容形式<b>${esc(p.format)}</b></div><div class="strip-item">目标受众<b>${p.min_audience_pct!==null?`≥ ${p.min_audience_pct}%`:'未设比例门槛'}${p.require_audience?' · 需核验':''}</b></div><div class="strip-item">广告使用权<b>${p.require_paid_rights?'必须包含':'本轮不要求'}</b></div><button class="ghost small" data-action="edit-project">${icon('edit')}${canEdit()?'修改条件':'查看条件'}</button></div>
    <section class="panel"><div class="panel-head"><div><div class="panel-title">备选名单 <span class="pill">${s.total}</span></div><div class="panel-sub">以匹配证据和完整合作条件为依据，保留每个未知项。</div></div><button class="ghost small" data-action="export">${icon('download')}导出</button></div>
    <div class="toolbar"><div class="filters">${filters.map(([v,l,n])=>`<button data-action="filter" data-filter="${v}" class="${state.filter===v?'active':''}">${l} <span>${n}</span></button>`).join('')}</div><label class="search">${icon('search')}<input id="candidate-search" placeholder="搜索达人、品类或平台" value="${esc(state.query)}" aria-label="搜索达人"></label></div>
    <div id="candidate-table">${candidateTable()}</div><div class="table-footer"><span>勾选加入报价组合；内部审批另行进行。</span><button class="ghost small" data-action="nav" data-view="compare"><strong>查看 ${s.selected_count} 位组合</strong>${icon('arrow')}</button></div></section>
    <div class="bottom-grid"><section class="panel compact"><h3>下一步值得推进的事</h3><p>优先补齐会影响合作决定的信息。</p>${missing.length?missing.slice(0,3).map((d,i)=>`<div class="todo-row"><span class="todo-num">${i+1}</span><div><strong>${esc(d.name)}</strong><p>${esc(d.next_action||d.assessment.blockers[0])}</p></div><button class="ghost small" data-action="candidate" data-id="${d.id}">${icon('arrow')}</button></div>`).join(''):`<div class="todo-row">${icon('check')}<p>候选证据已就绪，可比较合作包并提交决策。</p></div>`}</section>
    <section class="panel compact"><h3>达人资料与合作资料完整度</h3><p>条件满足只表示可以进入决策，不代表效果保证。</p><progress class="budget-progress" value="${ready.length}" max="${Math.max(s.total,1)}" aria-label="已就绪候选占比"></progress><div class="legend"><span><i></i>可决策 ${ready.length} 位</span><span><i class="amber"></i>待补充 ${missing.length} 位</span></div><div class="info">${s.pending?`${s.pending} 位达人正在等待审批人作出决定。`:'提交时将保留当前达人资料和合作条件；之后修改条件，需要重新审批。'}</div></section></div><div class="footer-note">数据保存在当前工作台。预估播放和转化仅供预算参考，不代表达人承诺的效果。</div>`;
}
function candidateTable(){
  const ds=state.data.candidates.filter(d=>{
    const match=(`${d.name} ${d.platform} ${d.content_genre}`).toLowerCase().includes(state.query.toLowerCase());
    return match && (state.filter==='all'||state.filter==='gaps'&&!d.assessment.ready||state.filter==='ready'&&d.assessment.ready||state.filter==='pending'&&d.state==='pending');
  });
  if(!ds.length)return `<div class="empty">${icon('search')}<h2>${state.data.candidates.length?'没有符合条件的候选':'备选名单还没有达人'}</h2><p>${state.data.candidates.length?'调整筛选条件，或搜索其他名字。':'手动添加达人，或下载名单模板，填好后上传。'}</p>${canEdit()&&!state.data.candidates.length?`<button class="primary" data-action="new-candidate">新增第一位达人</button>`:''}</div>`;
  return `<div class="table-scroll"><table><thead><tr><th class="check-col">组合</th><th>达人 / 平台</th><th>目标受众</th><th>合作资料完整度</th><th>完整合作费用</th><th>内部状态</th><th>负责人</th><th></th></tr></thead><tbody>${ds.map((d,i)=>{
    const a=d.assessment;
    return `<tr class="candidate-row"><td class="check-col"><input type="checkbox" data-select="${d.id}" ${d.selected?'checked':''} ${!canEdit()||d.state==='approved'?'disabled':''} aria-label="将 ${esc(d.name)} 加入组合"></td><td><div class="creator-cell">${avatar(d.name,i)}<div><button class="text-button" data-action="candidate" data-id="${d.id}">${esc(d.name)}</button><span class="subline">${d.platform} · ${num(d.followers)} 粉丝</span></div></div></td><td>${d.audience_pct!==null?`${esc(d.audience_market||'未知市场')} ${d.audience_pct}%`:'<span class="muted">数据待补充</span>'}<span class="subline">${d.audience_verified?'已人工核验':'尚未核验'}</span></td><td>${tag(a.ready?'可决策':a.label,a.ready?'green':a.label==='条件不满足'?'red':'amber')}<span class="subline">${a.blockers.length?`${a.blockers.length} 项待处理`:'证据与条款已齐备'}</span></td><td><span class="money">${money(a.known_cost,d.quote.currency)}${!a.cost_complete?' + 待定':''}</span><span class="subline">${a.cost_complete?'最高合作费用':'仅已知部分费用'}</span></td><td>${status(d)}</td><td><span class="owner"><span class="mini-avatar">${esc(ownerName(d.owner_id)[0])}</span>${esc(ownerName(d.owner_id))}</span></td><td><button class="ghost small" data-action="candidate" data-id="${d.id}" aria-label="查看 ${esc(d.name)}">${icon('arrow')}</button></td></tr>`;
  }).join('')}</tbody></table></div>`;
}
function compareView(){
  const {project:p,summary:s}=state.data, ds=state.data.candidates.filter(d=>d.selected||d.state==='approved');
  return pageHead('把合作条件，放在同一张桌上',`${p.name} · 金额按同币种、完整范围比较`,`<button data-action="report">${icon('download')}决策报告</button><button class="primary" data-action="nav" data-view="pool">调整组合 ${icon('arrow')}</button>`)+`
    <div class="budget-banner ${!s.selection_complete||s.over_budget?'warning':''}"><div><strong>${s.over_budget?'当前组合已超过预算':!s.selection_complete?'先补齐费用，再判断预算':'当前组合在预算范围内'}</strong><p>${s.selected_count} 位候选 · 预算 ${money(p.budget,p.currency)}${s.remaining!==null?` · 余量 ${money(s.remaining,p.currency)}`:' · 存在币种或费用缺口'}</p></div><div class="value">${money(s.known_selected_cost,p.currency)}${!s.selection_complete?' + 待定':''}</div></div>
    ${!ds.length?`<div class="panel empty spacer">${icon('compare')}<h2>先选出想比较的合作</h2><p>在备选名单勾选达人，即可比较完整报价、权利范围和合作前待确认事项。</p><button data-action="nav" data-view="pool">返回备选名单</button></div>`:`<div class="comparison">${ds.map((d,i)=>{const a=d.assessment,q=d.quote;return `<article class="compare-card">${avatar(d.name,i)}<h3>${esc(d.name)}</h3><span class="subline">${d.platform} · ${esc(d.format)}</span><div class="badge-row">${status(d)}${tag(a.label,a.ready?'green':'amber')}</div><div class="compare-price">${money(a.known_cost,q.currency)}</div><span class="subline">${a.cost_complete?'最高总费用 · 含已填写的全部费用':'仅含已确认费用 · 还有费用待补充'}</span><div class="spacer">${[['达人费','fee'],['素材授权','usage'],['排他费用','exclusivity_fee'],['制作 / 本地化','production'],['税费 / 代理 / 支付','tax'],['奖金上限','bonus_cap']].map(([l,k])=>`<div class="compare-row"><span>${l}</span><span>${money(q[k],q.currency)}</span></div>`).join('')}</div><div class="compare-section"><b>交付范围</b>${esc(q.deliverables||'待确认')}</div><div class="compare-section"><b>素材权利</b>${esc(q.rights||'待确认')}</div><div class="compare-section"><b>付款与取消</b>${esc(q.payment||'待确认')}</div><div class="compare-section"><b>预估投放成本 · 非实际效果</b><div class="compare-row"><span>每次预估播放成本</span><span>${a.forecast_cpv==null?'未计算':money(a.forecast_cpv,q.currency)}</span></div><div class="compare-row"><span>每次预期${esc(p.goal)}成本</span><span>${a.forecast_cpa==null?'未计算':money(a.forecast_cpa,q.currency)}</span></div><span class="subline">${esc(q.forecast_basis||'填写同类作品的预估表现和参考依据后计算。')}</span></div><div class="compare-section"><b>${a.blockers.length?'合作前待确认事项':'已满足当前条件'}</b>${a.blockers.length?`<ul>${a.blockers.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:'可由团队结合主目标与备选方案决定。'}</div><button class="small spacer" data-action="candidate" data-id="${d.id}">查看达人资料与合作条件 ${icon('arrow')}</button></article>`}).join('')}</div>`}<div class="footer-note">组合金额包含已批准合作；批准不等于对外签约。不同币种不得直接相加，缺失费用不会自动记作 0。</div>`;
}
function historyView(){
  const pending=state.data.candidates.filter(d=>d.state==='pending');
  return pageHead('让每个决定，都能回看','回看每次合作的资料、报价、审批理由和经办人。',`<button data-action="report">${icon('download')}导出决策报告</button>`)+
    (pending.length?`<div class="panel compact"><h3>等待内部决策 · ${pending.length}</h3>${pending.map(d=>`<div class="todo-row">${avatar(d.name)}<div><strong>${esc(d.name)}</strong><p>${d.assessment.blockers.length?`${d.assessment.blockers.length} 项条件待解决`:'条件已齐备，等待审批人判断'} · ${money(d.assessment.known_cost,d.quote.currency)}</p></div><button class="small" data-action="candidate" data-id="${d.id}" data-tab="collaboration">查看并决策 ${icon('arrow')}</button></div>`).join('')}</div>`:'')+
    `<section class="panel spacer"><div class="panel-head"><div class="panel-title">项目时间线</div><span class="version">最近 250 条记录</span></div><div class="timeline">${state.data.events.map(e=>eventHTML(e)).join('')||'<div class="blank">暂无记录</div>'}</div></section>`;
}
function eventHTML(e){return `<div class="event"><div class="event-time">${when(e.created_at)}<br>${esc(e.user_name)}</div><div><strong>${esc(actions[e.action]||e.action)}${e.candidate_id?` · ${esc(state.data.candidates.find(d=>d.id===e.candidate_id)?.name||'达人')}`:''}</strong><p>${esc(e.note)}</p>${e.action!=='comment'?`<details><summary>查看当时的合作资料</summary>${snapshotHTML(e.snapshot)}</details>`:''}</div></div>`;}
function snapshotHTML(s){
  if(!s)return '<p>暂无历史资料。</p>';
  const rows=items=>`<dl class="snapshot-grid">${items.filter(([,v])=>v!==undefined).map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v===null||v===''?'未记录':v)}</dd>`).join('')}</dl>`;
  const record=d=>{
    if(d.quote){const q=d.quote;return rows([['达人',d.name],['平台 / 账号',`${d.platform} · ${d.account_id||d.profile_url}`],['资料修订次数',d.version],['状态',d.state?states[d.state]?.[0]:undefined],['玩家匹配',({match:'符合本轮目标',mismatch:'不符合本轮目标',unknown:'尚未确认'})[d.fit]],['匹配依据',d.fit_note],['内容证据',d.source_url],['核验日期',d.evidence_date],['样本说明',d.evidence_note],['受众市场 / 占比',`${d.audience_market||'未知'} / ${d.audience_pct===null?'未知':d.audience_pct+'%'}`],['受众来源',d.audience_source],['人工核验',d.audience_verified?'已核验':'未核验'],['币种',q.currency],... [['达人费','fee'],['授权费','usage'],['排他费','exclusivity_fee'],['制作 / 本地化','production'],['税费 / 代理 / 支付','tax'],['奖金上限','bonus_cap']].map(([l,k])=>[l,money(q[k],q.currency)]),['费用核实',q.cost_complete?'已确认完整':'尚未完整'],['交付范围',q.deliverables],['权利范围',q.rights],['付款 / 取消',q.payment],['报价日期',q.quoted_at],['有效期',q.valid_until],['档期与排他依据',d.terms_note],['预测依据',q.forecast_basis],['下一步',d.next_action]]);}
    if(d.game)return rows([['项目',d.name],['要求修订次数',d.version],['游戏',d.game],['品类',d.genre],['目标',d.goal],['市场 / 语言',`${d.market} / ${d.language||'未限定'}`],['合作形式',d.format],['预算',money(d.budget,d.currency)],['最低受众占比',d.min_audience_pct===null?'未设置':d.min_audience_pct+'%'],['受众必须核验',d.require_audience?'是':'否'],['广告使用权',d.require_paid_rights?'必须包含':'本轮不要求'],['要求',d.notes]]);
    return rows([['是否入组合',d.selected===undefined?undefined:d.selected?'是':'否']]);
  };
  if(s.before&&s.after)return `<h4>变更前</h4>${record(s.before)}<h4>变更后</h4>${record(s.after)}`;
  if(s.record)return `<h4>当时的合作条件</h4>${record(s.record)}<h4>当时的项目条件</h4>${record(s.project)}${s.combination?`<h4>审批时的预算组合</h4>${rows(s.combination.candidates.map(d=>[d.name,money(d.assessment.max_cost,d.quote.currency)]))}${rows([['组合总额',money(s.combination.summary.selected_max_cost,s.project.currency)],['预算余量',money(s.combination.summary.remaining,s.project.currency)]])}`:''}`;
  return record(s);
}
function teamView(){if(state.localMode)return localWorkspaceView();return pageHead('同一套事实，一起做决定','执行成员整理证据和合作包，审批人记录最终判断。',`${state.user.role==='admin'?`<button class="primary" data-action="new-user">${icon('plus')}添加成员</button>`:''}<button data-action="password">修改我的密码</button><button data-action="logout">退出登录</button>`)+`
  <div class="info">此版本在当前电脑本地运行，支持多个成员账号与角色切换。团队所有成员共享项目；审批记录保留真实登录账号。尚未开放局域网或互联网访问。</div><div class="member-grid">${state.users.map(u=>`<article class="member-card"><span class="avatar">${esc(u.name[0])}</span><div><strong>${esc(u.name)}${u.id===state.user.id?' · 我':''}</strong><p>@${esc(u.username)}</p>${tag(roles[u.role],u.role==='admin'?'green':u.role==='reviewer'?'blue':'gray')}</div></article>`).join('')}</div><div class="panel compact spacer"><h3>角色与权限</h3><div class="table-scroll"><table><thead><tr><th>角色</th><th>项目与候选编辑</th><th>内部审批</th><th>成员管理</th><th>讨论与导出</th></tr></thead><tbody><tr><td>管理员</td><td>可以</td><td>可以</td><td>可以</td><td>可以</td></tr><tr><td>项目执行</td><td>可以</td><td>不可以</td><td>不可以</td><td>可以</td></tr><tr><td>审批人</td><td>只读</td><td>可以</td><td>不可以</td><td>可以</td></tr></tbody></table></div></div>`;}

function localWorkspaceView(){return pageHead('打开即用，专注合作决策','当前工作台使用免登录模式，所有内容保存在这台电脑。',`<button class="primary" data-action="new-project">${icon('plus')}创建项目</button>`)+`
  <div class="guide-grid"><section class="panel compact"><span class="guide-step">01</span><h3>整理候选与证据</h3><p>建立项目，录入或导入达人名单。记录代表内容、受众来源和匹配理由，未知信息可以留空。</p></section><section class="panel compact"><span class="guide-step">02</span><h3>比较完整合作包</h3><p>核对达人费、授权、排他、制作、税费和奖金上限。勾选候选后，查看组合总价和预算余量。</p></section><section class="panel compact"><span class="guide-step">03</span><h3>记录每个合作决定</h3><p>提交、批准或退回，留下具体理由。报价或项目条件修改后，原批准需要重新复核。</p></section></div>
  <section class="panel compact spacer"><h3>当前使用方式</h3><div class="workspace-facts"><div><span>访问</span><strong>本机直接打开，无需注册</strong></div><div><span>保存</span><strong>自动保存已提交的表单与记录</strong></div><div><span>操作身份</span><strong>统一记为“本地工作台”</strong></div><div><span>数据来源</span><strong>达人库搜索、手动添加或上传名单</strong></div></div><p class="spacer">免登录模式下，不区分个人操作权限。历史记录仍保留，示例项目与真实项目分别标识；项目与报价保存在本机；找达人时，只向所选达人库提交搜索条件及账号授权。</p></section>`;}

function renderAuth(setup){
  $('#app').innerHTML=`<div class="auth"><section class="auth-story"><div class="brand"><span class="brandmark">k.</span>KOL Desk</div><div><div class="eyebrow">GAME CREATOR OPERATIONS</div><h1>好的合作，<br>从有依据的<br>判断开始。</h1><p>从玩家匹配，到完整报价与内部决策。<br>把游戏 KOL 合作里的重要细节放在一起。</p></div><small>EVIDENCE → TERMS → DECISION</small></section><main class="auth-form-area">${languageButton()}<form id="auth-form" class="auth-form"><div class="eyebrow">${setup?'CREATE YOUR WORKSPACE':'WELCOME BACK'}</div><h2>${setup?'建立你的团队工作台':'回到工作台'}</h2><p>${setup?'创建首位管理员。数据保存在本机，后续可添加执行成员与审批人。':'使用你的团队账号登录，继续上一次合作决策。'}</p>${setup?field('你的姓名','name','', 'text',true):''}${field('登录名','username','', 'text',true,setup?'至少 3 位英文或数字，可含 . _ -':'')}${field('密码','password','', 'password',true,setup?'至少 10 个字符':'')}<div id="auth-error" class="auth-error" role="alert"></div><button class="primary" type="submit">${setup?'创建工作台':'登录'} ${icon('arrow')}</button><div class="auth-foot">本地保存 · 独立账号 · 版本与审批留痕<br>整理名单、比较报价和审批合作无需连接达人库。</div></form></main></div>`;
  $('#auth-form').addEventListener('submit',async e=>{
    e.preventDefault();const btn=$('button[type=submit]',e.target);btn.disabled=true;
    try{await api(setup?'/api/setup':'/api/login',{method:'POST',body:Object.fromEntries(new FormData(e.target))});await boot();}
    catch(err){$('#auth-error').textContent=err.message;btn.disabled=false;}
  });
}
function field(label,name,value='',type='text',required=false,hint='',full=false){return `<label class="field ${full?'full':''}"><span>${label}${required?' *':''}</span>${type==='textarea'?`<textarea name="${name}" ${required?'required':''}>${esc(value)}</textarea>`:`<input name="${name}" type="${type}" value="${esc(value)}" ${required?'required':''} ${type==='number'?'min="0" step="any"':''} ${type==='password'?'autocomplete="current-password"':''}>`}${hint?`<small>${esc(hint)}</small>`:''}</label>`;}
function selectField(label,name,value,options,full=false){return `<label class="field ${full?'full':''}"><span>${label}</span><select name="${name}">${options.map(x=>{const [v,l]=Array.isArray(x)?x:[x,x];return `<option value="${esc(v)}" ${v===value?'selected':''}>${esc(l)}</option>`}).join('')}</select></label>`;}
function checkField(label,name,value,hint=''){return `<label class="check-field"><input type="checkbox" name="${name}" ${value?'checked':''}><span>${label}${hint?`<span class="subline">${hint}</span>`:''}</span></label>`;}
function modal(title,subtitle,body){
  dirty=false;const el=$('#modal');el.innerHTML=`<div class="modal-header"><div><h2>${esc(title)}</h2><p>${esc(subtitle)}</p></div><button class="close" data-action="close" aria-label="关闭">×</button></div><div class="modal-body">${body}</div>`;
  if(!el.open)el.showModal();
}
function closeModal(force=false){if(!force&&dirty&&!confirm('尚有未保存内容，确定关闭？'))return;$('#modal').close();dirty=false;}
function readForm(form){const d=Object.fromEntries(new FormData(form));$$('input[type=checkbox]',form).forEach(x=>d[x.name]=x.checked);$$('input[type=number]',form).forEach(x=>d[x.name]=x.value===''?null:Number(x.value));return d;}
function projectModal(edit=false){
  const p=edit?state.data.project:{currency:'USD',budget:null,goal:'愿望单',format:'长视频',require_audience:true};
  modal(edit?'本次推广要求':'创建游戏项目','填写要推广的游戏、目标玩家和预算，后续按这些要求筛选合作。',`<form id="project-form"><fieldset ${edit&&!canEdit()?'disabled':''}><div class="form-grid">${field('项目名称','name',p.name,'text',true)}${field('游戏名称','game',p.game,'text',true)}${field('游戏品类','genre',p.genre)}${field('目标市场','market',p.market,'text',true,'建议统一写法，例如“德国”。受众市场按此核对。')}${field('内容语言','language',p.language,'text',false,'可留空，表示本轮不设语言门槛。')}${selectField('主要业务目标','goal',p.goal,['愿望单','安装激活','有效曝光','留存玩家'])}${selectField('合作形式','format',p.format,['长视频','短视频','直播','图文'])}${field('上线日期','launch_date',p.launch_date,'date')}${selectField('预算币种','currency',p.currency,['USD','EUR','CNY','GBP','JPY'])}${field('最高总预算','budget',p.budget,'number',true,'覆盖达人费、授权、税费及奖金上限等已承诺支出。')}${field('目标受众最低占比 %','min_audience_pct',p.min_audience_pct,'number',false,'可留空；只使用你的项目门槛，不内置平台标准。')}${field('其他项目要求','notes',p.notes,'textarea',false,'',true)}</div><div class="spacer">${checkField('推荐前必须人工核验目标受众证据','require_audience',p.require_audience)}${checkField('本轮合作必须包含付费广告使用权','require_paid_rights',p.require_paid_rights)}</div></fieldset>${edit?'<div class="info warning">修改推广要求后，已批准的合作需要重新确认；之前的审批记录会保留。</div>':''}<div class="form-footer"><button type="button" data-action="close">取消</button>${canEdit()?'<button type="submit" class="primary">保存项目</button>':''}</div></form>`);
  $('#project-form').addEventListener('submit',e=>{e.preventDefault();run(async()=>{const d={...readForm(e.target),is_demo:p.is_demo||false,...(edit?{version:p.version}:{})};const result=await api(edit?'/api/projects/'+p.id:'/api/projects',{method:edit?'PATCH':'POST',body:d});closeModal(true);state.pid=edit?p.id:result.id;state.view='pool';await boot();toast(edit?'条件已保存，原批准记录已转待复核。':'项目已建立。');});});
}
function candidateModal(id,tab='evidence'){
  const d=id?state.data.candidates.find(x=>x.id===id):{platform:'YouTube',format:state.data.project.format,language:state.data.project.language,audience_market:state.data.project.market,fit:'unknown',availability:'unknown',exclusivity:'unknown',owner_id:state.user.id,quote:{currency:state.data.project.currency,paid_rights:'unknown'}};
  if(!d)return;
  state.modalTab=tab;const q=d.quote,p=state.data.project,a=d.assessment;
  const assessment=id?`<div class="info ${a.ready?'':'warning'}"><strong>${a.ready?'当前证据与条款已满足项目检查':'以下条件仍需补齐或调整'}</strong>${a.blockers.length?`<ul class="audit-list">${a.blockers.map(x=>`<li>${icon('alert')}${esc(x)}</li>`).join('')}</ul>`:`<p>这是一项准备度检查。审批人仍需根据主目标和备选方案作出判断。</p>`}${a.warnings.length?`<div class="subline">提醒：${esc(a.warnings.join('；'))}</div>`:''}</div>`:'';
  modal(id?d.name:'新增候选达人',id?`${d.platform} · 第 ${d.version} 稿 · ${states[d.state][0]}`:'先记录已有事实。数据不全也可保存，系统会保留缺口。',`
    <div class="tabs"><button class="${tab==='evidence'?'active':''}" data-action="tab" data-tab="evidence">01 达人是否合适</button><button class="${tab==='quote'?'active':''}" data-action="tab" data-tab="quote">02 报价与合作条件</button><button class="${tab==='collaboration'?'active':''}" data-action="tab" data-tab="collaboration">03 跟进与审批</button></div>
    <form id="candidate-form"><fieldset ${!canEdit()?'disabled':''}>
    <div class="tab-panel ${tab==='evidence'?'active':''}" data-panel="evidence"><div class="form-grid">${d.source_ref?`<div class="info full">来自 ${esc(d.source_ref.provider_name)} · ${when(d.source_ref.fetched_at)}，搜索资料已留档。添加到备选后，还需确认内容是否合适、粉丝是否符合目标。<button type="button" class="ghost small" data-action="download-search" data-id="${d.source_ref.run_id}">下载搜索留档</button></div>`:''}${field('达人名称','name',d.name,'text',true)}${selectField('平台','platform',d.platform,['YouTube','TikTok','Twitch','Instagram','Bilibili','其他'])}${field('达人账号','account_id',d.account_id,'text',false,d.source_ref?'还不知道真实账号时可留空，这位达人不会因此被重复添加。':'达人账号或主页链接至少填一项，避免同名达人混淆。')}${field('主页链接','profile_url',d.profile_url,'url')}${field('内容语言','language',d.language)}${field('内容品类','content_genre',d.content_genre)}${selectField('本次合作形式','format',d.format,['长视频','短视频','直播','图文'])}${field('粉丝数','followers',d.followers,'number',false,'作为规模背景，不用于生成质量评分。')}</div>
    <div class="form-section-title">目标玩家与受众证据</div><div class="form-grid">${field('受众市场','audience_market',d.audience_market)}${field('该市场受众占比 %','audience_pct',d.audience_pct,'number')}${field('粉丝数据来自哪里、覆盖哪段时间','audience_source',d.audience_source,'textarea',false,'例如达人后台报告日期、覆盖范围；估计值不能冒充核实结果。',true)}</div>${checkField('我已核验上述受众数据及来源','audience_verified',d.audience_verified)}
    <div class="form-section-title">内容匹配判断</div><div class="form-grid">${selectField('人工匹配判断','fit',d.fit,[['unknown','尚未确认'],['match','符合本轮玩家与内容目标'],['mismatch','不符合本轮目标']])}${field('证据核验日期','evidence_date',d.evidence_date,'date')}${field('代表内容链接','source_url',d.source_url,'url',false,'推荐前需要可回查的内容证据。',true)}${field('为什么适合这款游戏与目标玩家','fit_note',d.fit_note,'textarea',false,'竞品经验可作为品类证据；不要只写粉丝多或互动高。',true)}${field('参考了哪些作品及其表现','evidence_note',d.evidence_note,'textarea',false,'例如：最近 6 条长视频发布后 7 天的播放量。注明是否投过广告，短视频与长视频分开比较。',true)}</div></div>
    <div class="tab-panel ${tab==='quote'?'active':''}" data-panel="quote"><div class="modal-wide-note">空白表示未知，填 0 表示已确认不收费。按完整费用和奖金上限计算最高合作费用。</div><div class="form-grid">${selectField('报价币种','q_currency',q.currency,['USD','EUR','CNY','GBP','JPY'])}${field('报价日期','q_quoted_at',q.quoted_at,'date')}${[['达人费','fee'],['素材授权费','usage'],['排他费','exclusivity_fee'],['制作 / 本地化','production'],['税费 / 代理 / 支付','tax'],['绩效奖金上限','bonus_cap']].map(([l,k])=>field(l,'q_'+k,q[k],'number')).join('')}${field('报价有效至','q_valid_until',q.valid_until,'date')}${selectField('付费广告使用权','q_paid_rights',q.paid_rights,[['unknown','尚未确认'],['included','已包含'],['not_included','明确不包含']])}${field('完整交付范围','q_deliverables',q.deliverables,'textarea',false,'数量、形式、时长、发布位置、修改次数和保留期限。',true)}${field('素材使用权范围','q_rights',q.rights,'textarea',false,'用途、地域、期限、剪辑权限；自然转载与付费投放分别约定。',true)}${field('付款、取消及补偿条件','q_payment',q.payment,'textarea',false,'付款触发点、取消处理、保量或补发约定；未约定不要推断。',true)}</div><div class="spacer">${checkField('所有费用项目已核实，且覆盖本次完整范围','q_cost_complete',q.cost_complete)}${checkField('已将报价与交付、权利和付款条件逐项对齐','q_confirmed',q.confirmed)}</div>
    <div class="form-section-title">预估投放效果（选填）</div><div class="form-grid">${field('预期播放次数','q_expected_views',q.expected_views,'number')}${field('预估带来的'+p.goal,'q_expected_actions',q.expected_actions,'number')}${field('预估依据和统计时间','q_forecast_basis',q.forecast_basis,'textarea',false,'说明参考了哪些同类作品，以及统计的是发布后几天的表现。没有依据时不计算成本效率；预估不代表效果承诺。',true)}</div></div>
    <div class="tab-panel ${tab==='collaboration'?'active':''}" data-panel="collaboration"><div class="form-grid">${selectField('档期状态','availability',d.availability,[['unknown','未确认'],['confirmed','已确认可交付'],['unavailable','不可用']])}${selectField('排他条款核验','exclusivity',d.exclusivity,[['unknown','未核实'],['clear','已核实无冲突'],['conflict','存在有效排他冲突']])}${field('档期、游戏访问与排他核验记录','terms_note',d.terms_note,'textarea',false,'记录时间、依据、具体约定，不能仅凭竞品视频推断排他。',true)}${selectField('负责人','owner_id',d.owner_id,[['','未分配'],...state.users.map(u=>[u.id,u.name])])}${field('下一步截止日期','due_date',d.due_date,'date')}${field('下一步执行动作','next_action',d.next_action,'textarea',false,'',true)}</div></div>
    </fieldset>${canEdit()?`<div class="form-footer"><button type="button" data-action="close">取消</button><button type="submit" class="primary">${icon('check')}保存${id?'变更':'候选'}</button></div>`:''}</form>
    <div class="tab-panel ${tab==='collaboration'?'active':''}" data-panel="collaboration">${assessment}${id?`
    <div class="review-box"><h3>内部合作决策</h3><p class="modal-wide-note">${d.state==='approved'?`已批准第 ${d.approved_version} 次修订的合作方案。修改证据、报价或项目条件后，需要重新复核。`:'提交将把该达人加入预算组合。内部批准不代表对方已接受或已签约。'}</p>
    ${canEdit()&&d.state!=='approved'?`<button type="button" class="primary small" data-action="submit" data-id="${d.id}">提交合作审批 ${icon('arrow')}</button>`:''}
    ${canReview()&&['pending','approved'].includes(d.state)?`<label class="field"><span>决策理由 *</span><textarea id="review-note" placeholder="说明为什么批准、需要补充什么，或为什么暂不合作。"></textarea></label><div class="review-actions">${d.state==='pending'?`<button type="button" class="primary" data-action="review" data-id="${d.id}" data-verdict="approve" ${a.blockers.length?'disabled':''}>${icon('check')}批准这份合作方案</button>`:''}<button type="button" data-action="review" data-id="${d.id}" data-verdict="changes">退回补充 / 撤销批准</button><button type="button" class="danger" data-action="review" data-id="${d.id}" data-verdict="reject">暂不合作</button></div>`:''}</div>
    <div class="review-box"><h3>团队讨论与交接</h3><textarea id="comment-note" placeholder="留下具体问题、处理进度或交接说明。"></textarea><div class="review-actions"><button type="button" data-action="comment" data-id="${d.id}">添加记录</button></div><div class="timeline">${state.data.events.filter(e=>e.candidate_id===d.id).slice(0,8).map(eventHTML).join('')}</div></div>`:'<div class="info">保存候选后即可提交决策、添加团队讨论与查看历史。</div>'}</div>`);
  $('#candidate-form').addEventListener('invalid',e=>{const panel=e.target.closest('[data-panel]');if(panel){state.modalTab=panel.dataset.panel;$$('.tabs button',$('#modal')).forEach(x=>x.classList.toggle('active',x.dataset.tab===state.modalTab));$$('[data-panel]',$('#modal')).forEach(x=>x.classList.toggle('active',x.dataset.panel===state.modalTab));}},true);
  $('#candidate-form').addEventListener('submit',e=>{e.preventDefault();run(async()=>{
    const raw=readForm(e.target), quote={};for(const k of Object.keys(raw))if(k.startsWith('q_')){quote[k.slice(2)]=raw[k];delete raw[k];}
    const result=await api(id?'/api/candidates/'+id:'/api/projects/'+state.pid+'/candidates',{method:id?'PATCH':'POST',body:{...raw,quote,...(id?{version:d.version}:{})}});
    dirty=false;await refresh();candidateModal(id||result.id,state.modalTab);toast(id?'变更已保存；已有审批需重新确认。':'候选已加入项目。');
  });});
}
function importModal(){
  previewCsv='';modal('导入达人名单','先检查名单，再确认加入项目。已存在的达人会跳过，不覆盖原资料。',`
  <div class="modal-wide-note">先下载模板，用 Excel 填写，再另存为“CSV UTF-8（逗号分隔）”文件上传，最多 500 位达人。暂不支持直接上传 Excel 工作簿。达人是否合适、费用和授权仍需逐项确认。</div><details><summary>模板填写说明</summary><p>保留模板表头：name 填达人名称，platform 填平台，account_id 填达人账号，profile_url 填主页链接。账号和主页至少填写一项，其他不确定的信息可留空。</p></details><div class="actions"><button data-action="template">${icon('download')}下载空白模板</button></div>
  <label class="file-drop spacer">${icon('upload')}选择你的候选名单<input id="csv-file" type="file" accept=".csv,text/csv"></label><div id="import-preview"></div>`);
  $('#csv-file').addEventListener('change',e=>run(async()=>{
    const file=e.target.files[0];if(!file)return;if(file.size>1500000)throw new Error('文件超过 1.5 MB。');
    previewCsv=await file.text();const preview=await api('/api/projects/'+state.pid+'/import-preview',{method:'POST',body:{csv:previewCsv}});
    $('#import-preview').innerHTML=`<div class="import-summary"><span>${preview.count} 条可导入</span><span>${preview.duplicates.length} 条重复，将跳过</span><span>${preview.errors.length} 条错误</span></div>${preview.unmapped_columns.length?`<div class="info warning">以下列不会导入：${esc(preview.unmapped_columns.join('、'))}</div>`:''}${preview.errors.length?`<div class="info error">${preview.errors.map(x=>`第 ${x.row} 行 ${esc(x.name)}：${esc(x.reason)}`).join('<br>')}<br>请修正后重新选择文件，当前名单尚未加入项目。</div>`:''}${preview.duplicates.length?`<div class="info">${preview.duplicates.map(x=>`第 ${x.row} 行 ${esc(x.name)}：${esc(x.reason)}`).join('<br>')}</div>`:''}<div class="table-scroll"><table><thead><tr><th>达人</th><th>平台</th><th>达人账号 / 主页</th><th>已知达人费</th></tr></thead><tbody>${preview.records.slice(0,8).map(d=>`<tr><td>${esc(d.name)}</td><td>${d.platform}</td><td>${esc(d.account_id||d.profile_url)}</td><td>${money(d.quote.fee,d.quote.currency)}</td></tr>`).join('')}</tbody></table></div>${preview.count>8?'<p class="subline">预览前 8 条。</p>':''}<div class="form-footer"><button data-action="close">取消</button><button class="primary" data-action="commit-import" ${preview.errors.length||!preview.count?'disabled':''}>确认导入 ${preview.count} 条</button></div>`;
  }));
}
function memberModal(){modal('添加团队成员','成员共享本工作台项目。只有管理员可以创建账号。',`<form id="member-form"><div class="form-grid">${field('姓名','name','','text',true)}${field('登录名','username','','text',true)}${field('初始密码','password','','password',true,'至少 10 个字符，成员可以自行修改。')}${selectField('角色','role','editor',[['editor','项目执行'],['reviewer','审批人'],['admin','管理员']])}</div><div class="form-footer"><button type="button" data-action="close">取消</button><button type="submit" class="primary">创建成员</button></div></form>`);$('#member-form').addEventListener('submit',e=>{e.preventDefault();run(async()=>{await api('/api/users',{method:'POST',body:readForm(e.target)});closeModal(true);await boot();toast('成员账号已创建。');});});}
function passwordModal(){modal('修改我的密码','修改后将退出其他会话，当前窗口保持登录。',`<form id="password-form"><div class="form-grid">${field('原密码','old_password','','password',true)}${field('新密码','new_password','','password',true,'至少 10 个字符。')}</div><div class="form-footer"><button type="button" data-action="close">取消</button><button class="primary" type="submit">修改密码</button></div></form>`);$('#password-form').addEventListener('submit',e=>{e.preventDefault();run(async()=>{await api('/api/password',{method:'POST',body:readForm(e.target)});closeModal(true);await boot();toast('密码已修改。');});});}
function ensureSaved(){if(dirty)throw new Error('请先保存表单变更，再执行提交、审批或添加记录。');}
document.addEventListener('click',e=>{
  const btn=e.target.closest('[data-action]');if(!btn)return;
  const action=btn.dataset.action,id=btn.dataset.id;
  run(async()=>{
    if(action==='nav'){state.view=btn.dataset.view;render();}
    if(action==='filter'){state.filter=btn.dataset.filter;render();}
    if(action==='language'){if(dirty&&!confirm(window.KOL_LANG==='en'?'Switch language and discard unsaved edits?':'切换语言会放弃尚未保存的内容，是否继续？'))return;dirty=false;const url=new URL(location.href);url.searchParams.set('lang',window.KOL_LANG==='en'?'zh':'en');location.href=url.href;return;}
    if(action==='new-project')projectModal();
    if(action==='edit-project')projectModal(true);
    if(action==='new-candidate')candidateModal();
    if(action==='candidate')candidateModal(id,btn.dataset.tab||'evidence');
    if(action==='close')closeModal();
    if(action==='tab'){state.modalTab=btn.dataset.tab;$$('.tabs button',$('#modal')).forEach(x=>x.classList.toggle('active',x.dataset.tab===state.modalTab));$$('[data-panel]',$('#modal')).forEach(x=>x.classList.toggle('active',x.dataset.panel===state.modalTab));}
    if(action==='demo'){btn.disabled=true;const r=await api('/api/demo',{method:'POST',body:{}});state.pid=r.id;state.view='pool';await boot();toast('示例项目已建立，所有内容均为合成数据。');}
    if(action==='logout'){await api('/api/logout',{method:'POST',body:{}});state.user=null;await boot();}
    if(action==='new-user')memberModal();
    if(action==='password')passwordModal();
    if(action==='import')importModal();
    if(action==='template')window.location='/api/csv-template';
    if(action==='export')window.location='/api/projects/'+state.pid+'/export?lang='+(window.KOL_LANG||'zh');
    if(action==='report')window.location='/api/projects/'+state.pid+'/report?lang='+(window.KOL_LANG||'zh');
    if(action==='commit-import'){btn.disabled=true;try{const r=await api('/api/projects/'+state.pid+'/import',{method:'POST',body:{csv:previewCsv}});closeModal(true);await refresh();toast(`已导入 ${r.count} 条，跳过 ${r.skipped} 条重复记录。`);}catch(err){btn.disabled=false;throw err;}}
    if(['submit','review','comment'].includes(action)){
      ensureSaved();const d=state.data.candidates.find(x=>x.id===id);const body={version:d.version};
      if(action==='review'){body.verdict=btn.dataset.verdict;body.note=$('#review-note').value;}
      if(action==='comment')body.note=$('#comment-note').value;
      btn.disabled=true;try{await api('/api/candidates/'+id+'/'+action,{method:'POST',body});await refresh();candidateModal(id,'collaboration');toast(action==='submit'?'已提交合作审批。':action==='review'?'审批已记录，当时的合作资料和报价已留档。':'讨论已记录。');}catch(err){btn.disabled=false;throw err;}
    }
  });
});
document.addEventListener('change',e=>{
  if(e.target.id==='project-switch'&&e.target.value)run(()=>loadProject(e.target.value));
  if(e.target.matches('[data-select]'))run(async()=>{
    const d=state.data.candidates.find(x=>x.id===e.target.dataset.select), selected=e.target.checked;e.target.disabled=true;
    try{await api('/api/candidates/'+d.id+'/select',{method:'POST',body:{version:d.version,selected}});await refresh();}
    catch(err){await refresh();throw err;}
  });
});
document.addEventListener('input',e=>{
  if(e.target.id==='candidate-search'){state.query=e.target.value;$('#candidate-table').innerHTML=candidateTable();}
  if(e.target.closest('#candidate-form,#project-form,#member-form,#password-form'))dirty=true;
});
$('#modal').addEventListener('cancel',e=>{if(dirty){e.preventDefault();closeModal();}});
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
boot().catch(err=>{$('#app').innerHTML=`<div class="empty"><h2>暂时无法打开工作台</h2><p>${esc(err.message)}</p><button id="retry-boot">重新连接</button></div>`;$('#retry-boot').onclick=()=>location.reload();});
