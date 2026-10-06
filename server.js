
const express=require("express"), path=require("path"), cheerio=require("cheerio");
const {Pool}=require("pg"), webpush=require("web-push");
const app=express(); app.use(express.json({limit:"1mb"})); app.use(express.static(path.join(__dirname,"public")));
const PORT=process.env.PORT||3000, DATABASE_URL=process.env.DATABASE_URL;
const pool=DATABASE_URL?new Pool({connectionString:DATABASE_URL,ssl:{rejectUnauthorized:false}}):null;
const APS=[
 ["APS • Esperados — Carga","https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/navios-esperados-carga/","Esperado"],
 ["APS • Esperados — Passageiros","https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/navios-esperados-passageiros/","Esperado"],
 ["APS • Atracações Programadas","https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/atracacoes-programadas/","Programado"],
 ["APS • Atracados","https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/atracados-porto-terminais/","Atracado"],
 ["APS • Fundeados","https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/navios-fundeados/","Fundeado"]
];
const SB="https://www.santosbrasil.com.br/v2021/lista-de-atracacao";
const PUBLIC=process.env.VAPID_PUBLIC_KEY||"", PRIVATE=process.env.VAPID_PRIVATE_KEY||"", SUBJECT=process.env.VAPID_SUBJECT||"mailto:admin@example.com";
if(PUBLIC&&PRIVATE) webpush.setVapidDetails(SUBJECT,PUBLIC,PRIVATE);

let memory={}; let lastSync=null; let syncing=false;

