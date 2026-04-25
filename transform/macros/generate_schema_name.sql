-- Macro padrão dbt para schema exato — sem concatenar o schema do profile.
-- Sem esta macro: dbt gera silver_bcb_gold_bcb ao invés de gold_bcb.
-- Comportamento: retorna custom_schema_name diretamente quando fornecido.
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
