'use strict';(()=>{
const $=id=>document.getElementById(id);
const ORIGIN='https://mcp.shardsinc.co.uk',ENDPOINT=ORIGIN+'/mcp';
const clients=[
['claude-code','Claude Code','bearer','https://code.claude.com/docs/en/mcp'],
['cursor','Cursor','bearer','https://cursor.com/docs/mcp'],
['hermes-agent','Hermes Agent','generic','https://github.com/NousResearch/hermes-agent'],
['chatgpt','ChatGPT','oauth','https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt'],
['claude-desktop','Claude Desktop','oauth','https://claude.ai/settings/connectors'],
['codex','Codex','generic','https://developers.openai.com/codex/mcp'],
['vscode','VS Code','generic','https://code.visualstudio.com/docs/copilot/customization/mcp-servers'],
['cline','Cline','generic','https://docs.cline.bot/mcp-servers/mcp'],
['roo-code','Roo Code','generic','https://docs.roocode.com/features/mcp/using-mcp-in-roo'],
['continue','Continue','generic','https://docs.continue.dev/customize/deep-dives/mcp'],
['amp','Amp','generic','https://ampcode.com'],
['grok','Grok','oauth','https://x.ai'],
['openclaw','OpenClaw','generic','https://github.com/openclaw/openclaw'],
['langgraph','LangGraph','generic','https://langchain-ai.github.io/langgraph/'],
['crewai','CrewAI','generic','https://docs.crewai.com'],
['gemini-cli','Gemini CLI','generic','https://github.com/google-gemini/gemini-cli'],
['openai-agents','OpenAI Agents SDK','generic','https://openai.github.io/openai-agents-python/mcp/'],
['zed','Zed','generic','https://zed.dev/docs/ai/mcp'],
['windsurf','Windsurf','generic','https://docs.windsurf.com/windsurf/cascade/mcp'],
['custom-mcp','Any MCP HTTP client','bearer','https://modelcontextprotocol.io/docs']
].map(x=>({id:x[0],name:x[1],mode:x[2],docs:x[3]}));
const state={selected:'custom-mcp',agents:[],token:null,issuedId:null,loading:false};
const node=(tag,klass,value)=>{const n=document.createElement(tag);if(klass)n.className=klass;if(value!==undefined)n.textContent=value;return n};
const message=(s,bad=false)=>{const n=$('announcement');n.textContent=String(s||'');n.classList.toggle('bad',bad)};
const selected=()=>clients.find(x=>x.id===state.selected);
const btn=(label,fn,bad=false)=>{const b=node('button',bad?'btn danger':'btn secondary',label);b.type='button';b.addEventListener('click',fn);return b};
async function request(path,method='GET',body){
 const headers=body===undefined?{}:{'content-type':'application/json'};
 if(method!=='GET')headers.origin=ORIGIN;
 const r=await fetch(path,{method,credentials:'same-origin',redirect:'error',cache:'no-store',signal:AbortSignal.timeout(16000),headers,body:body===undefined?undefined:JSON.stringify(body)});
 let data;try{data=await r.json()}catch(e){throw Error('Invalid response. Check your Cloudflare Access login.')}
 if(!r.ok)throw Error(data.error||'HTTP '+r.status);
 return data;
}
async function run(label,fn){if(state.loading)return;state.loading=true;message(label+'…');try{await fn();message(label+' completed')}catch(e){message(String(e.message||'Operation failed'),true)}finally{state.loading=false}}
function choices(){
 const q=$('agentSearch').value.trim().toLowerCase(),target=$('agentChoices');target.replaceChildren();
 for(const c of clients.filter(x=>x.name.toLowerCase().includes(q)||x.id.includes(q))){
  const b=node('button','agent-choice');b.type='button';b.setAttribute('aria-pressed',String(c.id===state.selected));
  b.append(node('span','glyph',c.name.slice(0,1)));
  const label=node('span');label.append(node('strong',null,c.name),node('small',null,c.mode==='bearer'?'Direct bearer':c.mode==='oauth'?'OAuth needed':'Check adapter'));
  b.append(label);b.addEventListener('click',()=>choose(c.id));target.append(b);
 }
 if(!target.children.length)target.append(node('p','hint','No matching agent client.'));
}
function choose(id){
 state.selected=id;
 const c=selected();
 $('selectedHelp').textContent=c.name+'. Connect a real, separately running agent to the Shards MCP HTTPS endpoint.';
 $('compatibility').textContent=c.mode==='oauth'?
   'Private Shards tools are not yet linkable through this client: its OAuth flow is not implemented. Public read-only MCP tools remain accessible without a private token.':
   c.mode==='bearer'?
   'Supported transport: remote MCP Streamable HTTP with an agent-scoped Authorization: Bearer header. The external agent must be running independently.':
   'Adapter required: use a running MCP client that supports HTTP transport and custom bearer headers. Do not assume this platform is connected merely because it appears in the catalogue.';
 $('enrolButton').disabled=c.mode==='oauth';
 $('enrolButton').textContent=c.mode==='oauth'?'PRIVATE OAUTH NOT AVAILABLE':'ENROL & CREATE TOKEN';
 $('clientDocs').href=c.docs;
 $('agentName').placeholder=c.id==='custom-mcp'?'e.g. my-production-agent':c.id+'-production';
 choices();if(state.token)renderConfig();
}
function scopes(role){
 if(role==='inbox')return ['agent:identity','message:read'];
 if(role==='collaborate')return ['agent:identity','agent:list','message:read','message:send'];
 if(role==='coordinate')return ['agent:identity','agent:list','message:read','message:send','task:create','task:read','task:claim','task:complete'];
 throw Error('Invalid permission profile');
}
function renderConfig(){
 if(!state.token)return;
 $('tokenDisplay').textContent=state.token;
 const c=selected();
 if(c.id==='claude-code'){
  $('configDisplay').textContent='First, securely set SHARDS_MCP_TOKEN in your shell, then run:\n\nclaude mcp add --transport http shards-mcp '+ENDPOINT+' --header "Authorization: Bearer $SHARDS_MCP_TOKEN"\n\nVerify using: claude mcp list';
 }else{
  const placeholder=c.id==='cursor'?'Bearer '+'$'+'{env:SHARDS_MCP_TOKEN}':'Bearer <INSERT_AGENT_TOKEN_IN_CLIENT_SECRET_MANAGER>';
  const conf={mcpServers:{'shards-mcp':{url:ENDPOINT,headers:{Authorization:placeholder}}}};
  $('configDisplay').textContent=JSON.stringify(conf,null,2)+(c.id==='cursor'?'\n\nSet SHARDS_MCP_TOKEN as a secure environment variable.':'\n\nThis is a generic template; confirm that your client supports remote MCP and custom headers.');
 }
}
function hideToken(){
 state.token=null;$('tokenDisplay').textContent='';$('configDisplay').textContent='';
 $('credentialPanel').hidden=true;
}
async function copy(s){try{await navigator.clipboard.writeText(s);message('Copied to clipboard.')}catch(e){message('Clipboard unavailable: select and copy manually.',true)}}
async function listAgents(){
 const result=await request('/manage/api/connections');state.agents=result.agents||[];
 $('authStatus').textContent='Signed operator · '+state.agents.length+' agents';
 const el=$('connectedList');el.replaceChildren();
 if(!state.agents.length)el.append(node('p','hint','No agents enrolled yet.'));
 for(const a of state.agents){
  const card=node('article','connected'),row=node('div','row');
  row.append(node('strong',null,a.name),node('span',a.last_authenticated_at?'tag verified':'tag',a.last_authenticated_at?'MCP AUTH VERIFIED':'AWAITING AUTH'));
  card.append(row,node('p',null,a.client+' · '+a.id));
  card.append(node('p',null,'Last authenticated MCP request: '+(a.last_authenticated_at?new Date(a.last_authenticated_at).toLocaleString():'Not observed')));
  if(!a.disabled_at)card.append(btn('REVOKE AGENT',()=>{if(!confirm('Revoke '+a.name+' and all its tokens?'))return;run('Revoke credential',async()=>{await request('/manage/api/connections/revoke','POST',{agent_id:a.id});await listAgents()})},true));
  el.append(card);
 }
 if(state.issuedId){
  const a=state.agents.find(x=>x.id===state.issuedId);
  $('verification').textContent=a?.last_authenticated_at?
   'A valid agent bearer key reached MCP at '+new Date(a.last_authenticated_at).toLocaleString()+'. This confirms credential use, not continuous runtime presence.':
   'Awaiting the newly enrolled agent’s first authenticated MCP request.';
 }
}
$('agentSearch').addEventListener('input',choices);
$('enrolForm').addEventListener('submit',ev=>{ev.preventDefault();run('Enrol agent',async()=>{
 const c=selected();if(c.mode==='oauth')throw Error('Private OAuth not supported for this client.');
 const name=$('agentName').value.trim();if(!/^[A-Za-z0-9][A-Za-z0-9_-]{2,49}$/.test(name))throw Error('Use a unique 3–50 character agent name.');
 const role=$('role').value;
 hideToken();
 const created=await request('/manage/api/agents','POST',{name,client:c.id,scopes:scopes(role)});
 if(!created?.id||!created?.token)throw Error('No credential was issued.');
 state.token=created.token;state.issuedId=created.id;
 $('credentialPanel').hidden=false;renderConfig();
 $('verification').textContent='Credential expires '+new Date(created.expires_at).toLocaleString()+'. Waiting for an actual authenticated client request.';
 await listAgents();$('credentialPanel').scrollIntoView({behavior:'smooth',block:'nearest'});
})});
$('copyToken').addEventListener('click',()=>{if(state.token)copy(state.token)});
$('discardToken').addEventListener('click',()=>{hideToken();message('Token hidden. Only its digest is stored server-side.')});
$('copyEndpoint').addEventListener('click',()=>copy(ENDPOINT));
$('copyConfig').addEventListener('click',()=>copy($('configDisplay').textContent));
$('refreshAfterConnect').addEventListener('click',()=>run('Refresh connection receipts',listAgents));
$('refreshAgents').addEventListener('click',()=>run('Refresh enrolled agents',listAgents));
window.addEventListener('pagehide',hideToken,{once:true});
choose('custom-mcp');run('Load enrolled agents',listAgents);
})();