async function init(){
 if(!pool) return;
 await pool.query(`CREATE TABLE IF NOT EXISTS navios(
  id TEXT PRIMARY KEY, data JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
 )`);
 await pool.query(`CREATE TABLE IF NOT EXISTS push_subscriptions(
  endpoint TEXT PRIMARY KEY, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
 )`);
}
function norm(s){return String(s??"").replace(/\s+/g," ").trim()}
function findHeader(headers, names){for(let i=0;i<headers.length;i++){let h=headers[i].toLowerCase();if(names.some(n=>h.includes(n)))return i}return -1}
function parseDate(s){return norm(s)}
function parseHtml(html,source,status){
 const $=cheerio.load(html), out=[];
 $("table").each((_,table)=>{
   const rows=$(table).find("tr"); if(rows.length<2)return;
   let headers=$(rows[0]).find("th,td").map((_,x)=>norm($(x).text())).get();
   if(headers.length<3)return;
   const navI=findHeader(headers,["navio","ship"]), etaI=findHeader(headers,["eta","cheg","arrival"]), ataI=findHeader(headers,["ata"]), etbI=findHeader(headers,["etb"]), atbI=findHeader(headers,["atb"]), bercoI=findHeader(headers,["berço","brc"]), tripI=findHeader(headers,["viagem","voyage"]), imoI=findHeader(headers,["imo"]);
   if(navI<0)return;
   rows.slice(1).each((_,row)=>{
     const cells=$(row).find("td,th").map((_,x)=>norm($(x).text())).get();
     if(cells.length<headers.length/2)return;
     const name=norm(cells[navI]); if(!name||/navio|ship/i.test(name))return;
     const voyage=tripI>=0?norm(cells[tripI]):"";
     const id=imoI>=0?norm(cells[imoI]):`${source}|${name}|${voyage}`;
     out.push({id,name:name.replace(/\s+/g," "),voyage,status,source,berco:bercoI>=0?norm(cells[bercoI]):"—",eta:etaI>=0?parseDate(cells[etaI]):"—",ata:ataI>=0?parseDate(cells[ataI]):"—",etb:etbI>=0?parseDate(cells[etbI]):"—",atb:atbI>=0?parseDate(cells[atbI]):"—",imo:imoI>=0?norm(cells[imoI]):""});
   });
 });
 return out;
}
async function fetchSource(source,url,status){
 try{
   const r=await fetch(url,{headers:{"User-Agent":"PortoSantosLive/3.0 (+monitoramento operacional)"}});
   if(!r.ok) throw new Error(`${r.status} ${r.statusText}`);
   const html=await r.text(); return parseHtml(html,source,status);
 }catch(e){console.error("Fonte:",source,e.message);return []}
}
async function collect(){
 if(syncing)return; syncing=true;
 try{
   let all=[];
   for(const [source,url,status] of APS) all.push(...await fetchSource(source,url,status));
   // A página pública da Santos Brasil expõe ETA/ATA/ETB/ATB e estados.
   all.push(...await fetchSource("Santos Brasil",SB,"Programado"));
   const merged=new Map();
   for(const n of all){
     const key=(n.imo||`${n.name}|${n.voyage}`).toUpperCase().replace(/\s+/g," ");
     const old=merged.get(key);
     if(!old) merged.set(key,n);
     else merged.set(key,{...old,...Object.fromEntries(Object.entries(n).filter(([_,v])=>v&&v!=="—")),source:`${old.source} + ${n.source}`,status:n.atb&&n.atb!=="—"?"Atracado":(n.ata&&n.ata!=="—"?"Na barra":old.status)});
   }
   const arr=[...merged.values()];
   const oldMap={};
   if(pool){const q=await pool.query("SELECT id,data FROM navios");q.rows.forEach(r=>oldMap[r.id]=r.data)}
   else Object.assign(oldMap,memory);
   for(const n of arr){
     const old=oldMap[n.id];
     if(pool) await pool.query("INSERT INTO navios(id,data) VALUES($1,$2) ON CONFLICT(id) DO UPDATE SET data=$2,updated_at=now()",[n.id,n]);
     else memory[n.id]=n;
     if(old) await notifyChanges(old,n);
   }
   lastSync=new Date().toISOString();
   console.log(`Sync ${lastSync}: ${arr.length} navios`);
   return arr.length;
 }finally{syncing=false}
}
async function getSubs(){if(!pool)return []; const q=await pool.query("SELECT data FROM push_subscriptions");return q.rows.map(r=>r.data)}
async function notifyChanges(old,n){
 if(!PUBLIC||!PRIVATE)return;
 const changed=[];
 for(const k of ["status","ata","atb"]){
   if((old[k]||"—")!==(n[k]||"—")&&(n[k]||"—")!=="—")changed.push(k);
 }
 if(!changed.length)return;
 const title=changed.includes("atb")?`⚓ ${n.name} atracou`:changed.includes("ata")?`🚢 ${n.name} entrou na barra`:`📡 ${n.name} foi atualizado`;
 const body=changed.includes("atb")?`ATB: ${n.atb} • Berço: ${n.berco||"—"}`:changed.includes("ata")?`ATA: ${n.ata}`:`Status: ${n.status}`;
 for(const s of await getSubs()){
   try{await webpush.sendNotification(s,JSON.stringify({title,body,url:"/"}))}
   catch(e){if(pool&&(e.statusCode===404||e.statusCode===410))await pool.query("DELETE FROM push_subscriptions WHERE endpoint=$1",[s.endpoint])}
 }
}
app.get("/api/config",(q,r)=>r.json({pushEnabled:!!(PUBLIC&&PRIVATE),publicKey:PUBLIC,updatedAt:lastSync}));
app.get("/api/health",(q,r)=>r.json({ok:true,lastSync,sources:APS.length+1}));
app.get("/api/navios",async(q,r)=>{
 let arr;
 if(pool){const x=await pool.query("SELECT data FROM navios ORDER BY updated_at DESC");arr=x.rows.map(a=>a.data)}
 else arr=Object.values(memory);
 r.json({updatedAt:lastSync,source:"APS + Santos Brasil",count:arr.length,navios:arr});
});
app.post("/api/push/subscribe",async(q,r)=>{
 if(!pool||!PUBLIC||!PRIVATE)return r.status(503).json({error:"Push/banco não configurado"});
 const s=q.body;if(!s?.endpoint)return r.status(400).json({error:"Assinatura inválida"});
 await pool.query("INSERT INTO push_subscriptions(endpoint,data) VALUES($1,$2) ON CONFLICT(endpoint) DO UPDATE SET data=$2",[s.endpoint,s]);r.json({ok:true});
});
app.post("/api/push/unsubscribe",async(q,r)=>{if(pool&&q.body?.endpoint)await pool.query("DELETE FROM push_subscriptions WHERE endpoint=$1",[q.body.endpoint]);r.json({ok:true})});
app.post("/api/internal/sync",async(q,r)=>{if(process.env.SYNC_TOKEN&&q.headers["x-sync-token"]!==process.env.SYNC_TOKEN)return r.sendStatus(401);const n=q.body?.navios||[];for(const x of n){memory[x.id]=x}r.json({ok:true,count:n.length})});

(async()=>{await init();app.listen(PORT,()=>console.log(`Porto Santos Live ${PORT}`));setTimeout(collect,3000);setInterval(collect,60000)})();
