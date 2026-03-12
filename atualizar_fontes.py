#!/usr/bin/env python3
"""
TERA — Atualizar Fontes
Script para coleta automática de atualizações tributárias de fontes oficiais.
Executado via GitHub Actions de segunda a sexta às 09:00 (horário de Brasília).

Fontes:
  1. RFB Reforma do Consumo (Notícias)
  2. Portal NFe/NFCe (Notas Técnicas)
  3. Diário Oficial da União (DOU) — seção tributária

Saída: data/atualizacoes.json
"""

import json
import os
import re
import sys
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Tenta importar requests e BeautifulSoup; se não estiver disponível, instala
try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "beautifulsoup4", "--quiet"])
    import requests
    from bs4 import BeautifulSoup

# ── Configurações ────────────────────────────────────────────
BRT = timezone(timedelta(hours=-3))
AGORA = datetime.now(BRT)
DATA_HOJE = AGORA.strftime("%Y-%m-%d")
MAX_HISTORICO = 500  # máximo de itens no histórico
TIMEOUT = 30
HEADERS = {
    "User-Agent": "TERA-LegalMonitor/1.0 (naytributario.github.io/TERA-LEI; educational)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.5",
}
DATA_DIR = Path("data")
SAIDA = DATA_DIR / "atualizacoes.json"


def log(msg):
    print(f"[{datetime.now(BRT).strftime('%H:%M:%S')}] {msg}")


def item_id(link, titulo):
    """Gera um ID único para evitar duplicatas."""
    raw = (link or "") + (titulo or "")
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


# ── Fonte 1: RFB Reforma do Consumo ─────────────────────────
def scrape_rfb_reforma():
    """Coleta notícias da página de Reforma do Consumo da RFB."""
    url = "https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/acoes-e-programas/programas-e-atividades/reforma-consumo/noticias"
    itens = []
    try:
        log("Buscando RFB Reforma do Consumo...")
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")

        # A página gov.br usa tiles/listagem de conteúdo
        # Tenta vários seletores comuns do portal gov.br
        links = soup.select("article a, .noticias a, .tileItem a, .tile-content a, ul.noticias li a, .listagem-item a")
        if not links:
            # Fallback: todos os links dentro do conteúdo principal
            content = soup.select_one("#content, #main-content, .content-area, main")
            if content:
                links = content.find_all("a", href=True)

        seen = set()
        for a in links:
            href = a.get("href", "").strip()
            titulo = a.get_text(strip=True)
            if not titulo or len(titulo) < 10 or not href:
                continue
            # Resolve URLs relativas
            if href.startswith("/"):
                href = "https://www.gov.br" + href
            if not href.startswith("http"):
                continue
            # Evita duplicatas e links genéricos
            if href in seen or "javascript:" in href:
                continue
            seen.add(href)

            # Tenta extrair data do URL ou texto próximo
            data = DATA_HOJE
            data_match = re.search(r"(\d{4})[/-](\d{2})[/-](\d{2})", href)
            if data_match:
                data = f"{data_match.group(1)}-{data_match.group(2)}-{data_match.group(3)}"
            else:
                # Procura data no texto pai
                parent = a.find_parent(["li", "article", "div"])
                if parent:
                    date_el = parent.select_one(".date, .data, time, span.publicado")
                    if date_el:
                        dtxt = date_el.get_text(strip=True)
                        dm = re.search(r"(\d{2})/(\d{2})/(\d{4})", dtxt)
                        if dm:
                            data = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}"

            itens.append({
                "id": item_id(href, titulo),
                "data": data,
                "titulo": titulo[:300],
                "portal": "RFB Reforma",
                "link": href,
                "resumo": ""
            })

        log(f"  → {len(itens)} itens encontrados na RFB Reforma")
    except Exception as e:
        log(f"  ✗ Erro ao buscar RFB Reforma: {e}")
    return itens


