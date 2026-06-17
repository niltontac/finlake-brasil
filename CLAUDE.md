# FinLake Brasil — Financial Data Platform

## Visão Geral
Plataforma de dados financeiros brasileiros end-to-end com dados reais do Banco Central do Brasil (BCB) e Comissão de Valores Mobiliários (CVM). Arquitetura Medallion (Bronze → Silver → Gold → Visualização) com princípios de Data Mesh organizados em 2 domínios. Projeto completo — todas as features SDD entregues.

## Engenheiro
- Nome: Nilton Coura
- GitHub: github.com/niltontac
- Perfil: Senior Data Engineer em transição para Staff/Principal Engineer com foco em plataformas AI-ready

## Domínios (Data Mesh)

### Domínio 1 — Macroeconomia (BCB)
- Owner: domain_macro
- Fonte: API pública do Banco Central do Brasil — SGS (dadosabertos.bcb.gov.br)
- Dados: SELIC, IPCA, PTAX (câmbio)
- Biblioteca: python-bcb
- Cobertura: histórico completo (SELIC desde 2000, IPCA desde 1994, PTAX desde 1999)
- Tabelas Gold principais: gold_bcb.macro_diario, gold_bcb.macro_mensal (com selic_real)

### Domínio 2 — Fundos de Investimento (CVM)
- Owner: domain_funds
- Fonte: Portal de Dados Abertos da CVM (dados.cvm.gov.br)
- Dados: cadastro de fundos (SCD Tipo 1, overwrite) + informe diário (captação, patrimônio líquido, rentabilidade)
- Formato: CSV/ZIP público
- Cobertura: ano de 2024 (~6.5M linhas no informe diário) — sem histórico plurianual
- Tabela Gold principal: gold_cvm.fundo_mensal

## Stack Técnica
- Linguagem: Python 3.12
- Gerenciamento de pacotes: uv
- Validação: Pydantic v2
- Transformação: dbt-core (adapter dbt-postgres)
- Storage (todas as camadas): PostgreSQL 15 único — Bronze, Silver e Gold no mesmo banco, separados por schema (bronze_bcb, bronze_cvm, silver_bcb, silver_cvm, gold_bcb, gold_cvm)
- Orquestração: Apache Airflow 2.10.4, executor standalone, retries=3 padronizado nas 7 DAGs
- Dashboard: Metabase (persistência H2), dashboards provisionados via automação REST API (scripts/setup_metabase_bcb.py, scripts/setup_metabase_cvm.py)
- Qualidade: dbt tests
- CI/CD: GitHub Actions
- Containerização: Docker Compose com profiles (core/orchestration/full)

> Nota: DuckDB, PySpark e Great Expectations foram avaliados no planejamento inicial mas não fazem parte da implementação final. Todo o processamento roda em PostgreSQL via dbt + Airflow.

## Arquitetura Medallion
- Bronze: dados brutos, ingestão via Airflow DAGs (psycopg2 execute_values/COPY), idempotente via ON CONFLICT DO NOTHING
- Silver: dados limpos, tipados, normalizados por domínio (modelos dbt) — não faz JOIN entre domínios
- Gold: métricas agregadas e cruzamento BCB×CVM, modelos dbt, pronto para consumo
- Visualização: dashboards Metabase consumindo os schemas Gold

## Convenções
- Todos os arquivos Python com type hints obrigatórios
- Docstrings em todos os módulos, classes e funções públicas
- Variáveis de ambiente para todas as credenciais (nunca hardcoded)
- Commits em inglês, mensagens no formato conventional commits
- Testes obrigatórios para toda função de transformação
- Nenhum dado sensível commitado no repositório

## Infraestrutura Local
- PostgreSQL 15: postgresql://postgres:***REMOVED***@localhost:5433/finlake
- Airflow: http://localhost:8080 (admin/***REMOVED***)
- Metabase: http://localhost:3030
- Subir tudo: `make up` (docker compose --profile full up -d)

## Projeto Complementar — AI Engineering Layer
`finlake-ai-analyst` (github.com/niltontac/finlake-ai-analyst) é a camada de AI Engineering construída sobre este projeto: agente Text-to-SQL via LangGraph/LangChain/Claude Sonnet 4.6, interface Chainlit, observabilidade via LangFuse Cloud e evals via DeepEval. Consome apenas os schemas gold_bcb e gold_cvm deste repositório — nunca escreve neles.

## Método de Desenvolvimento
- Spec-Driven Development (SDD) via AgentSpec
- Fases: /brainstorm → /define → /design → /build → /ship
- Nenhuma feature sem spec documentada
- PRDs versionados em .claude/sdd/features/, arquivados em .claude/sdd/archive/