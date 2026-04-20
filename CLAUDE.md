# FinLake Brasil — Financial Data Platform

## Visão Geral
Plataforma de dados financeiros brasileiros end-to-end com dados reais do Banco Central do Brasil (BCB) e Comissão de Valores Mobiliários (CVM). Arquitetura Medallion (Bronze → Silver → Gold) com princípios de Data Mesh organizados em 2 domínios.

## Engenheiro
- Nome: Nilton Coura
- GitHub: github.com/niltontac
- Perfil: Senior Data Engineer em transição para Staff/Principal Engineer com foco em plataformas AI-ready

## Domínios (Data Mesh)
### Domínio 1 — Macroeconomia (BCB)
- Owner: domain_macro
- Fonte: API pública do Banco Central do Brasil (dadosabertos.bcb.gov.br)
- Dados: SELIC, IPCA, PTAX (câmbio), expectativas de mercado, taxas de crédito
- Biblioteca: python-bcb

### Domínio 2 — Fundos de Investimento (CVM)
- Owner: domain_funds
- Fonte: Portal de Dados Abertos da CVM (dados.cvm.gov.br)
- Dados: informe diário de fundos, patrimônio líquido, captação, rentabilidade
- Formato: CSV público atualizado diariamente

## Stack Técnica
- Linguagem: Python 3.12
- Validação: Pydantic v2
- Transformação: dbt-core
- Processamento Gold: DuckDB
- Processamento histórico bulk: PySpark (dados históricos CVM)
- Orquestração: Apache Airflow
- Storage Bronze: Parquet files + PostgreSQL 15
- Dashboard: Metabase
- CI/CD: GitHub Actions
- Containerização: Docker Compose
- Qualidade: dbt tests + Great Expectations
- Observabilidade: LangFuse
- Gerenciamento de pacotes: uv

## Arquitetura Medallion
- Bronze: dados brutos, sem transformação, particionados por data de ingestão
- Silver: dados limpos, validados, tipados, normalizados por domínio
- Gold: métricas agregadas, cruzamento entre domínios, prontas para consumo

## Convenções
- Todos os arquivos Python com type hints obrigatórios
- Docstrings em todos os módulos, classes e funções públicas
- Variáveis de ambiente para todas as credenciais (nunca hardcoded)
- Commits em inglês, mensagens no formato conventional commits
- Testes obrigatórios para toda função de transformação
- Nenhum dado sensível commitado no repositório

## Infraestrutura Local
- PostgreSQL 15: postgresql://postgres:supabase123@localhost:5432/finlake
- DuckDB: ./data/finlake.duckdb
- Airflow: http://localhost:8080
- Metabase: http://localhost:3030
- LangFuse: configurado via .env

## Método de Desenvolvimento
- Spec-Driven Development (SDD) via AgentSpec
- Fases: /brainstorm → /define → /design → /build → /ship
- Nenhuma feature sem spec documentada
- PRDs versionados em .claude/sdd/features/