# ── Fonte 2: Portal NFe ─────────────────────────────────────
def scrape_nfe():
    """Coleta Notas Técnicas e comunicados do portal NFe."""
    url = "https://www.nfe.fazenda.gov.br/portal/listaConteudo.aspx?tipoConteudo=04BIflQt1aY="
    itens = []
    try:
        log("Buscando Portal NFe...")
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")

        # O portal NFe usa tabelas ou listas de conteúdo
        links = soup.select("table a, .listConteudo a, #ConteudoPagina a, .conteudo a")
        if not links:
            links = soup.find_all("a", href=True)

        seen = set()
        for a in links:
            href = a.get("href", "").strip()
            titulo = a.get_text(strip=True)
            if not titulo or len(titulo) < 5 or not href:
                continue
            # Resolve URLs relativas
            if href.startswith("/"):
                href = "https://www.nfe.fazenda.gov.br" + href
            elif not href.startswith("http"):
                href = "https://www.nfe.fazenda.gov.br/portal/" + href
            if href in seen or "javascript:" in href.lower():
                continue
            seen.add(href)

            # Tenta extrair data
            data = DATA_HOJE
            parent = a.find_parent(["tr", "li", "div"])
            if parent:
                tds = parent.find_all("td")
                for td in tds:
                    dm = re.search(r"(\d{2})/(\d{2})/(\d{4})", td.get_text())
                    if dm:
                        data = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}"
                        break

            itens.append({
                "id": item_id(href, titulo),
                "data": data,
                "titulo": titulo[:300],
                "portal": "NFe/NFCe",
                "link": href,
                "resumo": ""
            })

        log(f"  → {len(itens)} itens encontrados no Portal NFe")
    except Exception as e:
        log(f"  ✗ Erro ao buscar Portal NFe: {e}")
    return itens


# ── Fonte 3: DOU (Diário Oficial da União) ──────────────────
def scrape_dou():
    """Coleta publicações tributárias do DOU via API de busca."""
    itens = []
    termos = ["reforma tributária", "PIS COFINS", "IBS CBS", "Instrução Normativa RFB"]

    for termo in termos:
        try:
            log(f"Buscando DOU: '{termo}'...")
            # API de busca do IN.gov.br
            api_url = "https://www.in.gov.br/consulta/-/buscar/dou"
            params = {
                "q": termo,
                "s": "todos",
                "exactDate": "dia",
                "sortType": "0"
            }
            r = requests.get(api_url, params=params, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            r.encoding = "utf-8"
            soup = BeautifulSoup(r.text, "html.parser")

            # O DOU retorna resultados em cards/divs
            results = soup.select(".resultados-dou .resultado-item, .resultado-dou, .resultados-pesquisa .resultado, article.resultado")
            if not results:
                # Tenta outro padrão
                results = soup.select("div.resultado, .result-item, .searchresult-item")

            for res in results:
                a = res.find("a", href=True)
                if not a:
                    continue
                href = a.get("href", "").strip()
                titulo = a.get_text(strip=True)
                if not titulo or not href:
                    continue
                if href.startswith("/"):
                    href = "https://www.in.gov.br" + href

                # Extrai data e resumo
                data = DATA_HOJE
                resumo = ""
                date_el = res.select_one(".date, .data-publicacao, time")
                if date_el:
                    dtxt = date_el.get_text(strip=True)
                    dm = re.search(r"(\d{2})/(\d{2})/(\d{4})", dtxt)
                    if dm:
                        data = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}"

                resumo_el = res.select_one(".resumo, .abstract, p")
                if resumo_el:
                    resumo = resumo_el.get_text(strip=True)[:500]

                itens.append({
                    "id": item_id(href, titulo),
                    "data": data,
                    "titulo": titulo[:300],
                    "portal": "Diário Oficial",
                    "link": href,
                    "resumo": resumo
                })

        except Exception as e:
            log(f"  ✗ Erro ao buscar DOU '{termo}': {e}")

    # Remove duplicatas
    seen_ids = set()
    unique = []
    for item in itens:
        if item["id"] not in seen_ids:
            seen_ids.add(item["id"])
            unique.append(item)
    itens = unique
    log(f"  → {len(itens)} itens únicos encontrados no DOU")
    return itens


