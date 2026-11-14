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
    "shards_gateway_status", "shards_systems_catalog", "shards_dns_lookup"
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
  await page.click("protocolRun");
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
  assert.equal((await oldPublic.json()).result.tools.length,3);
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
      "shards_gateway_status","shards_systems_catalog","shards_dns_lookup","shards_user_identity"
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
