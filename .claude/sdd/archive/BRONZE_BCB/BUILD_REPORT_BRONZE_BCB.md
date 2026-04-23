# BUILD REPORT: BRONZE_BCB

> Data: 2026-04-23
> Autor: build-agent

---

## Metadata

| Atributo    | Valor                                                         |
|-------------|---------------------------------------------------------------|
| **Feature** | BRONZE_BCB                                                    |
| **Status**  | Build Completo                                                |
| **DESIGN**  | [DESIGN_BRONZE_BCB.md](../features/DESIGN_BRONZE_BCB.md)     |
| **Testes**  | 12 passed, 1 skipped (airflow-only)                          |

---

## Arquivos Criados / Modificados

| #  | Arquivo                                              | Ação     | Status |
|----|------------------------------------------------------|----------|--------|
| 1  | `docker/postgres/migrations/001_bronze_bcb.sql`      | Criado   | ✅     |
| 2  | `docker/airflow/requirements.txt`                    | Modificado | ✅   |
| 3  | `.env.example`                                       | Modificado | ✅   |
| 4  | `docker/compose.airflow.yml`                         | Modificado | ✅   |
| 5  | `dags/domain_bcb/__init__.py`                        | Criado   | ✅     |
| 6  | `dags/domain_bcb/ingestion/__init__.py`              | Criado   | ✅     |
| 7  | `dags/domain_bcb/ingestion/bcb_client.py`            | Criado   | ✅     |
| 8  | `dags/domain_bcb/ingestion/loaders.py`               | Criado   | ✅     |
| 9  | `dags/domain_bcb/dag_bronze_bcb.py`                  | Criado   | ✅     |
| 10 | `pyproject.toml`                                     | Criado   | ✅     |
| 11 | `tests/__init__.py`                                  | Criado   | ✅     |
| 12 | `tests/domain_bcb/__init__.py`                       | Criado   | ✅     |
| 13 | `tests/domain_bcb/test_bcb_client.py`                | Criado   | ✅     |
| 14 | `tests/domain_bcb/test_loaders.py`                   | Criado   | ✅     |
| 15 | `Makefile`                                           | Modificado (target `migrate`) | ✅ |

**Total:** 15 arquivos (10 criados + 5 modificados)

> **Nota:** `pyproject.toml` e target `Makefile migrate` foram adicionados
> além do manifesto original — necessários para o toolchain funcionar.

---

## Resultados dos Testes

```
pytest tests/ -v
======================== 12 passed, 1 skipped in 0.46s =========================
```

| Módulo                         | Resultado | Motivo do skip                            |
|--------------------------------|-----------|-------------------------------------------|
| `test_bcb_client.py` (12 testes)| ✅ 12/12  | —                                         |
| `test_loaders.py` (módulo)     | ⏭ skipped | `airflow` não instalado localmente (esperado) |

`test_loaders.py` executa dentro do container Airflow:
```bash
docker exec finlake-airflow python -m pytest /opt/airflow/dags/../tests/ -v
```

---

## Verificação dos Acceptance Tests (AT)

| ID     | Cenário                              | Status | Verificação                                          |
|--------|--------------------------------------|--------|------------------------------------------------------|
| AT-001 | Backfill no primeiro run             | ✅     | `get_load_range` retorna `(start_date, hoje)` se tabela vazia |
| AT-002 | Incremental no segundo run           | ✅     | `get_load_range` retorna `(max_date+1, hoje)` se há dados |
| AT-003 | Idempotência por reprocessamento     | ✅     | `ON CONFLICT (date) DO NOTHING` em todos os upserts |
| AT-004 | IPCA — skip quando mês já gravado   | ✅     | `AirflowSkipException` lançada quando `max_date >= current_month_start` |
| AT-005 | Tasks paralelas e independentes      | ✅     | Sem dependências entre tasks na DAG — falha isolada |
| AT-006 | Autenticação via variável de ambiente| ✅     | `PostgresHook(postgres_conn_id=CONN_ID)` + `AIRFLOW_CONN_*` |
| AT-007 | Migration cria schema e tabelas      | ✅     | `001_bronze_bcb.sql` com `IF NOT EXISTS` em todas as operações |

---

## Desvios do DESIGN Original

| Item                 | DESIGN                              | Build                                  | Motivo                                |
|----------------------|-------------------------------------|----------------------------------------|---------------------------------------|
| Contagem de arquivos | 13 arquivos                         | 15 arquivos                            | `pyproject.toml` + `Makefile migrate` necessários |
| `hook.return_conn()` | Mencionado no DESIGN                | Substituído por `conn.close()`         | `return_conn()` não existe no `PostgresHook` |
| `test_loaders.py`    | Testes executam localmente          | Skip local + execução no container     | `airflow` não disponível fora do Docker |

---

## Instruções de Ativação

### 1. Adicionar `AIRFLOW_CONN_FINLAKE_POSTGRES` ao `.env`

```bash
echo "AIRFLOW_CONN_FINLAKE_POSTGRES=postgresql://postgres:<SENHA>@postgres:5432/finlake" >> .env
```

### 2. Rebuild da imagem Airflow (novo provider)

```bash
make down
make up PROFILE=orchestration
```

### 3. Executar migration do schema `bronze_bcb`

```bash
make migrate
```

### 4. Verificar DAG na UI do Airflow

Acesse http://localhost:8080 — `dag_bronze_bcb` deve aparecer sem erros de parse.

### 5. Executar primeira run (backfill)

Trigger manual na UI ou via CLI:
```bash
docker exec finlake-airflow airflow dags trigger dag_bronze_bcb
```

### 6. Verificar dados no PostgreSQL

```bash
docker exec finlake-postgres psql -U postgres -d finlake -c \
  "SELECT COUNT(*), MIN(date), MAX(date) FROM bronze_bcb.selic_daily;"
```

---

## Observações Técnicas

- **`hook.return_conn()` não existe:** O `PostgresHook` do Airflow não implementa
  `return_conn()`. O padrão correto é `conn.close()` em bloco `finally`, que foi
  aplicado em `_upsert_dataframe()`.

- **`TYPE_CHECKING` para PostgresHook em `bcb_client.py`:** O import de `PostgresHook`
  é feito apenas durante type checking (`if TYPE_CHECKING`), evitando dependência
  de runtime em `bcb_client.py` e facilitando testes unitários sem Airflow instalado.

- **`pyproject.toml` com `pythonpath = ["dags"]`:** Necessário para que pytest
  encontre `domain_bcb` como módulo importável localmente, replicando o comportamento
  do Airflow que adiciona `dags/` ao `sys.path`.

---

## Próximo Passo

**Pronto para:** `/ship .claude/sdd/features/DEFINE_BRONZE_BCB.md`
