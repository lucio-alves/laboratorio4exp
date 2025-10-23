"""
====================================================
VALIDAÇÃO DO PILAR 1 (ENGAJAMENTO) - VERSÃO FINAL v2
====================================================

Objetivo:
Validar as métricas de engajamento para os repositórios
da Fase 1 de forma rápida e eficiente, com tratamento de
erros para commits não vinculados.

Dependências:
    pip install PyGithub pandas openpyxl
    (opcional) pip install python-dotenv

Entradas:
    - dataset_fase1_validacao-v2.xlsx
      (deve conter as colunas: URL, Data de morte, Data de ressurreição)

Saída:
    - validacao_pilar1_completo_final_v2.xlsx

Autor: [Seu Nome] & Gemini
====================================================
"""

from dotenv import load_dotenv
import os
import pandas as pd
import re
from datetime import timedelta, datetime
from github import Github, Auth, GithubException

# ====================================================
# 🔐 Carregar token do .env
# ====================================================
load_dotenv()

token = os.getenv("GITHUB_TOKEN")
if not token:
    raise EnvironmentError("⚠️ Defina o GITHUB_TOKEN no arquivo .env")

auth = Auth.Token(token)
g = Github(auth=auth, per_page=100)

# ====================================================
# 📘 Leitura do dataset base
# ====================================================
df_base = pd.read_excel("dataset_fase1_validacao-v2.xlsx")

repo_col = "URL"
data_dead_col = "Data de morte"
data_revive_col = "Data de ressurreição"

# ====================================================
# 🔧 Função para extrair owner/repo da URL
# ====================================================
def extrair_owner_repo(url):
    match = re.search(r"github\.com/([\w\-_.]+/[\w\-_.]+)", url)
    if match:
        return match.group(1)
    else:
        raise ValueError(f"URL inválida: {url}")

# ====================================================
# 📈 Funções de Análise (Refatoradas para receber dados)
# ====================================================

# --- Funções que não dependem do histórico (rápidas) ---
def tem_documentacao(repo):
    try:
        contents = repo.get_contents("")
        files = [f.path.lower() for f in contents]
        return any(x in str(files) for x in ["contributing.md", "code_of_conduct.md", "readme.md"])
    except Exception:
        return False

def adocao_ci(repo, data_revive):
    try:
        paths = [".github/workflows", ".travis.yml"]
        for path in paths:
            commits = repo.get_commits(path=path, since=data_revive)
            if commits.totalCount > 0:
                return True
        return False
    except GithubException as e:
        if e.status == 404: return False
        print(f"  (Info) Erro ao checar CI: {e}")
        return False
    except Exception:
        return False

def identifica_novos_mantenedores(repo, data_revive):
    return "Não aplicável (Limitação da API)"

# --- Funções que agora processam listas pré-buscadas ---

def conta_mencoes_incentivo(issues_list):
    count = 0
    for issue in issues_list:
        text = (issue.title or "") + " " + (issue.body or "")
        if re.search(r"good first issue|hacktoberfest", text, re.IGNORECASE):
            count += 1
    return count

def comentarios_antes_depois(issues_list, data_revive):
    antes, depois = [], []
    for i in issues_list:
        if i.created_at < data_revive:
            antes.append(i)
        else:
            depois.append(i)

    media_antes = sum(i.comments for i in antes) / len(antes) if antes else 0
    media_depois = sum(i.comments for i in depois) if depois else 0
    return media_antes, media_depois

# <<< FUNÇÃO CORRIGIDA >>>
def diversidade_contribuidores(commits_list, data_revive):
    """
    Conta número de contribuidores únicos antes e depois (M1.2.2).
    VERSÃO CORRIGIDA: Lida com commits cujo autor não é um usuário do GitHub.
    """
    antes, depois = set(), set()
    for c in commits_list:
        # A verificação 'if c.author:' é a forma mais segura. Se o autor do commit
        # não for um usuário do GitHub, c.author será 'None' e o código interno não será executado.
        if c.author:
            commit_date = c.commit.author.date
            if commit_date < data_revive:
                antes.add(c.author.login)
            else:
                depois.add(c.author.login)
    return len(antes), len(depois)

def taxa_fechamento_issues(issues_list):
    fechadas, fechadas_rapidas = 0, 0
    for issue in issues_list:
        if issue.state == 'closed':
            fechadas += 1
            if issue.closed_at and issue.created_at:
                if (issue.closed_at - issue.created_at).days <= 30:
                    fechadas_rapidas += 1
    return round(fechadas_rapidas / fechadas, 3) if fechadas > 0 else 0

