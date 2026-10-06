import os, json, re, time
from datetime import datetime, timezone
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

SOURCES = [
    ("Esperado", "APS — Navios esperados: Carga", "https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/navios-esperados-carga/"),
    ("Esperado", "APS — Navios esperados: Passageiros", "https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/navios-esperados-passageiros/"),
    ("Esperado", "APS — Atracações programadas", "https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/atracacoes-programadas/"),
    ("Atracado", "APS — Atracados Porto/Terminais", "https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/atracados-porto-terminais/"),
    ("Fundeado", "APS — Navios Fundeados", "https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/navios-fundeados/"),
    ("Atracado", "Santos Brasil — Lista de Atracação", "https://www.santosbrasil.com.br/v2021/lista-de-atracacao"),
]
HEADERS={"User-Agent":"Mozilla/5.0 (compatible; PortoSantosLive/1.0; +https://github.com/)"}

def clean(v):
    if v is None:return ""
    s=re.sub(r"\s+"," ",str(v)).strip()
    return "" if s.lower() in {"nan","none","nat","--","-"} else s

def norm_col(c):
    s=clean(c).lower()
    return re.sub(r"[^a-z0-9]+","",s)

def find_col(cols,*names):
    ncols=[norm_col(c) for c in cols]
    for name in names:
        n=norm_col(name)
        for i,c in enumerate(ncols):
            if n==c or n in c or c in n:return cols[i]
    return None

def rows_from_html(html, source_status, source_name):
    soup=BeautifulSoup(html,"html.parser")
    tables=soup.find_all("table")
    out=[]
    for table in tables:
        trs=table.find_all("tr")
        if len(trs)<2: continue
        rows=[]
        for tr in trs:
            cells=[clean(x.get_text(" ",strip=True)) for x in tr.find_all(["th","td"])]
            if cells: rows.append(cells)
        if len(rows)<2: continue
        header=rows[0]
        # Sometimes the first row is a section label; try each early row as header.
        candidates=[header]+rows[1:4]
        chosen=None
        for h in candidates:
            if any("navio" in norm_col(x) for x in h):
                chosen=h;break
        if not chosen: continue
        # Align data by chosen header row index
        hi=rows.index(chosen)
        data=rows[hi+1:]
        for r in data:
            if len(r)<len(chosen): r=r+[""]*(len(chosen)-len(r))
            if len(r)>len(chosen): r=r[:len(chosen)]
            d=dict(zip(chosen,r))
            name_col=find_col(chosen,"Navio","Navio/Viagem","Ship")
            imo_col=find_col(chosen,"IMO")
            eta_col=find_col(chosen,"ETA","Cheg/Arrival","Previsão de Chegada")
            ata_col=find_col(chosen,"ATA","Entrada na barra")
            etb_col=find_col(chosen,"ETB")
            atb_col=find_col(chosen,"ATB")
            terminal_col=find_col(chosen,"Terminal","Local","Lugar","Berço","BRC")
            voyage_col=find_col(chosen,"Viagem","Voyage")
            name=clean(d.get(name_col,"")) if name_col else ""
            if not name or name.lower() in {"navio","ship"}: continue
            imo=clean(d.get(imo_col,"")) if imo_col else ""
            # Avoid picking non-ship page rows.
            if len(name)<2: continue
            key=(imo or name).upper()
            out.append({
                "id":re.sub(r"[^A-Za-z0-9_-]+","-",key)[:100],
                "name":name,
                "imo":imo,
                "status":source_status,
                "eta":clean(d.get(eta_col,"")) if eta_col else "",
                "ata":clean(d.get(ata_col,"")) if ata_col else "",
                "etb":clean(d.get(etb_col,"")) if etb_col else "",
                "atb":clean(d.get(atb_col,"")) if atb_col else "",
                "terminal":clean(d.get(terminal_col,"")) if terminal_col else "",
                "voyage":clean(d.get(voyage_col,"")) if voyage_col else "",
                "source":source_name
            })
    return out

def main():
    all_rows=[]
    errors=[]
    for status,name,url in SOURCES:
        try:
            r=requests.get(url,headers=HEADERS,timeout=30)
            r.raise_for_status()
            rows=rows_from_html(r.text,status,name)
            if not rows: errors.append(f"{name}: nenhuma tabela reconhecida")
            all_rows.extend(rows)
            time.sleep(1)
        except Exception as e:
            errors.append(f"{name}: {e}")
    # De-duplicate: prefer more specific live status over expected.
    rank={"Atracado":4,"Fundeado":3,"Barra":3,"Esperado":1}
    merged={}
    for x in all_rows:
        key=x["imo"] or x["name"].upper()
        if key not in merged or rank.get(x["status"],0)>rank.get(merged[key]["status"],0):
            merged[key]=x
        else:
            # fill missing fields from another source
            for k,v in x.items():
                if not merged[key].get(k) and v: merged[key][k]=v
    now=datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M:%S")
    result=list(merged.values())
    for x in result:x["updatedAt"]=now
    result.sort(key=lambda x:(x["status"],x["name"]))
    os.makedirs("public",exist_ok=True)
    with open("public/navios.json","w",encoding="utf-8") as f:json.dump(result,f,ensure_ascii=False,indent=2)
    with open("public/atualizacao.json","w",encoding="utf-8") as f:json.dump({"updatedAt":now,"total":len(result),"errors":errors},f,ensure_ascii=False,indent=2)
    print(f"Registros: {len(result)}")
    if errors:
        print("AVISOS:")
        print("\n".join(errors))
    # Never erase a working dataset just because a source failed.
    if not result:
        raise RuntimeError("Nenhuma fonte retornou dados; mantendo o arquivo anterior seria preferível.")

if __name__=="__main__": main()
