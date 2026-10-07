import os
import json
import re
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SOURCES = [
    ("Esperado", "APS — Navios esperados: Carga",
     "https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/navios-esperados-carga/"),
    ("Esperado", "APS — Navios esperados: Passageiros",
     "https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/navios-esperados-passageiros/"),
    ("Esperado", "APS — Atracações programadas",
     "https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/atracacoes-programadas/"),
    ("Atracado", "APS — Atracados Porto/Terminais",
     "https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/atracados-porto-terminais/"),
    ("Fundeado", "APS — Navios Fundeados",
     "https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/navios-fundeados/"),
    ("Atracado", "Santos Brasil — Lista de Atracação",
     "https://www.santosbrasil.com.br/v2021/lista-de-atracacao"),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PortoSantosLive/1.0)"
}

def clean(value):
    if value is None:
        return ""
    value = re.sub(r"\s+", " ", str(value)).strip()
    return "" if value.lower() in {"nan", "none", "nat", "--", "-"} else value

def norm_col(value):
    return re.sub(r"[^a-z0-9]+", "", clean(value).lower())

def find_col(columns, *names):
    normalized = [norm_col(c) for c in columns]
    for name in names:
        target = norm_col(name)
        for i, col in enumerate(normalized):
            if target == col or target in col or col in target:
                return columns[i]
    return None

def rows_from_html(html, source_status, source_name):
    soup = BeautifulSoup(html, "html.parser")
    output = []

    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        if len(trs) < 2:
            continue

        rows = []
        for tr in trs:
            cells = [clean(c.get_text(" ", strip=True))
                     for c in tr.find_all(["th", "td"])]
            if cells:
                rows.append(cells)

        if len(rows) < 2:
            continue

        header_index = None
        for i, row in enumerate(rows[:4]):
            if any("navio" in norm_col(x) for x in row):
                header_index = i
                break

        if header_index is None:
            continue

        header = rows[header_index]

        for row in rows[header_index + 1:]:
            if len(row) < len(header):
                row = row + [""] * (len(header) - len(row))
            if len(row) > len(header):
                row = row[:len(header)]

            data = dict(zip(header, row))

            name_col = find_col(header, "Navio", "Navio/Viagem", "Ship")
            imo_col = find_col(header, "IMO")
            eta_col = find_col(header, "ETA", "Cheg/Arrival", "Previsão de Chegada")
            ata_col = find_col(header, "ATA", "Entrada na barra")
            etb_col = find_col(header, "ETB")
            atb_col = find_col(header, "ATB")
            terminal_col = find_col(header, "Terminal", "Local", "Lugar", "Berço", "BRC")
            voyage_col = find_col(header, "Viagem", "Voyage")

            name = clean(data.get(name_col, "")) if name_col else ""
            if not name or len(name) < 2:
                continue

            imo = clean(data.get(imo_col, "")) if imo_col else ""

            key = (imo or name).upper()
            safe_id = re.sub(r"[^A-Za-z0-9_-]+", "-", key)[:100]

            output.append({
                "id": safe_id,
                "name": name,
                "imo": imo,
                "status": source_status,
                "eta": clean(data.get(eta_col, "")) if eta_col else "",
                "ata": clean(data.get(ata_col, "")) if ata_col else "",
                "etb": clean(data.get(etb_col, "")) if etb_col else "",
                "atb": clean(data.get(atb_col, "")) if atb_col else "",
                "terminal": clean(data.get(terminal_col, "")) if terminal_col else "",
                "voyage": clean(data.get(voyage_col, "")) if voyage_col else "",
                "source": source_name,
            })

    return output