def frequencia_interacao_mantenedores(repo, issues_list, data_revive):
    tempos_antes, tempos_depois = [], []
    mantenedores = {repo.owner.login}

    for issue in issues_list:
        if issue.user.login in mantenedores:
            continue
        try:
            for comment in issue.get_comments():
                if comment.user.login in mantenedores:
                    delta = (comment.created_at - issue.created_at).total_seconds() / 3600
                    if issue.created_at < data_revive:
                        tempos_antes.append(delta)
                    else:
                        tempos_depois.append(delta)
                    break
        except Exception as e:
            print(f"  (Info) Não foi possível buscar comentários da issue #{issue.number}: {e}")

    media_antes = sum(tempos_antes) / len(tempos_antes) if tempos_antes else 0
    media_depois = sum(tempos_depois) / len(tempos_depois) if tempos_depois else 0
    return round(media_antes, 2), round(media_depois, 2)

def conta_mencoes_eventos_externos(issues_list):
    count = 0
    keywords = r"sponsor|sponsorship|funding|conference|patrocínio|financiamento|conferência"
    for issue in issues_list:
        text = (issue.title or "") + " " + (issue.body or "")
        if re.search(keywords, text, re.IGNORECASE):
            count += 1
    return count

# ====================================================
# 🚀 Loop Principal Otimizado
# ====================================================
resultados = []

for idx, row in df_base.iterrows():
    url_repo = row[repo_col]
    try:
        repo_name = extrair_owner_repo(url_repo)
    except ValueError as e:
        print(f"⚠️ {e}")
        continue

    data_dead = pd.to_datetime(row[data_dead_col]).tz_localize('UTC')
    data_revive = pd.to_datetime(row[data_revive_col]).tz_localize('UTC')
    analysis_start_date = data_dead - timedelta(days=365)

    print(f"🔍 Analisando {repo_name} ({idx+1}/{len(df_base)})")

    try:
        repo = g.get_repo(repo_name)

        print(f"  Buscando dados desde {analysis_start_date.date()}...")
        all_issues_in_window = list(repo.get_issues(state="all", since=analysis_start_date))
        all_commits_in_window = list(repo.get_commits(since=analysis_start_date))
        print(f"  Encontrados {len(all_issues_in_window)} issues e {len(all_commits_in_window)} commits.")

        print("  Processando métricas...")
        docs = tem_documentacao(repo)
        ci_adotado = adocao_ci(repo, data_revive)
        novos_maintainers = identifica_novos_mantenedores(repo, data_revive)
        incentivos = conta_mencoes_incentivo(all_issues_in_window)
        com_antes, com_depois = comentarios_antes_depois(all_issues_in_window, data_revive)
        div_antes, div_depois = diversidade_contribuidores(all_commits_in_window, data_revive) # Chamada da função corrigida
        taxa_fechamento = taxa_fechamento_issues(all_issues_in_window)
        mencoes_eventos = conta_mencoes_eventos_externos(all_issues_in_window)
        tempo_resp_antes, tempo_resp_depois = frequencia_interacao_mantenedores(repo, all_issues_in_window, data_revive)

        resultados.append({
            "repo": repo_name,
            "tem_documentacao": docs,
            "menções_incentivo": incentivos,
            "tempo_resposta_mantenedor_antes_h": tempo_resp_antes,
            "tempo_resposta_mantenedor_depois_h": tempo_resp_depois,
            "comentários_médios_antes": round(com_antes, 2),
            "comentários_médios_depois": round(com_depois, 2),
            "diversidade_contrib_antes": div_antes,
            "diversidade_contrib_depois": div_depois,
            "taxa_fechamento_30d": taxa_fechamento,
            "ci_adotado_pos_revive": ci_adotado,
            "novos_mantenedores_pos_revive": novos_maintainers,
            "menções_eventos_externos": mencoes_eventos,
        })

    except Exception as e:
        print(f"❌ Erro CRÍTICO ao processar {repo_name}: {e}")
        continue

# ====================================================
# 💾 Exportação dos Resultados Consolidados
# ====================================================
df_result = pd.DataFrame(resultados)
output_filename = "validacao_pilar1_completo_final_v2.xlsx"
df_result.to_excel(output_filename, index=False)
print(f"\n✅ Arquivo '{output_filename}' gerado com sucesso!")