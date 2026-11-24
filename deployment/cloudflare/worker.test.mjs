import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { webcrypto } from "node:crypto";

const src = fs.readFileSync(new URL("./worker.js", import.meta.url), "utf8");
const sandbox = {
  Request, Response, Headers, URL, TextEncoder, TextDecoder, crypto: webcrypto, AbortSignal, atob,
  fetch: async () => { throw new Error("test must never call the network"); },
};
vm.runInNewContext(src.replace("export default {", "globalThis.__edge = {"), sandbox, { filename: "worker.js" });
const worker = sandbox.__edge;
const endpoint = "https://mcp.shardsinc.co.uk/mcp";
function post(method, params = {}, headers = {}) {
  return new Request(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
  });
}

test("initialize negotiates requested legacy version, not HTTP header default", async () => {
  for (const version of ["2025-06-18", "2025-11-25"]) {
    const response = await worker.fetch(post("initialize", {
      protocolVersion: version, capabilities: {}, clientInfo: { name: "offline-test", version: "1" },
    }), {});
    const body = await response.json();
    assert.equal(response.status, 200);
    assert.equal(body.result.protocolVersion, version);
    assert.equal(response.headers.get("mcp-protocol-version"), version);
  }
  const response = await worker.fetch(post("initialize", { protocolVersion: "unsupported" }), {});
  assert.equal((await response.json()).result.protocolVersion, "2025-11-25");
});

test("malformed DNS calls are rejected without consuming any budget or contacting DoH", async () => {
  let writes = 0;
  const env = { EDGE_DB: { prepare() { writes++; throw Error("DB should not be touched"); } } };
  for (const value of [{ domain: "bad" }, { domain: "example.com", type: "A;DROP" }, {}]) {
    const response = await worker.fetch(post("tools/call", {
      name: "shards_dns_lookup", arguments: value,
    }), env);
    const body = await response.json();
    assert.equal(response.status, 200);
    assert.equal(body.result.isError, true);
    assert.match(body.result.content[0].text, /Invalid DNS arguments/);
  }
  assert.equal(writes, 0);
});

test("public status quotas use a hashed per-caller key plus global counter", async () => {
  const budgets = [];
  const env = {
    EDGE_DB: {
      prepare(sql) {
        assert.match(sql, /route_budgets/);
        return { bind(...values) {
          budgets.push(values);
          return { async run() { return { meta: { changes: 1 } }; } };
        } };
      },
    },
  };
  const response = await worker.fetch(post("tools/call", {
    name: "shards_gateway_status", arguments: {},
  }, { "cf-connecting-ip": "198.51.100.80" }), env);
  const body = await response.json();
  assert.equal(response.status, 200);
  assert.equal(body.result.isError, false);
  assert.equal(budgets.length, 2);
  assert.match(budgets[0][1], /^public:shards_gateway_status:caller:[a-f0-9]{24}$/);
  assert.equal(budgets[1][1], "shards_gateway_status");
  assert.equal(JSON.stringify(budgets).includes("198.51.100.80"), false);
});

test("operator issued-token rendering uses newline escapes, not literal backslashes", () => {
  const match = src.match(/^const CLIENT=("(?:\\.|[^"\\])*");/m);
  assert.ok(match, "embedded client source must be present");
  const client = JSON.parse(match[1]);
  const at = client.indexOf("SCOPED TOKEN — COPY NOW.");
  assert.ok(at >= 0);
  const fragment = client.slice(at, at + 145);
  assert.ok(fragment.includes("\\n\\n"), "embedded JS must contain proper newline escape sequences");
  assert.equal(fragment.includes("\\\\n"), false, "embedded JS must not contain literal \\n");
});


test("Live Lab is a real same-origin route with a strict script policy", async () => {
  const response = await worker.fetch(new Request("https://mcp.shardsinc.co.uk/lab"), {});
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type"), /text\/html/);
  const csp = response.headers.get("content-security-policy");
  const directives = csp.split(";").map(p => p.trim().split(/\s+/)).filter(a => a[0]);
  const policies = Object.fromEntries(directives.map(([key,...values]) => [key, values]));
  assert.deepEqual(policies["script-src"], ["'self'"], "No inline, remote, eval or data scripts");
  assert.deepEqual(policies["connect-src"], ["'self'"]);
  assert.deepEqual(policies["form-action"], ["'none'"]);
  assert.equal(directives.filter(([key]) => key === "script-src").length, 1);
  const html = await response.text();
  assert.match(html, /RUN PROTOCOL CHECK/);
  assert.match(html, /QUERY LIVE CATALOGUE/);
  assert.match(html, /id="dnsForm"/);
  assert.match(html, /src="\/lab\.js"/);
  assert.doesNotMatch(html, /<script(?![^>]*src=)/);
});