# ── Fallback: DOU via leitura do jornal ──────────────────────
def scrape_dou_leitura():
    """Fallback: coleta da página de leitura do jornal do DOU."""
    url = "https://in.gov.br/leiturajornal"
    itens = []
    try:
        log("Buscando DOU (leitura do jornal)...")
        r = requests.get(url, headers={**HEADERS, "Accept": "text/html"}, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")

        # Busca por publicações na página de leitura
        links = soup.select("a.materia, a.titulo-materia, .materia a, article a")
        seen = set()
        for a in links:
            href = a.get("href", "").strip()
            titulo = a.get_text(strip=True)
            if not titulo or len(titulo) < 10 or not href:
                continue
            if href.startswith("/"):
                href = "https://www.in.gov.br" + href
            if href in seen:
                continue
            seen.add(href)

            # Filtra por termos tributários
            titulo_lower = titulo.lower()
            tributario = any(t in titulo_lower for t in [
                "tribut", "pis", "cofins", "ibs", "cbs", "imposto",
                "instrução normativa", "rfb", "receita federal",
                "simples nacional", "reforma", "alíquota", "contribuição"
            ])
            if not tributario:
                continue

            itens.append({
                "id": item_id(href, titulo),
                "data": DATA_HOJE,
                "titulo": titulo[:300],
                "portal": "Diário Oficial",
                "link": href,
                "resumo": ""
            })

        log(f"  → {len(itens)} itens tributários encontrados na leitura do DOU")
    except Exception as e:
        log(f"  ✗ Erro ao buscar leitura do DOU: {e}")
    return itens


# ── Execução principal ───────────────────────────────────────
def main():
    log(f"═══ TERA Atualizar Fontes — {AGORA.strftime('%d/%m/%Y %H:%M')} BRT ═══")

    # Garante que o diretório data/ existe
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Carrega histórico existente
    historico = []
    if SAIDA.exists():
        try:
            with open(SAIDA, "r", encoding="utf-8") as f:
                dados = json.load(f)
                historico = dados.get("itens", [])
                log(f"Histórico carregado: {len(historico)} itens existentes")
        except Exception as e:
            log(f"Erro ao carregar histórico: {e}")

    # Coleta de todas as fontes
    novos = []
    novos.extend(scrape_rfb_reforma())
    novos.extend(scrape_nfe())

    dou_itens = scrape_dou()
    if len(dou_itens) == 0:
        dou_itens = scrape_dou_leitura()
    novos.extend(dou_itens)

    # Mescla com histórico (evita duplicatas por ID)
    ids_existentes = {item["id"] for item in historico}
    adicionados = 0
    for item in novos:
        if item["id"] not in ids_existentes:
            historico.append(item)
            ids_existentes.add(item["id"])
            adicionados += 1

    # Ordena por data (mais recente primeiro) e limita o tamanho
    historico.sort(key=lambda x: x.get("data", ""), reverse=True)
    if len(historico) > MAX_HISTORICO:
        historico = historico[:MAX_HISTORICO]

    # Salva
    saida = {
        "ultima_atualizacao": AGORA.isoformat(),
        "total": len(historico),
        "novos_nesta_execucao": adicionados,
        "fontes": [
            "https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/acoes-e-programas/programas-e-atividades/reforma-consumo/noticias",
            "https://www.nfe.fazenda.gov.br/portal/listaConteudo.aspx?tipoConteudo=04BIflQt1aY=",
            "https://in.gov.br/leiturajornal"
        ],
        "itens": historico
    }

    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)

    log(f"═══ Concluído: {adicionados} novos itens adicionados, {len(historico)} itens totais ═══")
    log(f"Arquivo salvo em: {SAIDA}")


if __name__ == "__main__":
    main()