def scheduled_name_key(value):
    value = clean(value).upper()
    value = re.sub(r"\s+\d{4,}.*$", "", value)
    value = re.sub(r"\s+--.*$", "", value)
    value = re.sub(r"[^A-Z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def parse_scheduled_berthings(html):
    """Extrai a previsão de atracação da página 'Atracações Programadas'.
    A fonte publica Data + Hora + Navio + IMO + Evento. Para evento ATRACACAO,
    usamos o início da janela de hora como ETB; se não houver hora, mantemos
    apenas a data.
    """
    soup = BeautifulSoup(html, "html.parser")
    result = {}

    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        if len(trs) < 2:
            continue

        rows = []
        for tr in trs:
            cells = [clean(c.get_text(" ", strip=True))
                     for c in tr.find_all(["th", "td"])]
            if cells:
                rows.append(cells)

        if len(rows) < 2:
            continue

        header_index = None
        for i, row in enumerate(rows[:5]):
            names = [norm_col(x) for x in row]
            if any("navio" in x for x in names) and any(
                ("data" in x or "date" in x) for x in names
            ):
                header_index = i
                break

        if header_index is None:
            continue

        header = rows[header_index]
        hnorm = [norm_col(x) for x in header]

        def col(*targets):
            for target in targets:
                nt = norm_col(target)
                for i, h in enumerate(hnorm):
                    if h == nt or nt in h or h in nt:
                        return i
            return None

        nav_i = col("Navio", "Ship")
        imo_i = col("IMO")
        date_i = col("Data", "Date")
        hour_i = col("Hora", "Hour")
        event_i = col("Evento", "Event")
        eta_i = col("ETA")

        if nav_i is None:
            continue

        for row in rows[header_index + 1:]:
            if len(row) < len(header):
                row = row + [""] * (len(header) - len(row))
            row = row[:len(header)]

            name = clean(row[nav_i])
            if not name or name.lower() in {"navio", "ship"}:
                continue

            event = clean(row[event_i]) if event_i is not None else ""
            # Só usar como ETB quando a fonte identifica o evento como atracação.
            if event and "ATRAC" not in event.upper():
                continue

            imo = clean(row[imo_i]) if imo_i is not None else ""
            date = clean(row[date_i]) if date_i is not None else ""
            hour = clean(row[hour_i]) if hour_i is not None else ""
            eta = clean(row[eta_i]) if eta_i is not None else ""

            etb = ""
            if date and hour:
                # Exemplos: "13:00/19:00", "13:00 - 19:00", "13:00"
                m = re.search(r"(\d{1,2}:\d{2})", hour)
                if m:
                    etb = f"{date} {m.group(1)}"
                else:
                    etb = date
            elif date:
                etb = date

            record = {
                "name": name,
                "imo": imo,
                "eta": eta,
                "etb": etb,
                "source": "APS — Atracações Programadas"
            }
            # Indexar pelos dois identificadores: a APS pode publicar IMO em
            # algumas tabelas e omiti-lo em outras.
            if imo:
                result[imo.upper()] = record
            result[scheduled_name_key(name)] = record

    return result


SANTOS_BRASIL_API = "https://integraaquiapi.santosbrasil.com.br/listaAtracacao/listaAtracacaoGeral"

def normalize_ship_name(value):
    value = clean(value).upper()
    # Remove viagem/armador anexados ao nome quando a fonte publica algo como
    # "CMA CGM IRON --" ou "CMA CGM IRON 04512 2026".
    value = re.sub(r"\s+\d{4,}.*$", "", value)
    value = re.sub(r"\s+--.*$", "", value)
    value = re.sub(r"[^A-Z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def parse_santos_brasil_api_payload(payload):
    """Extrai registros da API pública de Lista de Atracação do Santos Brasil.
    A API não documenta um schema de resposta no Swagger, então fazemos uma
    leitura tolerante das chaves e também percorremos listas/objetos aninhados.
    """
    rows = []

    def walk(obj):
        if isinstance(obj, list):
            for item in obj:
                walk(item)
            return
        if not isinstance(obj, dict):
            return

        keys = {norm_col(k): k for k in obj.keys()}
        def get(*names):
            for name in names:
                target = norm_col(name)
                for nk, original in keys.items():
                    if nk == target or target in nk or nk in target:
                        return obj.get(original)
            return ""

        name = clean(get("navio", "ship", "navionome", "nomenavio", "navioViagemArmador", "navioViagem", "shipname"))
        imo = clean(get("imo"))
        eta = clean(get("eta", "previsaochegada", "dataeta", "etaData", "previsaoChegada"))
        ata = clean(get("ata", "dataata"))
        etb = clean(get("etb", "previsaodeatracacao", "dataetb", "previsaoEtb", "previsaoAtracacao"))
        atb = clean(get("atb", "dataatb"))
        terminal = clean(get("terminal", "berco", "local"))
        voyage = clean(get("viagem", "voyage"))

        if name and len(name) >= 2:
            rows.append({
                "id": re.sub(r"[^A-Za-z0-9_-]+", "-", (imo or name).upper())[:100],
                "name": name,
                "imo": imo,
                "status": "Esperado",
                "eta": eta,
                "ata": ata,
                "etb": etb,
                "atb": atb,
                "terminal": terminal,
                "voyage": voyage,
                "source": "Santos Brasil — API Lista de Atracação",
            })

        for value in obj.values():
            if isinstance(value, (dict, list)):
                walk(value)

    walk(payload)
    # Remove duplicatas pelo IMO/nome, mantendo o registro mais preenchido.
    best = {}
    for row in rows:
        key = (row.get("imo") or normalize_ship_name(row.get("name"))).upper()
        score = sum(bool(row.get(k)) for k in ("eta", "ata", "etb", "atb", "terminal", "voyage"))
        old = best.get(key)
        if old is None or score > old[0]:
            best[key] = (score, row)
    return [x[1] for x in best.values()]

def fetch_santos_brasil_api():
    """Consulta a API oficial do Santos Brasil para uma janela móvel de 45 dias."""
    from datetime import timedelta
    now = datetime.now().astimezone()
    payload = {
        "inicioLista": (now - timedelta(days=7)).isoformat(),
        "fimLista": (now + timedelta(days=45)).isoformat(),
    }
    response = requests.post(
        SANTOS_BRASIL_API,
        headers={**HEADERS, "Content-Type": "application/json"},
        json=payload,
        timeout=45,
        verify=False,
    )
    response.raise_for_status()
    data = response.json()
    return parse_santos_brasil_api_payload(data)

def merge_cross_source_fields(all_rows):
    """Cruza navios por IMO ou por nome normalizado, sem depender da ordem das fontes."""
    index_imo = {}
    index_name = {}
    for ship in all_rows:
        imo = clean(ship.get("imo")).upper()
        name = normalize_ship_name(ship.get("name"))
        if imo:
            index_imo.setdefault(imo, []).append(ship)
        if name:
            index_name.setdefault(name, []).append(ship)

    # A API do Santos Brasil pode publicar um nome sem IMO; o cruzamento por nome
    # normalizado garante que "CMA CGM IRON --" e "CMA CGM IRON" sejam o mesmo navio.
    for ship in all_rows:
        matches = []
        imo = clean(ship.get("imo")).upper()
        name = normalize_ship_name(ship.get("name"))
        if imo:
            matches.extend(index_imo.get(imo, []))
        if not matches and name:
            matches.extend(index_name.get(name, []))

        for other in matches:
            if other is ship:
                continue
            for field in ("eta", "ata", "etb", "atb", "terminal", "voyage"):
                if not ship.get(field) and other.get(field):
                    ship[field] = other[field]
            if other.get("source") and other.get("source") != ship.get("source"):
                sources = ship.setdefault("sources", [])
                if other["source"] not in sources:
                    sources.append(other["source"])


def main():
    all_rows = []
    errors = []
    scheduled = {}

    for status, source_name, url in SOURCES:
        try:
            response = requests.get(url, headers=HEADERS, timeout=30, verify=False)
            response.raise_for_status()

            if "atracoes-programadas" in url:
                try:
                    scheduled.update(parse_scheduled_berthings(response.text))
                except Exception as exc:
                    errors.append(f"{source_name}: falha ao extrair previsão de atracação: {exc}")

            rows = rows_from_html(response.text, status, source_name)

            if not rows:
                errors.append(f"{source_name}: nenhuma tabela reconhecida")

            all_rows.extend(rows)
            time.sleep(1)

        except Exception as exc:
            errors.append(f"{source_name}: {exc}")

    # Consulta adicional à API oficial do Santos Brasil. Ela existe especificamente
    # para a Lista de Atracação e é mais confiável para ETA/ATA/ETB/ATB do que
    # tentar ler a tabela dinâmica diretamente do HTML.
    try:
        api_rows = fetch_santos_brasil_api()
        all_rows.extend(api_rows)
        print(f"Santos Brasil API: {len(api_rows)} registros")
    except Exception as exc:
        errors.append(f"Santos Brasil API Lista de Atracação: {exc}")

    # Complementa os registros com a previsão de atracação (ETB) publicada
    # pela APS. Nunca substitui um ETB mais específico já obtido de outra fonte.
    for ship in all_rows:
        key_imo = (ship.get("imo") or "").upper()
        key_name = scheduled_name_key(ship.get("name") or "")
        match = scheduled.get(key_imo) or scheduled.get(key_name)
        if match:
            if not ship.get("eta") and match.get("eta"):
                ship["eta"] = match["eta"]
            if not ship.get("etb") and match.get("etb"):
                ship["etb"] = match["etb"]
            if match.get("etb") and ship.get("source") != "APS — Atracações Programadas":
                ship["scheduledSource"] = match["source"]

    # Faz o cruzamento final por IMO/nome normalizado antes da consolidação.
    merge_cross_source_fields(all_rows)

    priority = {
        "Atracado": 4,
        "Fundeado": 3,
        "Barra": 3,
        "Esperado": 1,
    }

    merged = {}

    for ship in all_rows:
        key = ship["imo"] or ship["name"].upper()

        if key not in merged:
            merged[key] = ship
            continue

        if priority.get(ship["status"], 0) > priority.get(
            merged[key]["status"], 0
        ):
            current = merged[key]
            merged[key] = ship
            for field, value in current.items():
                if not merged[key].get(field) and value:
                    merged[key][field] = value
        else:
            for field, value in ship.items():
                if not merged[key].get(field) and value:
                    merged[key][field] = value

    now = datetime.now(timezone.utc).astimezone().strftime(
        "%d/%m/%Y %H:%M:%S"
    )

    result = list(merged.values())

    for ship in result:
        ship["updatedAt"] = now

    result.sort(key=lambda x: (x["status"], x["name"]))

    os.makedirs("public", exist_ok=True)

    with open("public/navios.json", "w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)

    with open("public/atualizacao.json", "w", encoding="utf-8") as file:
        json.dump({
            "updatedAt": now,
            "total": len(result),
            "errors": errors,
        }, file, ensure_ascii=False, indent=2)

    etb_count = sum(bool(x.get("etb")) for x in result)
    ata_count = sum(bool(x.get("ata")) for x in result)
    atb_count = sum(bool(x.get("atb")) for x in result)
    print(f"Registros encontrados: {len(result)}")
    print(f"Com ETB: {etb_count} | Com ATA: {ata_count} | Com ATB: {atb_count}")

    if errors:
        print("AVISOS:")
        for error in errors:
            print(error)

    if not result:
        raise RuntimeError(
            "Nenhuma fonte retornou dados. O arquivo anterior não deve ser substituído."
        )

if __name__ == "__main__":
    main()