test("Live Lab client is executable JS restricted to the public MCP operations", async () => {
  const response = await worker.fetch(new Request("https://mcp.shardsinc.co.uk/lab.js"), {});
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type"), /text\/javascript/);
  const js = await response.text();
  assert.doesNotThrow(() => new vm.Script(js));
  assert.match(js, /shards_gateway_status/);
  assert.match(js, /shards_systems_catalog/);
  assert.match(js, /shards_dns_lookup/);
  assert.match(js, /credentials: 'omit'/);
  assert.match(js, /response\.ok/);
  assert.match(js, /\.isError/);
  assert.doesNotMatch(js, /\/manage\/api\//);
  assert.doesNotMatch(js, /localStorage|sessionStorage|Bearer\s/);
  assert.match(js, /\$\('copyEvidence'\)\.textContent = 'COPY JSON'/);
  assert.match(js, /setTimeout\(\(\) => \{ \$\('copyEvidence'\)\.textContent = 'COPY JSON'; \}, 1600\)/);
});

test("Live Lab appears on the landing page, but never exposes cross-host routes", async () => {
  const main = await worker.fetch(new Request("https://mcp.shardsinc.co.uk/"), {});
  assert.equal(main.status, 200);
  assert.match(await main.text(), /href="\/lab">LIVE LAB/);
  const denied = await worker.fetch(new Request("https://example.com/lab"), {});
  assert.equal(denied.status, 404);
  const missing = await worker.fetch(new Request("https://mcp.shardsinc.co.uk/lab-other"), {});
  assert.equal(missing.status, 404);
});

test("Lab diagnostics do not require credentials; protected MCP tools still fail closed", async () => {
  const discovery = await worker.fetch(post("tools/list"), {});
  const listed = (await discovery.json()).result.tools.map(x => x.name);
  assert.deepEqual(Array.from(listed), [
    "shards_gateway_status", "shards_systems_catalog", "shards_dns_lookup",
    "shards_skill_search", "shards_skill_read", "shards_repo_document", "shards_open_prs"
  ]);
  const forbidden = await worker.fetch(post("tools/call", {name:"shards_task_create", arguments:{}}), {});
  const body = await forbidden.json();
  assert.equal(body.result.isError, true);
  assert.match(body.result.content[0].text, /AUTH_REQUIRED/);
});



function liveLabBrowser({ onFetch, shortTimeout = false } = {}) {
  const match = src.match(/^const LAB_CLIENT=("(?:\\.|[^"\\])*");/m);
  assert.ok(match, "The Live Lab must have a separate browser client");
  let client = JSON.parse(match[1]);
  if (shortTimeout) {
    assert.ok(client.includes("AbortSignal.timeout(10000)"), "The gateway request has an abortable timeout");
    client = client.replace("AbortSignal.timeout(10000)", "AbortSignal.timeout(20)");
  }
  const handlers = new Map();
  const nodes = new Map();
  const requests = [];
  function element(id) {
    if (!nodes.has(id)) nodes.set(id, {
      textContent: "", disabled: false,
      value: id === "domain" ? "example.com" : id === "dnsType" ? "A" : "",
      classList: { add() {} },
      addEventListener(event, cb) { handlers.set(id + ":" + event, cb); },
    });
    return nodes.get(id);
  }
  const document = {
    getElementById: element,
    querySelector(selector) {
      assert.equal(selector, "#dnsForm button");
      return element("dnsRun");
    },
  };
  const handle = async (url, init) => {
    requests.push({url, init});
    if (onFetch) return onFetch(url, init);
    if (url === "/api/status") return {ok:true, status:200, json:async() => ({
      db:"connected", service:"Shards MCP Edge", version:"0.2.0", tools:[{name:"shards_gateway_status"}]
    })};
    assert.equal(url, "/mcp");
    assert.equal(init.credentials, "omit");
    assert.equal(init.redirect, "error");
    assert.ok(init.signal, "MCP browser requests must be abortable");
    const payload = JSON.parse(init.body);
    const {method, params} = payload;
    let result;
    if (method === "initialize") result = {protocolVersion:"2025-11-25",serverInfo:{name:"shards-mcp-edge"}};
    else if (method === "tools/list") result = {tools:[{name:"shards_gateway_status"},{name:"shards_dns_lookup"}]};
    else if (method === "tools/call") {
      assert.ok(["shards_gateway_status","shards_systems_catalog","shards_dns_lookup"].includes(params.name));
      result = {isError:false, structuredContent:
        params.name === "shards_dns_lookup"
          ? {domain:params.arguments.domain, type:params.arguments.type,records:[{value:"93.184.215.14"}]}
          : params.name === "shards_systems_catalog"
            ? {projects:[{name:"Shards-MCP"}]} : {status:"online"}
      };
    }
    else assert.fail("Unexpected MCP method " + method);
    return {ok:true,status:200,json:async()=>({jsonrpc:"2.0",id:payload.id,result})};
  };
  let clipboard = "";
  const sandbox = {
    document, AbortSignal, Date, JSON, Set, performance:{now:() => 100},
    navigator:{clipboard:{writeText:async x => {clipboard=x;}}},
    setTimeout: () => 0, // suppress the cosmetic delayed copy-label reset
    fetch: handle,
  };
  assert.doesNotThrow(() => new vm.Script(client));
  vm.runInNewContext(client, sandbox, {filename:"lab.js"});
  return {
    element, requests, handlers,
    copied:() => clipboard,
    click:async id => {
      assert.ok(handlers.has(id+":click"), id+" click listener missing");
      await handlers.get(id+":click")();
      await new Promise(resolve => setImmediate(resolve));
    },
    submit:async id => {
      assert.ok(handlers.has(id+":submit"), id+" submit listener missing");
      let prevented = false;
      handlers.get(id+":submit")({preventDefault(){prevented=true;}});
      assert.equal(prevented,true);
      await new Promise(resolve => setImmediate(resolve));
    },
  };
}

test("Browser actions execute actual MCP workflows and show the returned evidence", async () => {
  const page = liveLabBrowser();
  await page.click("protocolRun");
  const first = page.requests.filter(x=>x.url==="/mcp").map(x=>JSON.parse(x.init.body));
  assert.deepEqual(first.map(x=>x.method), ["initialize","tools/list","tools/call"]);
  assert.equal(first[2].params.name,"shards_gateway_status");
  assert.match(page.element("outcome").textContent,/^PASS/);
  assert.equal(JSON.parse(page.element("response").textContent).result.status.status, "online");
  assert.equal(page.element("protocolRun").disabled, false);

  await page.click("catalogRun");
  const second = JSON.parse(page.requests.filter(x=>x.url==="/mcp").at(-1).init.body);
  assert.equal(second.params.name,"shards_systems_catalog");
  assert.equal(JSON.parse(page.element("response").textContent).result.projects[0].name,"Shards-MCP");

  page.element("domain").value = "EXAMPLE.COM";
  page.element("dnsType").value = "MX";
  await page.submit("dnsForm");
  const third = JSON.parse(page.requests.filter(x=>x.url==="/mcp").at(-1).init.body);
  assert.equal(third.params.name, "shards_dns_lookup");
  assert.equal(third.params.arguments.domain, "example.com");
  assert.equal(third.params.arguments.type, "MX");
  assert.equal(JSON.parse(page.element("response").textContent).result.records.length,1);
  await page.click("copyEvidence");
  assert.match(page.copied(), /"domain": "example.com"/);
  assert.equal(page.element("copyEvidence").textContent, "COPIED");
  await page.click("catalogRun");
  assert.equal(page.element("copyEvidence").textContent,"COPY JSON", "New evidence cannot be marked copied");
  assert.ok(page.requests.every(x=>["/api/status","/mcp"].includes(x.url)));
});

test("Invalid DNS input fails locally before any MCP call", async () => {
  const page = liveLabBrowser();
  page.element("domain").value = "invalid";
  const before = page.requests.filter(x=>x.url==="/mcp").length;
  await page.submit("dnsForm");
  assert.equal(page.requests.filter(x=>x.url==="/mcp").length,before);
  assert.match(page.element("outcome").textContent,/^FAIL/);
});

test("A stalled MCP call is actually aborted on timeout rather than left pending", async () => {
  let observedSignal = null;
  const page = liveLabBrowser({
    shortTimeout:true,
    onFetch: (url,init) => {
      if (url === "/api/status") return Promise.resolve({ok:true,status:200,json:async()=>({db:"connected",tools:[]})});
      observedSignal = init.signal;
      return new Promise((_resolve,reject)=>{
        init.signal.addEventListener("abort",()=>reject(Object.assign(new Error("MCP request aborted"),{name:"AbortError"})),{once:true});
      });
    },
  });
  // The button handler awaits the fetch and the fetch waits for
  // AbortSignal.timeout(20). Node's AbortSignal timeout is unref'd.
  // Start a referenced watchdog BEFORE awaiting the handler; otherwise
  // Node can exit with cancelledByParent while the click promise is pending.
  let watchdog;
  try{
    await Promise.race([
      page.click("protocolRun"),
      new Promise((_,reject)=>{
        watchdog=setTimeout(()=>reject(Error("MCP abort failed to settle within 1500ms")),1500);
      }),
    ]);
  }finally{
    clearTimeout(watchdog);
  }
  assert.ok(observedSignal, "Expected an in-flight MCP fetch");
  assert.equal(observedSignal.aborted,true, "MCP fetch signal must be aborted by the timeout");
  assert.match(page.element("outcome").textContent,/^FAIL/);
  assert.match(page.element("response").textContent,/MCP request aborted/);
  assert.equal(page.element("protocolRun").disabled,false);
});


test("Sign-in entrypoint exposes only a real Cloudflare Access handoff", async () => {
  const r=await worker.fetch(new Request("https://mcp.shardsinc.co.uk/signin"),{});
  assert.equal(r.status,200);
  const html=await r.text();
  assert.match(html, /Continue with Cloudflare/);
  assert.match(html, /href="\/connect\/profile"/);
  assert.deepEqual(html.match(/Continue with [^<]+<\/a>/g),["Continue with Cloudflare Access</a>"]);
  assert.doesNotMatch(html, /Continue with (Google|GitHub|Discord|Apple|ChatGPT)/);
  const csp=r.headers.get("content-security-policy");
  assert.match(csp, /script-src 'none'/);
  assert.doesNotMatch(html, /<script/);
});

test("Managed OAuth endpoint fails closed without configuration or signed Access JWT", async () => {
  const target="https://mcp.shardsinc.co.uk/connect";
  const unconfigured=await worker.fetch(new Request(target),{});
  assert.equal(unconfigured.status,503);
  const configured={ACCESS_TEAM:"test",CONNECT_ACCESS_AUD:"access-audience",ACCESS_AUD:"operator-audience"};
  const unauthenticated=await worker.fetch(new Request(target),configured);
  assert.equal(unauthenticated.status,401);
  assert.match(unauthenticated.headers.get("www-authenticate"),/shards-mcp-connect/);
  const fake=await worker.fetch(new Request(target,{headers:{"cf-access-jwt-assertion":"invalid.jwt.token"}}),configured);
  assert.equal(fake.status,401);
  const oldPublic=await worker.fetch(post("tools/list"),configured);
  assert.equal((await oldPublic.json()).result.tools.length,7);
});

test("Separate signed Cloudflare identity can discover only public and session tools", async () => {
  const {publicKey,privateKey}=await webcrypto.subtle.generateKey(
    {name:"RSASSA-PKCS1-v1_5",modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:"SHA-256"},true,["sign","verify"]
  );
  const jwk=await webcrypto.subtle.exportKey("jwk",publicKey);
  jwk.kid="test-key";
  const b64=x=>Buffer.from(JSON.stringify(x)).toString("base64url");
  const make=async (changes={})=>{
    const payload={iss:"https://test.cloudflareaccess.com",aud:["access-audience"],sub:"legitimate-access-user",email:"verified@example.com",exp:Math.floor(Date.now()/1000)+1200,nbf:Math.floor(Date.now()/1000)-10,...changes};
    const partial=b64({alg:"RS256",kid:"test-key"})+"."+b64(payload);
    const sig=await webcrypto.subtle.sign("RSASSA-PKCS1-v1_5",privateKey,new TextEncoder().encode(partial));
    return partial+"."+Buffer.from(sig).toString("base64url");
  };
  const oldFetch=sandbox.fetch;
  let jwksFetches=0;
  sandbox.fetch=async url=>{
    jwksFetches++;
    assert.equal(url,"https://test.cloudflareaccess.com/cdn-cgi/access/certs");
    return {ok:true,json:async()=>({keys:[jwk]})};
  };
  const env={ACCESS_TEAM:"test",CONNECT_ACCESS_AUD:"access-audience",ACCESS_AUD:"operator-audience"};
  const target="https://mcp.shardsinc.co.uk/connect";
  const signedPost=(method,params,token,extra={})=>new Request(target,{
    method:"POST",headers:{"Content-Type":"application/json","cf-access-jwt-assertion":token,...extra},
    body:JSON.stringify({jsonrpc:"2.0",id:7,method,params})
  });
  try{
    const good=await make();
    const profile=await worker.fetch(new Request(target+"/profile",{headers:{"cf-access-jwt-assertion":good}}),env);
    assert.equal(profile.status,200);
    const mcpGet=await worker.fetch(new Request(target,{headers:{"cf-access-jwt-assertion":good}}),env);
    assert.equal(mcpGet.status,405,"MCP GET must not serve an HTML profile");
    assert.equal(mcpGet.headers.get("allow"),"POST");
    const postProfile=await worker.fetch(signedPost("tools/list",{},good).clone(),env); // transport baseline still POST
    assert.equal(postProfile.status,200);
    const badProfileMethod=await worker.fetch(new Request(target+"/profile",{method:"POST",headers:{"cf-access-jwt-assertion":good}}),env);
    assert.equal(badProfileMethod.status,405);
    assert.equal(badProfileMethod.headers.get("allow"),"GET");
    const html=await profile.text();
    assert.match(html,/verified@example.com/);
    assert.match(html,/VERIFIED IDENTITY/);
    assert.doesNotMatch(html,/smcp_/);
    const init=await worker.fetch(signedPost("initialize",{protocolVersion:"2025-11-25",capabilities:{},clientInfo:{name:"test",version:"1"}},good),env);
    assert.equal((await init.json()).result.protocolVersion,"2025-11-25");
    const list=await worker.fetch(signedPost("tools/list",{},good),env);
    const visible=(await list.json()).result.tools.map(x=>x.name);
    assert.deepEqual(Array.from(visible),[
      "shards_gateway_status","shards_systems_catalog","shards_dns_lookup",
      "shards_skill_search","shards_skill_read","shards_repo_document","shards_open_prs","shards_user_identity"
    ]);
    const identity=await worker.fetch(signedPost("tools/call",{name:"shards_user_identity",arguments:{}},good),env);
    const own=(await identity.json()).result.structuredContent;
    assert.equal(own.authenticated,true);
    assert.equal(own.email,"verified@example.com");
    assert.equal(own.subject_fingerprint.length,20);
    assert.deepEqual(Array.from(own.privileged_scopes),[]);
    const noTask=await worker.fetch(signedPost("tools/call",{name:"shards_task_create",arguments:{assignee_agent_id:"internal-agent"}},good,{
      authorization:"Bearer smcp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }),env);
    const denied=(await noTask.json()).result;
    assert.equal(denied.isError,true);
    assert.match(denied.content[0].text,/PERMISSION_DENIED/);
    const manage=await worker.fetch(new Request("https://mcp.shardsinc.co.uk/manage/api/agents",{headers:{"cf-access-jwt-assertion":good}}),env);
    assert.equal(manage.status,401,"Public Access token cannot impersonate the operator");
    const badAudience=await worker.fetch(new Request(target,{headers:{"cf-access-jwt-assertion":await make({aud:["operator-audience"]})}}),env);
    assert.equal(badAudience.status,401);
    const wrongIssuer=await worker.fetch(new Request(target,{headers:{"cf-access-jwt-assertion":await make({iss:"https://wrong.cloudflareaccess.com"})}}),env);
    assert.equal(wrongIssuer.status,401,"Wrong signed issuer must be rejected");
    for(const value of [null,[],true,1,"string"]){
      const invalid=await worker.fetch(signedPost("tools/call",{name:"shards_user_identity",arguments:value},good),env);
      assert.equal((await invalid.json()).result.isError,true,"Primitive/array identity arguments must fail closed");
    }
    const expired=await worker.fetch(new Request(target,{headers:{"cf-access-jwt-assertion":await make({exp:Math.floor(Date.now()/1000)-10})}}),env);
    assert.equal(expired.status,401);
    const missingExpiry=await worker.fetch(new Request(target,{headers:{"cf-access-jwt-assertion":await make({exp:undefined})}}),env);
    assert.equal(missingExpiry.status,401);
    const nonNumericExpiry=await worker.fetch(new Request(target,{headers:{"cf-access-jwt-assertion":await make({exp:"never"})}}),env);
    assert.equal(nonNumericExpiry.status,401);
    const sameAudience=await worker.fetch(new Request(target,{headers:{"cf-access-jwt-assertion":good}}),{...env,CONNECT_ACCESS_AUD:env.ACCESS_AUD});
    assert.equal(sameAudience.status,503,"The new Access app must use a different audience");
    const unsigned=good.slice(0,-5)+"xxxxx";
    const tampered=await worker.fetch(new Request(target,{headers:{"cf-access-jwt-assertion":unsigned}}),env);
    assert.equal(tampered.status,401);
    const htmlEscapeProbe=await worker.fetch(new Request(target+"/profile",{headers:{"cf-access-jwt-assertion":await make({email:'<script>alert("x")</script>'})}}),env);
    assert.equal(htmlEscapeProbe.status,200);
    const escaped=await htmlEscapeProbe.text();
    assert.doesNotMatch(escaped,/<script>alert/);
    assert.match(escaped,/&lt;script&gt;alert/);
    const dollarEmail=await worker.fetch(new Request(target+"/profile",{headers:{"cf-access-jwt-assertion":await make({email:"user$&@example.com"})}}),env);
    assert.equal(dollarEmail.status,200);
    const exact=await dollarEmail.text();
    assert.ok(exact.includes("user$&amp;@example.com"),"Replacement dollar directives must display literally");
    assert.equal(jwksFetches,1,"Repeated signed requests reuse the verified issuer JWKS during the TTL");
    const badConfig=await worker.fetch(new Request(target),{...env,CONNECT_ACCESS_AUD:env.ACCESS_AUD});
    assert.equal(badConfig.status,503);
    const oldMock=sandbox.fetch;
    try {
      sandbox.fetch=async()=>{throw Error("upstream JWKS outage")};
      const upstream=await worker.fetch(new Request(target,{headers:{"cf-access-jwt-assertion":await make({iss:"https://unavailable.cloudflareaccess.com"})}}),{...env,ACCESS_TEAM:"unavailable"});
      assert.equal(upstream.status,503,"Signing-key outages should not be labelled invalid user logins");
    } finally { sandbox.fetch=oldMock; }
  }finally{sandbox.fetch=oldFetch;}
});


test("RFC 9728 OAuth discovery publishes the actual path-bound resource and trusted Access issuer", async () => {
  const env={ACCESS_TEAM:"gentle-shape-bee5",ACCESS_AUD:"operator-aud",CONNECT_ACCESS_AUD:"different-connect-aud"};
  const root="https://mcp.shardsinc.co.uk";
  const m=await worker.fetch(new Request(root+"/.well-known/oauth-protected-resource/connect"),env);
  assert.equal(m.status,200);
  assert.match(m.headers.get("content-type"),/application\/json/);
  assert.match(m.headers.get("cache-control"),/max-age=120/);
  assert.equal(m.headers.get("access-control-allow-origin"),"*","Public metadata can be read by standard browser OAuth clients");
  const metadata=await m.json();
  assert.equal(metadata.resource,root+"/connect");
  assert.deepEqual(Array.from(metadata.authorization_servers),["https://gentle-shape-bee5.cloudflareaccess.com"]);
  assert.deepEqual(Array.from(metadata.bearer_methods_supported),["header"]);
  assert.doesNotMatch(JSON.stringify(metadata),/client_secret|token|identity|email|ACCESS_AUD/);
  const cloudflareAlias=await worker.fetch(new Request(root+"/.well-known/cloudflare-access-protected-resource/connect"),env);
  assert.equal(cloudflareAlias.status,200,"Actual Access challenge discovery path is served");
  assert.equal(cloudflareAlias.headers.get("access-control-allow-origin"),"*");
  const cfMetadata=await cloudflareAlias.json();
  assert.equal(cfMetadata.resource,root+"/connect");
  assert.equal(cfMetadata.protected,true);
  assert.equal(cfMetadata.team_domain,"gentle-shape-bee5.cloudflareaccess.com");
  assert.deepEqual(Array.from(cfMetadata.authorization_servers),["https://gentle-shape-bee5.cloudflareaccess.com"]);

  const missing=await worker.fetch(new Request(root+"/.well-known/oauth-protected-resource/connect"),{});
  assert.equal(missing.status,503);
  const wrongAudience=await worker.fetch(new Request(root+"/.well-known/oauth-protected-resource/connect"),{...env,CONNECT_ACCESS_AUD:"operator-aud"});
  assert.equal(wrongAudience.status,503);
  const missingOperator=await worker.fetch(new Request(root+"/.well-known/oauth-protected-resource/connect"),{ACCESS_TEAM:env.ACCESS_TEAM,CONNECT_ACCESS_AUD:env.CONNECT_ACCESS_AUD});
  assert.equal(missingOperator.status,503);
  for(const bad of ["", " ", "  broken "]) {
    const invalidAudience=await worker.fetch(new Request(root+"/.well-known/oauth-protected-resource/connect"),{...env,CONNECT_ACCESS_AUD:bad});
    assert.equal(invalidAudience.status,503);
  }
  for(const badTeam of ["-bad","bad-","evil.test/path"]) {
    const invalidTeam=await worker.fetch(new Request(root+"/.well-known/oauth-protected-resource/connect"),{...env,ACCESS_TEAM:badTeam});
    assert.equal(invalidTeam.status,503);
  }
  const badTeam=await worker.fetch(new Request(root+"/.well-known/oauth-protected-resource/connect"),{...env,ACCESS_TEAM:"evil.test/path"});
  assert.equal(badTeam.status,503);
  const otherHost=await worker.fetch(new Request("https://untrusted.example/.well-known/oauth-protected-resource/connect"),env);
  assert.equal(otherHost.status,404);
  const wrongMethod=await worker.fetch(new Request(root+"/.well-known/oauth-protected-resource/connect",{method:"POST"}),env);
  assert.equal(wrongMethod.status,404);
});

test("Unauthenticated connect origin exposes discoverable metadata without granting identity", async () => {
  const env={ACCESS_TEAM:"gentle-shape-bee5",ACCESS_AUD:"operator-aud",CONNECT_ACCESS_AUD:"different-connect-aud"};
  const r=await worker.fetch(new Request("https://mcp.shardsinc.co.uk/connect",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({jsonrpc:"2.0",id:1,method:"tools/list",params:{}})}),env);
  assert.equal(r.status,401);
  assert.equal(r.headers.get("access-control-allow-origin"),null,"Authenticated MCP responses never get wildcard CORS");
  assert.match(r.headers.get("www-authenticate"),/realm="shards-mcp-connect"/);
  assert.match(r.headers.get("www-authenticate"),/resource_metadata="https:\/\/mcp\.shardsinc\.co\.uk\/\.well-known\/cloudflare-access-protected-resource\/connect"/);
  assert.deepEqual(await r.json(),{error:"Cloudflare Access authentication required"},"The 401 response is a generic challenge, not a user-profile disclosure");
  const metadataUrl=r.headers.get("www-authenticate").match(/resource_metadata="([^"]+)"/)[1];
  const metadata=await worker.fetch(new Request(metadataUrl),env);
  assert.equal(metadata.status,200);
  const resource=await metadata.json();
  assert.equal(resource.resource,"https://mcp.shardsinc.co.uk/connect");
  assert.deepEqual(Array.from(resource.authorization_servers),["https://gentle-shape-bee5.cloudflareaccess.com"]);
});


test("Public research tools are discoverable, and private task tools remain hidden", async () => {
  const response=await worker.fetch(post("tools/list"),{});
  const names=(await response.json()).result.tools.map(t=>t.name);
  for(const name of ["shards_skill_search","shards_skill_read","shards_repo_document","shards_open_prs"])assert.ok(names.includes(name),name);
  assert.equal(names.length,7);
  assert.equal(names.includes("shards_task_create"),false);
});

test("Public research rejects traversal, arbitrary repos and malformed searches before budgets or network", async () => {
  const invalid=[
    {name:"shards_skill_read",arguments:{slug:"../private"}},
    {name:"shards_skill_read",arguments:{slug:"shards-../SECRET"}},
    {name:"shards_skill_search",arguments:{query:""}},
    {name:"shards_skill_search",arguments:{query:"security",limit:100}},
    {name:"shards_repo_document",arguments:{repository:"other-org/private",document:"README.md"}},
    {name:"shards_repo_document",arguments:{repository:"Shards-MCP",document:"../../.env"}},
    {name:"shards_open_prs",arguments:{repository:"somebody-else"}}
  ];
  let dbHits=0;
  const env={EDGE_DB:{prepare(){dbHits++;throw Error("Malformed arguments must not consume D1 quota");}}};
  for(const params of invalid){
    const response=await worker.fetch(post("tools/call",params),env);
    const data=await response.json();
    assert.equal(data.result.isError,true,params.name);
    assert.match(data.result.content[0].text,/Invalid public research arguments/);
  }
  assert.equal(dbHits,0);
});

test("Public research returns bounded live-source results from fixed GitHub origins", async () => {
  const calls=[],budgetWrites=[];
  const longSlug="shards-"+"a".repeat(93);
  const index={version:"test",skill_paths:["skills/shards-sec-vibecoding-gate","skills/shards-agent-onboarding","skills/third-party-import","skills/third-party-vibecoding","skills/"+longSlug]};
  const mockFetch=async (url,options)=>{
    calls.push({url:String(url),options});
    const headers={"content-type":"application/json"};
    if(String(url).endsWith("/catalogue/catalogue.json"))return new Response(JSON.stringify(index),{status:200,headers});
    if(String(url).endsWith("/skills/shards-sec-vibecoding-gate/SKILL.md"))return new Response("# Real instructions, not executed",{status:200,headers:{"content-type":"text/plain"}});
    if(String(url).endsWith("/skills/"+longSlug+"/SKILL.md"))return new Response("# Readable long first-party slug\n"+"x".repeat(24000),{status:200,headers:{"content-type":"text/plain"}});
    if(String(url).endsWith("/Shards-MCP/main/AGENTS.md"))return new Response("# Agent rules",{status:200,headers:{"content-type":"text/plain"}});
    if(String(url).includes("/pulls?"))return new Response(JSON.stringify(Array.from({length:11},(_,i)=>({number:42+i,title:"Add tests "+i,body:"long-review-description".repeat(1200),html_url:"https://github.com/Shards-foundation/Shards-MCP/pull/"+(42+i),updated_at:"2026-11-15T00:00:00Z",draft:false}))),{status:200,headers});
    throw Error("Unexpected upstream URL: "+url);
  };
  const fake={Request,Response,Headers,URL,TextEncoder,TextDecoder,crypto:webcrypto,AbortSignal,atob,fetch:mockFetch};
  vm.runInNewContext(src.replace("export default {", "globalThis.__edge = {"),fake,{filename:"worker.js"});
  const edge=fake.__edge;
  const env={EDGE_DB:{prepare(sql){assert.match(sql,/route_budgets/);return {bind(...values){budgetWrites.push(values);return {run:async()=>({meta:{changes:1}})};}};}}};
  async function call(name,args){const r=await edge.fetch(post("tools/call",{name,arguments:args}),env);const j=await r.json();assert.equal(j.result.isError,false,JSON.stringify(j.result));return j.result.structuredContent;}
  const results=await call("shards_skill_search",{query:"vibecoding"});
  assert.equal(results.matched,1);
  assert.equal(results.skills[0].slug,"shards-sec-vibecoding-gate");
  assert.equal(results.skills[0].readable_by_shards_skill_read,true);
  const mixed=await call("shards_skill_search",{query:"vibecoding",first_party_only:false});
  assert.equal(mixed.matched,2,"Imported skill with same search term must be filtered by default");
  const imports=await call("shards_skill_search",{query:"third-party",first_party_only:false});
  assert.equal(imports.skills[0].readable_by_shards_skill_read,false);
  // Discovery of imported catalogue metadata must not authorise reading imported instructions.
  const chargedBeforeDeniedRead=budgetWrites.length, fetchedBeforeDeniedRead=calls.length;
  const blockedImport=await edge.fetch(post("tools/call",{
    name:"shards_skill_read",arguments:{slug:"third-party-import"}
  }),env);
  const blockedBody=await blockedImport.json();
  assert.equal(blockedBody.result.isError,true,"An imported skill must not be readable");
  assert.match(blockedBody.result.content[0].text,/Invalid public research arguments/);
  assert.equal(budgetWrites.length,chargedBeforeDeniedRead,"Denied import read must not charge D1 quota");
  assert.equal(calls.length,fetchedBeforeDeniedRead,"Denied import read must not fetch SKILL.md");
  const longResult=await call("shards_skill_search",{query:"aaaa"});
  assert.equal(longResult.skills[0].slug,longSlug);
  assert.equal(longResult.skills[0].readable_by_shards_skill_read,true);
  const longRead=await call("shards_skill_read",{slug:longSlug});
  assert.match(longRead.content,/Readable long/);
  assert.equal(longRead.content.length,20000);
  assert.equal(longRead.truncated,true);
  const read=await call("shards_skill_read",{slug:"shards-sec-vibecoding-gate"});
  assert.match(read.content,/Real instructions/);
  assert.equal(read.truncated,false);
  const doc=await call("shards_repo_document",{repository:"Shards-MCP",document:"AGENTS.md"});
  assert.equal(doc.content,"# Agent rules");
  const prs=await call("shards_open_prs",{repository:"Shards-MCP"});
  assert.equal(prs.pull_requests[0].number,42);
  assert.equal(prs.pull_requests.length,10,"GitHub responses with eleven PRs must truncate to ten metadata entries");
  assert.equal('body' in prs.pull_requests[0],false,"PR bodies must never be returned");
  assert.ok(calls.every(c=>c.url.startsWith("https://raw.githubusercontent.com/Shards-foundation/")||c.url.startsWith("https://api.github.com/repos/Shards-foundation/")));
  assert.ok(calls.every(c=>c.options.redirect==="manual"),"Cloudflare Workers supports manual redirects; all 3xx responses must fail closed");
  assert.ok(calls.every(c=>c.options.signal instanceof AbortSignal),"Each upstream request requires a timeout signal");
  assert.ok(calls.every(c=>c.options.cf?.cacheEverything===true&&c.options.cf?.cacheTtl===300),"All public reads must enable bounded caching");
  assert.equal(budgetWrites.length,16,"Eight valid public calls must each charge caller and global D1 budgets");
  assert.equal(budgetWrites.filter(v=>String(v[1]).startsWith("public:")).length,8);
  assert.equal(budgetWrites.filter(v=>["shards_skill_search","shards_skill_read","shards_repo_document","shards_open_prs"].includes(v[1])).length,8);
});


test("Public read streaming limit cancels an oversized source with no content-length", async () => {
  let cancelled=false,requested=false;
  const stream=new ReadableStream({
    start(controller){controller.enqueue(new Uint8Array(400000));},
    cancel(){cancelled=true;}
  });
  const mockFetch=async (url)=>{
    requested=true;
    assert.equal(String(url),"https://raw.githubusercontent.com/Shards-foundation/Shards-MCP/main/README.md");
    return new Response(stream,{status:200,headers:{"content-type":"text/plain"}});
  };
  const fake={Request,Response,Headers,URL,TextEncoder,TextDecoder,crypto:webcrypto,AbortSignal,atob,fetch:mockFetch};
  vm.runInNewContext(src.replace("export default {", "globalThis.__edge = {"),fake,{filename:"worker.js"});
  const env={EDGE_DB:{prepare(){return {bind(){return {run:async()=>({meta:{changes:1}})}}};}}};
  const result=await fake.__edge.fetch(post("tools/call",{name:"shards_repo_document",arguments:{repository:"Shards-MCP"}}),env);
  const json=await result.json();
  assert.equal(requested,true);
  assert.equal(json.result.isError,true);
  assert.match(json.result.content[0].text,/Public source too large/);
  assert.equal(cancelled,true,"Reader must cancel when the byte limit is crossed");
});

test("supplied invalid credentials cannot downgrade handshake or discovery to anonymous", async () => {
  const env={EDGE_DB:{prepare(sql){return {bind(){return {first:async()=>null}}}}}};
  for(const authorization of ["", "Basic invalid", "Bearer invalid", "Bearer smcp_"+"a".repeat(43)]) {
    for(const method of ["initialize","server/discover","ping","tools/list","tools/call","notifications/initialized"]) {
      const response=await worker.fetch(post(method,{name:"shards_gateway_status"},{authorization}),env);
      assert.equal(response.status,401);
      assert.match(response.headers.get("www-authenticate"),/invalid_token/);
      assert.equal(response.headers.get("cache-control"),"no-store");
      assert.equal((await response.text()).includes(authorization || "never-present"),false);
    }
  }
  const anonymous=await worker.fetch(post("tools/list"),{});
  assert.equal(anonymous.status,200);
  assert.equal((await anonymous.json()).result.tools.length,7);
});

test("bearer discovery is scoped, refreshed per request, and storage failure denies", async () => {
  let active=true,reads=0;
  const actor={id:"fixture-agent",tenant_id:"fixture-tenant",name:"fixture",client:"test",scopes:'["agent:identity"]'};
  const env={EDGE_DB:{prepare(sql){return {bind(){return {
    async first(){reads++;assert.match(sql,/revoked_at IS NULL/);assert.match(sql,/expires_at>\?/);assert.match(sql,/disabled_at IS NULL/);return active?actor:null},
    async run(){return {meta:{changes:1}}}
  }}}}}};
  const headers={authorization:"Bearer smcp_"+"b".repeat(43)};
  for(let i=0;i<2;i++){
    const response=await worker.fetch(post("tools/list",{},headers),env);
    const names=(await response.json()).result.tools.map(x=>x.name);
    assert.ok(names.includes("shards_agent_identity"));
    assert.ok(!names.includes("shards_message_send"));
    assert.ok(!names.includes("shards_agents_list"));
  }
  assert.equal(reads,2);
  const identity=await worker.fetch(post("tools/call",{name:"shards_agent_identity",arguments:{}},headers),env);
  assert.equal(identity.status,200);
  const who=(await identity.json()).result;
  assert.equal(who.isError,false);
  assert.equal(who.structuredContent.id,actor.id);
  assert.equal(who.structuredContent.tenant,actor.tenant_id);
  assert.deepEqual(Array.from(who.structuredContent.scopes),["agent:identity"]);
  const forbidden=await worker.fetch(post("tools/call",{name:"shards_message_send",arguments:{}},headers),env);
  assert.equal(forbidden.status,200);
  assert.equal((await forbidden.json()).result.isError,true);
  assert.equal(reads,4,"Discovery and each call reauthenticate independently");
  active=false;
  assert.equal((await worker.fetch(post("tools/list",{},headers),env)).status,401);
  const broken={EDGE_DB:{prepare(){throw Error("sensitive internal storage details")}}};
  const unavailable=await worker.fetch(post("tools/list",{},headers),broken);
  assert.equal(unavailable.status,503);
  assert.doesNotMatch(await unavailable.text(),/sensitive|fixture|smcp_/);
});


test("/mcp 401 metadata fallback never advertises /connect or an Access issuer", async () => {
  const configured={ACCESS_TEAM:"fixture",ACCESS_AUD:"operator-aud",CONNECT_ACCESS_AUD:"connect-aud"};
  const root="https://mcp.shardsinc.co.uk";
  // Absent or invalid Access configuration cannot change the bearer resource's authority.
  for(const env of [configured,{}, {...configured,CONNECT_ACCESS_AUD:configured.ACCESS_AUD}]) {
    const denied=await worker.fetch(post("tools/list",{},{authorization:"Bearer invalid"}),env);
    assert.equal(denied.status,401);
    assert.equal(denied.headers.get("www-authenticate"),'Bearer realm="shards-mcp", error="invalid_token"');
    assert.equal(denied.headers.get("location"),null);
    for(const path of ["/.well-known/oauth-protected-resource","/.well-known/oauth-protected-resource/mcp",
                       "/.well-known/oauth-authorization-server"]) {
      for(const method of ["GET","HEAD"]) {
        const response=await worker.fetch(new Request(root+path,{method}),env);
        assert.equal(response.status,404,method+" "+path);
        assert.equal(response.headers.get("location"),null);
        assert.equal(response.headers.get("www-authenticate"),null);
        assert.equal(response.headers.get("cache-control"),"no-store");
        assert.doesNotMatch(await response.text(),/connect|cloudflareaccess|authorization_servers/);
      }
    }
  }
});
