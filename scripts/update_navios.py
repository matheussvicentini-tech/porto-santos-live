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

            key = (imo or name).upper()
            result[key] = {
                "name": name,
                "imo": imo,
                "eta": eta,
                "etb": etb,
                "source": "APS — Atracações Programadas"
            }

    return result

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

    # Complementa os registros com a previsão de atracação (ETB) publicada
    # pela APS. Nunca substitui um ETB mais específico já obtido de outra fonte.
    for ship in all_rows:
        key_imo = (ship.get("imo") or "").upper()
        key_name = (ship.get("name") or "").upper()
        match = scheduled.get(key_imo) or scheduled.get(key_name)
        if match:
            if not ship.get("eta") and match.get("eta"):
                ship["eta"] = match["eta"]
            if not ship.get("etb") and match.get("etb"):
                ship["etb"] = match["etb"]
            if match.get("etb") and ship.get("source") != "APS — Atracações Programadas":
                ship["scheduledSource"] = match["source"]

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

    print(f"Registros encontrados: {len(result)}")

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


